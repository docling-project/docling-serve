# ruff: noqa: E402

from typing import Any

from kfp import dsl

PYTHON_BASE_IMAGE = "python:3.12"


@dsl.component(
    base_image=PYTHON_BASE_IMAGE,
)
def generate_chunks(
    request: dict[str, Any],
    batch_size: int,
) -> list[list[dict[str, Any]]]:
    sources = request["http_sources"]
    splits = [sources[i::batch_size] for i in range(batch_size)]
    return splits


@dsl.component(
    base_image=PYTHON_BASE_IMAGE,
    packages_to_install=[
        "pydantic",
        "docling-serve[cpu] @ git+https://github.com/docling-project/docling-serve@feat-kfp-engine",
        "httpx",
    ],
)
def notify_callbacks_totals(
    chunks: list[list[dict[str, Any]]],
    callbacks: list[dict[str, Any]],
):
    import ssl

    import certifi
    import httpx

    from docling_serve.datamodel.callback import ProgressSetNumDocs
    from docling_serve.datamodel.kfp import CallbackSpec

    if len(callbacks) == 0:
        return

    total = sum(len(chunk) for chunk in chunks)
    payload = ProgressSetNumDocs(num_docs=total)
    for callback_dict in callbacks:
        callback = CallbackSpec.model_validate(callback_dict)

        # https://www.python-httpx.org/advanced/ssl/#configuring-client-instances
        if callback.ca_cert:
            ctx = ssl.create_default_context(cadata=callback.ca_cert)
        else:
            ctx = ssl.create_default_context(cafile=certifi.where())

        try:
            httpx.post(
                str(callback.url),
                headers=callback.headers,
                json=payload.model_dump(mode="json"),
                verify=ctx,
            )
        except httpx.HTTPError as err:
            print(f"Error notifying callback {callback.url}: {err}")


@dsl.component(
    base_image=PYTHON_BASE_IMAGE,
    packages_to_install=[
        "pydantic",
        "docling-serve[cpu] @ git+https://github.com/docling-project/docling-serve@feat-kfp-engine",
    ],
)
def convert_batch(
    data_splits: list[dict[str, Any]],
    request: dict[str, Any],
    callbacks: list[dict[str, Any]],
    output_path: dsl.OutputPath("Directory"),  # type: ignore
):
    from pathlib import Path

    from pydantic import AnyUrl

    from docling_serve.datamodel.callback import (
        FailedDocsItem,
        ProgressUpdateProcessed,
        SucceededDocsItem,
    )
    from docling_serve.datamodel.convert import ConvertDocumentsOptions
    from docling_serve.datamodel.requests import HttpSource

    convert_options = ConvertDocumentsOptions.model_validate(request["options"])
    print(convert_options)

    output_dir = Path(output_path)
    output_dir.mkdir(exist_ok=True, parents=True)
    docs_succeeded: list[SucceededDocsItem] = []
    docs_failed: list[FailedDocsItem] = []
    for source_dict in data_splits:
        source = HttpSource.model_validate(source_dict)
        filename = Path(str(AnyUrl(source.url).path)).name
        output_filename = output_dir / filename
        print(f"Writing {output_filename}")
        with output_filename.open("w") as f:
            f.write(source.model_dump_json())
        docs_succeeded.append(SucceededDocsItem(source=source.url))

    if len(callbacks) > 0:
        payload = ProgressUpdateProcessed(
            num_failed=len(docs_failed),
            num_processed=len(docs_succeeded) + len(docs_failed),
            num_succeeded=len(docs_succeeded),
            docs_succeeded=docs_succeeded,
            docs_failed=docs_failed,
        )

        # todo: send...
        print(payload)


@dsl.pipeline()
def process(
    batch_size: int,
    request: dict[str, Any],
    callbacks: list[dict[str, Any]] = [],
):
    chunks_task = generate_chunks(request=request, batch_size=batch_size)

    with dsl.ParallelFor(chunks_task.output, parallelism=4) as data_splits:
        convert_batch(
            data_splits=data_splits,
            request=request,
            callbacks=callbacks,
        )
