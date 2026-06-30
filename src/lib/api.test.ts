import { afterEach, describe, expect, it, vi } from "vitest";

import {
  askQuestionStream,
  fetchHealth,
  fetchSettings,
  fetchSource,
  pullModelStream,
  startCodeIndex,
  updateSettings,
  type AppSettings,
  type FinalEvent,
  type MetaEvent,
  type PullProgress,
} from "./api";
import { jsonResponse, streamResponse } from "../test/stream";

function mockFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("askQuestionStream", () => {
  it("dispatches meta, tokens, and final in order", async () => {
    const lines = [
      JSON.stringify({ type: "meta", categories: ["code"], graph_used: false, sources: [], commits: [], docs: [] }) + "\n",
      JSON.stringify({ type: "token", text: "Hello " }) + "\n",
      JSON.stringify({ type: "token", text: "world" }) + "\n",
      JSON.stringify({ type: "final", grounded: true, unsupported: [], corrected: false }) + "\n",
    ];
    mockFetch(streamResponse(lines));

    const tokens: string[] = [];
    let meta: MetaEvent | null = null;
    let final: FinalEvent | null = null;
    await askQuestionStream("q", {
      onMeta: (m) => (meta = m),
      onToken: (t) => tokens.push(t),
      onFinal: (f) => (final = f),
    });

    expect(meta).not.toBeNull();
    expect(tokens.join("")).toBe("Hello world");
    expect(final).toEqual({ type: "final", grounded: true, unsupported: [], corrected: false });
  });

  it("reassembles an event split across chunks", async () => {
    const event = JSON.stringify({ type: "token", text: "split" }) + "\n";
    const mid = Math.floor(event.length / 2);
    mockFetch(streamResponse([event.slice(0, mid), event.slice(mid)]));

    const tokens: string[] = [];
    await askQuestionStream("q", { onToken: (t) => tokens.push(t) });
    expect(tokens).toEqual(["split"]);
  });
});

describe("pullModelStream", () => {
  it("dispatches progress then done", async () => {
    const lines = [
      JSON.stringify({ type: "progress", status: "downloading", completed: 5, total: 10 }) + "\n",
      JSON.stringify({ type: "done" }) + "\n",
    ];
    mockFetch(streamResponse(lines));

    const progress: PullProgress[] = [];
    let done = false;
    await pullModelStream("qwen3:8b", {
      onProgress: (e) => progress.push(e),
      onDone: () => (done = true),
    });

    expect(progress).toHaveLength(1);
    expect(progress[0].completed).toBe(5);
    expect(done).toBe(true);
  });

  it("surfaces an error event", async () => {
    mockFetch(streamResponse([JSON.stringify({ type: "error", detail: "boom" }) + "\n"]));
    let detail = "";
    await pullModelStream("m", { onError: (d) => (detail = d) });
    expect(detail).toBe("boom");
  });
});

describe("fetchSource", () => {
  it("builds the query string and parses the window", async () => {
    const fetchMock = mockFetch(
      jsonResponse({
        repo: "r",
        file_path: "a.py",
        start_line: 10,
        end_line: 12,
        window_start: 5,
        lines: ["a", "b"],
      }),
    );

    const view = await fetchSource("r", "a.py", 10, 12);
    expect(view.window_start).toBe(5);

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/source?");
    expect(url).toContain("repo=r");
    expect(url).toContain("start=10");
    expect(url).toContain("end=12");
  });
});

const SETTINGS: AppSettings = {
  rerank_enabled: true,
  mmr_enabled: true,
  mmr_lambda: 0.7,
  parent_expansion_enabled: true,
  query_expansion_enabled: false,
  query_expansion_n: 3,
  self_correct_enabled: true,
  iterative_enabled: false,
  iterative_max_rounds: 3,
  grounding_enabled: true,
  router_enabled: true,
  graphrag_enabled: true,
  conversation_enabled: true,
  retrieval_top_k: 8,
};

describe("settings", () => {
  it("fetchSettings GETs the current values", async () => {
    const fetchMock = mockFetch(jsonResponse(SETTINGS));
    const s = await fetchSettings();
    expect(s.mmr_lambda).toBe(0.7);
    expect(fetchMock.mock.calls[0][0] as string).toContain("/settings");
  });

  it("updateSettings PATCHes a partial body", async () => {
    const fetchMock = mockFetch(jsonResponse({ ...SETTINGS, iterative_enabled: true }));
    const s = await updateSettings({ iterative_enabled: true });
    expect(s.iterative_enabled).toBe(true);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ iterative_enabled: true });
  });

  it("updateSettings surfaces a validation error", async () => {
    mockFetch(jsonResponse({ detail: "bad" }, { ok: false, status: 422 }));
    await expect(updateSettings({ mmr_lambda: 2 })).rejects.toThrow(/bad/);
  });
});

describe("error handling", () => {
  it("extracts the detail from a non-2xx response", async () => {
    mockFetch(jsonResponse({ detail: "Not a directory" }, { ok: false, status: 400 }));
    await expect(startCodeIndex("/bad")).rejects.toThrow(/Not a directory/);
  });

  it("fetchHealth throws on a non-2xx response", async () => {
    mockFetch(jsonResponse({}, { ok: false, status: 500 }));
    await expect(fetchHealth()).rejects.toThrow(/HTTP 500/);
  });
});
