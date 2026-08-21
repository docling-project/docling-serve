# Usage

The API provides two endpoints: one for urls, one for files. This is necessary to send files directly in binary format instead of base64-encoded strings.

## Common parameters

On top of the source of file (see below), both endpoints support the same parameters.

<!-- begin: parameters-docs -->
<h4>ConvertDocumentsOptions</h4>

| Field Name | Type | Description |
|------------|------|-------------|
| `from_formats` | List[InputFormat] | Input format(s) to convert from. String or list of strings. Allowed values: `docx`, `doc`, `pptx`, `ppt`, `html`, `image`, `pdf`, `asciidoc`, `md`, `csv`, `xlsx`, `xls`, `odt`, `ods`, `odp`, `xml_uspto`, `xml_jats`, `xml_xbrl`, `xml_doclang`, `dclx`, `mets_gbs`, `json_docling`, `audio`, `video`, `vtt`, `latex`, `email`, `epub`, `boxnote`, `iwork_pages`, `ebcdic`. Optional, defaults to all formats. |
| `to_formats` | List[OutputFormat] | Output format(s) to convert to. String or list of strings. Allowed values: `md`, `json`, `yaml`, `html`, `html_split_page`, `text`, `doctags`, `vtt`, `doclang`, `dclx`, `chunks`. Optional, defaults to Markdown. |
| `image_export_mode` | ImageRefMode | Image export mode for the document (in case of JSON, Markdown or HTML). Allowed values: `placeholder`, `embedded`, `referenced`. Optional, defaults to Placeholder. |
| `do_ocr` | bool | If enabled, the bitmap content will be processed using OCR. Boolean. Optional, defaults to true |
| `force_ocr` | bool | If enabled, replace existing text with OCR-generated text over content. Boolean. Optional, defaults to false. |
| `ocr_engine` | str | DEPRECATED: Use ocr_preset instead. The OCR engine to use. String.  |
| `ocr_lang` | List[str] or NoneType | List of languages used by the OCR engine. Note that each OCR engine has different values for the language names. String or list of strings. Optional, defaults to empty. |
| `ocr_preset` | str | Preset ID for OCR engine. |
| `ocr_custom_config` | Dict[str, Any] or NoneType | Custom configuration for OCR engine. Use this to specify engine-specific options beyond `ocr_lang`. Each OCR engine kind has its own configuration schema. |
| `pdf_backend` | PdfBackend | The PDF backend to use. String. Allowed values: `pypdfium2`, `docling_parse`, `threaded_docling_parse`, `dlparse_v1`, `dlparse_v2`, `dlparse_v4`. Optional, defaults to `docling_parse`. |
| `table_mode` | TableFormerMode | Mode to use for table structure, String. Allowed values: `fast`, `accurate`. Optional, defaults to accurate. |
| `table_cell_matching` | bool | If true, matches table cells predictions back to PDF cells. Can break table output if PDF cells are merged across table columns. If false, let table structure model define the text cells, ignore PDF cells. |
| `pipeline` | ProcessingPipeline | Choose the pipeline to process PDF or image files. |
| `page_range` | Tuple | Only convert a range of pages. The page number starts at 1. |
| `document_timeout` | float or NoneType | The timeout for processing each document, in seconds. |
| `abort_on_error` | bool | Abort on error if enabled. Boolean. Optional, defaults to false. |
| `do_table_structure` | bool | If enabled, the table structure will be extracted. Boolean. Optional, defaults to true. |
| `do_pdf_heading_hierarchy` | bool | If enabled, section-header levels are inferred for PDF and image inputs processed by the standard pipeline, from the PDF bookmarks / table of contents, from outline numbering and from font style. When disabled, every detected heading stays at level 1 and the document hierarchy is flat. Boolean. Optional, defaults to false. |
| `pdf_heading_hierarchy_options` | HeadingHierarchyOptions | Fine-tuning of the section-header level inference, applied when do_pdf_heading_hierarchy is enabled. The nested enabled flag is set automatically from do_pdf_heading_hierarchy and does not need to be provided. |
| `include_images` | bool | If enabled, picture element images are generated and included in the output. Boolean. Optional, defaults to true. |
| `include_page_images` | bool | If enabled, full-page images are generated and included in the output. Boolean. Optional, defaults to false. |
| `images_scale` | float | Scale factor for images. Float. Optional, defaults to 2.0. |
| `md_page_break_placeholder` | str | Add this placeholder between pages in the markdown output. |
| `chunking_options` | HybridChunkerOptions or HierarchicalChunkerOptions or NoneType | Chunker configuration. |
| `chunking_preset` | str or NoneType | Preset ID for chunking (e.g. "granite_embedding_278m"). Mutually exclusive with chunking_options. |
| `do_code_enrichment` | bool | If enabled, perform OCR code enrichment. Boolean. Optional, defaults to false. |
| `do_formula_enrichment` | bool | If enabled, perform formula OCR, return LaTeX code. Boolean. Optional, defaults to false. |
| `do_picture_classification` | bool | If enabled, classify pictures in documents. Boolean. Optional, defaults to false. |
| `do_chart_extraction` | bool | If enabled, extract numeric data from charts. Boolean. Optional, defaults to false. |
| `do_picture_description` | bool | If enabled, describe pictures in documents. Boolean. Optional, defaults to false. |
| `picture_description_area_threshold` | float | Minimum percentage of the area for a picture to be processed with the models. |
| `picture_description_local` | PictureDescriptionLocal or NoneType | DEPRECATED: Options for running a local vision-language model in the picture description. The parameters refer to a model hosted on Hugging Face. This parameter is mutually exclusive with `picture_description_api`. Please migrate to `picture_description_preset` or `picture_description_custom_config`. |
| `picture_description_api` | PictureDescriptionApi or NoneType | DEPRECATED: API details for using a vision-language model in the picture description. This parameter is mutually exclusive with `picture_description_local`. Please migrate to `picture_description_preset` or `picture_description_custom_config`. |
| `vlm_pipeline_model` | VlmModelType or NoneType | DEPRECATED: Preset of local and API models for the `vlm` pipeline. This parameter is mutually exclusive with `vlm_pipeline_model_local` and `vlm_pipeline_model_api`. Use the other options for more parameters. Please migrate to `vlm_pipeline_preset` or `vlm_pipeline_custom_config`. |
| `vlm_pipeline_model_local` | VlmModelLocal or NoneType | DEPRECATED: Options for running a local vision-language model for the `vlm` pipeline. The parameters refer to a model hosted on Hugging Face. This parameter is mutually exclusive with `vlm_pipeline_model_api` and `vlm_pipeline_model`. Please migrate to `vlm_pipeline_preset` or `vlm_pipeline_custom_config`. |
| `vlm_pipeline_model_api` | VlmModelApi or NoneType | DEPRECATED: API details for using a vision-language model for the `vlm` pipeline. This parameter is mutually exclusive with `vlm_pipeline_model_local` and `vlm_pipeline_model`. Please migrate to `vlm_pipeline_preset` or `vlm_pipeline_custom_config`. |
| `vlm_pipeline_preset` | str or NoneType | Preset ID to use (e.g., "default", "`granite_docling`"). Use "default" for stable, admin-controlled configuration. |
| `picture_description_preset` | str or NoneType | Preset ID for picture description. |
| `code_formula_preset` | str or NoneType | Preset ID for code/formula extraction. |
| `vlm_pipeline_custom_config` | VlmConvertOptions or dict or NoneType | Custom VLM configuration including model spec and engine options. Only available if admin allows it. Must include '`model_spec`' and '`engine_options`'. |
| `picture_description_custom_config` | PictureDescriptionVlmEngineOptions or dict or NoneType | Custom picture description configuration including model spec and engine options. |
| `code_formula_custom_config` | CodeFormulaVlmOptions or dict or NoneType | Custom code/formula extraction configuration including model spec and engine options. |
| `table_structure_preset` | str or NoneType | Preset ID for table structure detection. |
| `table_structure_custom_config` | Dict[str, Any] or NoneType | Custom configuration for table structure model. Use this to specify a non-default kind with its options. The 'kind' field in the config dict determines which table structure implementation to use. If not specified, uses the default kind with preset configuration. |
| `layout_custom_config` | Dict[str, Any] or NoneType | Custom configuration for layout model. Use this to specify a non-default kind with its options. The 'kind' field in the config dict determines which layout implementation to use. If not specified, uses the default kind with preset configuration. |
| `layout_preset` | str or NoneType | Preset ID for layout detection. |
| `picture_classification_preset` | str or NoneType | Preset ID for picture classification. |
| `picture_classification_custom_config` | Dict[str, Any] or NoneType | Custom configuration for picture classification. Use this to specify custom options for the picture classifier. The configuration should match DocumentPictureClassifierOptions schema. |

