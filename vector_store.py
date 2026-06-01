from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document


DB_PATH = "faiss_index"


# Load env from the repo root .env even when callers forget to.
# This avoids surprises with import order (e.g. api_server imports vector_store
# before calling load_dotenv()).
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _vector_store_mode() -> str:
    """Vector store backend selector.

    - Default: faiss
    - Set VECTOR_STORE=pinecone to persist vectors in Pinecone.
    """
    return (_env("VECTOR_STORE", "faiss") or "faiss").lower()


def _pinecone_configured() -> bool:
    return bool(_env("PINECONE_API_KEY") and _env("PINECONE_INDEX_NAME"))


def _pinecone_dimension(embeddings: Any) -> int:
    # HuggingFaceEmbeddings provides embed_query; probe to infer dimension.
    vec = embeddings.embed_query("dimension probe")
    return len(vec)


def _get_or_create_pinecone_index(embeddings: Any):
    try:
        from pinecone import Pinecone, ServerlessSpec  # type: ignore
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(
            "Missing dependency: 'pinecone'. Install it (pip install pinecone) "
            "or ensure your environment was rebuilt after updating requirements.txt."
        ) from e

    api_key = _env("PINECONE_API_KEY")
    index_name = _env("PINECONE_INDEX_NAME")
    if not api_key or not index_name:
        raise ValueError(
            "Pinecone is selected but PINECONE_API_KEY and PINECONE_INDEX_NAME are not set."
        )

    cloud = _env("PINECONE_CLOUD", "aws")
    region = _env("PINECONE_REGION", "us-east-1")
    metric = (_env("PINECONE_METRIC", "cosine") or "cosine").lower()

    pc = Pinecone(api_key=api_key)

    try:
        existing = set(pc.list_indexes().names())
    except Exception:
        try:
            existing = {idx["name"] for idx in pc.list_indexes()}
        except Exception:
            existing = set()
    if index_name not in existing:
        dim = _pinecone_dimension(embeddings)
        pc.create_index(
            name=index_name,
            dimension=dim,
            metric=metric,
            spec=ServerlessSpec(cloud=cloud, region=region),
        )
    else:
        # Best-effort validation to catch common "dimension mismatch" errors.
        desc = None
        try:
            desc = pc.describe_index(index_name)
        except Exception:
            # If describe isn't available for this index type, skip validation.
            desc = None

        if desc is not None:
            existing_dim = None
            existing_metric = None
            if isinstance(desc, dict):
                existing_dim = desc.get("dimension")
                existing_metric = desc.get("metric")
            else:
                existing_dim = getattr(desc, "dimension", None)
                existing_metric = getattr(desc, "metric", None)

            desired_dim = _pinecone_dimension(embeddings)
            if isinstance(existing_dim, int) and existing_dim != desired_dim:
                raise ValueError(
                    "Pinecone index dimension mismatch: "
                    f"index '{index_name}' has dimension {existing_dim}, "
                    f"but local embeddings produce dimension {desired_dim}. "
                    "Create a new Pinecone index with the correct dimension or "
                    "switch your embedding model to match the existing index."
                )

            if (
                isinstance(existing_metric, str)
                and existing_metric
                and existing_metric.lower() != metric
            ):
                raise ValueError(
                    "Pinecone index metric mismatch: "
                    f"index '{index_name}' uses metric '{existing_metric}', "
                    f"but PINECONE_METRIC is '{metric}'. "
                    "Update PINECONE_METRIC or use a compatible index."
                )

    return pc.Index(index_name)


def _safe_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (meta or {}).items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[str(k)] = v
        else:
            out[str(k)] = str(v)
    return out


class PineconeVectorDB:
    def __init__(self, *, index: Any, embeddings: Any, namespace: str | None = None):
        self._index = index
        self._embeddings = embeddings
        self._namespace = namespace

    def add_documents(self, docs: list[Any]) -> None:
        if not docs:
            return
        texts = [d.page_content for d in docs]
        vectors = self._embeddings.embed_documents(texts)

        upserts = []
        for doc, vec in zip(docs, vectors):
            meta = _safe_metadata(getattr(doc, "metadata", {}) or {})
            meta["text"] = doc.page_content
            upserts.append({"id": str(uuid.uuid4()), "values": vec, "metadata": meta})

        # pinecone Index supports dict-style upserts.
        self._index.upsert(vectors=upserts, namespace=self._namespace)

    def similarity_search(self, query: str, k: int = 5) -> list[Document]:
        q = self._embeddings.embed_query(query)
        res = self._index.query(
            vector=q,
            top_k=k,
            include_metadata=True,
            namespace=self._namespace,
        )

        matches = None
        if isinstance(res, dict):
            matches = res.get("matches")
        else:
            matches = getattr(res, "matches", None)

        out: list[Document] = []
        for m in matches or []:
            md = None
            if isinstance(m, dict):
                md = m.get("metadata")
            else:
                md = getattr(m, "metadata", None)
            md = dict(md or {})
            text = str(md.pop("text", "") or "")
            out.append(Document(page_content=text, metadata=md))
        return out


def _pinecone_vector_store(embeddings: Any, namespace: str | None = None) -> PineconeVectorDB:
    index = _get_or_create_pinecone_index(embeddings)
    return PineconeVectorDB(index=index, embeddings=embeddings, namespace=namespace)


def create_vector_store(chunks: list[Any], embeddings: Any, namespace: str | None = None):
    """Create and persist a vector store from documents.

    - FAISS: stores locally in ./faiss_index
    - Pinecone: upserts into the configured Pinecone index (optionally scoped by namespace)
    """
    mode = _vector_store_mode()

    if mode == "pinecone":
        if not _pinecone_configured():
            raise ValueError(
                "VECTOR_STORE=pinecone but Pinecone is not configured. "
                "Set PINECONE_API_KEY and PINECONE_INDEX_NAME."
            )

        vector_db = _pinecone_vector_store(embeddings, namespace=namespace)
        # Upsert documents for this namespace.
        vector_db.add_documents(chunks)
        return vector_db

    # Default: FAISS
    vector_db = FAISS.from_documents(chunks, embeddings)

    os.makedirs(DB_PATH, exist_ok=True)
    vector_db.save_local(DB_PATH)
    return vector_db


def load_vector_store(embeddings: Any, namespace: str | None = None):
    """Load an existing vector store.

    Note: With Pinecone, this just returns a handle to the existing index.
    """
    mode = _vector_store_mode()

    if mode == "pinecone":
        if not _pinecone_configured():
            return None
        return _pinecone_vector_store(embeddings, namespace=namespace)

    if os.path.exists(DB_PATH):
        return FAISS.load_local(DB_PATH, embeddings, allow_dangerous_deserialization=True)

    return None