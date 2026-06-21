from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi import Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from auth import auth_router, get_current_user
from mongo_store import insert_chat_message, list_messages, list_sessions
from embeddings import get_embeddings
from pdf_loader import load_and_split_pdf
from rag_chain import get_llm
from router import retrieve_context_advanced, web_search
from vector_store import create_vector_store


load_dotenv()


SearchMode = Literal["pdf", "web"]


@dataclass
class ChatSession:
    session_id: str
    username: str
    pdf_name: str | None = None
    documents: list[Any] = field(default_factory=list)
    vector_db: Any | None = None
    messages: list[dict[str, str]] = field(default_factory=list)

    def add_message(self, role: Literal["user", "assistant"], content: str) -> None:
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > 20:
            self.messages = self.messages[-20:]


SESSIONS: dict[str, ChatSession] = {}
EMBEDDINGS = get_embeddings()


class SessionCreateResponse(BaseModel):
    session_id: str


class UploadResponse(BaseModel):
    session_id: str
    pdf_name: str


class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1)
    search_mode: SearchMode = "pdf"


class ChatResponse(BaseModel):
    answer: str
    search_mode: SearchMode
    subqueries: list[str] = []
    used_fallback_similarity: bool = False
    sources: list[dict[str, str]] = []


class HistorySession(BaseModel):
    session_id: str
    last_message: str
    last_role: Literal["user", "assistant"]
    last_at: str
    pdf_name: str | None = None
    last_search_mode: SearchMode | None = None


class HistoryResponse(BaseModel):
    sessions: list[HistorySession]


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    search_mode: SearchMode | None = None
    pdf_name: str | None = None


class HistoryMessagesResponse(BaseModel):
    session_id: str
    messages: list[HistoryMessage]


app = FastAPI(title="RAG PDF Chat API")
FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"

app.include_router(auth_router)


