from __future__ import annotations

from pathlib import Path

from docling_serve.datamodel.convert import ConvertDocumentsRequestOptions

from docling.datamodel.base_models import OutputFormat
from docling.service_client import DoclingServiceClient

BASE_URL = "http://127.0.0.1:5001"
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PACKAGE_ROOT / "tests"


def create_conversion_options() -> ConvertDocumentsRequestOptions:
    return ConvertDocumentsRequestOptions(
        do_ocr=False,
        do_table_structure=False,
        include_images=False,
        to_formats=[OutputFormat.JSON],
        abort_on_error=False,
    )


def run_convert(client: DoclingServiceClient) -> None:
    print("\n=== convert() (single source) ===")
    result = client.convert(
        source=FIXTURES_DIR / "2206.01062v1.pdf",
        options=create_conversion_options(),
    )
    print("status:", result.status.value)
    print("document name:", result.document.name)
    print("num pages in output:", len(result.document.pages))


def run_convert_all(client: DoclingServiceClient) -> None:
    print("\n=== convert_all() (multiple sources) ===")
    sources = [
        FIXTURES_DIR / "2206.01062v1.pdf",
        FIXTURES_DIR / "2408.09869v5.pdf",
    ]
    for idx, result in enumerate(
        client.convert_all(
            sources=sources,
            options=create_conversion_options(),
            max_concurrency=2,
            raises_on_error=False,
        ),
        start=1,
    ):
        print(
            f"{idx}.",
            "input=",
            result.input.file.name,
            "status=",
            result.status.value,
        )


def main() -> None:
    client = DoclingServiceClient(url=BASE_URL)
    try:
        health = client.health()
        print("health:", health.status)

        try:
            version = client.version()
            print("version keys:", ", ".join(sorted(version.keys())[:5]), "...")
        except Exception as exc:
            print("version endpoint unavailable:", exc)

        run_convert(client)
        run_convert_all(client)
    finally:
        client.close()


if __name__ == "__main__":
    main()
