# medlegal/preprocess/form_parser.py
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import DOC_AI, paths_for_claim
from ._docai_client import process_pdf_local
from utils.io import write_json_utf8, write_text_utf8

FORM_CATS = ["Bills", "Forms"]

def _form_one(page_pdf: Path, out_json: Path) -> str:
    doc = process_pdf_local(page_pdf, DOC_AI["form"], pages=[1])
    write_json_utf8(out_json / f"{page_pdf.stem}.form.json", doc)
    return page_pdf.name

def run_form_parser(claim_id: str, max_workers: int = 8, verbose: bool = True) -> None:
    p = paths_for_claim(claim_id)
    p.docai_json.mkdir(parents=True, exist_ok=True)

    pages = []
    for cat in FORM_CATS:
        cat_dir = p.classified_pages / cat
        if cat_dir.exists():
            pages.extend(sorted(cat_dir.glob("*.pdf")))

    if not pages:
        print("[form] no Bills/Forms pages")
        return
    if verbose:
        print(f"[form] pages: {len(pages)} across {FORM_CATS}")

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_form_one, pg, p.docai_json): pg for pg in pages}
        for fut in as_completed(futures):
            pg = futures[fut]
            try:
                name = fut.result()
                if verbose:
                    print(f"[form] ✔ {name}")
            except Exception as e:
                err_path = p.docai_json / f"{pg.stem}.form.ERROR.txt"
                write_text_utf8(err_path, str(e))
                print(f"[form] ✗ {pg.name} -> {err_path.name}: {e}")
