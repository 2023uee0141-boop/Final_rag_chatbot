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
    """Convert streamlit messages to conversation history string"""
    history_text = ""
    for msg in messages:
        if msg["role"] == "user":
            history_text += f"Q: {msg['content']}\n\n"
        else:
            history_text += f"A: {msg['content']}\n\n"
    return history_text


# ==========================================
# QUERY REWRITE
# ==========================================

def rewrite_query(llm, query, messages):
    """Rewrite query using conversation context"""
    history = get_message_history(messages)
    
    prompt = f"""Conversation History:
{history}

Current User Question:
{query}

Rewrite the current question clearly and completely, using conversation history for context. Make it standalone and self-contained."""

    rewritten_query = llm.invoke(prompt).content.strip()
    return rewritten_query


# ==========================================
# QUERY TRANSLATION
# ==========================================

def translate_query(llm, query):
    """Convert query into better semantic search query"""
    prompt = f"""Convert this query into a better semantic search query:

Query: {query}

Return ONLY the improved search query, nothing else."""

    translated_query = llm.invoke(prompt).content.strip()
    return translated_query


# ==========================================
# QUERY DECOMPOSITION
# ==========================================

def decompose_query(llm, query):
    """Break complex query into smaller subqueries"""
    prompt = f"""Break this query into 2-3 focused subqueries.
Return one subquery per line, without numbering.

Query: {query}"""

    response = llm.invoke(prompt).content

    subqueries = []
    for line in response.split("\n"):
        line = line.strip()
        if line and len(line) > 5:
            subqueries.append(line)

    # If decomposition fails, return original query
    if not subqueries:
        subqueries = [query]
    
    return subqueries


# ==========================================
# QUERY ROUTING
# ==========================================

def route_query_llm(llm, query):
    """Classify query: pdf, math, or general"""
    prompt = f"""Classify this query into ONE of these categories:
- pdf (asking about document content)
- math (mathematical calculation)
- general (general knowledge question)

Query: {query}

Respond with ONLY the category name (pdf, math, or general)."""

    result = llm.invoke(prompt).content.lower().strip()

    if "pdf" in result:
        return "pdf"
    elif "math" in result:
        return "math"
    return "general"


# ==========================================
# BM25 RERANKING
# ==========================================

def rerank_chunks(query, docs):
    """Rerank documents using BM25"""
    if not docs:
        return []

    bm25 = _get_bm25_index(docs)
    scores = bm25.get_scores(query.split())

    ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
    return [doc for doc, score in ranked[:5]]


# ==========================================
# RELEVANCE FILTER
# ==========================================

def filter_relevant_chunks(llm, query, docs):
    """Filter documents by relevance score"""
    if not docs:
        return []

    # Batch relevance scoring into a single LLM call (much faster than 1 call per chunk).
    chunks = "\n\n".join(
        [
            f"[{i+1}] {doc.page_content[:500]}"
            for i, doc in enumerate(docs)
        ]
    )

    prompt = f"""You will select which chunks are relevant to the query.

Query: {query}

Chunks:
{chunks}

Return ONLY the numbers of chunks that are relevant (score 7-10), one per line.
If none are relevant, return NONE.
"""

    try:
        response = (llm.invoke(prompt).content or "").strip()
        lower = response.lower()
        if "none" in lower:
            return []

        picked: list[int] = []
        for line in response.splitlines():
            line = line.strip()
            if not line:
                continue
            # Accept formats like "1", "[1]", "1.".
            digits = "".join([c for c in line if c.isdigit()])
            if not digits:
                continue
            idx = int(digits) - 1
            if 0 <= idx < len(docs):
                picked.append(idx)

        if not picked:
            # Conservative fallback: if parsing fails, keep all.
            return docs
        # Preserve order, de-dup.
        seen = set()
        out = []
        for idx in picked:
            if idx not in seen:
                out.append(docs[idx])
                seen.add(idx)
        return out
    except Exception:
        # If anything goes wrong, don't block retrieval.
        return docs


# ==========================================
# REMOVE DUPLICATES
# ==========================================

def remove_duplicates(docs):
    """Remove duplicate documents"""
    unique_docs = []
    seen = set()

    for doc in docs:
        content = doc.page_content
        if content not in seen:
            unique_docs.append(doc)
            seen.add(content)

    return unique_docs


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


# ==========================================
# CONTEXT RETRIEVAL PIPELINE
# ==========================================

def get_pdf_context(llm, query, docs):
    """Full RAG pipeline for PDF context retrieval"""
    # Rewrite query
    rewritten_query = rewrite_query(llm, query, [])
    
    # Translate query for better search
    translated_query = translate_query(llm, rewritten_query)
    
    # Decompose into subqueries
    subqueries = decompose_query(llm, translated_query)
    
    all_docs = []
    
    # Process each subquery
    for subquery in subqueries:
        # Rank chunks
        ranked_docs = rerank_chunks(subquery, docs)
        
        # Filter by relevance
        relevant_docs = filter_relevant_chunks(llm, subquery, ranked_docs)
        
        all_docs.extend(relevant_docs)
    
    # Remove duplicates
    final_docs = remove_duplicates(all_docs)
    
    # Build context from documents
    if final_docs:
        context = "\n\n".join([doc.page_content for doc in final_docs])
        return context
    
    return ""


# ==========================================
# ADVANCED SEARCH MODE
# ==========================================

def retrieve_context_advanced(llm, query, docs, messages):
    """Advanced retrieval using full pipeline with conversation context"""
    # Rewrite with conversation context
    rewritten_query = rewrite_query(llm, query, messages)
    
    # Translate for better search
    translated_query = translate_query(llm, rewritten_query)
    
    # Decompose into subqueries
    subqueries = decompose_query(llm, translated_query)
    
    all_docs = []
    
    # Process each subquery
    for subquery in subqueries:
        ranked_docs = rerank_chunks(subquery, docs)
        relevant_docs = filter_relevant_chunks(llm, subquery, ranked_docs)
        all_docs.extend(relevant_docs)
    
    # Remove duplicates
    final_docs = remove_duplicates(all_docs)
    
    if final_docs:
        context = "\n\n".join([doc.page_content for doc in final_docs])
        return context, subqueries
    
    return "", subqueries
