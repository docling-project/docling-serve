import httpx
import time
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from pydantic import BaseModel

from docling_core.types.doc.document import DoclingDocument, DocTagsDocument

# Variables to use
fname = 'fname'
out_dir = Path("examples/splitted_pdf/")
pages_per_file = 4
base_url = "http://localhost:5001/v1"
output_file= Path("examples/merged_pdf.json")


class ConvertedSplittedPdf(BaseModel):
    task_id: str
    conversion_finished: bool = False
    result: dict| None = None


def split_pdf(filename, pages_per_file=pages_per_file):
    with open(filename, 'rb') as input_pdf_file:
        pdf_reader = PdfReader(input_pdf_file)
        total_pages = len(pdf_reader.pages)
        
        for start_page in range(0, total_pages, pages_per_file):
            writer = PdfWriter()
            
            for page in range(start_page, min(start_page + pages_per_file, total_pages)):
                writer.add_page(pdf_reader.pages[page])
            
            output_pdf_path = f"{out_dir}/split_{start_page // pages_per_file + 1}.pdf"
            
            with open(output_pdf_path, 'wb') as output_pdf_file:
                writer.write(output_pdf_file)
            print(f'Created: {output_pdf_path}')

       
def get_task_result(task_id):
    response = httpx.get(
        f"{base_url}/result/{task_id}",timeout=15,
    )
    return response.json()


def check_task_status(task_id):
    response = httpx.get(f"{base_url}/status/poll/{task_id}")
    task = response.json()
    task_status = task['task_status']

    task_finished = False
    if task_status == "success":
        task_finished = True

    if task_status in ("failure", "revoked"):
        raise RuntimeError("A conversion failed")
    
    time.sleep(3)
    
    return task_finished


def post_file(file_path):
    payload = {
        "to_formats": ["doctags"],
        "image_export_mode": "placeholder",
        "ocr": False,
        "abort_on_error": False,
    }

    files = {
        "files": (file_path.name, file_path.open("rb"), "application/pdf"),
    }
    response = httpx.post(
        f"{base_url}/convert/file/async", files=files, data=payload
    )

    task = response.json()

    return task["task_id"]


def main():
    filename = "./docling_serve/2206.01062v1.pdf" # file to split process
    split_pdf(filename)

    splitted_pdfs: list[ConvertedSplittedPdf] = []

    for file in out_dir.rglob("*"):
        task_id = post_file(file)
        splitted_pdfs.append(ConvertedSplittedPdf(task_id=task_id))
    
    all_files_converted = False
    while not all_files_converted:
        found_conversion_running = False
        for splitted_pdf in splitted_pdfs:
            if not splitted_pdf.conversion_finished:
                found_conversion_running = True
                splitted_pdf.conversion_finished = check_task_status(splitted_pdf.task_id)
        if not found_conversion_running:
            all_files_converted = True
    
    for splitted_pdf in splitted_pdfs:
        splitted_pdf.result = get_task_result(splitted_pdf.task_id)
    

    list_docs = ""
    for i, splitted_pdf in enumerate(splitted_pdfs):
        list_docs+=splitted_pdf.result.get("document").get("doctags_content")

    doc_tag_doc = DocTagsDocument.from_multipage_doctags_and_images(doctags=list_docs, images=None)

    full_doc = DoclingDocument.load_from_doctags(doc_tag_doc)

    full_doc.save_as_json(output_file)
    
    print("Finished")


if __name__ == "__main__":
    main()