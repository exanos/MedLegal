# medlegal/preprocess/layout.py
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import DOC_AI, paths_for_claim
from ._docai_client import process_pdf_local
from utils.io import write_json_utf8, write_text_utf8

def _layout_one(chunk_pdf: Path, out_dir: Path) -> str:
    doc = process_pdf_local(chunk_pdf, DOC_AI["layout"])
    write_json_utf8(out_dir / f"{chunk_pdf.stem}.layout.json", doc)
    return chunk_pdf.name

def run_layout(claim_id: str, max_workers: int = 8, verbose: bool = True) -> None:
    p = paths_for_claim(claim_id)
    p.layout_json.mkdir(parents=True, exist_ok=True)

    chunks = sorted(p.chunks_30p.glob("*.pdf"))
    if verbose:
        print(f"[layout] chunks: {len(chunks)} from {p.chunks_30p}")

    if not chunks:
        print(f"[layout] no chunks found. did you run 'split'?")
        return

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_layout_one, c, p.layout_json): c for c in chunks}
        for fut in as_completed(futures):
            c = futures[fut]
            try:
                name = fut.result()
                if verbose:
                    print(f"[layout] ✔ {name}")
            except Exception as e:
                err_path = p.layout_json / f"{c.stem}.layout.ERROR.txt"
                write_text_utf8(err_path, str(e))
                print(f"[layout] ✗ {c.name} -> {err_path.name}: {e}")
