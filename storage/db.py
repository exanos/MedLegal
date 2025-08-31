# medlegal/storage/db.py
from pathlib import Path
import json, pandas as pd
from typing import Iterable
from google.cloud.documentai_toolbox import document as toolbox_doc
from config import paths_for_claim

def _load_doc(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

def _anchor_text(doc: dict, anchor: dict|None) -> str:
    if not anchor: return ""
    segs = anchor.get("textSegments", [])
    if not segs: return ""
    s = int(segs[0].get("startIndex", 0)); e = int(segs[0].get("endIndex", 0))
    return (doc.get("text") or "")[s:e]

def formfields_to_df(doc: dict, doc_id: str) -> pd.DataFrame:
    rows=[]
    for page_i, page in enumerate(doc.get("pages", []), start=1):
        for ff in page.get("formFields", []):
            key = _anchor_text(doc, ff.get("fieldName",{}).get("textAnchor"))
            val = _anchor_text(doc, ff.get("fieldValue",{}).get("textAnchor"))
            rows.append({"doc_id": doc_id, "page": page_i, "key": key, "value": val})
    return pd.DataFrame(rows)

def entities_to_df(doc: dict, doc_id: str) -> pd.DataFrame:
    rows=[]
    for ent in doc.get("entities", []):
        rows.append({
          "doc_id": doc_id,
          "type": ent.get("type"),
          "mentionText": ent.get("mentionText"),
          "normalized": ent.get("normalizedValue"),
          "confidence": ent.get("confidence"),
        })
    return pd.DataFrame(rows)

def tables_to_csvs(document_json_path: Path, out_dir: Path) -> list[Path]:
    """Export tables via Toolbox to CSV; returns list of CSV paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    wrapped = toolbox_doc.Document.from_document_path(document_path=str(document_json_path))
    csvs=[]
    for page in wrapped.pages:
        for idx, t in enumerate(page.tables):
            df = t.to_dataframe()
            base = out_dir / f"{document_json_path.stem}_p{page.page_number}_t{idx}"
            df.to_csv(base.with_suffix(".csv"), index=False)
            csvs.append(base.with_suffix(".csv"))
    return csvs

def text_chunks(doc: dict, doc_id: str, max_chars=3500, overlap=350) -> Iterable[dict]:
    text = doc.get("text") or ""
    i=0; n=len(text)
    while i<n:
        s=i; e=min(i+max_chars, n)
        yield {"doc_id": doc_id, "text_start": s, "text_end": e, "text": text[s:e]}
        i = e - overlap

def normalize_all(claim_id: str) -> None:
    p = paths_for_claim(claim_id)
    p.pandas_out.mkdir(parents=True, exist_ok=True)
    p.chunks_text.mkdir(parents=True, exist_ok=True)

    all_forms=[]; all_ents=[]
    for f in sorted(p.docai_json.glob("*.json")):
        doc = _load_doc(f); doc_id = f.stem
        df_form = formfields_to_df(doc, doc_id)
        if not df_form.empty: all_forms.append(df_form)
        df_ent = entities_to_df(doc, doc_id)
        if not df_ent.empty: all_ents.append(df_ent)

        # export tables for form docs
        if f.name.endswith(".form.json"):
            tables_to_csvs(f, p.artifacts_tables)

        # write text chunks
        with open(p.chunks_text / f"{doc_id}.jsonl", "w", encoding="utf-8") as w:
            for ch in text_chunks(doc, doc_id):
                w.write(json.dumps(ch, ensure_ascii=False) + "\n")

    if all_forms:
        pd.concat(all_forms, ignore_index=True).to_parquet(p.pandas_out / "form_fields.parquet")
    if all_ents:
        pd.concat(all_ents, ignore_index=True).to_parquet(p.pandas_out / "entities.parquet")
