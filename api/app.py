# medlegal/api/app.py
from __future__ import annotations
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from typing import List, Optional
from pathlib import Path
import shutil
import json

from config import paths_for_claim
from preprocess.splitter import run_split
from preprocess.classifier import run_classify
from preprocess.collect_text import run_collect_text
from storage.index import build_chunks_and_index
from llm.case_builder import run_case_builder
from llm.severity import run_severity
from llm.scorer import run_score
from reports.report_generator import run_report
from pathlib import Path

app = FastAPI(title="MedLegal API", version="0.1.0")
def _input_dir_for_claim(claim_id: str) -> Path:
    # Always samples/input_docs/<claim_id>
    in_dir = Path("samples") / "input_docs" / claim_id
    in_dir.mkdir(parents=True, exist_ok=True)
    return in_dir
@app.get("/health")
def health():
    return {"ok": True}

@app.post("/claims/{claim_id}/ingest")
async def ingest_claim(claim_id: str, files: list[UploadFile] = File(...)):
    in_dir = _input_dir_for_claim(claim_id)
    saved = []
    for f in files:
        if not f.filename.lower().endswith(".pdf"):
            raise HTTPException(400, f"Only PDF allowed: {f.filename}")
        dst = in_dir / f.filename
        with dst.open("wb") as out:
            out.write(await f.read())
        saved.append(dst.name)
    return {"claim_id": claim_id, "saved": saved, "input_dir": str(in_dir)}


@app.post("/claims/{claim_id}/adjudicate")
def adjudicate(claim_id: str, workers: int = 6, build_index: bool = True):
    p = paths_for_claim(claim_id)

    # 1) split → pages must exist
    run_split(claim_id)
    pages = list(p.pages.glob("*.pdf"))
    if not pages:
        raise HTTPException(400, f"No single-page PDFs in {p.pages}. Did you upload & split?")

    # 2) classify (idempotent)
    run_classify(claim_id, max_workers=workers)

    # 3) collect text (idempotent)
    run_collect_text(claim_id)

    # 4) index (optional)
    if build_index:
        build_chunks_and_index(claim_id)

    # 5) LLMs
    run_case_builder(claim_id)

    # Severity + Score + Report: keep going even if one has issues
    try:
        run_severity(claim_id)
    except Exception as e:
        # Last-ditch: create default severity so scorer & report can proceed
        from utils.io import write_json_utf8
        p2 = paths_for_claim(claim_id)
        case = json.loads((p2.reports_dir / "case.json").read_text(encoding="utf-8"))
        defaults = {f["id"]: {"multiplier": 1.0, "reason": "default 1.0"} for f in (case.get("flags") or [])}
        write_json_utf8(p2.reports_dir / "severity.json", defaults)

    try:
        run_score(claim_id)
    except Exception:
        # If this ever fails, there is nothing else to compute; re-raise
        raise

    try:
        run_report(claim_id)
    except Exception:
        # Report is just a view over JSON; don't kill the endpoint if it fails
        pass

    scoring_path = p.reports_dir / "scoring.json"
    report_path  = p.reports_dir / f"{claim_id}_report.md"
    case_path    = p.reports_dir / "case.json"
    severity_path= p.reports_dir / "severity.json"

    # validate
    for (pth, label) in [(case_path,"case.json"), (severity_path,"severity.json"),
                         (scoring_path,"scoring.json"), (report_path,"report.md")]:
        if not pth.exists():
            raise HTTPException(500, f"{label} not produced at {pth}")

    confidence = json.loads(scoring_path.read_text(encoding="utf-8")).get("confidence", 0.5)
    return JSONResponse({
        "claim_id": claim_id,
        "confidence": confidence,
        "paths": {
            "pages": str(p.pages),
            "classified_pages": str(p.classified_pages),
            "text_dir": str(p.text_dir),
            "reports_dir": str(p.reports_dir),
            "index_db": str((p.index_dir/"index.db")) if build_index else None
        },
        "artifacts": {
            "case": str(case_path),
            "severity": str(severity_path),
            "scoring": str(scoring_path),
            "report_md": str(report_path),
        }
    })

@app.get("/claims/{claim_id}/report.md")
def get_report_md(claim_id: str):
    p = paths_for_claim(claim_id)
    path = p.reports_dir / f"{claim_id}_report.md"
    if not path.exists():
        raise HTTPException(404, f"Report not found at {path}. Run /adjudicate first.")
    return PlainTextResponse(path.read_text(encoding="utf-8"))

'''@app.get("/claims/{claim_id}/search")
def search(claim_id: str, q: str, k: int = 10):
    """
    Keyword search over chunked dossier (SQLite FTS5).
    """
    res = search_chunks(claim_id, q, k)
    return {"claim_id": claim_id, "query": q, "results": res}
'''