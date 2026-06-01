from dotenv import load_dotenv
load_dotenv()

import streamlit as st

from pdf_loader import load_and_split_pdf
from embeddings import get_embeddings
from vector_store import create_vector_store, load_vector_store
from rag_chain import get_llm

from router import (
    retrieve_context_advanced,
    web_search,
    rewrite_query,
    translate_query,
    decompose_query
)

st.set_page_config(page_title="RAG Chat", layout="wide")

st.title("💬 PDF Chat Assistant")
st.write("Upload a PDF and chat with it - keep last 10 questions in memory")

# ---------------- SESSION STATE ---------------- #

embeddings = get_embeddings()

if "vector_db" not in st.session_state:
    # For FAISS this loads ./faiss_index; for Pinecone this returns None unless configured.
    st.session_state.vector_db = load_vector_store(embeddings)

if "documents" not in st.session_state:
    st.session_state.documents = []

if "messages" not in st.session_state:
    st.session_state.messages = []

if "pdf_name" not in st.session_state:
    st.session_state.pdf_name = None

if "search_mode" not in st.session_state:
    st.session_state.search_mode = "pdf"

# ---------------- PDF UPLOAD ---------------- #

uploaded_file = st.file_uploader("📄 Upload PDF", type="pdf")

if uploaded_file:

    # Process only if new PDF uploaded
    if st.session_state.pdf_name != uploaded_file.name:

        with st.spinner("Processing PDF..."):

            try:

                # Save uploaded file temporarily
                with open("temp.pdf", "wb") as f:
                    f.write(uploaded_file.read())

                # Split PDF into chunks
                chunks = load_and_split_pdf("temp.pdf")

                # Create vector database
                vector_db = create_vector_store(
                    chunks,
                    embeddings,
                    namespace=uploaded_file.name,
                )

                # Store in session state
                st.session_state.vector_db = vector_db
                st.session_state.documents = chunks
                st.session_state.pdf_name = uploaded_file.name
                st.session_state.messages = []

                st.success(f"✅ Loaded: {uploaded_file.name}")

            except Exception as e:

                st.error(f"❌ Error processing PDF: {e}")
                st.stop()

# ---------------- MAIN APP ---------------- #

if st.session_state.vector_db:

    st.markdown("---")

    # ---------------- SEARCH MODE ---------------- #

    col1, col2 = st.columns(2)

    with col1:
        if st.button("📄 Search PDF", use_container_width=True):
            st.session_state.search_mode = "pdf"

    with col2:
        if st.button("🌐 Web Search", use_container_width=True):
            st.session_state.search_mode = "web"

    mode_label = (
        "📄 PDF Mode"
        if st.session_state.search_mode == "pdf"
        else "🌐 Web Mode"
    )

    st.info(f"Current mode: {mode_label}")

    # ---------------- CHAT DISPLAY ---------------- #

    st.subheader("Chat")

    for message in st.session_state.messages:

        with st.chat_message(message["role"]):
            st.write(message["content"])

    # ---------------- USER INPUT ---------------- #

    if user_input := st.chat_input("Ask a question..."):

        # Store user message
        st.session_state.messages.append(
            {
                "role": "user",
                "content": user_input
            }
        )

        # Keep only last 10 Q&A pairs
        if len(st.session_state.messages) > 20:
            st.session_state.messages = (
                st.session_state.messages[-20:]
            )

        # Display user message
        with st.chat_message("user"):
            st.write(user_input)

        # ---------------- ASSISTANT RESPONSE ---------------- #

        with st.chat_message("assistant"):

            with st.spinner("Thinking..."):

                try:

                    llm = get_llm()

                    # Build conversation context
                    conversation_context = "\n".join(
                        [
                            (
                                f"Q: {msg['content']}"
                                if msg["role"] == "user"
                                else f"A: {msg['content']}"
                            )
                            for msg in st.session_state.messages[:-1]
                        ]
                    )

                    # ---------------- PDF SEARCH ---------------- #

                    if st.session_state.search_mode == "pdf":

                        context, subqueries = (
                            retrieve_context_advanced(
                                llm,
                                user_input,
                                st.session_state.documents,
                                st.session_state.messages[:-1]
                            )
                        )

                        # Fallback similarity search
                        if not context:

                            results = (
                                st.session_state.vector_db
                                .similarity_search(user_input, k=5)
                            )

                            if results:

                                context = "\n".join(
                                    [
                                        doc.page_content
                                        for doc in results
                                    ]
                                )

                        prompt = f"""
Based on the document context below,
answer the user's question clearly and accurately.

Previous conversation:
{conversation_context}

Document Context:
{context}

User Question:
{user_input}

Provide a clear and detailed answer.
"""

                        answer = llm.invoke(prompt).content

                        # Search details
                        with st.expander("🔍 Search Details"):

                            if subqueries:

                                st.write(
                                    "**Sub-queries processed:**"
                                )

                                for i, sq in enumerate(subqueries, 1):

                                    st.write(f"{i}. {sq}")

                    # ---------------- WEB SEARCH ---------------- #

                    else:

                        search_results = web_search(user_input)

                        if (
                            search_results
                            and search_results[0].get("body")
                        ):

                            context = "\n\n".join(
                                [
                                    f"**{r['title']}**\n{r['body']}"
                                    for r in search_results[:3]
                                ]
                            )

                            prompt = f"""
Based on the web search results below,
answer the user's question.

Previous conversation:
{conversation_context}

Web Search Results:
{context}

User Question:
{user_input}

Provide a clear and detailed answer.
"""

                        else:

                            prompt = f"""
Answer the user's question.

Previous conversation:
{conversation_context}

User Question:
{user_input}

Answer:
"""

                        answer = llm.invoke(prompt).content

                    # Display answer
                    st.write(answer)

                    # Store assistant response
                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": answer
                        }
                    )

                except Exception as e:

                    st.error(f"❌ Error: {e}")

                    # Remove failed user message
                    st.session_state.messages.pop()

else:

    st.info("Upload a PDF to start chatting")