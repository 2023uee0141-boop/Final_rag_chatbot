# 💬 RAG PDF Chat Assistant

![RAG Flowchart](flowchart.png)

A powerful Retrieval-Augmented Generation (RAG) based PDF Chat Assistant built using:

- Streamlit
- LangChain
- FAISS
- HuggingFace Embeddings
- Groq LLM
- BM25 Re-ranking
- Query Translation
- Query Decomposition
- Web Search

This application allows users to:

✅ Upload PDFs  
✅ Chat with documents  
✅ Perform advanced retrieval  
✅ Use conversation memory  
✅ Switch between PDF Search and Web Search  
✅ Use query translation + decomposition for better retrieval  

---

# 📌 Features

## 📄 PDF Processing Pipeline

- Upload PDF
- Load PDF using `PyPDFLoader`
- Split document into chunks
- Generate embeddings
- Store embeddings in FAISS vector database

---

## 🧠 Advanced RAG Retrieval

The project uses an advanced retrieval pipeline:

### 1. Query Rewrite
Uses conversation history to rewrite the user query into a standalone query.

### 2. Query Translation
Optimizes query for semantic retrieval.

### 3. Query Decomposition
Breaks complex queries into smaller subqueries.

### 4. BM25 Re-ranking
Ranks chunks based on keyword relevance.

### 5. Relevance Filtering
Filters chunks using LLM relevance scoring.

### 6. Duplicate Removal
Removes repeated chunks.

### 7. Context Construction
Builds final context for answer generation.

---

# 🏗️ Project Structure

```bash
project/
│
├── app.py
├── embeddings.py
├── pdf_loader.py
├── rag_chain.py
├── vector_store.py
├── router.py
├── requirements.txt
├── .env
└── README.md