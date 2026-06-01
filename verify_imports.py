"""Quick sanity check: import the key dependencies used by the app.

Run this in the SAME environment that starts Streamlit.
If this passes, 'ModuleNotFoundError' issues should be gone.
"""

import importlib
import sys

MODULES = [
    # App/runtime
    "streamlit",
    "dotenv",
    # LangChain + loaders/vector store
    "langchain",
    "langchain_community",
    "langchain_text_splitters",
    # Embeddings stack
    "sentence_transformers",
    "transformers",
    "accelerate",
    "torch",
    # Vector store
    "faiss",
    # PDF
    "pypdf",
    # Router utilities
    "rank_bm25",
    "duckduckgo_search",
    # LLM provider
    "langchain_groq",
]


def main() -> int:
    failures: list[tuple[str, str]] = []

    for name in MODULES:
        try:
            importlib.import_module(name)
            print(f"OK  {name}")
        except Exception as e:  # keep broad to catch binary import errors too
            failures.append((name, f"{type(e).__name__}: {e}"))
            print(f"FAIL {name} -> {type(e).__name__}: {e}")

    if failures:
        print("\nMissing/broken imports detected:")
        for name, err in failures:
            print(f"- {name}: {err}")
        print("\nFix: install/update packages in this environment, then re-run.")
        return 1

    print("\nAll imports OK.")
    print(f"Python: {sys.executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
