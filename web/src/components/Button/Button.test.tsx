import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChevronLeft, Upload, X } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./Button";
import { IconButton } from "./IconButton";
import styles from "./Button.module.css";

describe("Button", () => {
  it("is a secondary, medium, type=button button by default", () => {
    render(<Button>Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveClass(styles.button, styles.secondary, styles.md);
  });

  it("applies the variant and size", () => {
    render(<Button variant="primary" size="lg">Go</Button>);
    expect(screen.getByRole("button", { name: "Go" })).toHaveClass(styles.primary, styles.lg);
  });

  it("keeps the icon out of the accessible name", () => {
    render(<Button icon={Upload}>Upload</Button>);
    const button = screen.getByRole("button", { name: "Upload" });
    expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("is disabled and says so", async () => {
    const onClick = vi.fn();
    render(<Button disabled onClick={onClick}>Choose PDFs</Button>);
    const button = screen.getByRole("button", { name: "Choose PDFs" });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("IconButton", () => {
  it("labels an icon button and shows the same text as its tooltip", () => {
    render(<IconButton label="Collapse navigation" icon={ChevronLeft} />);
    const button = screen.getByRole("button", { name: "Collapse navigation" });
    expect(button).toHaveAttribute("data-tip", "Collapse navigation");
    expect(button).toHaveAttribute("type", "button");
  });

  it("can drop the tooltip when visible text already names the action", () => {
    render(<IconButton label="Close" icon={X} tip={false} />);
    expect(screen.getByRole("button", { name: "Close" })).not.toHaveAttribute("data-tip");
  });
});
