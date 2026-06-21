import { GraphPanel } from "./components/GraphPanel";
import { IndexPanel } from "./components/IndexPanel";
import { QueryPanel } from "./components/QueryPanel";
import { StatusPanel } from "./components/StatusPanel";
import "./App.css";

/**
 * Root component of the Lore frontend.
 *
 * Renders the branded header, the live system-status panel, and the Code Index
 * builder (choose a repository and index it). Q&A arrives in later phases.
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
        <StatusPanel />
        <IndexPanel />
        <QueryPanel />
        <GraphPanel />
      </section>
    </main>
  );
}

export default App;
