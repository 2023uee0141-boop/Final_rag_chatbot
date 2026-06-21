from rank_bm25 import BM25Okapi
import threading
import time
from typing import Any

try:
    # Newer package name
    from ddgs import DDGS  # type: ignore
except Exception:
    # Legacy package name
    from duckduckgo_search import DDGS  # type: ignore


# ==========================================
# CONVERSATION HISTORY
# ==========================================

def get_message_history(messages):
    """Convert messages to conversation history string"""
    history_text = ""
    for msg in messages:
        if msg["role"] == "user":
            history_text += f"Q: {msg['content']}\n\n"
        else:
            history_text += f"A: {msg['content']}\n\n"
    return history_text


# ==========================================
# QUERY GENERATION (1 LLM Call)
# ==========================================

def generate_search_queries(llm, query, messages) -> list[str]:
    """Generate 2-3 optimized search sub-queries based on history and current query."""
    history = get_message_history(messages)
    
    prompt = f"""Conversation History:
{history}

Current User Question:
{query}

Based on the conversation history and the current user question, generate 2 to 3 standalone, optimized search queries to find the most relevant information in a document.
Return ONLY the subqueries, one per line, without numbering or bullets.
"""

    response = llm.invoke(prompt).content
    
    subqueries = []
    for line in response.split("\n"):
        line = line.strip()
        # Remove any leading numbers or bullets just in case
        line = line.lstrip("0123456789.-* ")
        if line and len(line) > 5:
            subqueries.append(line)

    if not subqueries:
        subqueries = [query]
    
    return subqueries[:3]  # Limit to max 3


# ==========================================
# HYBRID SEARCH & RRF
# ==========================================

def rerank_chunks_bm25(query: str, docs: list[Any], top_k: int = 5) -> list[Any]:
    """Get top K documents using BM25"""
    if not docs:
        return []

    bm25 = _get_bm25_index(docs)
    scores = bm25.get_scores(query.split())

    ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
    return [doc for doc, score in ranked[:top_k]]


def reciprocal_rank_fusion(vector_results: list[Any], bm25_results: list[Any], k: int = 60) -> list[Any]:
    """Merge Vector and BM25 results using Reciprocal Rank Fusion."""
    scores: dict[str, float] = {}
    doc_map: dict[str, Any] = {}

    def add_ranks(results: list[Any]):
        for rank, doc in enumerate(results):
            # Use page_content as a unique identifier for the chunk
            doc_id = doc.page_content
            if doc_id not in scores:
                scores[doc_id] = 0.0
                doc_map[doc_id] = doc
            scores[doc_id] += 1.0 / (k + rank + 1)

    add_ranks(vector_results)
    add_ranks(bm25_results)

    # Sort by RRF score descending
    sorted_docs = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    
    # Return documents
    return [doc_map[doc_id] for doc_id, score in sorted_docs]


# ==========================================
# ADVANCED SEARCH MODE
# ==========================================

def retrieve_context_advanced(llm, query: str, docs: list[Any], messages: list[dict[str, str]], vector_db=None):
    """Advanced retrieval using Hybrid Search (Vector + BM25) and RRF"""
    
    # 1. Generate optimized sub-queries (Single LLM call)
    subqueries = generate_search_queries(llm, query, messages)
    
    all_hybrid_results = []
    
    # 2. Hybrid Search for each sub-query
    for subquery in subqueries:
        
        # A. Vector Search (if available)
        vector_results = []
        if vector_db:
            try:
                vector_results = vector_db.similarity_search(subquery, k=5)
            except Exception:
                pass
                
        # B. BM25 Search
        bm25_results = rerank_chunks_bm25(subquery, docs, top_k=5)
        
        # C. Merge with RRF
        merged_results = reciprocal_rank_fusion(vector_results, bm25_results)
        
        # Keep top 5 from this subquery's merged results
        all_hybrid_results.extend(merged_results[:5])
    
    # 3. Deduplicate final results across all subqueries
    unique_docs = []
    seen_content = set()
    for doc in all_hybrid_results:
        if doc.page_content not in seen_content:
            unique_docs.append(doc)
            seen_content.add(doc.page_content)
    
    # Return top 10 unique merged chunks max
    final_docs = unique_docs[:10]
    
    if final_docs:
        context = "\n\n".join([doc.page_content for doc in final_docs])
        return context, subqueries
    
    return "", subqueries


# ==========================================
# WEB SEARCH
# ==========================================

def web_search(query):
    """Search the web using DuckDuckGo"""
    cached = _web_cache_get(query)
    if cached is not None:
        return cached

    try:
        results = []
        with DDGS() as ddgs:
            # Keep this small: the app uses only top 3 anyway.
            search_results = ddgs.text(query, max_results=3)
            for result in search_results:
                results.append({
                    "title": result.get("title", ""),
                    "body": result.get("body", ""),
                    "link": result.get("href", "")
                })
        _web_cache_set(query, results)
        return results
    except Exception:
        _web_cache_set(query, [])
        return []


# ==========================================
# INTERNAL CACHES (PER-PROCESS)
# ==========================================

_BM25_LOCK = threading.Lock()
_BM25_CACHE: dict[tuple[int, int, int], BM25Okapi] = {}


def _docs_fingerprint(docs: list[Any]) -> int:
    if not docs:
        return 0
    try:
        first = docs[0].page_content
        last = docs[-1].page_content
        return hash((len(first), len(last), first[:64], last[:64]))
    except Exception:
        return 0


def _get_bm25_index(docs: list[Any]) -> BM25Okapi:
    key = (id(docs), len(docs), _docs_fingerprint(docs))
    with _BM25_LOCK:
        cached = _BM25_CACHE.get(key)
        if cached is not None:
            return cached

    corpus = [doc.page_content.split() for doc in docs]
    bm25 = BM25Okapi(corpus)

    with _BM25_LOCK:
        _BM25_CACHE[key] = bm25
    return bm25


_WEB_LOCK = threading.Lock()
_WEB_CACHE: dict[str, tuple[float, list[dict[str, str]]]] = {}
_WEB_TTL_SECONDS = 120.0


def _web_cache_get(query: str) -> list[dict[str, str]] | None:
    now = time.time()
    with _WEB_LOCK:
        item = _WEB_CACHE.get(query)
        if not item:
            return None
        ts, data = item
        if now - ts > _WEB_TTL_SECONDS:
            _WEB_CACHE.pop(query, None)
            return None
        return data


def _web_cache_set(query: str, results: list[dict[str, str]]) -> None:
    with _WEB_LOCK:
        _WEB_CACHE[query] = (time.time(), results)
