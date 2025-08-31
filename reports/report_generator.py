# medlegal/reports/report_generator.py (only run_report shown)
from __future__ import annotations
from pathlib import Path
import json
from config import paths_for_claim
from utils.io import write_text_utf8

def _sec(title: str) -> str:
    return f"\n\n# {title}\n"

def _md_table(rows, headers):
    # simple Markdown table builder
    out = []
    out.append("| " + " | ".join(headers) + " |")
    out.append("| " + " | ".join("---" for _ in headers) + " |")
    out.extend("| " + " | ".join(str(c) for c in r) + " |" for r in rows)
    return "\n".join(out)

def run_report(claim_id: str, top_k: int = 8, verbose: bool = True) -> None:
    p = paths_for_claim(claim_id)
    out_dir = p.reports_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    case = json.loads((out_dir / "case.json").read_text(encoding="utf-8"))
    sev  = json.loads((out_dir / "severity.json").read_text(encoding="utf-8"))
    sc   = json.loads((out_dir / "scoring.json").read_text(encoding="utf-8"))

    lines = []
    lines.append(f"# Insurance Claim – Automated Draft\n**Claim ID:** {claim_id}\n")
    lines.append(_sec("Executive Summary"))
    c = case.get("case", {})
    lines.append(f"- **Verdict (preliminary):** {c.get('verdict','Not stated')}")
    lines.append(f"- **Estimated payable:** {c.get('estimated_payable_amount','Not stated')}")
    lines.append(f"- **Confidence:** {sc.get('confidence',0.5):.2f}")
    if c.get("notes"):
        lines.append(f"- **Notes:** {c['notes']}")

    lines.append(_sec("Case Summary"))
    lines.append(c.get("summary","Not available"))

    # Full matrix (id, title, direction, score, multiplier, weighted, citations, details)
    flags = sc.get("flags", [])
    # enrich with details from case.flags
    details_map = {f["id"]: f.get("details","") for f in case.get("flags", [])}
    rows = []
    for r in flags:
        fid = r["id"]
        mult = sev.get(fid, {}).get("multiplier", 1.0)
        cites = ", ".join(r.get("citations", [])[:8]) or "—"
        rows.append([
            fid,
            r.get("title",""),
            r.get("direction",""),
            f"{r.get('score',0):+}",
            f"{mult:.2f}",
            f"{r.get('weighted',0.0):+.2f}",
            cites,
            details_map.get(fid,"")
        ])

    lines.append(_sec("Full Flag Matrix"))
    lines.append(_md_table(
        rows,
        ["ID","Title","Dir","Score","Multiplier","Weighted","Citations","Details"]
    ))

    # Top lists
    flags_sorted = sorted(flags, key=lambda r: abs(r.get("weighted",0.0)), reverse=True)
    sup = [f for f in flags_sorted if f.get("weighted",0) > 0][:top_k]
    red = [f for f in flags_sorted if f.get("weighted",0) < 0][:top_k]

    def _fmt_flag(f):
        fid = f["id"]
        mult = sev.get(fid, {}).get("multiplier", 1.0)
        cites = ", ".join(f.get("citations", [])[:6]) or "—"
        return (f"- **{fid}** ({f.get('title','')}) · dir={f.get('direction','')} · "
                f"score={f.get('score',0)}, mult={mult} → **weighted={f.get('weighted',0):+.2f}** · cites: {cites}")

    lines.append(_sec("Top Supporting Points"))
    lines += [_fmt_flag(f) for f in sup] or ["(none)"]

    lines.append(_sec("Top Red Flags / Contradictions"))
    lines += [_fmt_flag(f) for f in red] or ["(none)"]

    out_md = out_dir / f"{claim_id}_report.md"
    write_text_utf8(out_md, "\n".join(lines))
    if verbose:
        print(f"[report] wrote {out_md}")
