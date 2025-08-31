# medlegal/storage/index.py  (only the build_chunks_and_index shown)
from __future__ import annotations
from pathlib import Path
import json, re, sqlite3, hashlib
from typing import Iterable, Tuple, List, Dict
from config import paths_for_claim

HEADER_RE = re.compile(r"^===\s+([A-Za-z]+)#(\d+)\s+::\s+(.+?)\s+===\s*$")

def _yield_sections(all_text: str) -> Iterable[Tuple[str,int,str,str]]:
    lines = all_text.splitlines()
    curr_cat, curr_page, curr_fn, buf = None, None, None, []
    for ln in lines:
        m = HEADER_RE.match(ln.strip())
        if m:
            if curr_cat is not None:
                yield curr_cat, curr_page, curr_fn, "\n".join(buf).strip()
            curr_cat, curr_page, curr_fn = m.group(1), int(m.group(2)), m.group(3)
            buf = []
        else:
            buf.append(ln)
    if curr_cat is not None:
        yield curr_cat, curr_page, curr_fn, "\n".join(buf).strip()

def _chunk_text(text: str, chunk_chars: int = 1500, overlap: int = 200) -> List[Tuple[int,int,str]]:
    text = text.strip()
    if not text:
        return []
    out, i, n = [], 0, len(text)
    while i < n:
        j = min(i + chunk_chars, n)
        if j < n:
            k = text.rfind("\n", i+1000, j)
            if k != -1 and k > i:
                j = k
        out.append((i, j, text[i:j]))
        if j == n: break
        i = max(0, j - overlap)
    return out

def build_chunks_and_index(claim_id: str,
                           chunk_chars: int = 1500,
                           overlap: int = 200,
                           verbose: bool = True) -> Path:
    p = paths_for_claim(claim_id)

    text_dir = p.text_dir
    all_txt  = text_dir / "ALL.txt"
    assert all_txt.exists(), f"{all_txt} not found (run 'collect' first)"

    with open(all_txt, "r", encoding="utf-8") as fh:
        all_text = fh.read()

    out_chunks = text_dir / "chunks.jsonl"
    total_chunks = 0
    section_counters: Dict[tuple, int] = {}

    with open(out_chunks, "w", encoding="utf-8") as f:
        for cat, page, fn, section_text in _yield_sections(all_text):
            key = (cat, page, fn)
            section_no = section_counters.get(key, 0)
            section_counters[key] = section_no + 1

            cite = f"{cat}#{page}"
            for cidx, (s,e,chunk) in enumerate(_chunk_text(section_text, chunk_chars, overlap)):
                # 🔒 Make chunk_id globally unique & deterministic
                h = hashlib.sha1(f"{cat}|{page}|{fn}|{s}|{e}|{len(chunk)}".encode("utf-8")).hexdigest()[:10]
                chunk_id = f"{cat}_{page}_s{section_no}_c{cidx}_{h}"

                rec = {
                    "chunk_id": chunk_id,
                    "category": cat,
                    "page": page,
                    "citation": cite,
                    "filename": fn,
                    "start": s,
                    "end": e,
                    "text": chunk,
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                total_chunks += 1

    if verbose:
        print(f"[index] wrote {out_chunks} ({total_chunks} chunks)")

    idx_dir = p.index_dir
    idx_dir.mkdir(parents=True, exist_ok=True)
    db_path = idx_dir / "index.db"
    if db_path.exists():
        try: db_path.unlink()
        except Exception: pass

    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE chunks (
      chunk_id TEXT PRIMARY KEY,
      category TEXT,
      page INTEGER,
      citation TEXT,
      filename TEXT,
      start INTEGER,
      end INTEGER
    );
    CREATE VIRTUAL TABLE chunks_fts USING fts5(
      chunk_id UNINDEXED,
      content,
      citation UNINDEXED,
      category UNINDEXED,
      filename UNINDEXED
    );
    """)
    con.commit()

    rows, fts_rows = [], []
    with open(out_chunks, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            rows.append((
                rec["chunk_id"], rec["category"], rec["page"],
                rec["citation"], rec["filename"], rec["start"], rec["end"]
            ))
            fts_rows.append((
                rec["chunk_id"], rec["text"], rec["citation"],
                rec["category"], rec["filename"]
            ))
    cur.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?,?)", rows)
    cur.executemany(
        "INSERT INTO chunks_fts (chunk_id,content,citation,category,filename) VALUES (?,?,?,?,?)",
        fts_rows
    )
    con.commit()
    con.close()

    if verbose:
        print(f"[index] built SQLite FTS at {db_path}")
    return db_path
