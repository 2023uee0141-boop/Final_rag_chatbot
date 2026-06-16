# PDF BOT - RAG PDF Chat Assistant
Website is live at--https://final-rag-chatbot.onrender.com/

![RAG Data Pipeline](flowchart.png)

PDF BOT is a Retrieval-Augmented Generation (RAG) chat application for asking questions over uploaded PDF files and optional web search results. The project now includes a FastAPI backend, a React/Vite frontend, JWT authentication, MongoDB-backed users and chat history, optional Pinecone vector storage, local FAISS fallback storage, and an updated ChatGPT-style interface.

The original RAG data pipeline is still used: a PDF is uploaded, split into chunks, embedded, stored in a vector database, retrieved with advanced ranking, and passed to an LLM to generate answers grounded in the document.

## What The App Does

- Upload a PDF and ask questions about it.
- Chat in two modes:
  - `Work`: answer from the uploaded PDF.
  - `Web`: answer from web search results.
- Store users in MongoDB when `MONGO_URI` is configured.
- Store chat history in MongoDB so recent conversations appear in the sidebar.
- Store vectors locally with FAISS by default.
- Store vectors in Pinecone when `VECTOR_STORE=pinecone` is enabled.
- Use JWT bearer tokens for authenticated API calls.
- Provide a ChatGPT-like UI with sidebar toggle, recents, bottom composer, and light theme.
- Render assistant responses with Markdown and tables.
- Show web search source links when web mode returns sources.

## Tech Stack

### Backend

- FastAPI
- Uvicorn
- LangChain
- Groq LLM integration
- HuggingFace sentence-transformer embeddings
- FAISS for local vector search
- Pinecone for cloud vector search
- MongoDB Atlas or local MongoDB through PyMongo
- JWT auth with `python-jose`
- Password hashing with Passlib `pbkdf2_sha256`
- DuckDuckGo/DDGS based web search

### Frontend

- React
- Vite
- React Router
- React Markdown
- Remark GFM for tables and GitHub-flavored Markdown
- Custom CSS for a ChatGPT-style layout

## High-Level Architecture

```text
Browser UI
  |
  | HTTP requests with Bearer token
  v
FastAPI backend
  |
  |-- /auth/signup and /auth/token
  |     |
  |     |-- MongoDB users collection when MONGO_URI exists
  |     |-- users.json fallback when MongoDB is not configured
  |
  |-- /upload
  |     |
  |     |-- PDF loader and splitter
  |     |-- HuggingFace embeddings
  |     |-- FAISS or Pinecone vector store
  |
  |-- /chat
  |     |
  |     |-- PDF retrieval path for Work mode
  |     |-- Web search path for Web mode
  |     |-- Groq LLM answer generation
  |     |-- MongoDB chat history persistence
  |
  |-- /history and /history/{session_id}
        |
        |-- MongoDB chat_messages collection
```

## RAG Data Pipeline

The PDF RAG pipeline follows these steps:

1. The user uploads a PDF from the frontend.
2. FastAPI receives the file through `/upload`.
3. The file is temporarily written to disk.
4. `pdf_loader.py` loads and splits the PDF into text chunks.
5. `embeddings.py` creates HuggingFace embeddings.
6. `vector_store.py` stores the chunks:
   - In local FAISS under `./faiss_index` by default.
   - In Pinecone when `VECTOR_STORE=pinecone`.
7. When the user asks a question in Work mode, `/chat` sends the query through the advanced retrieval path in `router.py`.
8. The retriever performs query transformation and ranking before building context.
9. If the advanced retriever does not produce enough context, the app falls back to vector similarity search.
10. The selected context, conversation history, and user question are sent to the LLM.
11. The answer is returned to the frontend and saved to MongoDB chat history.

## Advanced Retrieval Features

The advanced retrieval pipeline includes:

### Query Rewrite

Conversation history is used to turn follow-up questions into standalone questions.

### Query Translation

The user query is rewritten into a form that is better suited for semantic retrieval.

### Query Decomposition

Complex questions are split into smaller subqueries so the retriever can collect evidence from multiple sections of the PDF.

### BM25 Re-Ranking

Keyword-based BM25 ranking is used along with semantic retrieval to improve relevance.

### LLM Relevance Filtering

Retrieved chunks can be filtered for relevance before being included in the final context.

### Duplicate Removal

Repeated chunks are removed before context construction.

### Fallback Similarity Search

If the advanced retriever produces no useful context, the app falls back to vector similarity search against FAISS or Pinecone.

## MongoDB Usage

MongoDB is used when `MONGO_URI` is set.

The app uses two collections:

### `users`

Stores registered users:

```json
{
  "username": "test",
  "password_hash": "$pbkdf2-sha256$..."
}
```

The backend creates a unique index on `username`.

### `chat_messages`

Stores conversation history:

```json
{
  "username": "test",
  "session_id": "uuid",
  "role": "user",
  "content": "What is this PDF about?",
  "pdf_name": "resume.pdf",
  "search_mode": "pdf",
  "created_at": "2026-06-01T..."
}
```