<h4>CodeFormulaVlmOptions</h4>

| Field Name | Type | Description |
|------------|------|-------------|
| `engine_options` | BaseVlmEngineOptions | Runtime configuration (transformers, mlx, api, etc.) |
| `model_spec` | VlmModelSpec | Model specification with runtime-specific overrides |
| `scale` | float | Image scaling factor for preprocessing |
| `max_size` | int or NoneType | Maximum image dimension (width or height) |
| `extract_code` | bool | Extract code blocks |
| `extract_formulas` | bool | Extract mathematical formulas |

<h4>VlmModelSpec</h4>

| Field Name | Type | Description |
|------------|------|-------------|
| `name` | str | Human-readable model name |
| `default_repo_id` | str | Default HuggingFace repository ID |
| `revision` | str | Default model revision |
| `prompt` | str | Prompt template for this model |
| `response_format` | ResponseFormat | Expected response format from the model |
| `supported_engines` | Set or NoneType | Set of supported engines (None = all supported) |
| `engine_overrides` | Dict[VlmEngineType, EngineModelConfig] | Engine-specific configuration overrides |
| `api_overrides` | Dict[VlmEngineType, ApiModelConfig] | API-specific configuration overrides |
| `trust_remote_code` | bool | Whether to trust remote code for this model |
| `stop_strings` | List[str] | Stop strings for generation |
| `temperature` | float | Sampling temperature for generation |
| `max_new_tokens` | int | Maximum number of new tokens to generate |
| `extra_generation_config` | Dict[str, Any] | Additional generation configuration |

