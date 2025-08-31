# medlegal/tools/describe_processors.py
from google.api_core.client_options import ClientOptions
from google.cloud import documentai
from config import DOC_LOCATION, DOC_AI_CLASSIFIER_ID, DOC_AI_CLASSIFIER_VERSION_ID, GCP_PROJECT_ID

def main():
    client = documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=f"{DOC_LOCATION}-documentai.googleapis.com")
    )

    proc_name = f"projects/{GCP_PROJECT_ID}/locations/{DOC_LOCATION}/processors/{DOC_AI_CLASSIFIER_ID}"
    print("[describe] processor:", proc_name)
    proc = client.get_processor(name=proc_name)
    print("  display_name:", proc.display_name)
    print("  type:", proc.type_)  # e.g., CUSTOM_CLASSIFIER_PROCESSOR
    print("  default_version:", proc.default_processor_version)

    if DOC_AI_CLASSIFIER_VERSION_ID:
        ver_name = f"{proc_name}/processorVersions/{DOC_AI_CLASSIFIER_VERSION_ID}"
        ver = client.get_processor_version(name=ver_name)
        print("[describe] version:", ver.name)
        print("  display_name:", ver.display_name)
        print("  state:", ver.state)
        print("  type:", ver.processor_type)  # should still reflect classifier
    else:
        print("[describe] No DOC_AI_CLASSIFIER_VERSION_ID set")

if __name__ == "__main__":
    main()
