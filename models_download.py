import os
import zipfile

import requests
from deepsearch_glm.utils.load_pretrained_models import load_pretrained_nlp_models
from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline

# Download Docling models
StandardPdfPipeline.download_models_hf(force=True)
load_pretrained_nlp_models(verbose=True)

# Download EasyOCR models
urls = [
    "https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/latin_g2.zip",
    "https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/craft_mlt_25k.zip"
]

local_zip_paths = [
    "/root/latin_g2.zip",
    "/root/craft_mlt_25k.zip"
]

extract_path = "/root/.EasyOCR/model/"

# Create the extract directory if it doesn't exist
os.makedirs(extract_path, exist_ok=True)
os.makedirs(os.path.dirname(local_zip_paths[0]), exist_ok=True)  # Create directory for zip files

for url, local_zip_path in zip(urls, local_zip_paths):
    # Download the file
    response = requests.get(url)
    with open(local_zip_path, "wb") as file:
        file.write(response.content)

    # Unzip the file
    with zipfile.ZipFile(local_zip_path, "r") as zip_ref:
        zip_ref.extractall(extract_path)

    # Clean up the zip file
    os.remove(local_zip_path)
