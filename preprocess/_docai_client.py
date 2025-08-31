from typing import Optional
from pathlib import Path
from google.api_core.client_options import ClientOptions
from google.api_core.exceptions import GoogleAPICallError, NotFound, PermissionDenied, ResourceExhausted
from google.cloud import documentai
from google.protobuf.json_format import MessageToDict
from config import DOC_LOCATION

def _client():
    return documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=f"{DOC_LOCATION}-documentai.googleapis.com")
    )

def process_pdf_local(pdf_path: Path, processor_name: str,
                      pages: Optional[list[int]] = None,
                      field_mask: Optional[str] = None) -> dict:
    client = _client()
    with open(pdf_path, "rb") as f:
        content = f.read()
    raw = documentai.RawDocument(content=content, mime_type="application/pdf")
    opts = None
    if pages:
        opts = documentai.ProcessOptions(
            individual_page_selector=documentai.ProcessOptions.IndividualPageSelector(pages=pages)
        )
    req = documentai.ProcessRequest(
        name=processor_name, raw_document=raw,
        field_mask=field_mask, process_options=opts
    )
    try:
        result = client.process_document(request=req)
        return MessageToDict(result.document._pb, preserving_proto_field_name=True)
    except (NotFound, PermissionDenied, ResourceExhausted) as e:
        raise RuntimeError(f"[DocAI] processor='{processor_name}' file='{pdf_path.name}': {e}") from e
    except GoogleAPICallError as e:
        raise RuntimeError(f"[DocAI] call failed for '{pdf_path.name}': {e}") from e
    except Exception as e:
        raise RuntimeError(f"[DocAI] unexpected error for '{pdf_path.name}': {e}") from e