<h4>BaseVlmEngineOptions</h4>

| Field Name | Type | Description |
|------------|------|-------------|
| `engine_type` | VlmEngineType | Type of inference engine to use |

<h4>PictureDescriptionVlmEngineOptions</h4>

| Field Name | Type | Description |
|------------|------|-------------|
| `batch_size` | int | Number of images to process in a single batch during picture description. Higher values improve throughput but increase memory usage. Adjust based on available GPU/CPU memory. |
| `scale` | float | Scaling factor for image resolution before processing. Higher values (e.g., 2.0) provide more detail for the vision model but increase processing time and memory. Range: 0.5-4.0 typical. |
| `picture_area_threshold` | float | Minimum picture area as fraction of page area (0.0-1.0) to trigger description. Pictures smaller than this threshold are skipped. Use lower values (e.g., 0.01) to describe small images. |
| `classification_allow` | List[PictureClassificationLabel] or NoneType | List of picture classification labels to allow for description. Only pictures classified with these labels will be processed. If None, all picture types are allowed unless explicitly denied. Use to focus description on specific image types (e.g., diagrams, charts). |
| `classification_deny` | List[PictureClassificationLabel] or NoneType | List of picture classification labels to exclude from description. Pictures classified with these labels will be skipped. If None, no picture types are denied unless not in allow list. Use to exclude unwanted image types (e.g., decorative images, logos). |
| `classification_min_confidence` | float | Minimum classification confidence score (0.0-1.0) required for a picture to be processed. Pictures with classification confidence below this threshold are skipped. Higher values ensure only confidently classified images are described. Range: 0.0 (no filtering) to 1.0 (maximum confidence). |
| `engine_options` | BaseVlmEngineOptions | Runtime configuration (transformers, mlx, api, etc.) |
| `model_spec` | VlmModelSpec | Model specification with runtime-specific overrides |
| `prompt` | str | Prompt template for the vision model. Customize to control description style, detail level, or focus. |
| `generation_config` | Dict[str, Any] | Generation configuration for text generation. Controls output length, sampling strategy, temperature, etc. |

