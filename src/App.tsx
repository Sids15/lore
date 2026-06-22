import { useState, type ReactNode } from "react";

import { GraphPanel } from "./components/GraphPanel";
import { IndexPanel } from "./components/IndexPanel";
import { QueryPanel } from "./components/QueryPanel";
import { StatusPanel } from "./components/StatusPanel";
import "./App.css";

type View = "ask" | "index" | "graph" | "eval";

const NAV: { id: View; label: string }[] = [
  { id: "ask", label: "Ask" },
  { id: "index", label: "Index" },
  { id: "graph", label: "Graph" },
  { id: "eval", label: "Eval" },
];

/**
 * Root layout: a header (brand + health badge), a left nav, and a content area.
 * Views stay mounted (toggled with `hidden`) so each panel keeps its state —
 * Q&A history, the loaded graph, indexing progress — across tab switches.
 */
function App() {
  const [view, setView] = useState<View>("ask");

  return (
    <div className="app">
      <header className="app__header">
        <div className="app__brand">
          <span className="app__logo">Lore</span>
          <span className="app__tagline">local-first agentic RAG</span>
        </div>
        <StatusPanel />
      </header>

      <div className="app__layout">
        <nav className="app__nav">
          {NAV.map((n) => (
            <button
              key={n.id}
              className={`app__nav-btn${view === n.id ? " is-active" : ""}`}
              onClick={() => setView(n.id)}
            >
              {n.label}
            </button>
          ))}
        </nav>

        <main className="app__content">
          <Tab id="ask" view={view}><QueryPanel /></Tab>
          <Tab id="index" view={view}><IndexPanel /></Tab>
          <Tab id="graph" view={view}><GraphPanel /></Tab>
          <Tab id="eval" view={view}>
            <p className="placeholder">
              Run quality evaluations here. Add a <code>.lore/eval.yml</code> to your repo
              with a few questions, then evaluation metrics will appear in this tab.
            </p>
          </Tab>
        </main>
      </div>
    </div>
  );
}

function Tab({ id, view, children }: { id: View; view: View; children: ReactNode }) {
  return (
    <div className="app__view" hidden={view !== id}>
      {children}
    </div>
  );
}

export default App;
