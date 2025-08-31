# medlegal/preprocess/splitter.py
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from config import paths_for_claim
import shutil

def run_split(claim_id: str, max_pages: int | None = None, verbose: bool = True) -> int:
    p = paths_for_claim(claim_id)
    in_dir = p.input_docs
    out_dir = p.pages
    out_dir.mkdir(parents=True, exist_ok=True)

    # 🔧 Clean previous pages to avoid duplicates
    for f in out_dir.glob("*.pdf"):
        try:
            f.unlink()
        except Exception:
            pass

    pdfs = sorted(in_dir.glob("*.pdf"))
    if verbose:
        print(f"[split] found {len(pdfs)} PDF(s) in {in_dir}")

    written = 0
    for src in pdfs:
        reader = PdfReader(str(src))
        n = len(reader.pages)
        if verbose:
            print(f"[split] {src.name}: {n} page(s)")
        for i in range(n):
            pw = PdfWriter()
            pw.add_page(reader.pages[i])
            out = out_dir / f"{src.stem}_page_{i+1}.pdf"
            with out.open("wb") as f:
                pw.write(f)
            written += 1

    if verbose:
        print(f"[split] wrote {written} single-page PDFs to {out_dir}")
    return written
