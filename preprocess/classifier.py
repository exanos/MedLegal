import re, shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import DOC_AI, paths_for_claim
from ._docai_client import process_pdf_local
from utils.io import write_json_utf8, write_text_utf8

# Your categories (exact strings)
CATEGORIES = [
    "Bills","DischargeSummaries","er_notes","Forms","Graphs","InsuranceClaims",
    "MedicalDrawings","PatientHistory","PoliceReports","Scans","Visualizations","other"
]

_norm_re = re.compile(r"[^a-z0-9]+")
def _norm(s: str) -> str:
    return _norm_re.sub("", (s or "").lower())

CANON = { _norm(c): c for c in CATEGORIES if c != "other" }

# --- local fallback (keywords -> category), very permissive ---
KEYMAP = [
    (("invoice","amount due","bill to","total","charges","statement"), "Bills"),
    (("form","application","signature","checkbox","date of birth","policyholder"), "Forms"),
    (("discharge summary","admission","discharge diagnosis","hospital course"), "DischargeSummaries"),
    (("emergency department","er note","ed note","triage","chief complaint"), "er_notes"),
    (("police report","case #","officer","badge","citation","accident report"), "PoliceReports"),
    (("claim number","insurer","adjuster","policy #","coverage","deductible"), "InsuranceClaims"),
    (("mri","ct","x-ray","xr","radiology report","imaging"), "Scans"),
    (("ecg","ekg","cardiogram","bpm","lead ii","rhythm"), "Graphs"),
    (("history of present illness","past medical history","pmh","allergies"), "PatientHistory"),
    (("diagram","drawing","illustration","operative sketch"), "MedicalDrawings"),
    (("collision scene","impact diagram","sketch of accident","vehicle position"), "Visualizations"),
]
def _fallback_from_text(text: str) -> str:
    t = (text or "").lower()
    for keys, cat in KEYMAP:
        if any(k in t for k in keys):
            return cat
    return "other"

# Confidence gate off (we’ll accept low conf too per your note)
CONFIDENCE_THRESHOLD = 0.0

def _to_canonical(label: str) -> str:
    n = _norm(label)
    return CANON.get(n, "other")

def _extract_candidates(doc: dict) -> list[tuple[str, float, str]]:
    out = []

    # Entities
    for ent in (doc.get("entities") or []):
        e_type = ent.get("type") or ""
        e_mention = ent.get("mentionText") or ent.get("mention_text") or ""
        conf = ent.get("confidence", None)
        conf = float(conf) if conf not in (None, "") else None

        # sometimes the label is in 'type'
        if _to_canonical(e_type) != "other":
            out.append((e_type, conf, "entity.type"))
        # sometimes it's the mention text
        if _to_canonical(e_mention) != "other":
            out.append((e_mention, conf, "entity.mentionText"))

        # properties may also contain labels
        for prop in (ent.get("properties") or []):
            p_type = prop.get("type") or ""
            p_mention = prop.get("mentionText") or ""
            p_conf = prop.get("confidence", conf)
            p_conf = float(p_conf) if p_conf not in (None, "") else conf
            if _to_canonical(p_type) != "other":
                out.append((p_type, p_conf, "entity.prop.type"))
            if _to_canonical(p_mention) != "other":
                out.append((p_mention, p_conf, "entity.prop.mentionText"))

    # Top-level classification(s)
    for key in ("classification","classifications"):
        if key in doc:
            blocks = doc[key] if isinstance(doc[key], list) else [doc[key]]
            for b in blocks:
                lbl = b.get("category") or b.get("type") or b.get("label") or ""
                conf = b.get("confidence", None)
                conf = float(conf) if conf not in (None, "") else None
                if _to_canonical(lbl) != "other":
                    out.append((lbl, conf, f"document.{key}"))

    return out

def _best(cands):
    if not cands: return None
    return max(((l, (c if c is not None else 1.0), s) for (l,c,s) in cands), key=lambda t: t[1])

def _classify_one(page_pdf: Path, out_base: Path) -> tuple[str,str,dict]:
    # force the fields we care about
    fm = "entities,classification,classifications,text"
    doc = process_pdf_local(page_pdf, DOC_AI["classifier"], pages=[1], field_mask=fm)

    cands = _extract_candidates(doc)
    debug = [{"label": l, "confidence": c, "source": s, "mapped": _to_canonical(l)} for (l,c,s) in cands]
    write_json_utf8(out_base / f"{page_pdf.stem}.labels.json", {"candidates": debug})

    best = _best(cands)
    if best:
        raw, conf, _ = best
        mapped = _to_canonical(raw)
        final = mapped if (conf is None or conf >= CONFIDENCE_THRESHOLD) else "other"
    else:
        # --- fallback from text ---
        final = _fallback_from_text(doc.get("text",""))

    dst_dir = out_base / final
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(page_pdf, dst_dir / page_pdf.name)
    write_json_utf8(dst_dir / f"{page_pdf.stem}.classified.json", doc)
    return page_pdf.name, final, {"best": best, "": final if best is None else None}

def run_classify(claim_id: str, max_workers: int = 8, verbose: bool = True) -> None:
    p = paths_for_claim(claim_id)
    p.classified_pages.mkdir(parents=True, exist_ok=True)
    for c in CATEGORIES: (p.classified_pages / c).mkdir(parents=True, exist_ok=True)

    pages = sorted(p.pages.glob("*.pdf"))  # instead of p.pages_1p
    if verbose:
        print(f"[classify] pages: {len(pages)} from {p.pages.glob("*.pdf")}")
        print(f"[classify] using processor: {DOC_AI['classifier']}")

    if not pages:
        print("[classify] no single-page PDFs found; did you run 'split'?")
        return

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_classify_one, pg, p.classified_pages): pg for pg in pages}
        for fut in as_completed(futures):
            pg = futures[fut]
            try:
                name, cat, info = fut.result()
                if verbose:
                    print(f"[classify] ✔ {name} → {cat} ({'' if info['best'] is None else 'model'})")
            except Exception as e:
                err_path = p.classified_pages / f"{pg.stem}.classify.ERROR.txt"
                write_text_utf8(err_path, str(e))
                print(f"[classify] ✗ {pg.name} -> {err_path.name}: {e}")
