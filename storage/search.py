# medlegal/storage/search.py
from __future__ import annotations
from pathlib import Path
import sqlite3
from typing import List, Dict, Any
from config import paths_for_claim

def search_chunks(claim_id: str, query: str, k: int = 10) -> List[Dict[str,Any]]:
    p = paths_for_claim(claim_id)
    claim_root = p.docai_json.parent.parent
    db_path = claim_root / "index" / "index.db"
    if not db_path.exists():
        raise FileNotFoundError(f"{db_path} not found; build index first.")

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    # FTS5 rank using bm25()
    sql = """
    SELECT c.chunk_id, c.category, c.page, c.citation, c.filename,
           snippets(chunks_fts, 1, '[', ']', ' … ', 12) AS snippet,
           bm25(chunks_fts) AS rank
    FROM chunks_fts
    JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
    WHERE chunks_fts MATCH ?
    ORDER BY rank LIMIT ?
    """
    cur.execute(sql, (query, k))
    out = []
    for row in cur.fetchall():
        out.append({
            "chunk_id": row[0],
            "category": row[1],
            "page": row[2],
            "citation": row[3],
            "filename": row[4],
            "snippet": row[5],
            "rank": row[6],
        })
    con.close()
    return out
