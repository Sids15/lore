import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ModelManager } from "./ModelManager";
import { fetchHealth, pullModelStream, type HealthResponse } from "../lib/api";

vi.mock("../lib/api", () => ({
  fetchHealth: vi.fn(),
  pullModelStream: vi.fn(),
}));

function health(missing: string[]): HealthResponse {
  return {
    status: missing.length ? "degraded" : "ok",
    service: "Lore",
    version: "0.1.0",
    databases: { sqlite: true, lancedb: true },
    ollama: {
      reachable: true,
      installed_models: ["nomic-embed-text"],
      missing_models: missing,
    },
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("ModelManager", () => {
  it("renders nothing when no models are missing", async () => {
    vi.mocked(fetchHealth).mockResolvedValue(health([]));
    render(<ModelManager />);
    await waitFor(() => expect(fetchHealth).toHaveBeenCalled());
    expect(screen.queryByText("Local models required")).toBeNull();
  });

  it("shows the banner with the missing model and a pull action", async () => {
    vi.mocked(fetchHealth).mockResolvedValue(health(["qwen3:8b"]));
    render(<ModelManager />);
    expect(await screen.findByText("Local models required")).toBeInTheDocument();
    expect(screen.getByText("qwen3:8b")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /pull models/i })).toBeInTheDocument();
  });

  it("pulls the missing model with progress", async () => {
    vi.mocked(fetchHealth).mockResolvedValue(health(["qwen3:8b"]));
    vi.mocked(pullModelStream).mockImplementation((_model, handlers) => {
      handlers.onProgress?.({ status: "downloading", completed: 5, total: 10 });
      return new Promise<void>(() => {});
    });

    render(<ModelManager />);
    await userEvent.click(await screen.findByRole("button", { name: /pull models/i }));

    expect(pullModelStream).toHaveBeenCalledWith("qwen3:8b", expect.anything());
    expect(await screen.findByText(/50%/)).toBeInTheDocument();
  });
});
