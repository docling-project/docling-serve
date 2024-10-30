import base64
import os
from contextlib import asynccontextmanager
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Union

import httpx
from docling.datamodel.base_models import (
    ConversionStatus,
    DocumentStream,
    PipelineOptions,
)
from docling.datamodel.document import ConversionResult, DocumentConversionInput
from docling.document_converter import DocumentConverter
from fastapi import FastAPI, HTTPException, File, UploadFile
from pydantic import BaseModel

from docling_serve.settings import Settings

from llama_index.core.readers.base import BasePydanticReader
from llama_index.core.schema import Document as LIDocument
from llama_index.core.node_parser import MarkdownNodeParser
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.milvus import MilvusVectorStore
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.llms.openai import OpenAI
from pymilvus import connections, Collection, utility

class HttpSource(BaseModel):
    url: str
    headers: Dict[str, Any] = {}


class FileSource(BaseModel):
    base64_string: str
    filename: str


class ConvertDocumentHttpSourceRequest(BaseModel):
    http_source: HttpSource


class ConvertDocumentFileSourceRequest(BaseModel):
    file_source: FileSource


class ConvertDocumentResponse(BaseModel):
    content_md: str


ConvertDocumentRequest = Union[
    ConvertDocumentFileSourceRequest, ConvertDocumentHttpSourceRequest
]


# New models for RAG functionality
class CreateCollectionRequest(BaseModel):
    collection_name: str


class QueryRequest(BaseModel):
    question: str


class DocumentMetadata(BaseModel):
    dl_doc_hash: str


models = {}

# Setting TOKENIZERS_PARALLELISM to avoid warnings
os.environ["TOKENIZERS_PARALLELISM"] = "false"
MILVUS_LOCAL_FILE_PATH = "/Users/brent/code/docling/rag-svc-pr/docling-serve"


class DoclingPDFReader(BasePydanticReader):
    class ParseType(str, Enum):
        MARKDOWN = "markdown"
        # JSON = "json"

    parse_type: ParseType = ParseType.MARKDOWN

    def lazy_load_data(
            self, file_path: Union[str, List[str]]
    ) -> Iterable[LIDocument]:
        file_paths = file_path if isinstance(file_path, list) else [file_path]
        converter = DocumentConverter()
        for source in file_paths:
            dl_doc = converter.convert_single(source).output
            if self.parse_type == self.ParseType.MARKDOWN:
                text = dl_doc.export_to_markdown()
            else:
                raise RuntimeError(
                    f"Unexpected parse type encountered: {self.parse_type}"
                )
            excl_metadata_keys = ["dl_doc_hash"]
            li_doc = LIDocument(
                doc_id=dl_doc.file_info.document_hash,
                text=text,
                excluded_embed_metadata_keys=excl_metadata_keys,
                excluded_llm_metadata_keys=excl_metadata_keys,
            )
            li_doc.metadata = DocumentMetadata(
                dl_doc_hash=dl_doc.file_info.document_hash,
            ).model_dump()
            yield li_doc


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Converter
    settings = Settings()
    pipeline_options = PipelineOptions()
    pipeline_options.do_ocr = settings.do_ocr
    pipeline_options.do_table_structure = settings.do_table_structure
    models["converter"] = DocumentConverter(pipeline_options=pipeline_options)

    # Embedding model
    embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")
    models["embed_model"] = embed_model

    # Calculate the dimension once and store it
    sample_embedding = embed_model.get_text_embedding("sample text")
    models["embed_dim"] = len(sample_embedding)

    # Use OpenAI API for the Instructlab endpoint
    models["llm"] = OpenAI(
        api_key="dummy-key",
        api_base="http://127.0.0.1:8080/v1",
        model="merlinite-7b-lab-Q4_K_M.gguf",
        max_tokens=1500,
        temperature=0.1,
    )

    # Node Parser
    models["node_parser"] = MarkdownNodeParser()

    # Check if database exists, if not, create it
    if not os.path.exists(MILVUS_LOCAL_FILE_PATH):
        os.makedirs(MILVUS_LOCAL_FILE_PATH)
        print(f"Created Milvus storage directory at {MILVUS_LOCAL_FILE_PATH}")
    else:
        print(f"Milvus storage directory exists at {MILVUS_LOCAL_FILE_PATH}")

    yield

    models.clear()


app = FastAPI(
    title="Docling Serve",
    lifespan=lifespan,
)


@app.post("/convert")
def convert_pdf_document(
    body: ConvertDocumentRequest,
) -> ConvertDocumentResponse:
    filename: str
    buf: BytesIO

    if isinstance(body, ConvertDocumentFileSourceRequest):
        buf = BytesIO(base64.b64decode(body.file_source.base64_string))
        filename = body.file_source.filename
    elif isinstance(body, ConvertDocumentHttpSourceRequest):
        http_res = httpx.get(body.http_source.url, headers=body.http_source.headers)
        buf = BytesIO(http_res.content)
        filename = Path(
            body.http_source.url
        ).name

    docs_input = DocumentConversionInput.from_streams(
        [DocumentStream(filename=filename, stream=buf)]
    )
    result: ConversionResult = next(models["converter"].convert(docs_input), None)

    if result is None or result.status != ConversionStatus.SUCCESS:
        raise HTTPException(status_code=500, detail={"errors": result.errors})

    return ConvertDocumentResponse(content_md=result.render_as_markdown())


