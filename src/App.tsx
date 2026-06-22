import { useState, type ReactNode } from "react";

import { GraphPanel } from "./components/GraphPanel";
import { IndexPanel } from "./components/IndexPanel";
import { QueryPanel } from "./components/QueryPanel";
import { StatusPanel } from "./components/StatusPanel";
import "./App.css";

type View = "ask" | "index" | "graph" | "eval";

const NAV: { id: View; label: string }[] = [
  { id: "ask", label: "ask" },
  { id: "index", label: "index" },
  { id: "graph", label: "graph" },
  { id: "eval", label: "eval" },
];

/**
 * Shell: a top bar (wordmark + nav), the active view, and an IDE-style status
 * line. Views stay mounted (toggled with `hidden`) so each panel keeps its state
 * — Q&A history, the loaded graph, indexing progress — across tab switches.
 */
function App() {
  const [view, setView] = useState<View>("ask");

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar__brand">
          <span className="topbar__mark">lore</span>
          <span className="topbar__caret" aria-hidden />
        </div>
        <nav className="topbar__nav">
          {NAV.map((n) => (
            <button
              key={n.id}
              className={`tab${view === n.id ? " is-active" : ""}`}
              onClick={() => setView(n.id)}
            >
              {n.label}
            </button>
          ))}
        </nav>
        <span className="topbar__sub">codebase lorekeeper</span>
      </header>

      <main className="app__content">
        <Tab id="ask" view={view}><QueryPanel /></Tab>
        <Tab id="index" view={view}><IndexPanel /></Tab>
        <Tab id="graph" view={view}><GraphPanel /></Tab>
        <Tab id="eval" view={view}>
          <p className="placeholder">
            Run quality evaluations here. Add a <code>.lore/eval.yml</code> to your repo with a
            few questions, then evaluation metrics will appear in this tab.
          </p>
        </Tab>
      </main>

      <footer className="statusbar">
        <StatusPanel />
        <span className="statusbar__right">100% local · no cloud</span>
      </footer>
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
