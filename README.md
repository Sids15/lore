# Lore

**Lore** is a local-first, offline-capable **agentic RAG desktop assistant** that answers
natural-language questions about a code repository — its source code, its git history, and its
documentation — without sending anything to the cloud.

Point Lore at a local repo and ask things like:

- *"Where is the retry logic for failed API calls implemented?"*
- *"Which functions did Sarah change in March, and why?"*
- *"Are there any circular dependencies in the payments module?"*
- *"Summarise the evolution of the auth service over the last year."*

Lore is the implementation of the product specified in [`rag-prd-v2.pdf`](./rag-prd-v2.pdf).

---

## How it works (architecture)

Lore is built around **three independent indexes** that feed a unified query layer:

| Index | Source | Contents |
|-------|--------|----------|
| **A — Code** | source files | AST-aware chunks + embeddings + dependency graph (static) + semantic graph |
| **B — Git history** | `.git/` | LLM-summarised commits, blame map, author/file coverage |
| **C — Docs** | markdown / text / PDF | recursive text chunks + embeddings |

A query flows through:

```
question
  → agentic router (local LLM classifies: code / multi-hop / historical / architectural / cross-layer / trivial)
  → retrieval (vector + BM25 → Reciprocal Rank Fusion → cross-encoder reranker; graph traversal; history lookup)
  → context assembly
  → LLM generation (Ollama)
  → grounding / faithfulness check (second LLM pass)
  → grounded answer with source attribution
```

The whole system runs on the developer's machine. There are **no paid dependencies**.

---

## Tech stack

| Layer | Technology |
|-------|------------|
| Desktop shell | Tauri 2 |
| Frontend | React + TypeScript + Vite |
| Backend ("sidecar") | Python + FastAPI |
| LLM runtime | [Ollama](https://ollama.com) |
| Generation model | `qwen3:8b` (configurable) |
| Embeddings | `nomic-embed-text` |
| Reranker | `bge-reranker-base` (cross-encoder) |
| Vector store | LanceDB (embedded) |
| Graph + git store | SQLite (embedded) |
| Keyword search | Tantivy / BM25 |
| Code parsing | tree-sitter |
| Graph algorithms | networkx |
| Git access | gitpython |
| Evaluation | RAGAS |

The Tauri (Rust) shell hosts the UI and **launches the Python sidecar** as a child process.
The frontend talks to the sidecar over local HTTP. At release time the sidecar is bundled
into a single binary with PyInstaller, so end users need neither Python nor Node.

---

## Prerequisites (development)

- **Node.js** ≥ 20 and npm
- **Rust** (stable) + Cargo — see <https://rustup.rs>
- **Python** ≥ 3.11
- **Ollama** — install from <https://ollama.com> (on Windows: `winget install Ollama.Ollama`),
  then pull the models:
  ```
  ollama pull qwen3:8b
  ollama pull nomic-embed-text
  ```

> Ollama is only required for the LLM-powered features. The app will run and report Ollama as
> "unavailable" until it is installed and the models are pulled.

---

## Getting started (development)

```bash
# 1. Frontend / Tauri dependencies
npm install

# 2. Python sidecar (isolated virtual environment)
cd sidecar
python -m venv .venv
# Windows:  .venv\Scripts\activate     |  macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
cd ..

# 3. Configuration — copy the example env files and adjust if needed
cp .env.example .env                 # frontend (VITE_SIDECAR_URL)
cp sidecar/.env.example sidecar/.env # sidecar (port, data dir, Ollama URL, models)

# 4. Run the desktop app (Tauri starts the sidecar automatically)
npm run tauri dev
```

To run the sidecar on its own (useful for backend work):

```bash
cd sidecar && python -m uvicorn app.main:app --reload --port 8765
# then open http://127.0.0.1:8765/health
```

---

## Project layout

```
lore/
├── src/          # React + TypeScript frontend
├── src-tauri/    # Tauri (Rust) desktop shell + sidecar supervisor
├── sidecar/      # Python FastAPI backend (RAG / ML logic)
└── rag-prd-v2.pdf  # product spec
```

See [`CLAUDE.md`](./CLAUDE.md) for the development conventions and a deeper map of the codebase.

---

## Status

Under active development, built phase-by-phase per the PRD roadmap. **Phase 0 (foundation)**
establishes the desktop shell, the sidecar, the embedded data stores, and health monitoring.
Retrieval, the graph, the agentic router, and git-history intelligence follow in later phases.
