"""Load, chunk, embed and store documents.

The pipeline keeps a document store next to the vector store, keyed by
file path. Running it again skips unchanged files and re-embeds changed
ones, so restarting the service does not pay for every embedding again.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from llama_index.core import Settings, SimpleDirectoryReader, StorageContext, VectorStoreIndex
from llama_index.core.ingestion import DocstoreStrategy, IngestionPipeline
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import BaseNode, Document
from llama_index.core.storage.docstore import SimpleDocumentStore
from llama_index.core.vector_stores.types import BasePydanticVectorStore

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_documents(path: Path = DATA_DIR, subdir: str | None = None) -> list[Document]:
    """Read Markdown files; the folder name becomes a `collection` metadata field."""
    root = path / subdir if subdir else path
    reader = SimpleDirectoryReader(
        input_dir=str(root),
        recursive=True,
        required_exts=[".md"],
        filename_as_id=True,
        raise_on_error=True,
        file_metadata=lambda p: {"file_name": Path(p).name, "collection": Path(p).parent.name},
    )
    return reader.load_data()


def splitter() -> SentenceSplitter:
    return SentenceSplitter(chunk_size=512, chunk_overlap=50)


def split(documents: list[Document]) -> list[BaseNode]:
    return splitter().get_nodes_from_documents(documents)


@dataclass
class IngestResult:
    index: VectorStoreIndex
    nodes_written: int


def ingest(
    documents: list[Document],
    vector_store: BasePydanticVectorStore,
    docstore_path: Path | None = None,
) -> IngestResult:
    """Upsert documents into `vector_store`; only new or changed files are embedded."""
    docstore = (
        SimpleDocumentStore.from_persist_path(str(docstore_path))
        if docstore_path and docstore_path.exists()
        else SimpleDocumentStore()
    )
    pipeline = IngestionPipeline(
        transformations=[splitter(), Settings.embed_model],
        vector_store=vector_store,
        docstore=docstore,
        docstore_strategy=DocstoreStrategy.UPSERTS,
    )
    written = pipeline.run(documents=documents)
    if docstore_path:
        docstore_path.parent.mkdir(parents=True, exist_ok=True)
        pipeline.docstore.persist(str(docstore_path))
    index = VectorStoreIndex.from_vector_store(vector_store)
    return IngestResult(index=index, nodes_written=len(written))


def chroma_store(path: Path, collection: str = "documents") -> BasePydanticVectorStore:
    import chromadb
    from llama_index.vector_stores.chroma import ChromaVectorStore

    client = chromadb.PersistentClient(path=str(path))
    return ChromaVectorStore(chroma_collection=client.get_or_create_collection(collection))


def qdrant_store(path: Path | None = None, url: str | None = None, collection: str = "documents") -> BasePydanticVectorStore:
    """Local on-disk Qdrant by default; pass `url` for a Qdrant server or Qdrant Cloud."""
    from qdrant_client import QdrantClient
    from llama_index.vector_stores.qdrant import QdrantVectorStore

    client = QdrantClient(url=url) if url else QdrantClient(path=str(path))
    return QdrantVectorStore(client=client, collection_name=collection)


def in_memory_index(documents: list[Document]) -> VectorStoreIndex:
    return VectorStoreIndex(split(documents), storage_context=StorageContext.from_defaults())
