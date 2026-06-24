import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SourceViewer } from "./SourceViewer";
import { fetchSource } from "../lib/api";

vi.mock("../lib/api", () => ({
  fetchSource: vi.fn(),
}));

const TARGET = { repo: "r", path: "a.py", start: 2, end: 2 };

afterEach(() => {
  vi.clearAllMocks();
});

function mockWindow() {
  vi.mocked(fetchSource).mockResolvedValue({
    repo: "r",
    file_path: "a.py",
    start_line: 2,
    end_line: 2,
    window_start: 1,
    lines: ["first", "second", "third"],
  });
}

describe("SourceViewer", () => {
  it("renders the window with the cited line highlighted", async () => {
    mockWindow();
    render(<SourceViewer target={TARGET} onClose={() => undefined} />);

    const cited = await screen.findByText("second");
    expect(cited.closest(".viewer__line")).toHaveClass("viewer__line--cited");
    expect(screen.getByText("first").closest(".viewer__line")).not.toHaveClass(
      "viewer__line--cited",
    );
  });

  it("closes on Escape", async () => {
    mockWindow();
    const onClose = vi.fn();
    render(<SourceViewer target={TARGET} onClose={onClose} />);
    await screen.findByText("second");

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("closes when the ✕ button is clicked", async () => {
    mockWindow();
    const onClose = vi.fn();
    render(<SourceViewer target={TARGET} onClose={onClose} />);
    await screen.findByText("second");

    await userEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalled();
  });
});