<h4>VlmConvertOptions</h4>

| Field Name | Type | Description |
|------------|------|-------------|
| `engine_options` | BaseVlmEngineOptions | Runtime configuration (transformers, mlx, api, etc.) |
| `model_spec` | VlmModelSpec | Model specification with runtime-specific overrides |
| `scale` | float | Image scaling factor for preprocessing |
| `max_size` | int or NoneType | Maximum image dimension (width or height) |
| `batch_size` | int | Batch size for processing multiple pages |
| `force_backend_text` | bool | Force use of backend text extraction instead of VLM |

<h4>VlmModelApi</h4>

| Field Name | Type | Description |
|------------|------|-------------|
| `url` | AnyUrl | Endpoint which accepts openai-api compatible requests. |
| `headers` | Dict[str, str] | Headers used for calling the API endpoint. For example, it could include authentication headers. |
| `params` | Dict[str, Any] | Model parameters. |
| `timeout` | float | Timeout for the API request. |
| `concurrency` | int | Maximum number of concurrent requests to the API. |
| `prompt` | str | Prompt used when calling the vision-language model. |
| `scale` | float | Scale factor of the images used. |
| `response_format` | ResponseFormat | Type of response generated by the model. |
| `temperature` | float | Temperature parameter controlling the reproducibility of the result. |

<h4>VlmModelLocal</h4>

| Field Name | Type | Description |
|------------|------|-------------|
| `repo_id` | str | Repository id from the Hugging Face Hub. |
| `prompt` | str | Prompt used when calling the vision-language model. |
| `scale` | float | Scale factor of the images used. |
| `response_format` | ResponseFormat | Type of response generated by the model. |
| `inference_framework` | InferenceFramework | Inference framework to use. |
| `transformers_model_type` | TransformersModelType | Type of transformers auto-model to use. |
| `extra_generation_config` | Dict[str, Any] | Config from https://huggingface.co/docs/transformers/en/main_classes/text_generation#transformers.GenerationConfig |
| `temperature` | float | Temperature parameter controlling the reproducibility of the result. |

<h4>PictureDescriptionApi</h4>

| Field Name | Type | Description |
|------------|------|-------------|
| `url` | AnyUrl | Endpoint which accepts openai-api compatible requests. |
| `headers` | Dict[str, str] | Headers used for calling the API endpoint. For example, it could include authentication headers. |
| `params` | Dict[str, Any] | Model parameters. |
| `timeout` | float | Timeout for the API request. |
| `concurrency` | int | Maximum number of concurrent requests to the API. |
| `prompt` | str | Prompt used when calling the vision-language model. |
| `classification_allow` | List[PictureClassificationLabel] or NoneType | Only describe pictures whose predicted class is in this allow-list. |
| `classification_deny` | List[PictureClassificationLabel] or NoneType | Do not describe pictures whose predicted class is in this deny-list. |
| `classification_min_confidence` | float | Minimum classification confidence required before a picture can be described. |

<h4>PictureDescriptionLocal</h4>

| Field Name | Type | Description |
|------------|------|-------------|
| `repo_id` | str | Repository id from the Hugging Face Hub. |
| `prompt` | str | Prompt used when calling the vision-language model. |
| `generation_config` | Dict[str, Any] | Config from https://huggingface.co/docs/transformers/en/main_classes/text_generation#transformers.GenerationConfig |
| `classification_allow` | List[PictureClassificationLabel] or NoneType | Only describe pictures whose predicted class is in this allow-list. |
| `classification_deny` | List[PictureClassificationLabel] or NoneType | Do not describe pictures whose predicted class is in this deny-list. |
| `classification_min_confidence` | float | Minimum classification confidence required before a picture can be described. |