@app.get("/collections")
def list_collections():
    try:
        connections.connect(uri=f"{MILVUS_LOCAL_FILE_PATH}/milvus_llamaindex.db")

        # List all collections
        collections = utility.list_collections()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"collections": collections}


@app.delete("/collections/{collection_name}")
def delete_collection(collection_name: str):
    # Connect to Milvus using the local file path
    connections.connect(uri=f"{MILVUS_LOCAL_FILE_PATH}/milvus_llamaindex.db")

    # Check if the collection exists
    if collection_name not in utility.list_collections():
        raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' does not exist.")

    try:
        # Drop the collection
        utility.drop_collection(collection_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"message": f"Collection '{collection_name}' deleted successfully"}


@app.post("/collections/{collection_name}/documents/file")
async def ingest_document_file(
        collection_name: str,
        file: UploadFile = File(...)
):
    # Handle the file upload
    file_content = await file.read()
    buf = BytesIO(file_content)
    filename = file.filename

    # Convert the document and ingest into the vector DB
    return await process_and_ingest_document(collection_name, filename, buf)


@app.post("/collections/{collection_name}/documents/url")
async def ingest_document_http(
        collection_name: str,
        body: ConvertDocumentHttpSourceRequest
):
    # Fetch the document from the URL
    http_res = httpx.get(body.http_source.url, headers=body.http_source.headers)
    if http_res.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch document from URL: {body.http_source.url}",
        )
    buf = BytesIO(http_res.content)
    filename = Path(body.http_source.url).name

    # Convert the document and ingest into the vector DB
    return await process_and_ingest_document(collection_name, filename, buf)


async def process_and_ingest_document(collection_name: str, filename: str, buf: BytesIO):
    # Convert the document to markdown using the converter
    converter = models.get("converter")
    docs_input = DocumentConversionInput.from_streams(
        [DocumentStream(filename=filename, stream=buf)]
    )
    result: ConversionResult = next(converter.convert(docs_input), None)

    if result is None or result.status != ConversionStatus.SUCCESS:
        raise HTTPException(status_code=500, detail={"errors": result.errors})

    # Get the markdown content
    markdown_content = result.render_as_markdown()

    # Create a LlamaIndex document
    li_doc = LIDocument(
        doc_id=result.output.file_info.document_hash,
        text=markdown_content,
        excluded_embed_metadata_keys=["dl_doc_hash"],
        excluded_llm_metadata_keys=["dl_doc_hash"],
    )
    li_doc.metadata = DocumentMetadata(
        dl_doc_hash=result.output.file_info.document_hash,
    ).model_dump()

    # Transformations
    node_parser = models.get("node_parser")
    transformations = [node_parser]

    # Embed model
    embed_model = models.get("embed_model")

    # Index name and parameters (must match the ones used during collection creation)
    index_name = "default_index"
    index_params = {
        "metric_type": "IP",
        "index_type": "HNSW",
        "params": {"M": 8, "efConstruction": 64},
    }

    # Initialize the vector store for the collection
    vector_store = MilvusVectorStore(
        collection_name=collection_name,
        dim=len(embed_model.get_text_embedding("hi")),
        index_params=index_params,
        index_name=index_name,
        overwrite=False,  # Do not overwrite existing collection

    )

    # Create storage context
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    # Create or update the index
    index = VectorStoreIndex.from_documents(
        documents=[li_doc],
        embed_model=embed_model,
        storage_context=storage_context,
        transformations=transformations,
    )

    # Return success
    return {"message": "Document ingested successfully into collection"}


@app.post("/collections/{collection_name}/query")
def query_collection(collection_name: str, body: QueryRequest):
    question = body.question

    # Embed model
    embed_model = models.get("embed_model")

    # Use the Instructlab API initialized earlier
    llm = models.get("llm")

    # Initialize the vector store for the collection
    vector_store = MilvusVectorStore(
        collection_name=collection_name,
    )

    # Check if the collection exists
    if collection_name not in vector_store.client.list_collections():
        raise HTTPException(
            status_code=400,
            detail=f"Collection '{collection_name}' does not exist.",
        )

    # Check if _collection is loaded, otherwise load it
    if not hasattr(vector_store, '_collection') or vector_store._collection is None:
        vector_store._collection = Collection(collection_name, using=vector_store.client._using)

    # Load the index
    index = VectorStoreIndex.from_vector_store(
        vector_store=vector_store,
        embed_model=embed_model,
    )

    # Create query engine
    query_engine = index.as_query_engine(llm=llm)

    # Form the prompt and perform the query
    prompt = f"Question: {question}\nProvide a detailed answer based on the document."
    query_res = query_engine.query(prompt)

    response = {
        "query": question,
        "answer": query_res.response.strip(),
        "sources": [{"text": node.node.get_text(), "metadata": node.node.metadata} for node in query_res.source_nodes]
    }

    # Print the response to the console
    print("Query:", response["query"])
    print("Answer:", response["answer"])

    # Print sources and metadata
    if "sources" in response:
        print("Sources:")
        for source in response["sources"]:
            print(f"Text: {source['text']}")
            print(f"Metadata: {source['metadata']}")

    return response
