# medlegal/preprocess/collect_text.py
from __future__ import annotations
import json, re
from pathlib import Path
from typing import Dict, List, Tuple
from config import DOC_AI, paths_for_claim
from utils.io import write_text_utf8, write_json_utf8
from preprocess._docai_client import process_pdf_local

# robust patterns: _page_<n>.pdf OR last number in filename
_PAGE_RE = re.compile(r"_page_(\d+)\.pdf$", re.IGNORECASE)
_LAST_NUM_RE = re.compile(r"(\d+)(?=\.pdf$)", re.IGNORECASE)

def _page_no(pdf: Path) -> int:
    m = _PAGE_RE.search(pdf.name)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    m2 = _LAST_NUM_RE.search(pdf.name)
    if m2:
        try:
            return int(m2.group(1))
        except Exception:
            pass
    return 1  # sensible default

def _load_text_from_json(jp: Path) -> str:
    try:
        data = json.loads(jp.read_text(encoding="utf-8"))
        # cover both shapes: {"text": "..."} or {"document": {"text": "..."}}
        if isinstance(data, dict):
            if "text" in data and isinstance(data["text"], str):
                return data["text"]
            if "document" in data and isinstance(data["document"], dict):
                t = data["document"].get("text")
                if isinstance(t, str):
                    return t
        return ""
    except Exception:
        return ""

def _ensure_text_for_page(pdf: Path, out_json_dir: Path) -> str:
    """
    Returns text for this single-page PDF by:
      1) using <stem>.classified.json if present
      2) else using <stem>.ocr.json if present
      3) else calls DocAI OCR once and writes <stem>.ocr.json, then returns text
    """
    # 1) classified
    classified_json = pdf.with_name(f"{pdf.stem}.classified.json")
    if classified_json.exists():
        txt = _load_text_from_json(classified_json)
        if txt:
            return txt

    # 2) OCR sidecar
    out_json_dir.mkdir(parents=True, exist_ok=True)
    ocr_json = out_json_dir / f"{pdf.stem}.ocr.json"
    if ocr_json.exists():
        txt = _load_text_from_json(ocr_json)
        if txt:
            return txt

    # 3) Run DocAI OCR once (single-page PDF → pages=[1])
    doc = process_pdf_local(pdf, DOC_AI["ocr"], pages=[1], field_mask="text")
    write_json_utf8(ocr_json, doc)
    return _load_text_from_json(ocr_json)

def run_collect_text(claim_id: str, verbose: bool = True) -> None:
    """
    Writes:
      07_text/
        ├─ ALL.txt
        ├─ <Category>.txt
        ├─ manifest.json      (category -> [pdf filenames])
        └─ citations.json     ({ "<pdf_stem>": { "category":..., "page":..., "citation": "Category#page" }, ... })
    """
    p = paths_for_claim(claim_id)

    text_dir = p.text_dir
    cats_root = p.classified_pages
    text_dir.mkdir(parents=True, exist_ok=True)

    # Build logical groups: if classified buckets exist and contain PDFs, use them;
    # otherwise fall back to a single ("other", pages) group.
    groups: List[Tuple[str, List[Path]]] = []
    classified_dirs = [d for d in cats_root.iterdir() if d.is_dir()] if cats_root.exists() else []

    total_classified = 0
    for d in sorted(classified_dirs, key=lambda x: x.name.lower()):
        pdfs = sorted(d.glob("*.pdf"), key=_page_no)
        if pdfs:
            groups.append((d.name, pdfs))
            total_classified += len(pdfs)

    if not groups:
        # fallback to raw pages
        raw_pages = sorted(p.pages.glob("*.pdf"), key=_page_no)
        if not raw_pages:
            print("[collect] no pages found; did you run 'split'?")
            return
        groups = [("other", raw_pages)]

    # Manifest & citations
    manifest: Dict[str, List[str]] = {}
    citations: Dict[str, Dict[str, object]] = {}

    # Per-category text files
    for cat, pdfs in groups:
        if verbose:
            print(f"[collect] {cat}: {len(pdfs)} page(s)")
        manifest[cat] = [pdf.name for pdf in pdfs]

        cat_lines: List[str] = []
        for pdf in pdfs:
            pg = _page_no(pdf)
            cite = f"{cat}#{pg}"
            stem = pdf.stem

            citations[stem] = {"category": cat, "page": pg, "citation": cite, "file": pdf.name}
            txt = _ensure_text_for_page(pdf, p.docai_json)

            cat_lines.append(f"\n\n=== {cite} :: {pdf.name} ===\n")
            cat_lines.append(txt or "[[NO_TEXT_EXTRACTED]]")

        write_text_utf8(text_dir / f"{cat}.txt", "\n".join(cat_lines))

    # ALL.txt in category+page order
    all_lines: List[str] = []
    for cat, pdfs in groups:
        for pdf in pdfs:
            pg = _page_no(pdf)
            cite = f"{cat}#{pg}"

            # prefer classified JSON if present; else OCR sidecar; else call OCR
            classified_json = pdf.with_name(f"{pdf.stem}.classified.json")
            if classified_json.exists():
                txt = _load_text_from_json(classified_json)
            else:
                txt = _ensure_text_for_page(pdf, p.docai_json)

            all_lines.append(f"\n\n=== {cite} :: {pdf.name} ===\n")
            all_lines.append(txt or "[[NO_TEXT_EXTRACTED]]")

    write_text_utf8(text_dir / "ALL.txt", "\n".join(all_lines))
    write_json_utf8(text_dir / "manifest.json", manifest)
    write_json_utf8(text_dir / "citations.json", citations)

    if verbose:
        print(f"[collect] wrote {text_dir/'ALL.txt'}")
        print(f"[collect] wrote {text_dir/'manifest.json'}")
        print(f"[collect] wrote {text_dir/'citations.json'}")