allowed_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")
allowed_origins = [o.strip() for o in allowed_origins if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/history", response_model=HistoryResponse)
def history(current_user: Any = Depends(get_current_user)) -> HistoryResponse:
    sessions_raw = list_sessions(current_user.username)
    sessions: list[HistorySession] = []
    for item in sessions_raw:
        last_at = item.get("last_at")
        sessions.append(
            HistorySession(
                session_id=str(item.get("_id")),
                last_message=str(item.get("last_message") or ""),
                last_role=item.get("last_role") or "user",
                last_at=last_at.isoformat() if hasattr(last_at, "isoformat") else "",
                pdf_name=item.get("pdf_name"),
                last_search_mode=item.get("last_search_mode"),
            )
        )
    return HistoryResponse(sessions=sessions)


@app.get("/history/{session_id}", response_model=HistoryMessagesResponse)
def history_session(
    session_id: str,
    current_user: Any = Depends(get_current_user),
) -> HistoryMessagesResponse:
    messages_raw = list_messages(current_user.username, session_id)
    messages: list[HistoryMessage] = []
    for item in messages_raw:
        created_at = item.get("created_at")
        messages.append(
            HistoryMessage(
                role=item.get("role") or "user",
                content=str(item.get("content") or ""),
                created_at=created_at.isoformat()
                if hasattr(created_at, "isoformat")
                else "",
                search_mode=item.get("search_mode"),
                pdf_name=item.get("pdf_name"),
            )
        )
    return HistoryMessagesResponse(session_id=session_id, messages=messages)


@app.post("/session", response_model=SessionCreateResponse)
def create_session(current_user: Any = Depends(get_current_user)) -> SessionCreateResponse:
    session_id = str(uuid.uuid4())
    SESSIONS[session_id] = ChatSession(
        session_id=session_id,
        username=current_user.username,
    )
    return SessionCreateResponse(session_id=session_id)


@app.post("/upload", response_model=UploadResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    current_user: Any = Depends(get_current_user),
) -> UploadResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a .pdf file")

    session_id = str(uuid.uuid4())
    session = ChatSession(
        session_id=session_id,
        username=current_user.username,
        pdf_name=file.filename,
    )

    temp_path = f"temp_{session_id}.pdf"
    try:
        content = await file.read()
        with open(temp_path, "wb") as f:
            f.write(content)

        chunks = load_and_split_pdf(temp_path)
        session.documents = chunks
        # Namespace vectors per-session to avoid mixing PDFs in Pinecone.
        session.vector_db = create_vector_store(chunks, EMBEDDINGS, namespace=session_id)
        SESSIONS[session_id] = session
        return UploadResponse(session_id=session_id, pdf_name=file.filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {e}") from e
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, current_user: Any = Depends(get_current_user)) -> ChatResponse:
    session = SESSIONS.get(req.session_id)
    if not session:
        session = ChatSession(
            session_id=req.session_id,
            username=current_user.username,
        )
        SESSIONS[req.session_id] = session
    if session.username != current_user.username:
        raise HTTPException(status_code=403, detail="Forbidden")

    llm = get_llm()

    session.add_message("user", req.message)
    insert_chat_message(
        username=current_user.username,
        session_id=req.session_id,
        role="user",
        content=req.message,
        pdf_name=session.pdf_name,
        search_mode=req.search_mode,
    )

    # Build conversation context (exclude current message at end)
    conversation_context = "\n".join(
        [
            (f"Q: {m['content']}" if m["role"] == "user" else f"A: {m['content']}")
            for m in session.messages[:-1]
        ]
    )

    used_fallback_similarity = False
    subqueries: list[str] = []
    sources: list[dict[str, str]] = []

    if req.search_mode == "pdf":
        if not session.documents or session.vector_db is None:
            raise HTTPException(
                status_code=400,
                detail="No PDF loaded for this session. Upload a PDF first or switch to web mode.",
            )

        context, subqueries = retrieve_context_advanced(
            llm,
            req.message,
            session.documents,
            session.messages[:-1],
            vector_db=session.vector_db,
        )


        prompt = f"""
    Based on the document context below,
    answer the user's question clearly and accurately.

Previous conversation:
{conversation_context}

Document Context:
{context}

User Question:
{req.message}

Provide a clear and detailed answer.
"""

        answer = llm.invoke(prompt).content

    else:
        search_results = web_search(req.message)

        sources = [
            {
                "title": (r.get("title") or r.get("link") or "").strip(),
                "link": (r.get("link") or "").strip(),
            }
            for r in (search_results or [])[:5]
            if (r.get("title") or r.get("link"))
        ]

        if search_results and search_results[0].get("body"):
            context = "\n\n".join(
                [f"**{r['title']}**\n{r['body']}" for r in search_results[:3]]
            )

            prompt = f"""
Based on the web search results below,
answer the user's question.

Rules:
- Answer ONLY using the Web Search Results.
- If the answer is not present, say: "I couldn't find it in the web results."
- Do NOT mention training data, knowledge cutoffs, or browsing limitations.

Previous conversation:
{conversation_context}

Web Search Results:
{context}

User Question:
{req.message}

Provide a clear and detailed answer.
"""
        else:
            prompt = f"""
Answer the user's question.

Previous conversation:
{conversation_context}

User Question:
{req.message}
 
Answer:
"""

        answer = llm.invoke(prompt).content

    session.add_message("assistant", answer)
    insert_chat_message(
        username=current_user.username,
        session_id=req.session_id,
        role="assistant",
        content=answer,
        pdf_name=session.pdf_name,
        search_mode=req.search_mode,
    )
    return ChatResponse(
        answer=answer,
        search_mode=req.search_mode,
        subqueries=subqueries,
        used_fallback_similarity=used_fallback_similarity,
        sources=sources,
    )


if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str) -> FileResponse:
        requested = FRONTEND_DIST / full_path
        if requested.is_file():
            return FileResponse(requested)
        return FileResponse(FRONTEND_DIST / "index.html")
