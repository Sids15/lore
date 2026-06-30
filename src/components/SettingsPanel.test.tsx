import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SettingsPanel } from "./SettingsPanel";
import { fetchSettings, updateSettings, type AppSettings } from "../lib/api";

vi.mock("../lib/api", () => ({
  fetchSettings: vi.fn(),
  updateSettings: vi.fn(),
}));

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

afterEach(() => {
  vi.clearAllMocks();
});

describe("SettingsPanel", () => {
  it("loads and renders the current settings", async () => {
    vi.mocked(fetchSettings).mockResolvedValue(SETTINGS);
    render(<SettingsPanel />);
    expect(await screen.findByText("Iterative loop")).toBeInTheDocument();
    expect(screen.getByText("MMR diversity")).toBeInTheDocument();
  });

  it("PATCHes when a toggle is flipped", async () => {
    vi.mocked(fetchSettings).mockResolvedValue(SETTINGS);
    vi.mocked(updateSettings).mockResolvedValue({ ...SETTINGS, query_expansion_enabled: true });

    render(<SettingsPanel />);
    const toggle = await screen.findByText("Query expansion");
    const row = toggle.closest(".set__row") as HTMLElement;
    await userEvent.click(row.querySelector('input[type="checkbox"]') as HTMLElement);

    expect(updateSettings).toHaveBeenCalledWith({ query_expansion_enabled: true });
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("steps a number setting up via the + button", async () => {
    vi.mocked(fetchSettings).mockResolvedValue(SETTINGS);
    vi.mocked(updateSettings).mockResolvedValue({ ...SETTINGS, query_expansion_n: 4 });

    render(<SettingsPanel />);
    const row = (await screen.findByText("Expansion phrasings")).closest(".set__row") as HTMLElement;
    await userEvent.click(row.querySelector('button[aria-label="Increase"]') as HTMLElement);

    expect(updateSettings).toHaveBeenCalledWith({ query_expansion_n: 4 }); // 3 + step(1)
  });

  it("shows an error and re-fetches authoritative state when saving fails", async () => {
    vi.mocked(fetchSettings).mockResolvedValue(SETTINGS);
    vi.mocked(updateSettings).mockRejectedValue(new Error("HTTP 422"));

    render(<SettingsPanel />);
    const row = (await screen.findByText("Iterative loop")).closest(".set__row") as HTMLElement;
    const checkbox = row.querySelector('input[type="checkbox"]') as HTMLInputElement;
    await userEvent.click(checkbox);

    await waitFor(() => expect(screen.getByText("HTTP 422")).toBeInTheDocument());
    // The failed save resyncs from the server instead of reverting to a stale snapshot:
    // mount fetch + error-path re-fetch = 2 calls, and the checkbox reverts to false.
    await waitFor(() => expect(fetchSettings).toHaveBeenCalledTimes(2));
    expect(checkbox.checked).toBe(false); // reverted to the authoritative value
  });
});