The backend creates an index on:

```text
username, session_id, created_at
```

This allows the frontend sidebar to show recent conversations and reload old sessions.

### MongoDB Fallback Behavior

If `MONGO_URI` is not configured, auth uses `users.json` as a local fallback. When MongoDB is enabled later, local users from `users.json` are migrated into MongoDB so older accounts can still sign in.

## Pinecone Usage

FAISS is the default vector store. Pinecone is optional.

When Pinecone is enabled:

- The app creates the Pinecone index if it does not already exist.
- The embedding dimension is inferred automatically from the configured embedding model.
- The index metric is validated against `PINECONE_METRIC`.
- Each uploaded PDF session is stored in a separate Pinecone namespace using the `session_id`.
- This prevents vectors from different uploaded PDFs from mixing.

To enable Pinecone:

```env
VECTOR_STORE=pinecone
PINECONE_API_KEY=your_pinecone_api_key
PINECONE_INDEX_NAME=rag-chatbot
PINECONE_CLOUD=aws
PINECONE_REGION=us-east-1
PINECONE_METRIC=cosine
```

To use local FAISS instead, leave `VECTOR_STORE` unset or set:

```env
VECTOR_STORE=faiss
```

FAISS stores local index files in:

```text
faiss_index/
```

## Authentication

The FastAPI backend exposes auth routes under `/auth`.

### Sign Up

```http
POST /auth/signup
Content-Type: application/json
```

```json
{
  "username": "newuser",
  "password": "password123"
}
```

### Sign In

```http
POST /auth/token
Content-Type: application/x-www-form-urlencoded
```

```text
username=newuser&password=password123
```

The response returns a JWT:

```json
{
  "access_token": "jwt-token",
  "token_type": "bearer"
}
```

Use it on protected routes:

```text
Authorization: Bearer <access_token>
```

### Development Test User

A development test user was added for local testing:

```text
username: test
password: test1234
```

This is useful for quickly verifying login. Remove or disable the hardcoded test user before deploying publicly.

## API Endpoints

### Health

```http
GET /health
```

Returns:

```json
{
  "status": "ok"
}
```

### Auth

```http
POST /auth/signup
POST /auth/token
GET  /auth/me
```

### Sessions

```http
POST /session
```

Creates a new chat session for the authenticated user.

### Upload PDF

```http
POST /upload
Content-Type: multipart/form-data
Authorization: Bearer <token>
```

Form field:

```text
file=<pdf-file>
```

Returns:

```json
{
  "session_id": "uuid",
  "pdf_name": "document.pdf"
}
```

### Chat

```http
POST /chat
Content-Type: application/json
Authorization: Bearer <token>
```

```json
{
  "session_id": "uuid",
  "message": "What is this PDF about?",
  "search_mode": "pdf"
}
```

`search_mode` can be:

- `pdf`: answer from the uploaded PDF.
- `web`: answer from web search results.

Response:

```json
{
  "answer": "Generated answer",
  "search_mode": "pdf",
  "subqueries": [],
  "used_fallback_similarity": false,
  "sources": []
}
```

### History

```http
GET /history
GET /history/{session_id}
```

These routes power the Recents sidebar.

## Frontend UI Changes

The frontend now uses a ChatGPT-like layout:

- Browser tab title: `PDF BOT`
- Favicon: `frontend/public/logo.png`
- Left sidebar with open/close toggle
- Recents-only sidebar list
- Bottom profile/sign-out row
- Main header with app title and Work/Web mode switch
- Bottom fixed message composer
- Upload button inside the composer
- Markdown rendering for assistant answers
- Table rendering for structured answers
- Light theme forced through `color-scheme: light`

The old extra sidebar sections such as New Chat, Search Chats, Library, and Projects were removed from the sidebar. New chat remains available from the main header.

## Project Structure

```text
.
├── api_server.py              # FastAPI app, chat/upload/history routes
├── auth.py                    # Signup, login, JWT, password hashing
├── mongo_store.py             # MongoDB users and chat history helpers
├── vector_store.py            # FAISS and Pinecone vector-store logic
├── pdf_loader.py              # PDF loading and chunking
├── embeddings.py              # Embedding model setup
├── rag_chain.py               # LLM setup
├── router.py                  # Advanced retrieval and web search logic
├── app.py                     # Original Streamlit app
├── users.json                 # Local auth fallback when MongoDB is disabled
├── faiss_index/               # Local FAISS index files
├── flowchart.png              # Original RAG data pipeline image
├── logo.png                   # Source logo
├── requirements.txt           # Python dependencies
├── Dockerfile
└── frontend/
    ├── index.html             # PDF BOT title and favicon
    ├── public/
    │   ├── logo.png           # Browser favicon
    │   ├── favicon.svg
    │   └── icons.svg
    ├── src/
    │   ├── App.jsx            # Routes and auth state
    │   ├── ChatPage.jsx       # Chat UI and API calls
    │   ├── LoginPage.jsx      # Login page
    │   ├── SignupPage.jsx     # Signup page
    │   ├── App.css            # UI styles
    │   └── index.css          # Global styles
    ├── package.json
    └── vite.config.js
```

