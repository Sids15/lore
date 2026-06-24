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
    ollama: { reachable, installed_models: ["m"], missing_models: missing },
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("StatusPanel", () => {
  it("shows Ready when everything is healthy", async () => {
    vi.mocked(fetchHealth).mockResolvedValue(health(true, []));
    render(<StatusPanel />);
    expect(await screen.findByText("Ready")).toBeInTheDocument();
  });

  it("shows Models missing when models are absent", async () => {
    vi.mocked(fetchHealth).mockResolvedValue(health(true, ["qwen3:8b"]));
    render(<StatusPanel />);
    expect(await screen.findByText("Models missing")).toBeInTheDocument();
  });

  it("shows Sidecar offline when the health check fails", async () => {
    vi.mocked(fetchHealth).mockRejectedValue(new Error("ECONNREFUSED"));
    render(<StatusPanel />);
    expect(await screen.findByText("Sidecar offline")).toBeInTheDocument();
  });
});
