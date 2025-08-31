# medlegal/llm/severity.py
from __future__ import annotations
from pathlib import Path
import json, re, traceback
from typing import Dict, List
import google.generativeai as genai
from config import GEMINI_API_KEY, paths_for_claim
from utils.io import write_json_utf8, write_text_utf8

# Keep reasons short to reduce output size and avoid truncation
PROMPT = """You will receive:
- a short CASE (summary/verdict/notes),
- a list of FLAGS (each has: id, title, direction, citations, details). Numeric scores are NOT provided.

Return a JSON object mapping each provided flag id to:
  { "multiplier": float, "reason": string }

Rules:
- Use EXACTLY the provided IDs; do not add or drop any.
- Range: 0.5 (very minor) .. 3.0 (decisive). 1.0 = normal.
- Be concise and evidence-aware (titles/citations/details only; no invented facts).
- Keep each reason ≤ 12 words.
- Output ONLY valid JSON (no markdown fences).
"""

BATCH_SIZE = 8  # keep small to avoid long outputs per call
MAX_OUTPUT_TOKENS = 2048  # fits ~8 items w/ short reasons

def _shorten_reason(s: str, max_words: int = 12) -> str:
    parts = (s or "").split()
    return " ".join(parts[:max_words])

def _strip_code_fences(s: str) -> str:
    s = re.sub(r"^```(?:json)?\s*", "", (s or "").strip(), flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s.strip())
    return s.strip()

def _extract_json_object(s: str) -> str:
    s = _strip_code_fences(s)
    start = s.find("{")
    if start == -1:
        return "{}"
    depth = 0
    for i, c in enumerate(s[start:], start):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start:i+1]
    # unbalanced braces -> truncated
    return "{}"

def _sanitize_trailing_commas(s: str) -> str:
    s = re.sub(r",\s*}", "}", s)
    s = re.sub(r",\s*]", "]", s)
    return s

def _defaults_for_ids(ids: List[str]) -> Dict[str, Dict[str, object]]:
    return {fid: {"multiplier": 1.0, "reason": "default 1.0"} for fid in ids}

def _salvage_partial(raw: str, allowed_ids: List[str]) -> Dict[str, Dict[str, object]]:
    """
    Try to salvage any complete per-flag objects out of a truncated JSON string.
    Strategy: for each known fid, find the substring starting at `"fid": {`
    and parse the first balanced `{...}` object that follows (if any).
    """
    out: Dict[str, Dict[str, object]] = {}
    for fid in allowed_ids:
        key_pat = f'"{re.escape(fid)}"'
        m = re.search(key_pat + r"\s*:\s*\{", raw)
        if not m:
            continue
        # from the '{' after the colon, walk braces to find end
        start = raw.find("{", m.end() - 1)
        if start == -1:
            continue
        depth = 0
        end = -1
        for i, c in enumerate(raw[start:], start):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != -1:
            obj_text = raw[start:end+1]
            try:
                parsed = json.loads(_sanitize_trailing_commas(obj_text))
                mul = parsed.get("multiplier", 1.0)
                try:
                    mul = float(mul)
                except Exception:
                    mul = 1.0
                mul = max(0.5, min(3.0, mul))
                reason = _shorten_reason(parsed.get("reason", "default 1.0"))
                out[fid] = {"multiplier": mul, "reason": reason}
            except Exception:
                # ignore parse error for this fid
                pass
    return out

def run_severity(claim_id: str, temperature: float = 0.1, verbose: bool = True) -> None:
    p = paths_for_claim(claim_id)
    in_case  = p.reports_dir / "case.json"
    out_path = p.reports_dir / "severity.json"
    raw_path = p.reports_dir / "severity_raw.txt"  # append per batch for debugging
    err_path = p.reports_dir / "severity_error.log"

    data  = json.loads(in_case.read_text(encoding="utf-8"))
    case  = data.get("case") or {}
    flags = data.get("flags") or []

    all_ids = [f["id"] for f in flags]
    if not all_ids:
        write_json_utf8(out_path, {})
        if verbose:
            print(f"[severity] no flags; wrote empty {out_path}")
        return

    # Keep the case text compact to reduce token usage
    compact_case = {
        "summary": case.get("summary", "")[:2500],  # safety cap
        "verdict": case.get("verdict", ""),
        "notes":   (case.get("notes") or "")[:800]
    }

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(model_name="gemini-2.5-pro")

    final_map: Dict[str, Dict[str, object]] = {}

    # Clear previous raw file
    try:
        raw_path.write_text("", encoding="utf-8")
    except Exception:
        pass

    # Batch over flags
    for i in range(0, len(flags), BATCH_SIZE):
        batch = flags[i:i+BATCH_SIZE]
        batch_ids = [f["id"] for f in batch]
        flags_for_batch = [{
            "id": f["id"],
            "title": f.get("title",""),
            "direction": f.get("direction",""),
            "citations": f.get("citations",[]),
            "details": f.get("details","")
        } for f in batch]

        payload = {
            "allowed_ids": batch_ids,
            "case": compact_case,
            "flags": flags_for_batch
        }

        raw_text = None
        try:
            resp = model.generate_content(
                [PROMPT, json.dumps(payload, ensure_ascii=False)],
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    top_p=0.9,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    response_mime_type="application/json"
                )
            )
            raw_text = resp.text or "{}"
        except Exception as e:
            raw_text = f"<<EXCEPTION DURING GENERATION>>\n{e}\n\n{traceback.format_exc()}"

        # Append raw for this batch
        try:
            with raw_path.open("a", encoding="utf-8") as fh:
                fh.write(f"\n\n### BATCH {i//BATCH_SIZE + 1} ({len(batch_ids)} ids)\n")
                fh.write(raw_text)
                fh.write("\n")
        except Exception:
            pass

        # Parse (normal path)
        parsed_map: Dict[str, Dict[str, object]] = {}
        try:
            body = _sanitize_trailing_commas(_extract_json_object(raw_text))
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                for fid in batch_ids:
                    item = parsed.get(fid, {})
                    if isinstance(item, dict):
                        mul = item.get("multiplier", 1.0)
                        try:
                            mul = float(mul)
                        except Exception:
                            mul = 1.0
                        mul = max(0.5, min(3.0, mul))
                        reason = _shorten_reason(item.get("reason", "default 1.0"))
                        parsed_map[fid] = {"multiplier": mul, "reason": reason}
        except Exception as e:
            # Salvage any complete items in this raw batch
            try:
                salvaged = _salvage_partial(raw_text, batch_ids)
                parsed_map.update(salvaged)
                if not salvaged:
                    # log only if nothing salvaged
                    with err_path.open("a", encoding="utf-8") as eh:
                        eh.write(f"\nBATCH {i//BATCH_SIZE + 1} parse failed: {e}\n")
            except Exception:
                pass

        # Fill defaults for any missing in this batch
        for fid in batch_ids:
            if fid not in parsed_map:
                parsed_map[fid] = {"multiplier": 1.0, "reason": "default 1.0"}

        final_map.update(parsed_map)

    # One last safety pass on bounds
    for fid, item in final_map.items():
        try:
            m = float(item.get("multiplier", 1.0))
        except Exception:
            m = 1.0
        final_map[fid]["multiplier"] = max(0.5, min(3.0, m))
        final_map[fid]["reason"] = _shorten_reason(item.get("reason", "default 1.0"))

    write_json_utf8(out_path, final_map)
    if verbose:
        print(f"[severity] wrote {out_path} (ids={len(final_map)})")
