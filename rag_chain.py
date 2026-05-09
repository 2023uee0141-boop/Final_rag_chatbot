from langchain_groq import ChatGroq
from dotenv import load_dotenv
import os

load_dotenv()

def get_llm():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is not set. Please check your .env file.")
    return ChatGroq(
        model="openai/gpt-oss-120b",
        api_key=api_key,
        temperature=0
    )
def generate_answer(llm, context, query):
    prompt = f"""
Answer ONLY from the context.

Context:
{context}

Question:
{query}
"""

    return llm.invoke(prompt).content