# medlegal/llm/scorer.py
from __future__ import annotations
from pathlib import Path
import json
from config import paths_for_claim
from utils.io import write_json_utf8

def run_score(claim_id: str, verbose: bool = True) -> None:
    p = paths_for_claim(claim_id)
    out_dir  = p.reports_dir
    case_path = out_dir / "case.json"
    sev_path  = out_dir / "severity.json"
    out_path  = out_dir / "scoring.json"

    case = json.loads(case_path.read_text(encoding="utf-8"))

    # If severity.json is missing or corrupt, synthesize defaults (1.0)
    if not sev_path.exists():
        flags = case.get("flags") or []
        sev = {f["id"]: {"multiplier": 1.0, "reason": "default 1.0"} for f in flags}
    else:
        try:
            sev = json.loads(sev_path.read_text(encoding="utf-8"))
            if not isinstance(sev, dict):
                raise ValueError("severity.json is not a dict")
        except Exception:
            flags = case.get("flags") or []
            sev = {f["id"]: {"multiplier": 1.0, "reason": "default 1.0"} for f in flags}

    flags = case.get("flags") or []
    rows  = []
    total = 0.0
    max_possible = 0.0

    for f in flags:
        fid   = f["id"]
        try:
            score = float(f.get("score", 0))
        except Exception:
            score = 0.0
        try:
            mult  = float(sev.get(fid, {}).get("multiplier", 1.0))
        except Exception:
            mult = 1.0
        mult = max(0.5, min(3.0, mult))
        w     = score * mult
        rows.append({
            "id": fid,
            "title": f.get("title",""),
            "direction": f.get("direction",""),
            "score": score,
            "multiplier": mult,
            "weighted": w,
            "citations": f.get("citations",[])
        })
        total += w
        max_possible += abs(2.0 * mult)  # max magnitude per flag

    confidence = (total + max_possible) / (2.0 * max_possible) if max_possible > 0 else 0.5
    out = {
        "flags": rows,
        "sum_weighted": total,
        "max_possible": max_possible,
        "confidence": round(confidence, 4)
    }
    write_json_utf8(out_path, out)
    if verbose:
        print(f"[score] wrote {out_path} (confidence={out['confidence']})")
