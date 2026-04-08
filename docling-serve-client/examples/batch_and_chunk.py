from __future__ import annotations

from pathlib import Path

from docling_serve.datamodel.convert import ConvertDocumentsRequestOptions

from docling.datamodel.base_models import ConversionStatus, OutputFormat
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


def main() -> None:
    sources = [
        FIXTURES_DIR / "2206.01062v1.pdf",
        FIXTURES_DIR / "2408.09869v5.pdf",
    ]

    client = DoclingServiceClient(url=BASE_URL)
    try:
        options = create_conversion_options()
        print("batch results:", len(sources))
        chunked_count = 0
        for idx, (source, result) in enumerate(
            zip(
                sources,
                client.convert_all(
                    sources=sources,
                    options=options,
                    max_concurrency=2,
                    raises_on_error=False,
                ),
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

            if result.status not in {
                ConversionStatus.SUCCESS,
                ConversionStatus.PARTIAL_SUCCESS,
            }:
                print("skip chunking due to failed conversion:", source.name)
                continue

            chunk_response = client.chunk(
                source=source,
                chunker="hierarchical",
                options=options,
            )
            chunked_count += 1
            print("chunked source:", source.name)
            print("num chunks:", len(chunk_response.chunks))
            print("num documents:", len(chunk_response.documents))

        print("sources chunked:", chunked_count)
    finally:
        client.close()


if __name__ == "__main__":
    main()
