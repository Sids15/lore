import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";

import { fetchGraph, type GraphNode, type GraphViz } from "../lib/api";

const CANVAS_HEIGHT = 360;

/**
 * Visualizes the repository's import/dependency graph with a force-directed
 * layout. Node size reflects total degree; nodes in an import cycle are red.
 * Click a node to see its file and its immediate neighbours.
 */
export function GraphPanel() {
  const [graph, setGraph] = useState<GraphViz | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [width, setWidth] = useState(480);
  const containerRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setGraph(await fetchGraph());
      setSelected(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load graph");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Keep the canvas width in sync with its container.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setWidth(el.clientWidth);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [graph]);

  // Undirected neighbour map, computed from the raw links (before the force
  // graph mutates link.source/target into node objects).
  const neighbours = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const link of graph?.links ?? []) {
      if (!map.has(link.source)) map.set(link.source, new Set());
      if (!map.has(link.target)) map.set(link.target, new Set());
      map.get(link.source)!.add(link.target);
      map.get(link.target)!.add(link.source);
    }
    return map;
  }, [graph]);

  // Fresh copies for the force graph (which mutates the arrays it receives).
  const graphData = useMemo(
    () => ({
      nodes: (graph?.nodes ?? []).map((n) => ({ ...n })),
      links: (graph?.links ?? []).map((l) => ({ ...l })),
    }),
    [graph],
  );

  const hasData = !!graph && graph.nodes.length > 0;

  return (
    <section className="graph">
      <div className="graph__head">
        <h2 className="graph__title">Dependency graph</h2>
        <button className="graph__refresh" onClick={() => void load()} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && <p className="graph__error">{error}</p>}

      {!hasData && !loading && !error && (
        <p className="graph__empty">No graph yet — index a repository first.</p>
      )}

      {hasData && (
        <>
          <div className="graph__canvas" ref={containerRef}>
            <ForceGraph2D
              graphData={graphData}
              width={width}
              height={CANVAS_HEIGHT}
              backgroundColor="#0b0d11"
              nodeId="id"
              nodeRelSize={4}
              nodeLabel={(n: GraphNode) =>
                `${n.file_path} — in ${n.in_degree} / out ${n.out_degree}`
              }
              nodeVal={(n: GraphNode) => 1 + n.in_degree + n.out_degree}
              nodeColor={(n: GraphNode) => (n.in_cycle ? "#e5484d" : "#6ea8fe")}
              linkColor={() => "rgba(154,163,178,0.25)"}
              linkDirectionalArrowLength={2.5}
              linkDirectionalArrowRelPos={1}
              cooldownTicks={80}
              onNodeClick={(n: GraphNode) => setSelected(n)}
            />
          </div>

          {graph!.truncated && (
            <p className="graph__note">
              Showing the {graph!.nodes.length} highest-degree modules.
            </p>
          )}

          {selected && (
            <div className="graph__detail">
              <code className="graph__detail-file">{selected.file_path}</code>
              <span className="graph__detail-meta">
                in {selected.in_degree} · out {selected.out_degree}
                {selected.in_cycle ? " · in cycle" : ""}
              </span>
              <div className="graph__neighbours">
                {[...(neighbours.get(selected.id) ?? [])].slice(0, 12).map((nb) => (
                  <span key={nb} className="graph__chip">
                    {nb}
                  </span>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
