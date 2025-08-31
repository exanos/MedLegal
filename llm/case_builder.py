# medlegal/llm/case_builder.py
from __future__ import annotations
from pathlib import Path
import json, hashlib
from typing import List, Dict
import google.generativeai as genai
from config import GEMINI_API_KEY, paths_for_claim
from utils.io import write_json_utf8

MIN_FLAGS = 15

SYSTEM = """You are an insurance adjudication assistant.

RULES (read carefully):
- Use ONLY the dossier text provided in this conversation as your evidence.
- NEVER invent facts. If something is missing, say it’s not present in the dossier.
- Cite evidence using [Category#Page] tokens appearing in the dossier headers.
- Do not reveal chain-of-thought. Output concise, structured JSON only.
"""

TASK = f"""Build a coherent case from the full dossier, then produce >= {MIN_FLAGS} FLAGS with signed scores.

Scoring:
- score ∈ {{-2, -1, 0, +1, +2}}
  +2 strongly supports the case; -2 strongly contradicts; 0 neutral/uncertain.

Each flag MUST:
- include a short `title`,
- set `direction` ∈ {{support, contradict, neutral}} (consistent with score sign),
- include 1..N citations like [Bills#5], [PoliceReports#3] where possible,
- include 1–3 sentence `details` focused on dossier evidence (no speculation).

If the dossier cannot support {MIN_FLAGS} evidence-backed flags:
- still return exactly {MIN_FLAGS} items,
- for any missing ones, set `direction="neutral"`, `score=0`, `citations=[]`,
  and `details="Insufficient dossier evidence to ground this flag."`

Return strictly JSON using this schema:

{{
  "case": {{
    "summary": "Concise, evidence-grounded narrative of what happened",
    "verdict": "Approve | Deny | Needs human review",
    "estimated_payable_amount": "number OR a range string OR 'unknown'",
    "notes": "short notes, include key uncertainties"
  }},
  "flags": [
    {{
      "id": "F1",
      "title": "Short name",
      "direction": "support|contradict|neutral",
      "score": -2,
      "citations": ["Bills#5","PoliceReports#3"],
      "details": "1–3 sentences grounded in dossier text."
    }}
  ]
}}
"""

def _read_all_text(claim_id: str) -> str:
    p = paths_for_claim(claim_id)
    all_txt = p.text_dir / "ALL.txt"
    if not all_txt.exists():
        raise RuntimeError(f"[case] {all_txt} not found. Run 'collect' first.")
    return all_txt.read_text(encoding="utf-8")

def _chunk_text(s: str, max_chars: int = 180_000) -> List[str]:
    if len(s) <= max_chars:
        return [s]
    parts, i = [], 0
    while i < len(s):
        parts.append(s[i:i+max_chars])
        i += max_chars
    return parts

def _normalize_and_pad(payload: Dict) -> Dict:
    # Ensure flags exist, have ids F1.., proper direction, and at least MIN_FLAGS items
    flags = payload.get("flags") or []
    # Fix IDs and directions
    for idx, fl in enumerate(flags, 1):
        fl["id"] = fl.get("id") or f"F{idx}"
        sc = fl.get("score", 0)
        try:
            sc = int(sc)
        except Exception:
            sc = 0
        # Derive direction from score if missing/wrong
        dir_in = (fl.get("direction") or "").lower()
        if sc > 0:
            dir_out = "support"
        elif sc < 0:
            dir_out = "contradict"
        else:
            dir_out = "neutral"
        if dir_in not in {"support", "contradict", "neutral"}:
            fl["direction"] = dir_out
        else:
            fl["direction"] = dir_in or dir_out
        # Defensive defaults
        fl["title"] = fl.get("title") or f"Flag {idx}"
        fl["citations"] = fl.get("citations") or []
        fl["details"] = fl.get("details") or "No details provided."

    # Pad to MIN_FLAGS with neutral placeholders if needed
    n = len(flags)
    while len(flags) < MIN_FLAGS:
        k = len(flags) + 1
        flags.append({
            "id": f"F{k}",
            "title": "Insufficient evidence",
            "direction": "neutral",
            "score": 0,
            "citations": [],
            "details": "Insufficient dossier evidence to ground this flag."
        })

    payload["flags"] = flags[:MIN_FLAGS]
    payload["case"] = payload.get("case") or {}
    return payload

def run_case_builder(claim_id: str, temperature: float = 0.2, verbose: bool = True) -> None:
    p = paths_for_claim(claim_id)
    out_dir = p.reports_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    dossier = _read_all_text(claim_id)
    chunks = _chunk_text(dossier)

    if verbose:
        print(f"[case] feeding dossier: {sum(len(c) for c in chunks)} chars via {len(chunks)} part(s)")

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name="gemini-2.5-pro",
        system_instruction=SYSTEM
    )

    # Build content parts: label the dossier, then append all text parts, then the task
    parts: List[str] = [
        f"CLAIM {claim_id} DOSSIER. Use ONLY this text. Cite evidence as [Category#Page]."
    ]
    parts.extend(chunks)
    parts.append(TASK)

    resp = model.generate_content(
        parts,
        generation_config=genai.types.GenerationConfig(
            temperature=temperature,
            top_p=0.9,
            max_output_tokens=8192,
            response_mime_type="application/json"  # ← force JSON
        )
    )

    text = resp.text or "{}"
    # direct JSON is expected; still guard against wrappers
    start, end = text.find("{"), text.rfind("}")
    raw = text[start:end+1] if (start != -1 and end != -1) else "{}"

    try:
        payload = json.loads(raw)
    except Exception:
        payload = {}

    payload = _normalize_and_pad(payload)

    out = {
        "claim_id": claim_id,
        "case": payload.get("case") or {},
        "flags": payload.get("flags") or []
    }
    write_json_utf8(out_dir / "case.json", out)
    if verbose:
        print(f"[case] wrote {out_dir/'case.json'}")