<h4>HierarchicalChunkerOptions</h4>

| Field Name | Type | Description |
|------------|------|-------------|
| `chunker` | Literal | No description provided. |
| `use_markdown_tables` | bool | Use markdown table format instead of triplets for table serialization. |
| `use_markdown_images` | bool | Enable image serialization and image references inside chunks. Also adds a `has_image` field to chunk metadata to make image-containing chunks easier to identify. |
| `image_placeholder` | str | Placeholder text used inside chunks to reference an image when markdown image serialization is disabled. |
| `include_raw_text` | bool | Include both raw_text and text (contextualized) in response. If False, only text is included. |

<h4>HybridChunkerOptions</h4>

| Field Name | Type | Description |
|------------|------|-------------|
| `chunker` | Literal | No description provided. |
| `use_markdown_tables` | bool | Use markdown table format instead of triplets for table serialization. |
| `use_markdown_images` | bool | Enable image serialization and image references inside chunks. Also adds a `has_image` field to chunk metadata to make image-containing chunks easier to identify. |
| `image_placeholder` | str | Placeholder text used inside chunks to reference an image when markdown image serialization is disabled. |
| `include_raw_text` | bool | Include both raw_text and text (contextualized) in response. If False, only text is included. |
| `max_tokens` | int or NoneType | Maximum number of tokens per chunk. When left to none, the value is automatically extracted from the tokenizer. |
| `tokenizer` | str | HuggingFace model name for custom tokenization. If not specified, uses 'sentence-transformers/all-MiniLM-L6-v2' as default. |
| `merge_peers` | bool | Merge undersized successive chunks with same headings. |

<h4>HeadingHierarchyOptions</h4>

| Field Name | Type | Description |
|------------|------|-------------|
| `enabled` | bool | Enable inference of section-header levels for the PDF/image pipeline. When disabled (default), all detected headings remain at level 1 (unchanged behavior). |
| `use_bookmarks` | bool | Use the PDF bookmarks / table-of-contents (when present) as the authoritative heading signal. Bookmarks are fuzzily matched to detected headings by title and page; confident matches win over numbering and style, and a confidently matched list-item is promoted to a heading. Unmatched entries fall back to numbering/style. |
| `use_numbering` | bool | Use legal/outline numbering (e.g. PART I -> 1. -> 1.1 -> (a) -> (i), Roman vs Arabic numerals) as the primary signal for headings without a bookmark match. |
| `use_style` | bool | Use the visual style of the heading (font size, and with `use_font_style` also weight, slant and letter case) as a fallback for headings without recognizable numbering. Requires `generate_parsed_pages=True`. |
| `use_font_style` | bool | Refine the style fallback with the font weight and slant read from the embedded PDF font names, plus all-caps detection, so that headings sharing a font size are still ranked (bold above regular, upright above italic, all-caps above mixed case). Ignored when `use_style` is disabled; font names that carry no recognizable styling fall back to font size alone. |
| `style_size_tolerance` | float | Relative difference below which two heading font sizes are treated as one size by the style fallback. The size of a heading is measured from its cells, so the same font measures a little taller on a heading that has descenders; without this tolerance such headings would land on different levels. Higher = more sizes collapse into one level. |
| `numbering_schemes` | List[str] or NoneType | Optional override of the numbering-scheme precedence (highest level first). Known schemes: 'part', 'chapter', 'article', 'roman_u', 'arabic', 'alpha_u', 'alpha_l', 'roman_l'. When None, a default legal/regulatory ordering is used. |
| `max_level` | int | Maximum heading level to assign. Deeper levels are clamped. |
| `bookmark_match_threshold` | float | Minimum normalized title-similarity (0..1) for a bookmark to be considered a match to a detected heading/list-item. Below this, the bookmark is ignored and the heading falls back to numbering/style. Higher = stricter. |

