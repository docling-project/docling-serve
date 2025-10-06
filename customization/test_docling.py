import requests
import time

PORT = "8080"

docling_async_url = f"http://localhost:{PORT}/invocations"
docling_status_url = f"http://localhost:{PORT}/invocations"
docling_fetch_url = f"http://localhost:{PORT}/invocations"

def send_docling_request(file_path: str):
        # Request headers
        # The 'Content-Type: multipart/form-data' header is automatically added by the `requests` library when using the `files` parameter.
        headers = {
            'accept': 'application/json',
        }

        # All form fields, including those with multiple values and the file itself.
        # `requests` will correctly format fields with the same key.
        # The structure for simple key-value fields is: ('key', (None, 'value'))
        # The structure for the file is: ('field_name', ('filename', file_object, 'content_type'))
        md_content = None
        res_time = -1
        try:
            if "s3" in file_path:
                files_payload = [
                    ('ocr_engine', (None, 'easyocr')),
                    ('pdf_backend', (None, 'dlparse_v4')),
                    ('from_formats', (None, 'pdf')),
                    ('from_formats', (None, 'docx')),
                    ('force_ocr', (None, 'false')),
                    ('image_export_mode', (None, 'placeholder')),
                    ('ocr_lang', (None, 'en')),
                    ('table_mode', (None, 'fast')),
                    ('abort_on_error', (None, 'false')),
                    ('to_formats', (None, 'md')),
                    ('to_formats', (None, 'json')),
                    ('return_as_file', (None, 'false')),
                    ('do_ocr', (None, 'true')),
                    # The actual file to upload
                    ('s3_input', (None, file_path)),
                    #('files', (file_path, b"", 'application/pdf'))
                ]
                start = time.time()
                response = requests.post(docling_async_url, headers=headers, files=files_payload).json()
            else:
                with open(file_path, 'rb') as f:                
                    files_payload = [
                        ('ocr_engine', (None, 'easyocr')),
                        ('pdf_backend', (None, 'dlparse_v4')),
                        ('from_formats', (None, 'pdf')),
                        ('from_formats', (None, 'docx')),
                        ('force_ocr', (None, 'false')),
                        ('image_export_mode', (None, 'placeholder')),
                        ('ocr_lang', (None, 'en')),
                        ('table_mode', (None, 'fast')),
                        ('abort_on_error', (None, 'false')),
                        ('to_formats', (None, 'md')),
                        ('to_formats', (None, 'json')),
                        ('return_as_file', (None, 'false')),
                        ('do_ocr', (None, 'true')),
                        # The actual file to upload
                        ('files', (file_path, f, 'application/pdf'))
                    ]
                    print("calling async")
                    start = time.time()
                    response = requests.post(docling_async_url, headers=headers, files=files_payload).json()
            task_status = response["task_status"]
            task_id = response["task_id"]
            while task_status != "success" and task_status != "failure":
                poll_payload = [
                    ('task_id', (None, task_id)),
                    ('files', (file_path, b"", 'application/pdf'))
                ]
                response = requests.post(docling_status_url, headers=headers, files=poll_payload).json()
                print(response)                    
                task_status = response["task_status"]
                time.sleep(1)
            res_time = time.time() - start
            print(f"res time is {res_time}")
            fetch_payload = [
                ('task_id', (None, task_id)),
                ('fetch', (None, 'true')),
                ('files', (file_path, b"", 'application/pdf')),
                ('chunk', (None, 'true')),
            ]
            response = requests.post(docling_fetch_url, headers=headers, files=fetch_payload)
            
            # Print the server's response
            print(f"Status Code: {response.status_code}")
                            
            # Pretty-print JSON response if possible
            try:
                print(response.json())
                # md_content = response.json()["document"]["md_content"]
                # res_time = response.elapsed.total_seconds()
            except requests.exceptions.JSONDecodeError:
                print("Response Text:")
                print(response.text)                

        except FileNotFoundError:
            print(f"Error: The file '{file_path}' was not found in the current directory.")
        except requests.exceptions.RequestException as e:
            print(f"An error occurred during the request: {e}")
        return md_content, res_time

send_docling_request("/Users/liamadams/repos/ai-lab/docling/2408.09869v4.pdf")
# send_docling_request("s3://201486032796-docling-serve/input/Onebrief-User-Manual.pdf")