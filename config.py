# medlegal/config.py
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# -------------------------------------------------------------------
# 1) Env & constants
# -------------------------------------------------------------------
load_dotenv()

GOOGLE_APPLICATION_CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
DOC_LOCATION = os.environ.get("DOC_LOCATION", "us")

DOC_AI_CLASSIFIER_ID = os.environ.get("DOC_AI_CLASSIFIER_ID")
DOC_AI_CLASSIFIER_VERSION_ID = os.environ.get("DOC_AI_CLASSIFIER_VERSION_ID")  # optional
DOC_AI_LAYOUT_ID     = os.environ.get("DOC_AI_LAYOUT_ID")
DOC_AI_OCR_ID        = os.environ.get("DOC_AI_OCR_ID")
DOC_AI_FORM_ID       = os.environ.get("DOC_AI_FORM_ID")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Default samples root (can be overridden by MEDLEGAL_SAMPLES_DIR)
SAMPLES_DIR = Path(os.environ.get("MEDLEGAL_SAMPLES_DIR", "samples")).resolve()
MAX_PAGES_PER_PDF = int(os.environ.get("MAX_PAGES_PER_PDF", "30"))

# Basic validation (keep this strict to surface misconfig early)
_missing = [
    k for k, v in dict(
        GOOGLE_APPLICATION_CREDENTIALS=GOOGLE_APPLICATION_CREDENTIALS,
        GCP_PROJECT_ID=GCP_PROJECT_ID,
        DOC_LOCATION=DOC_LOCATION,
        DOC_AI_CLASSIFIER_ID=DOC_AI_CLASSIFIER_ID,
        DOC_AI_LAYOUT_ID=DOC_AI_LAYOUT_ID,
        DOC_AI_OCR_ID=DOC_AI_OCR_ID,
        DOC_AI_FORM_ID=DOC_AI_FORM_ID,
        GEMINI_API_KEY=GEMINI_API_KEY,
    ).items() if not v
]
if _missing:
    raise RuntimeError(f"Missing required env vars: {', '.join(_missing)}")

# -------------------------------------------------------------------
# 2) DocAI paths (versioned or default)
# -------------------------------------------------------------------
def processor_path(proc_id: str) -> str:
    """projects/{project}/locations/{loc}/processors/{id}"""
    return f"projects/{GCP_PROJECT_ID}/locations/{DOC_LOCATION}/processors/{proc_id}"

def processor_version_path(proc_id: str, version_id: str) -> str:
    """projects/{project}/locations/{loc}/processors/{id}/processorVersions/{version_id}"""
    return (
        f"projects/{GCP_PROJECT_ID}/locations/{DOC_LOCATION}/processors/"
        f"{proc_id}/processorVersions/{version_id}"
    )

DOC_AI = {
    "classifier": (
        processor_version_path(DOC_AI_CLASSIFIER_ID, DOC_AI_CLASSIFIER_VERSION_ID)
        if DOC_AI_CLASSIFIER_VERSION_ID else
        processor_path(DOC_AI_CLASSIFIER_ID)
    ),
    "layout": processor_path(DOC_AI_LAYOUT_ID),
    "ocr":    processor_path(DOC_AI_OCR_ID),
    "form":   processor_path(DOC_AI_FORM_ID),
}

# -------------------------------------------------------------------
# 3) File layout helpers (backward-compatible)
# -------------------------------------------------------------------
SAMPLES_ROOT = SAMPLES_DIR
INPUT_ROOT   = SAMPLES_ROOT / "input_docs"
PROC_ROOT    = SAMPLES_ROOT / "processed"

@dataclass
class ClaimPaths:
    claim_id: str

    # --- canonical roots ---
    @property
    def samples_root(self) -> Path:
        return SAMPLES_ROOT

    @property
    def input_docs(self) -> Path:
        """samples/input_docs/<claim_id>"""
        p = INPUT_ROOT / self.claim_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def processed_root(self) -> Path:
        """samples/processed/<claim_id>"""
        p = PROC_ROOT / self.claim_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    # Back-compat alias some modules still use
    @property
    def claim_root(self) -> Path:
        """Alias to processed_root (legacy name)"""
        return self.processed_root

    # --- subdirs ---
    @property
    def pages(self) -> Path:
        p = self.processed_root / "01_pages"
        p.mkdir(parents=True, exist_ok=True)
        return p

    # legacy alias used by older classifier code
    @property
    def pages_1p(self) -> Path:
        return self.pages

    @property
    def classified_pages(self) -> Path:
        p = self.processed_root / "03_classified_pages"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def docai_json(self) -> Path:
        p = self.processed_root / "04_docai_json"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def pandas_out(self) -> Path:
        p = self.processed_root / "06_pandas"
        p.mkdir(parents=True, exist_ok=True)
        return p

    # legacy alias
    @property
    def pandas(self) -> Path:
        return self.pandas_out

    @property
    def text_dir(self) -> Path:
        p = self.processed_root / "07_text"
        p.mkdir(parents=True, exist_ok=True)
        return p

    # legacy alias
    @property
    def text(self) -> Path:
        return self.text_dir

    @property
    def reports_dir(self) -> Path:
        p = self.processed_root / "08_reports"
        p.mkdir(parents=True, exist_ok=True)
        return p

    # legacy alias
    @property
    def reports(self) -> Path:
        return self.reports_dir

    @property
    def index_dir(self) -> Path:
        p = self.processed_root / "index"
        p.mkdir(parents=True, exist_ok=True)
        return p

def paths_for_claim(claim_id: str) -> ClaimPaths:
    """
    Single entry-point for consumers. Returns a ClaimPaths that creates dirs lazily.
    """
    # Ensure top-level roots exist (so API endpoints can show them immediately)
    INPUT_ROOT.mkdir(parents=True, exist_ok=True)
    PROC_ROOT.mkdir(parents=True, exist_ok=True)
    return ClaimPaths(claim_id)

__all__ = [
    # env
    "GOOGLE_APPLICATION_CREDENTIALS", "GCP_PROJECT_ID", "DOC_LOCATION",
    "DOC_AI_CLASSIFIER_ID", "DOC_AI_CLASSIFIER_VERSION_ID",
    "DOC_AI_LAYOUT_ID", "DOC_AI_OCR_ID", "DOC_AI_FORM_ID",
    "GEMINI_API_KEY", "SAMPLES_DIR", "SAMPLES_ROOT", "INPUT_ROOT",
    "PROC_ROOT", "MAX_PAGES_PER_PDF",
    # docai helpers
    "processor_path", "processor_version_path", "DOC_AI",
    # paths
    "ClaimPaths", "paths_for_claim",
]
