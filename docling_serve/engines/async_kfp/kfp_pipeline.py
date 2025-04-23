# ruff: noqa: E402, UP006, UP035

from typing import Any, Dict, List

from kfp import dsl

PYTHON_BASE_IMAGE = "python:3.12"


@dsl.component(
    base_image=PYTHON_BASE_IMAGE,
    packages_to_install=[
        "pydantic",
        "docling-serve @ git+https://github.com/docling-project/docling-serve@feat-kfp-engine",
    ],
    pip_index_urls=["https://download.pytorch.org/whl/cpu", "https://pypi.org/simple"],
)
def generate_chunks(
    run_name: str,
    request: Dict[str, Any],
    batch_size: int,
    callbacks: List[Dict[str, Any]],
) -> List[List[Dict[str, Any]]]:
    from pydantic import TypeAdapter

    from docling_serve.datamodel.callback import (
        ProgressCallbackRequest,
        ProgressSetNumDocs,
    )
    from docling_serve.datamodel.kfp import CallbackSpec
    from docling_serve.engines.async_kfp.notify import notify_callbacks

    CallbacksListType = TypeAdapter(list[CallbackSpec])

    sources = request["http_sources"]
    splits = [sources[i : i + batch_size] for i in range(0, len(sources), batch_size)]

    total = sum(len(chunk) for chunk in splits)
    payload = ProgressCallbackRequest(
        task_id=run_name, progress=ProgressSetNumDocs(num_docs=total)
    )
    notify_callbacks(
        payload=payload,
        callbacks=CallbacksListType.validate_python(callbacks),
    )

    return splits


@dsl.component(
    base_image=PYTHON_BASE_IMAGE,
    packages_to_install=[
        "pydantic",
        "docling-serve @ git+https://github.com/docling-project/docling-serve@feat-kfp-engine",
    ],
    pip_index_urls=["https://download.pytorch.org/whl/cpu", "https://pypi.org/simple"],
)
def convert_batch(
    run_name: str,
    data_splits: List[Dict[str, Any]],
    request: Dict[str, Any],
    callbacks: List[Dict[str, Any]],
    output_path: dsl.OutputPath("Directory"),  # type: ignore
):
    from pathlib import Path

    from pydantic import AnyUrl, TypeAdapter

    from docling_serve.datamodel.callback import (
        FailedDocsItem,
        ProgressCallbackRequest,
        ProgressUpdateProcessed,
        SucceededDocsItem,
    )
    from docling_serve.datamodel.convert import ConvertDocumentsOptions
    from docling_serve.datamodel.kfp import CallbackSpec
    from docling_serve.datamodel.requests import HttpSource
    from docling_serve.engines.async_kfp.notify import notify_callbacks

    CallbacksListType = TypeAdapter(list[CallbackSpec])

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

    payload = ProgressCallbackRequest(
        task_id=run_name,
        progress=ProgressUpdateProcessed(
            num_failed=len(docs_failed),
            num_processed=len(docs_succeeded) + len(docs_failed),
            num_succeeded=len(docs_succeeded),
            docs_succeeded=docs_succeeded,
            docs_failed=docs_failed,
        ),
    )

    print(payload)
    notify_callbacks(
        payload=payload,
        callbacks=CallbacksListType.validate_python(callbacks),
    )


@dsl.pipeline()
def process(
    batch_size: int,
    request: Dict[str, Any],
    callbacks: List[Dict[str, Any]] = [],
    run_name: str = "",
):
    chunks_task = generate_chunks(
        run_name=run_name,
        request=request,
        batch_size=batch_size,
        callbacks=callbacks,
    )
    chunks_task.set_caching_options(False)

    with dsl.ParallelFor(chunks_task.output, parallelism=4) as data_splits:
        convert_batch(
            run_name=run_name,
            data_splits=data_splits,
            request=request,
            callbacks=callbacks,
        )
