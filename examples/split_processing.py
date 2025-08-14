import json
import time
from pathlib import Path

import httpx
from pydantic import BaseModel
from pypdf import PdfReader

from docling_core.types.doc.document import DoclingDocument

# Variables to use
out_dir = Path("examples/splitted_pdf/")
pages_per_file = 4
base_url = "http://localhost:5001/v1"
output_file = Path("examples/merged_pdf.json")


class ConvertedSplittedPdf(BaseModel):
    task_id: str
    conversion_finished: bool = False
    result: dict | None = None


def get_task_result(task_id: str):
    response = httpx.get(
        f"{base_url}/result/{task_id}",
        timeout=15,
    )
    return response.json()


def check_task_status(task_id: str):
    response = httpx.get(f"{base_url}/status/poll/{task_id}", timeout=15)
    task = response.json()
    task_status = task["task_status"]

    task_finished = False
    if task_status == "success":
        task_finished = True

    if task_status in ("failure", "revoked"):
        raise RuntimeError("A conversion failed")

    time.sleep(5)

    return task_finished


def post_file(file_path: Path, start_page: int, end_page: int):
    payload = {
        "to_formats": ["json"],
        "image_export_mode": "placeholder",
        "ocr": False,
        "abort_on_error": False,
        "page_range": [start_page, end_page],
    }

    files = {
        "files": (file_path.name, file_path.open("rb"), "application/pdf"),
    }
    response = httpx.post(
        f"{base_url}/convert/file/async",
        files=files,
        data=payload,
        timeout=15,
    )

    task = response.json()

    return task["task_id"]


def main():
    filename = Path("./tests/2206.01062v1.pdf")  # file to split process

    splitted_pdfs: list[ConvertedSplittedPdf] = []

    with open(filename, "rb") as input_pdf_file:
        pdf_reader = PdfReader(input_pdf_file)
        total_pages = len(pdf_reader.pages)

        for start_page in range(0, total_pages, pages_per_file):
            task_id = post_file(
                filename, start_page + 1, min(start_page + pages_per_file, total_pages)
            )
            splitted_pdfs.append(ConvertedSplittedPdf(task_id=task_id))

    all_files_converted = False
    while not all_files_converted:
        found_conversion_running = False
        for splitted_pdf in splitted_pdfs:
            if not splitted_pdf.conversion_finished:
                found_conversion_running = True
                print("checking conversion status...")
                splitted_pdf.conversion_finished = check_task_status(
                    splitted_pdf.task_id
                )
        if not found_conversion_running:
            all_files_converted = True

    for splitted_pdf in splitted_pdfs:
        splitted_pdf.result = get_task_result(splitted_pdf.task_id)

    # TODO: merge using JSON not working atm; currently outputs splited JSON into folder
    # merged_document = DoclingDocument(name="merged_pdf.pdf")
    for i, splitted_pdf in enumerate(splitted_pdfs):
        # page_step = i * pages_per_file
        json_content = json.dumps(
            splitted_pdf.result.get("document").get("json_content"), indent=2
        )
        doc = DoclingDocument.model_validate_json(json_content)
        doc.save_as_json(filename=f"{out_dir}/splited_json_{i}.json")
    #     for page, page_item in doc.pages.items():
    #         merged_document.add_page(page_no=page_step+page, size=page_item.size, image=page_item.image)

    #     for group in doc.groups:
    #         merged_document.add_group(
    #             label=group.label,
    #             name=group.name,
    #             parent=group.parent,
    #             content_layer=group.content_layer,
    #         )

    #     for text in doc.texts:
    #         merged_document.add_text(
    #             label=text.label,
    #             text=text.text,
    #             orig=text.orig,
    #             parent=text.parent,
    #             content_layer=text.content_layer,
    #         )

    #     for picture in doc.pictures:
    #         merged_document.add_picture(
    #             annotations=picture.annotations,
    #             image=picture.image,
    #             caption=picture.captions[0],
    #             prov=picture.prov,
    #             parent=picture.parent,
    #             content_layer=picture.content_layer,
    #         )

    #     for table in doc.tables:
    #         merged_document.add_table(
    #             data=table.data,
    #             caption=table.captions[0],
    #             prov=table.prov,
    #             parent=table.parent,
    #             label=table.label,
    #             content_layer=table.content_layer,
    #         )

    #     for key_value in doc.key_value_items:
    #         merged_document.add_key_values(
    #             graph=key_value.graph,
    #             prov=key_value.prov,
    #             parent=key_value.parent,
    #         )

    #     for doc_form in doc.form_items:
    #         merged_document.add_form(
    #             graph=doc_form.graph,
    #             prov=doc_form.prov,
    #             parent=doc_form.parent,
    #         )

    # merged_document.save_as_json(output_file)

    print("Finished")


if __name__ == "__main__":
    main()
