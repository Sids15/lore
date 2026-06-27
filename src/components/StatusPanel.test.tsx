import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StatusPanel } from "./StatusPanel";
import { fetchHealth, type HealthResponse } from "../lib/api";

vi.mock("../lib/api", () => ({
  fetchHealth: vi.fn(),
}));

function health(reachable: boolean, missing: string[]): HealthResponse {
  return {
    status: "ok",
    service: "Lore",
    version: "0.1.0",
    databases: { sqlite: true, lancedb: true },
    ollama: { reachable, installed_models: ["m", "n"], missing_models: missing },
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("StatusPanel", () => {
  it("shows healthy segments when everything is up", async () => {
    vi.mocked(fetchHealth).mockResolvedValue(health(true, []));
    render(<StatusPanel />);
    expect(await screen.findByText("sidecar")).toBeInTheDocument();
    expect(screen.getByText("db ready")).toBeInTheDocument();
    expect(screen.getByText("Ollama · 2 models")).toBeInTheDocument();
  });

  it("shows missing models", async () => {
    vi.mocked(fetchHealth).mockResolvedValue(health(true, ["qwen3:8b"]));
    render(<StatusPanel />);
    expect(await screen.findByText("Ollama · 1 missing")).toBeInTheDocument();
  });

  it("shows Sidecar offline when the health check fails", async () => {
    vi.mocked(fetchHealth).mockRejectedValue(new Error("ECONNREFUSED"));
    render(<StatusPanel />);
    expect(await screen.findByText("Sidecar offline")).toBeInTheDocument();
  });
});
