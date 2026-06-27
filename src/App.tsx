import { useEffect, useState, type ReactNode } from "react";

import { EvalPanel } from "./components/EvalPanel";
import { GraphPanel } from "./components/GraphPanel";
import { IndexPanel } from "./components/IndexPanel";
import { ModelManager } from "./components/ModelManager";
import { QueryPanel } from "./components/QueryPanel";
import { RefactorPanel } from "./components/RefactorPanel";
import { StatusPanel } from "./components/StatusPanel";
import loreWordmark from "./assets/lore-wordmark.png";
import "./App.css";

/** Last path segment of a repo path, e.g. C:\work\relay → relay. */
function repoNameOf(path: string | null): string | null {
  if (!path) return null;
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : path;
}

type View = "ask" | "index" | "graph" | "eval" | "refactor";
type Theme = "dark" | "light";

const NAV: { id: View; label: string; icon: ReactNode }[] = [
  { id: "ask", label: "Ask", icon: <IconChat /> },
  { id: "index", label: "Index", icon: <IconDatabase /> },
  { id: "graph", label: "Graph", icon: <IconGraph /> },
  { id: "eval", label: "Eval", icon: <IconChart /> },
  { id: "refactor", label: "Refactor", icon: <IconBranch /> },
];

/**
 * The Lore shell: a model-setup banner (when needed), a left sidebar, the active
 * workspace, and a full-width status bar. Views stay mounted (toggled with
 * `hidden`) so each keeps its state across navigation.
 */
function App() {
  const [view, setView] = useState<View>("ask");
  const [repoPath, setRepoPath] = useState<string | null>(null);
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("lore-theme") as Theme) || "dark",
  );
  const repoName = repoNameOf(repoPath);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("lore-theme", theme);
  }, [theme]);

  return (
    <div className="app">
      <ModelManager />

      <div className="app__body">
        <aside className="sb">
          <div className="sb__brand">
            <img className="sb__wordmark" src={loreWordmark} alt="Lore" />
            <div className="sb__cap">codebase memory · v0.4</div>
          </div>

          <nav className="sb__nav" aria-label="Primary">
            {NAV.map((n) => (
              <button
                key={n.id}
                className={`navitem${view === n.id ? " is-active" : ""}`}
                onClick={() => setView(n.id)}
                aria-current={view === n.id ? "page" : undefined}
              >
                <span className="navitem__icon" aria-hidden>{n.icon}</span>
                <span className="navitem__label">{n.label}</span>
              </button>
            ))}
          </nav>

          <div className="sb__foot">
            <div className="sb__repo">
              <div className="sb__repo-eyebrow">Repository</div>
              <div className="sb__repo-name">{repoName ?? "no repository"}</div>
            </div>
            <button
              className="sb__appearance"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              <span>Appearance</span>
              <span className="sb__appearance-val">{theme === "dark" ? "Dark" : "Light"}</span>
            </button>
          </div>
        </aside>

        <div className="main">
          <div className="stage">
            <Tab id="ask" view={view}><QueryPanel /></Tab>
            <Tab id="index" view={view}><IndexPanel path={repoPath} setPath={setRepoPath} /></Tab>
            <Tab id="graph" view={view}><GraphPanel /></Tab>
            <Tab id="eval" view={view}><EvalPanel /></Tab>
            <Tab id="refactor" view={view}><RefactorPanel /></Tab>
          </div>
        </div>
      </div>

      <StatusPanel repo={repoName} />
    </div>
  );
}

function Tab({ id, view, children }: { id: View; view: View; children: ReactNode }) {
  return (
    <div className="stage__view" hidden={view !== id}>
      {children}
    </div>
  );
}

/* ── Nav icons (line, 1.7px, currentColor) ─────────────────────────────────── */

function Svg({ children }: { children: ReactNode }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  );
}

function IconChat() {
  return <Svg><path d="M3.5 4.5h13v8h-7l-3.2 2.7V12.5H3.5z" /></Svg>;
}
function IconDatabase() {
  return (
    <Svg>
      <ellipse cx="10" cy="5" rx="6" ry="2.3" />
      <path d="M4 5v10c0 1.27 2.69 2.3 6 2.3s6-1.03 6-2.3V5" />
      <path d="M4 10c0 1.27 2.69 2.3 6 2.3s6-1.03 6-2.3" />
    </Svg>
  );
}
function IconGraph() {
  return (
    <Svg>
      <circle cx="5" cy="14.5" r="2" />
      <circle cx="15" cy="13" r="2" />
      <circle cx="10.5" cy="5" r="2" />
      <path d="M6.6 13 9.4 6.6M12 6.4 13.9 11.2" />
    </Svg>
  );
}
function IconChart() {
  return <Svg><path d="M4 16h12M5.5 16v-5M10 16V5M14.5 16v-7.5" /></Svg>;
}
function IconBranch() {
  return (
    <Svg>
      <circle cx="5.5" cy="5" r="1.8" />
      <circle cx="5.5" cy="15" r="1.8" />
      <circle cx="14.5" cy="10" r="1.8" />
      <path d="M5.5 6.8v6.4M5.5 10h4.2A3 3 0 0 0 12.7 7" />
    </Svg>
  );
}

export default App;
