# medlegal/main.py
import argparse
from config import paths_for_claim
from preprocess.splitter import run_split
from preprocess.layout import run_layout
from preprocess.classifier import run_classify
from preprocess.ocr_parser import run_ocr
from preprocess.form_parser import run_form_parser
from preprocess.normalize import run_normalize
from llm.sifter import run_sifter
from llm.case_builder import run_case_builder
from llm.severity import run_severity
from llm.scorer import run_score
from reports.report_generator import run_report
from preprocess.collect_text import run_collect_text
from reports.simple_report import run_simple_report


def main():
    ap = argparse.ArgumentParser(description="Local-first insurance PoC pipeline")
    ap.add_argument("--claim-id", required=True)
    ap.add_argument("--steps", nargs="*", default=[
        "split","layout","classify","ocr","form","normalize","sift","case","severity","score","report"
    ], help="Subset of steps to run")
    ap.add_argument("--pdf", action="store_true", help="Also render PDF report")
    args = ap.parse_args()

    p = paths_for_claim(args.claim_id)
    # Ensure input dir exists
    p.raw_in.mkdir(parents=True, exist_ok=True)
    p.working.mkdir(parents=True, exist_ok=True)

    if "split" in args.steps:
        run_split(args.claim_id)
    if "layout" in args.steps:
        run_layout(args.claim_id)
    if "classify" in args.steps:
        run_classify(args.claim_id)
    if "ocr" in args.steps:
        run_ocr(args.claim_id)
    if "form" in args.steps:
        run_form_parser(args.claim_id)
    if "normalize" in args.steps:
        run_normalize(args.claim_id)
    if "sift" in args.steps:
        run_sifter(args.claim_id)
    if "case" in args.steps:
        run_case_builder(args.claim_id)
    if "severity" in args.steps:
        run_severity(args.claim_id)
    if "score" in args.steps:
        run_score(args.claim_id)
    # In main(), add:
    if "collect" in args.steps:
        run_collect_text(args.claim_id)
    if "report" in args.steps or "simple_report" in args.steps:
        run_report(args.claim_id)

if __name__ == "__main__":
    main()
