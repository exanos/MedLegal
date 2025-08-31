# medlegal/preprocess/normalize.py
from pathlib import Path
import json
import pandas as pd
from config import paths_for_claim
from utils.io import write_text_utf8
import hashlib

def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()

def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

def run_normalize(claim_id: str, verbose: bool = True) -> None:
    p = paths_for_claim(claim_id)
    out_dir = p.pandas
    out_dir.mkdir(parents=True, exist_ok=True)

    # Gather all doc JSONs (ocr + form) we produced
    jpaths = sorted((p.docai_json).glob("*.json"))
    if verbose:
        print(f"[normalize] input JSON files: {len(jpaths)} from {p.docai_json}")

    pages_rows = []
    forms_rows = []
    tables_rows = []

    for jp in jpaths:
        data = _read_json(jp)
        if not data: 
            continue

        # doc_id is stem of file (e.g., X_page_3.ocr/form)
        doc_id = jp.stem

        # category is the parent folder one level above the PDF (inside 03_classified_pages)
        # try to locate the matching pdf to infer the category
        cat_guess = None
        pdf_guess = p.classified_pages.rglob(f"{doc_id.split('.')[0]}.pdf")
        for g in pdf_guess:
            # parent folder under 03_classified_pages is the category
            cat_guess = g.parent.name
            break

        text = data.get("text", "") or ""
        # Dedup: hash to filter reduplicated blobs
        text_hash = _sha1(text)
        pages_rows.append({
            "doc_id": doc_id,
            "category": cat_guess or "unknown",
            "text_len": len(text),
            "text_hash": text_hash,
            "text": text[:20000]  # cap to keep CSV reasonable; raw JSON stays on disk
        })

        # --- extract form fields when present ---
        # DocAI Form Parser places fields at pages[].form_fields[*].fieldName/fieldValue -> text_anchor
        # Some versions also populate entities with normalized values.
        # We’ll read from pages[].form_fields first.
        for pg in (data.get("pages") or []):
            for ff in (pg.get("form_fields") or []):
                key = (ff.get("fieldName") or {}).get("text_anchor") or ff.get("field_name", {})
                val = (ff.get("fieldValue") or {}).get("text_anchor") or ff.get("field_value", {})
                key_text = key.get("content") or ""  # recent API includes content
                val_text = val.get("content") or ""
                forms_rows.append({
                    "doc_id": doc_id, "page_number": pg.get("page_number"),
                    "key": key_text, "value": val_text
                })

        # --- extract table cells into a flat table ---
        for pg in (data.get("pages") or []):
            for ti, tb in enumerate(pg.get("tables") or []):
                # headers
                headers = []
                for r in (tb.get("header_rows") or []):
                    cells = []
                    for c in (r.get("cells") or []):
                        blocks = (c.get("layout") or {}).get("text_anchor") or {}
                        cells.append(blocks.get("content",""))
                    headers.append("|".join(cells))
                header_text = headers[0] if headers else ""
                # body
                for ri, r in enumerate(tb.get("body_rows") or []):
                    vals = []
                    for c in (r.get("cells") or []):
                        blocks = (c.get("layout") or {}).get("text_anchor") or {}
                        vals.append(blocks.get("content",""))
                    tables_rows.append({
                        "doc_id": doc_id, "page_number": pg.get("page_number"),
                        "table_index": ti, "row_index": ri,
                        "header": header_text, "row": "|".join(vals)
                    })

    # Build DataFrames
    df_pages = pd.DataFrame(pages_rows)
    df_forms = pd.DataFrame(forms_rows)
    df_tables = pd.DataFrame(tables_rows)

    # Drop duplicate texts by hash (keep first)
    if not df_pages.empty:
        before = len(df_pages)
        df_pages = df_pages.drop_duplicates(subset=["text_hash"])
        after = len(df_pages)
        if verbose:
            print(f"[normalize] de-duplicated pages by text_hash: {before} → {after}")

    # Write compact CSVs
    df_pages.to_csv(out_dir / "pages.csv", index=False, encoding="utf-8")
    df_forms.to_csv(out_dir / "forms.csv", index=False, encoding="utf-8")
    df_tables.to_csv(out_dir / "tables.csv", index=False, encoding="utf-8")

    if verbose:
        print(f"[normalize] wrote {out_dir/'pages.csv'} ({len(df_pages)} rows)")
        print(f"[normalize] wrote {out_dir/'forms.csv'} ({len(df_forms)} rows)")
        print(f"[normalize] wrote {out_dir/'tables.csv'} ({len(df_tables)} rows)")
