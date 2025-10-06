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
python -m docling_serve run
```

## Create endpoint
Run `python create_endpoint.py`

## Test endpoint
Run `python test_endpoint.py`

## Chunking
* Tokenizer files taken from `https://huggingface.co/intfloat/multilingual-e5-large/tree/main` commit `0dc5580a448e4284468b8909bae50fa925907bc5`
* Our embedding model will truncate anything over [512 tokens](https://huggingface.co/intfloat/multilingual-e5-large#limitations)
* In order to prevent docling from attempting to download from Huggingface high side, the tokenizer files are built into the docker image
* The chunker should use the same tokenizer as the embedding model so the embedding model doesn't truncate any of the chunks

## Limitations
* Sagemaker Endpoints accept a maximum request size of 25 MB, otherwise they respond with a 413 error code. If we want to process files larger than 25 MB one potential workaround is to put the inference container in a VPC so that it can query the file directly in our database

## Resources
* https://docs.aws.amazon.com/sagemaker/latest/dg/adapt-inference-container.html