## Environment Variables

Create a `.env` file in the project root for backend settings.

```env
# LLM provider
GROQ_API_KEY=your_groq_api_key
TOGETHER_API_KEY=your_together_api_key_if_needed

# Auth
AUTH_USERNAME=admin
AUTH_PASSWORD=change_this_password
AUTH_SECRET_KEY=replace_with_a_long_random_secret
AUTH_ACCESS_TOKEN_EXPIRE_MINUTES=120

# MongoDB
MONGO_URI=mongodb+srv://user:password@cluster.mongodb.net/?appName=Cluster0
MONGO_DB=rag_chat

# CORS
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

# Vector store
VECTOR_STORE=faiss

# Pinecone, only required when VECTOR_STORE=pinecone
PINECONE_API_KEY=your_pinecone_api_key
PINECONE_INDEX_NAME=rag-chatbot
PINECONE_CLOUD=aws
PINECONE_REGION=us-east-1
PINECONE_METRIC=cosine
```

Create `frontend/.env` for frontend settings:

```env
VITE_API_BASE=http://127.0.0.1:8001
```

If your backend runs on port `8000`, use:

```env
VITE_API_BASE=http://127.0.0.1:8000
```

## Local Setup

### 1. Create and activate Python environment

```bash
python -m venv rag_env
source rag_env/bin/activate
```

On Windows:

```bash
rag_env\Scripts\activate
```

### 2. Install backend dependencies

```bash
pip install -r requirements.txt
```

### 3. Install frontend dependencies

```bash
cd frontend
npm install
```

### 4. Configure environment

Create `.env` in the project root and `frontend/.env` as shown above.

### 5. Run the FastAPI backend

If `frontend/.env` uses port `8001`:

```bash
uvicorn api_server:app --reload --port 8001
```

If `frontend/.env` uses port `8000`:

```bash
uvicorn api_server:app --reload --port 8000
```

### 6. Run the frontend

```bash
cd frontend
npm run dev
```

Open:

```text
http://localhost:5173
```

## Example API Calls

### Login

```bash
curl -X POST "http://127.0.0.1:8001/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test&password=test1234"
```

### Create Session

```bash
curl -X POST "http://127.0.0.1:8001/session" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Ask In Web Mode

```bash
curl -X POST "http://127.0.0.1:8001/chat" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "SESSION_ID",
    "message": "What is retrieval augmented generation?",
    "search_mode": "web"
  }'
```

## Running With FAISS

FAISS is best for local development.

```env
VECTOR_STORE=faiss
```

When a PDF is uploaded:

- The vectors are written to `faiss_index/`.
- The active FastAPI session keeps the session's vector DB in memory.
- This is simple and fast for local testing.

## Running With Pinecone

Pinecone is best when you want cloud vector storage.

```env
VECTOR_STORE=pinecone
PINECONE_API_KEY=your_key
PINECONE_INDEX_NAME=rag-chatbot
```

When a PDF is uploaded:

- The app checks whether the Pinecone index exists.
- If it does not exist, the app creates it using the embedding dimension.
- Chunks are upserted into a namespace named after the session ID.
- Later similarity searches query only that namespace.

## Running With MongoDB

MongoDB is enabled by setting:

```env
MONGO_URI=your_mongo_connection_string
MONGO_DB=rag_chat
```

When enabled:

- New users are created in MongoDB.
- Login checks MongoDB users.
- Chat messages are saved in MongoDB.
- Recents are loaded from MongoDB.
- Local `users.json` accounts are migrated into MongoDB automatically.

When disabled:

- The app falls back to `users.json` for users.
- Chat history persistence is not available through MongoDB.

## Development Checks

Backend syntax check:

```bash
python -m py_compile auth.py mongo_store.py api_server.py vector_store.py
```

Frontend lint:

```bash
cd frontend
npm run lint
```

Frontend production build:

```bash
cd frontend
npm run build
```

## Notes And Limitations

- FastAPI sessions are kept in memory in `SESSIONS`, so uploaded PDF session state resets when the backend restarts.
- MongoDB stores chat messages and recents, but the in-memory vector DB for uploaded PDFs must be recreated after a server restart unless Pinecone is used and the session can be reconnected.
- The hardcoded `test/test1234` user is for development only.
- Do not commit real API keys, MongoDB credentials, or Pinecone credentials.
- Use a strong `AUTH_SECRET_KEY` in any shared or deployed environment.

## Main Files To Know

- `api_server.py`: API routes and chat orchestration.
- `auth.py`: authentication, JWTs, user migration, and test user.
- `mongo_store.py`: MongoDB persistence.
- `vector_store.py`: FAISS/Pinecone switching.
- `router.py`: advanced retrieval and web search.
- `frontend/src/ChatPage.jsx`: ChatGPT-style UI and API client calls.
- `frontend/src/App.css`: main UI styling.
