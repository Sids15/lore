import "./App.css";

/**
 * Root component of the Lore frontend.
 *
 * Phase 0 renders a minimal branded landing screen. The system status panel
 * (sidecar / databases / Ollama health) is wired in a later feature.
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
      </section>
    </main>
  );
}

export default App;