<!-- end: parameters-docs -->

### Authentication

When authentication is activated (see the parameter `DOCLING_SERVE_API_KEY` in [configuration.md](./configuration.md)), all the API requests **must** provide the header `X-Api-Key` with the correct secret key.

### Batch connector plugins

`DoclingServiceClient.submit_batch()` accepts mappings for connector source and
artifact-target kinds that the installed SDK does not know:

```python
job = client.submit_batch(
    sources=[
        {
            "kind": "filenet",
            "base_url": "https://filenet.example.com/graphql",
            "username": "user",
            "api_key": "secret",
            "repository_id": "OS1",
            "folder_id": "/incoming",
        }
    ],
    target={
        "kind": "plugin_artifact_store",
        "bucket": "converted",
        "prefix": "results/",
        "api_key": "secret",
    },
)
```

The SDK's generic models only preserve and serialize these mappings. The running
server validates them against the concrete connector models installed in that
deployment. Configure both `DOCLING_SERVE_ALLOWED_SOURCE_TYPES` and
`DOCLING_SERVE_ALLOWED_TARGET_TYPES`; third-party connectors also require
`DOCLING_SERVE_ALLOW_EXTERNAL_PLUGINS=true`.

Install the same connector package versions in every API and Local, RQ, or Ray
worker process, and keep their Docling, Jobkit, and Serve versions aligned. The
running deployment's `/openapi.json` lists its enabled concrete connector
schemas. Plugin installation or policy changes appear there only after restart.

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

#### Callbacks

Both `/v1/convert/file` and `/v1/convert/file/async` accept an optional `callbacks` field.
Repeat the field once per endpoint you want notified when the conversion completes.

Each value is either a **bare URL** (shortcut) or a **JSON-encoded `CallbackSpec` object** with optional headers and a CA certificate:

| Format | Example value |
|--------|---------------|
| Bare URL | `https://hook.example.com/done` |
| JSON object | `{"url":"https://hook.example.com/done","headers":{"Authorization":"Bearer tok"},"ca_cert":""}` |

The bare-URL format is the easiest way to register a webhook. Use the JSON-object format when you need custom request headers (e.g. an auth token) or a non-default CA certificate for TLS verification.

<details>
<summary>CURL example — bare URL callback:</summary>

```sh
curl -X 'POST' \
  'http://127.0.0.1:5001/v1/convert/file' \
  -H 'accept: application/json' \
  -H 'Content-Type: multipart/form-data' \
  -F 'files=@document.pdf;type=application/pdf' \
  -F 'callbacks=https://hook.example.com/done'
```

</details>

<details>
<summary>CURL example — multiple callbacks, one with custom headers:</summary>

```sh
curl -X 'POST' \
  'http://127.0.0.1:5001/v1/convert/file' \
  -H 'accept: application/json' \
  -H 'Content-Type: multipart/form-data' \
  -F 'files=@document.pdf;type=application/pdf' \
  -F 'callbacks=https://hook.example.com/done' \
  -F 'callbacks={"url":"https://secure.example.com/notify","headers":{"Authorization":"Bearer my-token"}}'
```

</details>

<details>
<summary>Python example — callbacks with httpx:</summary>

```python
import httpx

async_client = httpx.AsyncClient(timeout=60.0)
url = "http://localhost:5001/v1/convert/file"

with open("document.pdf", "rb") as f:
    response = await async_client.post(
        url,
        files={"files": ("document.pdf", f, "application/pdf")},
        data={
            "callbacks": [
                "https://hook.example.com/done",
                '{"url":"https://secure.example.com/notify","headers":{"Authorization":"Bearer my-token"}}',
            ]
        },
    )

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
            if payload["message"] == "update" and payload["task"]["task_status"] in ("success", "failure"):
                break
        except:
          break
```

</details>

### Fetch results

When the task is completed, the result can be fetched with the endpoint:

- `GET /v1/result/{task_id}`
