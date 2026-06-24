import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ModelManager } from "./ModelManager";
import { fetchHealth, pullModelStream, type HealthResponse } from "../lib/api";

vi.mock("../lib/api", () => ({
  fetchHealth: vi.fn(),
  pullModelStream: vi.fn(),
}));

function health(reachable: boolean, missing: string[]): HealthResponse {
  return {
    status: missing.length ? "degraded" : "ok",
    service: "Lore",
    version: "0.1.0",
    databases: { sqlite: true, lancedb: true },
    ollama: {
      reachable,
      installed_models: ["nomic-embed-text"],
      missing_models: missing,
    },
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("ModelManager", () => {
  it("renders nothing when Ollama is ready", async () => {
    vi.mocked(fetchHealth).mockResolvedValue(health(true, []));
    render(<ModelManager />);
    await waitFor(() => expect(fetchHealth).toHaveBeenCalled());
    expect(screen.queryByText(/required models missing/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /pull/i })).toBeNull();
  });

  it("shows a start-Ollama hint when unreachable", async () => {
    vi.mocked(fetchHealth).mockResolvedValue(health(false, ["qwen3:8b"]));
    render(<ModelManager />);
    expect(await screen.findByText(/pull the models it needs/i)).toBeInTheDocument();
  });

  it("lets the user pull a missing model", async () => {
    vi.mocked(fetchHealth).mockResolvedValue(health(true, ["qwen3:8b"]));
    // Report progress, then stay pending so the progress UI remains visible
    // (a resolved pull would immediately clear the row and re-check health).
    vi.mocked(pullModelStream).mockImplementation((_model, handlers) => {
      handlers.onProgress?.({ status: "downloading", completed: 5, total: 10 });
      return new Promise<void>(() => {});
    });

    render(<ModelManager />);
    expect(await screen.findByText("qwen3:8b")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /pull/i }));

    expect(pullModelStream).toHaveBeenCalledWith("qwen3:8b", expect.anything());
    expect(await screen.findByText(/downloading 50%/i)).toBeInTheDocument();
  });
});
