import { StatusPanel } from "./components/StatusPanel";
import "./App.css";

/**
 * Root component of the Lore frontend.
 *
 * Phase 0 renders a minimal branded landing screen plus a live sidecar status
 * indicator. Database and Ollama readiness are added to the panel in later
 * features.
 */
function App() {
  return (
    <main className="app">
      <header className="app__header">
        <h1 className="app__title">Lore</h1>
        <p className="app__tagline">
          Local-first agentic RAG for your codebase.
        </p>
      </header>

      <section className="app__body">
        <p className="app__hint">
          The desktop shell is running. Indexing and Q&amp;A arrive in upcoming
          phases.
        </p>
        <StatusPanel />
      </section>
    </main>
  );
}

export default App;
