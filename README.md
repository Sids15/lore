# Lore

[![CI](https://github.com/Sids15/lore/actions/workflows/ci.yml/badge.svg)](https://github.com/Sids15/lore/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/Sids15/lore?display_name=tag&sort=semver)](https://github.com/Sids15/lore/releases/latest)
[![Platform](https://img.shields.io/badge/platform-Windows-blue)](https://github.com/Sids15/lore/releases/latest)

**Lore** is a local-first, offline-capable **agentic RAG desktop assistant** that answers
natural-language questions about a code repository — its source code, its git history, and its
documentation — without sending anything to the cloud.

Point Lore at a local repository and ask things like:

- *"Where is the retry logic for failed API calls implemented?"*
- *"Which functions did Sarah change in March, and why?"*
- *"Are there any circular dependencies in the payments module?"*
- *"Summarise the evolution of the auth service over the last year."*

Every answer is **grounded in cited evidence** drawn from your code, history, and docs, and is
checked for faithfulness by a second model pass before it reaches you. The entire system —
embeddings, retrieval, generation, and storage — runs on your machine. There are **no paid
dependencies and no telemetry.**

---

## Download

Pre-built **Windows** installers are attached to each release:

### → [**Download the latest release**](https://github.com/Sids15/lore/releases/latest)

Pick one:

- **`Lore_<version>_x64-setup.exe`** — NSIS installer (recommended).
- **`Lore_<version>_x64_en-US.msi`** — MSI package (for managed/silent installs).

No Python or Node.js is required — the backend is bundled inside the app. You **do** need
[Ollama](https://ollama.com) running with the models pulled (see [Prerequisites](#prerequisites-development));
Lore reports Ollama as *unavailable* until then.

> **Note:** the installers are currently **unsigned** (code-signing requires a paid certificate),
> so Windows SmartScreen will warn on first run — choose **More info → Run anyway**.

---

## How it works (architecture)

Lore is built around **three independent indexes** that feed one unified query layer:

| Index | Source | Contents |
|-------|--------|----------|
| **A — Code** | source files | AST-aware chunks + embeddings, a static dependency graph, and an LLM-extracted semantic graph |
| **B — Git history** | `.git/` | LLM-summarised commits (the summaries are embedded), function-level blame, and authorship |
| **C — Docs** | markdown / text | recursive, heading-aware text chunks + embeddings |

A question flows through an agentic pipeline:

```
question
  → agentic router (local LLM classifies: code / relational / architectural / historical / docs / trivial)
  → retrieval        (vector + full-text search → Reciprocal Rank Fusion → cross-encoder reranker
                      → MMR diversity; graph traversal; history & docs lookup)
  → context assembly (+ parent-chunk expansion: each snippet's class header & file imports)
  → generation       (Ollama, streamed token-by-token)
  → grounding check  (second LLM pass verifies the answer against its sources)
  → grounded answer  (with click-through citations; a bounded retrieve→reason retry kicks in if weak)
```

Keyword search uses **LanceDB's built-in full-text search** (Tantivy-backed) through its native
hybrid query API, so vector + FTS + RRF run in a single call — there is no separate search engine.
The reranker is a small ONNX cross-encoder run via `fastembed` (no PyTorch); it, like MMR diversity
and parent-chunk expansion, fails open so a degraded component never breaks a query.

---

## Tech stack

| Layer | Technology |
|-------|------------|
| Desktop shell | Tauri 2 (Rust) |
| Frontend | React + TypeScript + Vite |
| Backend ("sidecar") | Python + FastAPI |
| LLM runtime | [Ollama](https://ollama.com) |
| Generation model | `qwen3:8b` (configurable) |
| Embeddings | `nomic-embed-text` (768-dim, configurable) |
| Reranker | ONNX cross-encoder via `fastembed` (default `Xenova/ms-marco-MiniLM-L-6-v2`) |
| Vector store + keyword search | LanceDB (embedded) — vectors + built-in full-text search (Tantivy) |
| Graph + git store | SQLite (embedded) |
| Code parsing | tree-sitter |
| Graph algorithms | networkx |
| Git access | gitpython |
| Evaluation | RAGAS |

The Tauri (Rust) shell hosts the UI and **launches the Python sidecar** as a supervised child
process; the frontend talks to it over local HTTP. For releases the sidecar is frozen into a
standalone binary with PyInstaller and bundled inside the app, so end users need neither Python nor
Node.js.

---

## Prerequisites (development)

- **Node.js** ≥ 20 and npm
- **Rust** (stable) + Cargo — see <https://rustup.rs>
- **Python** ≥ 3.11
- **Ollama** — install from <https://ollama.com> (on Windows: `winget install Ollama.Ollama`),
  then pull the models:
  ```bash
  ollama pull qwen3:8b
  ollama pull nomic-embed-text
  ```

> Ollama is only required for the LLM-powered features. The app launches and reports Ollama as
> *unavailable* until it is installed and the models are pulled.

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

Retrieval and agent behaviour (reranking, MMR, parent-chunk expansion, grounding, the iterative
retrieve→reason loop, and more) is tunable **live from the in-app Settings panel** — changes apply
to the next question and persist across restarts. The same knobs can be set via environment
variables (`LORE_*`); see `sidecar/.env.example`.

### Running the tests

```bash
npm run test                                  # frontend: Vitest + React Testing Library
cd sidecar && python -m pytest -q             # backend: network-free pytest suite
```

Lint/format checks mirror CI:

```bash
npm run lint && npm run typecheck             # frontend: ESLint + tsc --noEmit
cd sidecar && ruff check .                    # backend: Ruff (lint-only)
```

Both test suites and all lint checks run on every push/PR via GitHub Actions
([`.github/workflows/ci.yml`](./.github/workflows/ci.yml)).

---

## Building the installer

Lore ships as a single desktop installer with **no Python required** at runtime — the FastAPI
sidecar is frozen into a standalone binary with PyInstaller and bundled inside the app.

```bash
# 1. Freeze the sidecar into a standalone binary (onedir).
cd sidecar
./build.ps1                 # creates the venv, installs deps, runs PyInstaller
                            # → sidecar/dist/lore-sidecar/lore-sidecar.exe
cd ..

# 2. Build the desktop installer (bundles the sidecar via tauri.conf.json resources).
npm run tauri build         # → src-tauri/target/release/bundle/
```

Releases are produced automatically: pushing a `v*` tag runs
[`.github/workflows/release.yml`](./.github/workflows/release.yml), which builds the sidecar, packages
the NSIS + MSI installers via `tauri-action`, and drafts a GitHub Release with the artifacts attached.

Notes:

- Build the sidecar binary **before** `npm run tauri build` — the Tauri bundle references
  `sidecar/dist/lore-sidecar`.
- The installed app stores its indexes under a per-user data directory (not next to the binary).
- The cross-encoder reranker model is **not** bundled; it downloads once (~90 MB) on first use to the
  data directory and then runs fully offline.
- **Ollama is still required at runtime** for the LLM features — the installer bundles Lore, not the
  language models.
- In development (`npm run tauri dev`) the bundled binary is absent, so the shell automatically falls
  back to running the sidecar from the Python virtualenv.

---

## Project layout

```
lore/
├── src/             # React + TypeScript frontend (UI; talks to the sidecar over HTTP)
├── src-tauri/       # Tauri (Rust) desktop shell + sidecar supervisor
├── sidecar/         # Python FastAPI backend (all RAG / ML logic)
└── .github/         # CI + release workflows
```

See [`CLAUDE.md`](./CLAUDE.md) for the development conventions and a deeper map of the codebase.

---

## Features

Lore is feature-complete and shipped as **v1.0.2**:

- **Code index** — tree-sitter AST chunking → LLM contextual enrichment → embeddings in LanceDB.
- **Grounded Q&A** — hybrid retrieval (vector + full-text + RRF) with an ONNX cross-encoder reranker,
  **MMR diversity** to drop near-duplicate evidence, and **parent-chunk expansion** for enclosing
  context; grounded generation with a faithfulness check.
- **Agentic router** — classifies each question and adapts retrieval (GraphRAG, history, docs), with a
  bounded **iterative retrieve→reason loop** that re-retrieves on the grounding pass's unsupported
  claims, plus opt-in **query expansion**.
- **Architecture graph** — static dependency graph + LLM semantic graph (calls/inherits), cycle
  detection, an architecture-rule engine, and a 2D/3D visualization.
- **Git history index** — embedded commit summaries, function-level blame, and authorship.
- **Docs index** — markdown/text split into heading-aware chunks; documentation questions are answered
  with file/line citations.
- **Streaming answers** — token-by-token responses over an NDJSON stream, with a Stop button and a
  latency readout.
- **Incremental indexing** — re-indexing only re-processes changed files/commits and prunes deleted
  ones; a "Force full re-index" option restores a clean rebuild.
- **Multi-turn conversation** — follow-ups are condensed against prior turns, so "explain that further"
  works; a "New chat" button resets the thread.
- **Click-through citations** — cited sources open in an in-app viewer at the exact lines (served by a
  read-only, path-traversal-guarded endpoint).
- **Live Settings panel** — tune retrieval/agent behaviour from the app with plain-language hover help;
  changes apply to the next question and persist (atomic, race-safe overrides).
- **Model management** — pull the required Ollama models from inside the app with a progress bar.
- **Refactoring agent** — surfaces structural problems (cycles, coupling hubs, rule violations) and
  proposes a grounded, on-demand LLM fix for each.
- **Evaluation** — a local harness reporting retrieval recall, faithfulness, and answer relevancy.
- **Packaging & CI** — PyInstaller-frozen sidecar bundled into the Tauri installer; a network-free
  pytest suite plus Vitest/RTL tests run on every push/PR.
