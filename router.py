from rank_bm25 import BM25Okapi
from duckduckgo_search import DDGS


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
    
    corpus = [doc.page_content.split() for doc in docs]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(query.split())

    ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
    return [doc for doc, score in ranked[:5]]


# ==========================================
# RELEVANCE FILTER
# ==========================================

def filter_relevant_chunks(llm, query, docs):
    """Filter documents by relevance score"""
    filtered_docs = []

    for doc in docs:
        prompt = f"""Rate the relevance of this chunk to the query on a scale 1-10.
Respond with ONLY the number.

Query: {query}

Chunk: {doc.page_content[:500]}"""

        try:
            response = llm.invoke(prompt).content.strip()
            score = int(''.join(filter(str.isdigit, response.split()[0])))
            
            if score >= 7:
                filtered_docs.append(doc)
        except:
            # If we can't parse score, include the doc
            filtered_docs.append(doc)

    return filtered_docs


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
    try:
        results = []
        with DDGS() as ddgs:
            search_results = ddgs.text(query, max_results=5)
            for result in search_results:
                results.append({
                    "title": result.get("title", ""),
                    "body": result.get("body", ""),
                    "link": result.get("href", "")
                })
        return results
    except Exception as e:
        return [{"title": "Error", "body": f"Web search failed: {str(e)}", "link": ""}]


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
