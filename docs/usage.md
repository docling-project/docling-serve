# Usage

The API provides two endpoints: one for urls, one for files. This is necessary to send files directly in binary format instead of base64-encoded strings.

## Common parameters

On top of the source of file (see below), both endpoints support the same parameters, which are almost the same as the Docling CLI.

- `from_formats` (List[str]): Input format(s) to convert from. Allowed values: `docx`, `pptx`, `html`, `image`, `pdf`, `asciidoc`, `md`. Defaults to all formats.
- `to_formats` (List[str]): Output format(s) to convert to. Allowed values: `md`, `json`, `html`, `text`, `doctags`. Defaults to `md`.
- `pipeline` (str). The choice of which pipeline to use. Allowed values are `standard` and `vlm`. Defaults to `standard`.
- `page_range` (tuple). If specified, only convert a range of pages. The page number starts at 1.
- `do_ocr` (bool): If enabled, the bitmap content will be processed using OCR. Defaults to `True`.
- `image_export_mode`: Image export mode for the document (only in case of JSON, Markdown or HTML). Allowed values: embedded, placeholder, referenced. Optional, defaults to `embedded`.
- `force_ocr` (bool): If enabled, replace any existing text with OCR-generated text over the full content. Defaults to `False`.
- `ocr_engine` (str): OCR engine to use. Allowed values: `easyocr`, `tesserocr`, `tesseract`, `rapidocr`, `ocrmac`. Defaults to `easyocr`. To use the `tesserocr` engine, `tesserocr` must be installed where docling-serve is running: `pip install tesserocr`
- `ocr_lang` (List[str]): List of languages used by the OCR engine. Note that each OCR engine has different values for the language names. Defaults to empty.
- `pdf_backend` (str): PDF backend to use. Allowed values: `pypdfium2`, `dlparse_v1`, `dlparse_v2`, `dlparse_v4`. Defaults to `dlparse_v4`.
- `table_mode` (str): Table mode to use. Allowed values: `fast`, `accurate`. Defaults to `fast`.
- `abort_on_error` (bool): If enabled, abort on error. Defaults to false.
- `md_page_break_placeholder` (str): Add this placeholder between pages in the markdown output.
- `do_table_structure` (bool): If enabled, the table structure will be extracted. Defaults to true.
- `do_code_enrichment` (bool): If enabled, perform OCR code enrichment. Defaults to false.
- `do_formula_enrichment` (bool): If enabled, perform formula OCR, return LaTeX code. Defaults to false.
- `do_picture_classification` (bool): If enabled, classify pictures in documents. Defaults to false.
- `do_picture_description` (bool): If enabled, describe pictures in documents. Defaults to false.
- `picture_description_area_threshold` (float): Minimum percentage of the area for a picture to be processed with the models. Defaults to 0.05.
- `picture_description_local` (dict): Options for running a local vision-language model in the picture description. The parameters refer to a model hosted on Hugging Face. This parameter is mutually exclusive with `picture_description_api`.
- `picture_description_api` (dict): API details for using a vision-language model in the picture description. This parameter is mutually exclusive with `picture_description_local`.
- `include_images` (bool): If enabled, images will be extracted from the document. Defaults to false.
- `images_scale` (float): Scale factor for images. Defaults to 2.0.
- `do_chunking` (bool): If enabled, the response will contain chunks instead of the full document formats. Useful for RAG applications. Defaults to false.
- `chunking_options` (dict): Configuration options for document chunking. See [Chunking for RAG Applications](#chunking-for-rag-applications) section for detailed configuration options.

## Convert endpoints

### Source endpoint

The endpoint is `/v1/convert/source`, listening for POST requests of JSON payloads.

On top of the above parameters, you must send the URL(s) of the document you want process with either the `http_sources` or `file_sources` fields.
The first is fetching URL(s) (optionally using with extra headers), the second allows to provide documents as base64-encoded strings.
No `options` is required, they can be partially or completely omitted.

Simple payload example:

```json
{
  "http_sources": [{"url": "https://arxiv.org/pdf/2206.01062"}]
}
```

<details>

<summary>Complete payload example:</summary>

```json
{
  "options": {
    "from_formats": ["docx", "pptx", "html", "image", "pdf", "asciidoc", "md", "xlsx"],
    "to_formats": ["md", "json", "html", "text", "doctags"],
    "image_export_mode": "placeholder",
    "do_ocr": true,
    "force_ocr": false,
    "ocr_engine": "easyocr",
    "ocr_lang": ["en"],
    "pdf_backend": "dlparse_v2",
    "table_mode": "fast",
    "abort_on_error": false,
  },
  "http_sources": [{"url": "https://arxiv.org/pdf/2206.01062"}]
}
```

</details>

<details>

<summary>CURL example:</summary>

```sh
curl -X 'POST' \
  'http://localhost:5001/v1/convert/source' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "options": {
    "from_formats": [
      "docx",
      "pptx",
      "html",
      "image",
      "pdf",
      "asciidoc",
      "md",
      "xlsx"
    ],
    "to_formats": ["md", "json", "html", "text", "doctags"],
    "image_export_mode": "placeholder",
    "do_ocr": true,
    "force_ocr": false,
    "ocr_engine": "easyocr",
    "ocr_lang": [
      "fr",
      "de",
      "es",
      "en"
    ],
    "pdf_backend": "dlparse_v2",
    "table_mode": "fast",
    "abort_on_error": false,
    "do_table_structure": true,
    "include_images": true,
    "images_scale": 2
  },
  "http_sources": [{"url": "https://arxiv.org/pdf/2206.01062"}]
}'
```

</details>

<details>
<summary>Python example:</summary>

```python
import httpx

async_client = httpx.AsyncClient(timeout=60.0)
url = "http://localhost:5001/v1/convert/source"
payload = {
  "options": {
    "from_formats": ["docx", "pptx", "html", "image", "pdf", "asciidoc", "md", "xlsx"],
    "to_formats": ["md", "json", "html", "text", "doctags"],
    "image_export_mode": "placeholder",
    "do_ocr": True,
    "force_ocr": False,
    "ocr_engine": "easyocr",
    "ocr_lang": "en",
    "pdf_backend": "dlparse_v2",
    "table_mode": "fast",
    "abort_on_error": False,
  },
  "http_sources": [{"url": "https://arxiv.org/pdf/2206.01062"}]
}

response = await async_client_client.post(url, json=payload)

data = response.json()
```

</details>

#### File as base64

The `file_sources` argument in the endpoint allows to send files as base64-encoded strings.
When your PDF or other file type is too large, encoding it and passing it inline to curl
can lead to an “Argument list too long” error on some systems. To avoid this, we write
the JSON request body to a file and have curl read from that file.

<details>
<summary>CURL steps:</summary>

```sh
# 1. Base64-encode the file
B64_DATA=$(base64 -w 0 /path/to/file/pdf-to-convert.pdf)

# 2. Build the JSON with your options
cat <<EOF > /tmp/request_body.json
{
  "options": {
  },
  "file_sources": [{
    "base64_string": "${B64_DATA}",
    "filename": "pdf-to-convert.pdf"
  }]
}
EOF

# 3. POST the request to the docling service
curl -X POST "localhost:5001/v1/convert/source" \
     -H "Content-Type: application/json" \
     -d @/tmp/request_body.json
```

</details>

### File endpoint

The endpoint is: `/v1/convert/file`, listening for POST requests of Form payloads (necessary as the files are sent as multipart/form data). You can send one or multiple files.

<details>
<summary>CURL example:</summary>

```sh
curl -X 'POST' \
  'http://127.0.0.1:5001/v1/convert/file' \
  -H 'accept: application/json' \
  -H 'Content-Type: multipart/form-data' \
  -F 'ocr_engine=easyocr' \
  -F 'pdf_backend=dlparse_v2' \
  -F 'from_formats=pdf' \
  -F 'from_formats=docx' \
  -F 'force_ocr=false' \
  -F 'image_export_mode=embedded' \
  -F 'ocr_lang=en' \
  -F 'ocr_lang=pl' \
  -F 'table_mode=fast' \
  -F 'files=@2206.01062v1.pdf;type=application/pdf' \
  -F 'abort_on_error=false' \
  -F 'to_formats=md' \
  -F 'to_formats=text' \
  -F 'do_ocr=true'
```

</details>

<details>
<summary>Python example:</summary>

```python
import httpx

async_client = httpx.AsyncClient(timeout=60.0)
url = "http://localhost:5001/v1/convert/file"
parameters = {
"from_formats": ["docx", "pptx", "html", "image", "pdf", "asciidoc", "md", "xlsx"],
"to_formats": ["md", "json", "html", "text", "doctags"],
"image_export_mode": "placeholder",
"do_ocr": True,
"force_ocr": False,
"ocr_engine": "easyocr",
"ocr_lang": ["en"],
"pdf_backend": "dlparse_v2",
"table_mode": "fast",
"abort_on_error": False,
}

current_dir = os.path.dirname(__file__)
file_path = os.path.join(current_dir, '2206.01062v1.pdf')

files = {
    'files': ('2206.01062v1.pdf', open(file_path, 'rb'), 'application/pdf'),
}

response = await async_client.post(url, files=files, data=parameters)
assert response.status_code == 200, "Response should be 200 OK"

data = response.json()
```

</details>

### Picture description options

When the picture description enrichment is activated, users may specify which model and which execution mode to use for this task. There are two choices for the execution mode: _local_ will run the vision-language model directly, _api_ will invoke an external API endpoint.

The local option is specified with:

```jsonc
{
  "picture_description_local": {
    "repo_id": "",  // Repository id from the Hugging Face Hub.
    "generation_config": {"max_new_tokens": 200, "do_sample": false},  // HF generation config.
    "prompt": "Describe this image in a few sentences. ",  // Prompt used when calling the vision-language model.
  }
}
```

The possible values for `generation_config` are documented in the [Hugging Face text generation docs](https://huggingface.co/docs/transformers/en/main_classes/text_generation#transformers.GenerationConfig).

The api option is specified with:

```jsonc
{
  "picture_description_api": {
    "url": "",  // Endpoint which accepts openai-api compatible requests.
    "headers": {},  // Headers used for calling the API endpoint. For example, it could include authentication headers.
    "params": {},  // Model parameters.
    "timeout": 20,  // Timeout for the API request.
    "prompt": "Describe this image in a few sentences. ",  // Prompt used when calling the vision-language model.
  }
}
```

Example URLs are:

- `http://localhost:8000/v1/chat/completions` for the local vllm api, with example `picture_description_api`:
  - the `HuggingFaceTB/SmolVLM-256M-Instruct` model

    ```json
    {
      "url": "http://localhost:8000/v1/chat/completions",
      "params": {
        "model": "HuggingFaceTB/SmolVLM-256M-Instruct",
        "max_completion_tokens": 200,
      }
    }
    ```

  - the `ibm-granite/granite-vision-3.2-2b` model

    ```json
    {
      "url": "http://localhost:8000/v1/chat/completions",
      "params": {
        "model": "ibm-granite/granite-vision-3.2-2b",
        "max_completion_tokens": 200,
      }
    }
    ```

- `http://localhost:11434/v1/chat/completions` for the local Ollama api, with example `picture_description_api`:
  - the `granite3.2-vision:2b` model

    ```json
    {
      "url": "http://localhost:11434/v1/chat/completions",
      "params": {
        "model": "granite3.2-vision:2b"
      }
    }
    ```

Note that when using `picture_description_api`, the server must be launched with `DOCLING_SERVE_ENABLE_REMOTE_SERVICES=true`.

### Chunking for RAG Applications

When `do_chunking` is enabled, the API returns document chunks instead of full document formats. This is particularly useful for RAG (Retrieval-Augmented Generation) applications.

#### Chunking Options

The `chunking_options` parameter supports the following configuration:

- `max_tokens` (int): Maximum number of tokens per chunk. Defaults to 512.
- `overlap` (int): Number of overlapping tokens between chunks. Defaults to 128.
- `tokenizer` (str): HuggingFace model name for custom `tokenization`. Defaults to "Qwen/Qwen3-Embedding-0.6B".
- `use_markdown_tables` (bool): Use markdown table format instead of triplets for table serialization. Defaults to false.
- `merge_peers` (bool): Merge undersized successive chunks with same headings. Defaults to true.
- `include_raw_text` (bool): Include both `chunk_text` and `contextualized_text` in response. If false, only `contextualized_text` is included. Defaults to true.

#### Chunking Examples

<details>
<summary>Basic chunking:</summary>

```json
{
  "options": {
    "do_chunking": true,
    "chunking_options": {
      "max_tokens": 512,
      "overlap": 128
    }
  },
  "sources": [{"kind": "http", "url": "https://example.com/document.pdf"}]
}
```

</details>

<details>
<summary>With markdown tables:</summary>

```json
{
  "options": {
    "do_chunking": true,
    "chunking_options": {
      "max_tokens": 512,
      "use_markdown_tables": true
    }
  },
  "sources": [{"kind": "http", "url": "https://example.com/document.pdf"}]
}
```

</details>

<details>
<summary>With custom `tokenizer`:</summary>

```json
{
  "options": {
    "do_chunking": true,
    "chunking_options": {
      "max_tokens": 512,
      "tokenizer": "Qwen/Qwen3-Embedding-0.6B",
      "use_markdown_tables": true
    }
  },
  "sources": [{"kind": "http", "url": "https://example.com/document.pdf"}]
}
```

</details>

<details>
<summary>Without serialized text (smaller payload):</summary>

```json
{
  "options": {
    "do_chunking": true,
    "chunking_options": {
      "max_tokens": 512,
      "include_raw_text": false
    }
  },
  "sources": [{"kind": "http", "url": "https://example.com/document.pdf"}]
}
```

</details>

## Response format

The response can be a JSON Document or a File.

- If you process only one file, the response will be a JSON document with the following format:

  ```jsonc
  {
    "document": {
      "md_content": "",
      "json_content": {},
      "html_content": "",
      "text_content": "",
      "doctags_content": ""
      },
    "status": "<success|partial_success|skipped|failure>",
    "processing_time": 0.0,
    "timings": {},
    "errors": []
  }
  ```

  Depending on the value you set in `output_formats`, the different items will be populated with their respective results or empty.

  `processing_time` is the Docling processing time in seconds, and `timings` (when enabled in the backend) provides the detailed
  timing of all the internal Docling components.

- If you set the parameter `target` to the zip mode, the response will be a zip file.
- If multiple files are generated (multiple inputs, or one input but multiple outputs with the zip target mode), the response will be a zip file.

### Chunking Response Format

When chunking is enabled, the response uses returns chunks instead of document formats:

```json
{
  "chunks": [
    {
      "filename": "document.pdf",
      "chunk_index": 0,
      "contextualized_text": "Context-enriched text...",
      "chunk_text": "Raw text content...",
      "heading": "Chapter 1",
      "page_number": 1,
      "metadata": {
        "doc_items": [...]
      }
    }
  ],
  "status": "<success|partial_success|skipped|failure>",
  "errors": [],
  "processing_time": 0,
  "timings": {},
  "chunking_info": {
    "max_tokens": 512,
    "use_markdown_tables": true,
    "tokenizer": "Qwen/Qwen3-Embedding-0.6B",
    "include_raw_text": true
  }
}
```

## Asynchronous API

Both `/v1/convert/source` and `/v1/convert/file` endpoints are available as asynchronous variants.
The advantage of the asynchronous endpoints is the possible to interrupt the connection, check for the progress update and fetch the result.
This approach is more resilient against network instabilities and allows the client application logic to easily interleave conversion with other tasks.

Launch an asynchronous conversion with:

- `POST /v1/convert/source/async` when providing the input as sources.
- `POST /v1/convert/file/async` when providing the input as multipart-form files.

The response format is a task detail:

```jsonc
{
  "task_id": "<task_id>",  // the task_id which can be used for the next operations
  "task_status": "pending|started|success|failure",  // the task status
  "task_position": 1,  // the position in the queue
  "task_meta": null,  // metadata e.g. how many documents are in the total job and how many have been converted
}
```

### Polling status

For checking the progress of the conversion task and wait for its completion, use the endpoint:

- `GET /v1/status/poll/{task_id}`

<details>
<summary>Example waiting loop:</summary>

```python
import time
import httpx

# ...
# response from the async task submission
task = response.json()

while task["task_status"] not in ("success", "failure"):
    response = httpx.get(f"{base_url}/status/poll/{task['task_id']}")
    task = response.json()

    time.sleep(5)
```

<details>

### Subscribe with websockets

Using websocket you can get the client application being notified about updates of the conversion task.
To start the websocket connection, use the endpoint:

- `/v1/status/ws/{task_id}`

Websocket messages are JSON object with the following structure:

```jsonc
{
  "message": "connection|update|error",  // type of message being sent
  "task": {},  // the same content of the task description
  "error": "",  // description of the error
}
```

<details>
<summary>Example websocket usage:</summary>

```python
from websockets.sync.client import connect

uri = f"ws://{base_url}/v1/status/ws/{task['task_id']}"
with connect(uri) as websocket:
    for message in websocket:
        try:
            payload = json.loads(message)
            if payload["message"] == "error":
                break
            if payload["message"] == "error" and payload["task"]["task_status"] in ("success", "failure"):
                break
        except:
          break
```

</details>

### Fetch results

When the task is completed, the result can be fetched with the endpoint:

- `GET /v1/result/{task_id}`
