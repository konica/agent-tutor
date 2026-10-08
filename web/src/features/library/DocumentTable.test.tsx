import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DocumentResponse } from "../../api/documents";
import { DocumentTable } from "./DocumentTable";

const doc: DocumentResponse = { document_id: "d1", title: "Toolformer", state: "ready", failure_reason: null, created_at: "2026-10-04T09:00:00Z", subjects: [], attempt: null, max_attempts: 3, can_retry: false, authors: ["Timo Schick", "Jane Dwivedi-Yu", "Roberto Dessì"], year: 2023 };

describe("DocumentTable", () => {
  it("shows authors and year under the title", () => {
    render(<DocumentTable documents={[doc]} onRetry={() => {}} retrying={new Set()} />);
    const row = screen.getByText("Toolformer").closest("tr")!;
    expect(within(row).getByText("Schick et al. · 2023")).toBeVisible();
  });

  it("shows no byline when authors and year are missing", () => {
    render(<DocumentTable documents={[{ ...doc, authors: [], year: null }]} onRetry={() => {}} retrying={new Set()} />);
    const cell = screen.getByText("Toolformer").closest("td")!;
    expect(cell).toHaveTextContent(/^Toolformer$/);
  });
});

describe("DocumentTable upload day", () => {
  afterEach(() => vi.useRealTimers());

  it("shows the day in GMT+7, not the browser's", () => {
    vi.useFakeTimers({ now: new Date("2026-10-20T00:00:00Z") });
    render(<DocumentTable documents={[{ ...doc, created_at: "2026-10-01T17:30:00Z" }]} onRetry={() => {}} retrying={new Set()} />);
    expect(screen.getByRole("cell", { name: /2 Oct 2026|Oct 2, 2026/ })).toBeVisible();
  });

  it("says Today when the upload is on the current GMT+7 day", () => {
    vi.useFakeTimers({ now: new Date("2026-10-02T01:00:00Z") });
    render(<DocumentTable documents={[{ ...doc, created_at: "2026-10-01T17:30:00Z" }]} onRetry={() => {}} retrying={new Set()} />);
    expect(screen.getByText("Today")).toBeVisible();
  });
});
