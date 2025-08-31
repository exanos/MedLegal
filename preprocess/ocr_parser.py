from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import DOC_AI, paths_for_claim
from ._docai_client import process_pdf_local
from utils.io import write_json_utf8, write_text_utf8
import json

# Everything except Bills & Forms goes to OCR if we don't already have text
OCR_CATS = [
    "DischargeSummaries","er_notes","Graphs","InsuranceClaims","MedicalDrawings",
    "PatientHistory","PoliceReports","Scans","Visualizations","other"
]

def _has_text(json_path: Path) -> bool:
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        return bool(data.get("text"))
    except Exception:
        return False

def _ocr_one(page_pdf: Path, out_json: Path) -> str:
    # if classifier JSON (any cat) already saved with text, skip
    # we search sibling *_classified.json we wrote during classify
    classified_json = list(page_pdf.parent.glob(f"{page_pdf.stem}.classified.json"))
    if classified_json and _has_text(classified_json[0]):
        # copy classifier json into docai_json as the ocr output for consistency
        target = out_json / f"{page_pdf.stem}.ocr.json"
        if not target.exists():
            target.write_text(classified_json[0].read_text(encoding="utf-8"), encoding="utf-8")
        return f"{page_pdf.name} (skipped; already had text)"
    doc = process_pdf_local(page_pdf, DOC_AI["ocr"], pages=[1], field_mask="text,pages.page_number,layout")
    write_json_utf8(out_json / f"{page_pdf.stem}.ocr.json", doc)
    return page_pdf.name

def run_ocr(claim_id: str, max_workers: int = 8, verbose: bool = True) -> None:
    p = paths_for_claim(claim_id)
    p.docai_json.mkdir(parents=True, exist_ok=True)
    pages = []
    for cat in OCR_CATS:
        cat_dir = p.classified_pages / cat
        if cat_dir.exists():
            pages.extend(sorted(cat_dir.glob("*.pdf")))
    if verbose:
        print(f"[ocr] pages: {len(pages)} across {OCR_CATS}")

    if not pages:
        print("[ocr] nothing to OCR")
        return

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_ocr_one, pg, p.docai_json): pg for pg in pages}
        for fut in as_completed(futures):
            pg = futures[fut]
            try:
                msg = fut.result()
                if verbose:
                    print(f"[ocr] ✔ {msg}")
            except Exception as e:
                err_path = p.docai_json / f"{pg.stem}.ocr.ERROR.txt"
                write_text_utf8(err_path, str(e))
                print(f"[ocr] ✗ {pg.name} -> {err_path.name}: {e}")
