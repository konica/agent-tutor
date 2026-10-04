import { render, screen } from "@testing-library/react";
import { Upload } from "lucide-react";
import { describe, expect, it } from "vitest";

import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("renders the heading, text, and actions", () => {
    render(
      <EmptyState icon={Upload} title="Nothing here" actions={<button>Add</button>}>
        Add something.
      </EmptyState>,
    );
    expect(screen.getByRole("heading", { level: 2, name: "Nothing here" })).toBeInTheDocument();
    expect(screen.getByText("Add something.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add" })).toBeInTheDocument();
  });
});
