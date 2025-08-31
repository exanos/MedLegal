# server.py
from flask import Flask, request, send_from_directory, Response, jsonify
import os
import requests
import markdown

app = Flask(__name__, static_folder="static", static_url_path="/static")

# Point this to your running FastAPI (change port if you used a different one)
API_BASE = os.environ.get("MEDLEGAL_API_BASE", "http://127.0.0.1:8010")

@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.route("/upload", methods=["POST"])
def upload_file():
    """
    Accepts a single PDF and an optional claim_id.
    Proxies to FastAPI:
      - /claims/{claim_id}/ingest
      - /claims/{claim_id}/adjudicate
      - /claims/{claim_id}/report.md
    Returns: HTML (converted from Markdown) to render in the page.
    """
    if "pdf" not in request.files:
        return jsonify({"error": "No PDF file found"}), 400

    claim_id = request.form.get("claim_id") or "demo-claim-001"
    pdf_file = request.files["pdf"]

    if not pdf_file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Please upload a .pdf file"}), 400

    try:
        # 1) Ingest
        ingest_url = f"{API_BASE}/claims/{claim_id}/ingest"
        files = {"files": (pdf_file.filename, pdf_file.stream, "application/pdf")}
        r = requests.post(ingest_url, files=files, timeout=60)
        r.raise_for_status()

        # 2) Adjudicate (split → classify → collect → case → severity → score → report)
        adjudicate_url = f"{API_BASE}/claims/{claim_id}/adjudicate"
        r = requests.post(adjudicate_url, params={"workers": 6, "build_index": True}, timeout=600)
        r.raise_for_status()

        # 3) Fetch the Markdown report
        report_url = f"{API_BASE}/claims/{claim_id}/report.md"
        r = requests.get(report_url, timeout=60)
        r.raise_for_status()
        md_text = r.text

        # Convert Markdown → HTML (lightweight)
        html = markdown.markdown(
            md_text,
            extensions=["extra", "sane_lists", "tables", "nl2br"]
        )

        # Wrap in a simple container so we can style it on the client
        wrapped = f"""
        <div class="report-container">
            {html}
        </div>
        """

        return Response(wrapped, mimetype="text/html")

    except requests.HTTPError as e:
        return jsonify({"error": f"Upstream API error: {e.response.text}"}), 500
    except requests.RequestException as e:
        return jsonify({"error": f"Could not reach API at {API_BASE}: {e}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Flask dev server; change host/port as you like
    app.run(host="127.0.0.1", port=5000, debug=True)
