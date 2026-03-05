import json
from urllib3 import encode_multipart_formdata
import boto3
import time

REGION = "us-east-1"
ENDPOINT_NAME = "docling-serve-2025-09-04-03-09-08"
SAGEMAKER_RUNTIME_URL = f"https://runtime.sagemaker.{REGION}.amazonaws.com"

sm_client = boto3.client('sagemaker-runtime', region_name=REGION, endpoint_url=SAGEMAKER_RUNTIME_URL)

# https://stackoverflow.com/a/76677637/3614578
def test_convert(file_name: str = None, local_file: str = None, s3_input: str = None):
    data = {
        "files": (file_name, open(local_file, "rb").read(), "application/pdf"),
        'ocr_engine': (None, 'tesserocr'),
        'pdf_backend': (None, 'dlparse_v4'),
        'from_formats': (None, 'pdf'),
        'force_ocr': (None, 'false'),
        'image_export_mode': (None, 'placeholder'),
        'ocr_lang': (None, 'eng'),
        'table_mode': (None, 'fast'),
        'abort_on_error': (None, 'false'),
        # it will convert to one of md or json, if both passed it converts to json
        'to_formats': (None, 'md'),
        'to_formats': (None, 'json'),
        'return_as_file': (None, 'false'),
        'do_ocr': (None, 'true'),
    }
    
    if s3_input is not None:
        del data["files"]
        data["s3_input"] = (None, s3_input)

    body, header = encode_multipart_formdata(data)

    result = sm_client.invoke_endpoint(EndpointName=ENDPOINT_NAME, ContentType=header, Body=body)['Body'].read().decode()
    print(result)
    result = json.loads(result)
    return result["task_id"], result["task_status"]
    
def test_poll(task_id, task_status, file_name: str = "current"):
    data = {
        "files": (file_name, b"", "application/pdf"),
        'task_id': (None, task_id),
    }

    body, header = encode_multipart_formdata(data)

    while task_status != "success" and task_status != "failure":
        result = sm_client.invoke_endpoint(EndpointName=ENDPOINT_NAME, ContentType=header, Body=body)['Body'].read().decode()
        result = json.loads(result)
        task_status = result["task_status"]
        print(f"{task_id} status is {task_status}")
        print(f"poll response is {result}")
        time.sleep(2)
        
def test_fetch(task_id, file_name: str = "current"):
    data = {
        "files": (file_name, b"", "application/pdf"),
        'task_id': (None, task_id),
        'fetch': (None, 'true'),
        'chunk': (None, 'false'),
    }

    body, header = encode_multipart_formdata(data)
    result = sm_client.invoke_endpoint(EndpointName=ENDPOINT_NAME, ContentType=header, Body=body)['Body'].read().decode()
    print(result)
        

task_id, task_status = test_convert(file_name="2206.01062v1.pdf", local_file="../tests/2206.01062v1.pdf")
# task_id, task_status = test_convert(s3_input="s3://201486032796-docling-serve/input/Nepal-Earthquake-CONPLAN.pdf")
test_poll(task_id, task_status)
test_fetch(task_id)