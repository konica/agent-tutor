import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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
