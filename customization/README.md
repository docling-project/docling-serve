## Syncing fork
```bash
git remote add upstream git@github.com:docling-project/docling-serve.git # this only needs to be run once
git fetch upstream
git checkout main
git merge upstream/main
git push
```

## Building the image
1. Checkout `docling-serve` main branch
2. Update files
    * `docling-serve/docling_serve/app.py`
    * `docling-serve/docling_serve/settings.py`
    * `docling-serve/docling_serve/datamodel/convert.py`
    * `docling-serve/docling_serve/helper_functions.py`
    * `docling-serve/docling_serve/datamodel/responses.py`
    * `docling_serve/__main__.py`
    * `pyproject.toml`
3. Add files
    * `docling-serve/Dockerfile`
    * `docling-serve/serve`
4. Delete files
    * `docling-serve/Containerfile`
5. Build the image - First login to AWS and then run `build.sh`
6. Run the image `docker run --rm -e DOCLING_SERVE_ENABLE_UI="1" -e S3_MODEL_URI="s3://201486032796-sagemaker-models/app/models" -e AWS_ACCESS_KEY_ID="" -e AWS_SECRET_ACCESS_KEY="" -e AWS_SESSION_TOKEN="" -p 8080:8080 201486032796.dkr.ecr.us-east-1.amazonaws.com/docling-sagemaker:$VERSION`
7. Test conversion `python test_docling.py`


## Running outside docker
```bash
uv venv --python 3.12
source .venv/bin/activate
cd docling-serve # this is important, if you run this from the root of repo it will the pypi docling-serve
uv pip install .
python -m docling_serve run --reload
```

## Create endpoint
Run `python create_endpoint.py`

## Test endpoint
Run `python test_endpoint.py`

## Docling parameter tuning
The below are parameters that can only be set when docling starts up https://github.com/docling-project/docling-serve/blob/main/docs/configuration.md.
* `DOCLING_SERVE_ENG_LOC_NUM_WORKERS` - Number of workers/threads processing the incoming tasks. Default is 2. This is the number of workers subscribed to the internal `asyncio.Queue` where requests are placed
* `DOCLING_NUM_THREADS` - Number of concurrent threads for processing a document. Default is 4. This is only used if using `cpu` during model inference
* `DOCLING_SERVE_ENG_LOC_SHARE_MODELS` - If true, each process will share the same models among all thread workers. Otherwise, one instance of the models is allocated for each worker thread, would be `DOCLING_SERVE_ENG_LOC_NUM_WORKERS` instances. Default is False
* `DOCLING_SERVE_OPTIONS_CACHE_SIZE` - How many DocumentConveter objects (including their loaded models) to keep in the cache. Default is 2. This config is passed to `LocalOrchestrator`
* `DOCLING_SERVE_MAX_DOCUMENT_TIMEOUT` - The maximum time in seconds for processing a document. Default is 7 days
* `DOCLING_SERVE_ENG_KIND` - Compute engine for async tasks, default is local

The below can be set per request https://github.com/docling-project/docling-serve/blob/main/docs/usage.md
* `do_picture_classification` - classify pictures in documents
* `do_picture_description` - must set either `picture_description_local` or `picture_description_api` to use this
* `picture_description_local` - options for local vlm
* `picture_description_api` - options for api vlm
* `include_images` - extract images from document
* `image_export_mode` - how images are stored in the output document
* `pipeline` - `standard` or `vlm`, if using `vlm` the `vlm` model must be installed
* `do_ocr` - process bitmap content using ocr
* `force_ocr` - treat entire PDF as an image
* `pdf_backend` - library to use for text extraction
* `table_mode` - `fast` or `accurate` when extracting tables
* `document_timeout` - this overrides `DOCLING_SERVE_MAX_DOCUMENT_TIMEOUT` above

docling-serve uses uvicorn, so the default uvicorn parameters are also available
* `UVICORN_WORKERS` - Defaults to 1. If this is not 1 it may scale `DOCLING_SERVE_OPTIONS_CACHE_SIZE` and `DOCLING_SERVE_ENG_LOC_NUM_WORKERS`


## Request queue
If using the default local orhcestrator set by `DOCLING_SERVE_ENG_KIND`, it creates a `asyncio.Queue` which is monitored by `DOCLING_SERVE_ENG_LOC_NUM_WORKERS`. `app._enque_file` adds a request to this queue, by default only 2 requests can be processed concurrently

Functions available to inspect queue are [here](https://github.com/docling-project/docling-jobkit/blob/main/docling_jobkit/orchestrators/local/orchestrator.py). `queue_size`, `get_queue_position`, `task_status` are the functions available

`asycio` is used to run the workers, when a worker runs a conversion task it awaits `asyncio.to_thread` which allows the other worker's event loop to proceed. By awaiting `asyncio.to_thread` this caps the concurrent tasks processed to 2, without the await it could create an arbitrary number of concurrent tasks


## Chunking
* Tokenizer files taken from `https://huggingface.co/intfloat/multilingual-e5-large/tree/main` commit `0dc5580a448e4284468b8909bae50fa925907bc5`
* Our embedding model will truncate anything over [512 tokens](https://huggingface.co/intfloat/multilingual-e5-large#limitations)
* In order to prevent docling from attempting to download from Huggingface high side, the tokenizer files are built into the docker image
* The chunker should use the same tokenizer as the embedding model so the embedding model doesn't truncate any of the chunks

## Limitations
* Sagemaker Endpoints accept a maximum request size of 25 MB, otherwise they respond with a 413 error code. We have modified the docling-serve code to support downloading a file from S3 to get around this

## Resources
* https://docs.aws.amazon.com/sagemaker/latest/dg/adapt-inference-container.html