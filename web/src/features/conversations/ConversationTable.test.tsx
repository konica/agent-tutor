import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { ThreadSummaryResponse } from "../../api/conversations";
import { ConversationTable } from "./ConversationTable";

const subject = (id: string, name: string) => ({ subject_id: id, name });

const thread = (over: Partial<ThreadSummaryResponse> = {}): ThreadSummaryResponse => ({
  thread_id: "t1",
  title: "How does ReAct work?",
  subjects: [subject("s1", "AI Agents")],
  documents: 3,
  last_activity: "2026-09-30T03:00:00Z",
  ...over,
});

type Extra = Partial<Omit<ComponentProps<typeof ConversationTable>, "conversations">>;

function renderTable(conversations: ThreadSummaryResponse[], extra: Extra = {}) {
  render(
    <MemoryRouter initialEntries={["/conversations"]}>
      <Routes>
        <Route path="/conversations" element={<ConversationTable conversations={conversations} archived={false} onArchive={() => {}} onRestore={() => {}} {...extra} />} />
        <Route path="/chat/:threadId" element={<p>Chat page</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ConversationTable", () => {
  it("has the four columns and a header-less actions one", () => {
    renderTable([thread()]);
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Conversation", "Subjects of documents used", "Documents", "Last activity", "Actions"]);
  });

  it("links the title to the conversation", () => {
    renderTable([thread()]);
    expect(screen.getByRole("link", { name: "How does ReAct work?" })).toHaveAttribute("href", "/chat/t1");
  });

  it("opens the conversation when the row is clicked outside the link", async () => {
    renderTable([thread()]);
    await userEvent.click(screen.getByRole("cell", { name: "3" }));
    expect(screen.getByText("Chat page")).toBeInTheDocument();
  });

  it("opens the conversation when its link is clicked", async () => {
    renderTable([thread()]);
    await userEvent.click(screen.getByRole("link", { name: "How does ReAct work?" }));
    expect(screen.getByText("Chat page")).toBeInTheDocument();
  });

  it("shows two subject chips and a +N naming the hidden ones", () => {
    renderTable([thread({ subjects: [subject("s1", "AI Agents"), subject("s2", "LLMs"), subject("s3", "Reinforcement Learning")] })]);
    const row = within(screen.getAllByRole("row")[1]!);
    expect(row.getByText("AI Agents")).toBeInTheDocument();
    expect(row.getByText("LLMs")).toBeInTheDocument();
    expect(row.queryByText("Reinforcement Learning")).not.toBeInTheDocument();
    expect(row.getByText("+1")).toBeInTheDocument();
    const reader = row.getByText("1 more: Reinforcement Learning");
    expect(reader).toHaveClass("visually-hidden");
    expect(reader.parentElement).toHaveAttribute("title", "Reinforcement Learning");
  });

  it("says None yet without subjects", () => {
    renderTable([thread({ subjects: [] })]);
    expect(screen.getByText("None yet")).toBeInTheDocument();
  });

  it("shows the documents count and the last activity in a time element", () => {
    renderTable([thread({ documents: 2 })]);
    expect(screen.getByRole("cell", { name: "2" })).toBeInTheDocument();
    const time = screen.getByText(/30 Sep/);
    expect(time.tagName).toBe("TIME");
    expect(time).toHaveAttribute("datetime", "2026-09-30T03:00:00Z");
  });

  it("an untitled conversation reads Untitled conversation", () => {
    renderTable([thread({ title: null })]);
    expect(screen.getByRole("link", { name: "Untitled conversation" })).toHaveAttribute("href", "/chat/t1");
  });

  const menuItems = () => screen.getAllByRole("menuitem").map((i) => i.textContent);

  it("an active row's menu offers Open and Archive", async () => {
    const onArchive = vi.fn();
    const row = thread();
    renderTable([row], { onArchive });
    await userEvent.click(screen.getByRole("button", { name: "Actions for How does ReAct work?" }));
    expect(menuItems()).toEqual(["Open", "Archive"]);
    await userEvent.click(screen.getByRole("menuitem", { name: "Archive" }));
    expect(onArchive).toHaveBeenCalledWith(row);
    expect(screen.queryByText("Chat page")).not.toBeInTheDocument(); // the row's click-to-open stayed out of it
  });

  it("an archived row's menu offers Open and Restore", async () => {
    const onRestore = vi.fn();
    const row = thread();
    renderTable([row], { archived: true, onRestore });
    await userEvent.click(screen.getByRole("button", { name: "Actions for How does ReAct work?" }));
    expect(menuItems()).toEqual(["Open", "Restore"]);
    await userEvent.click(screen.getByRole("menuitem", { name: "Restore" }));
    expect(onRestore).toHaveBeenCalledWith(row);
  });

  it("Open navigates to the conversation", async () => {
    renderTable([thread()]);
    await userEvent.click(screen.getByRole("button", { name: "Actions for How does ReAct work?" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Open" }));
    expect(screen.getByText("Chat page")).toBeInTheDocument();
  });

  it("opening the menu does not open the conversation", async () => {
    renderTable([thread()]);
    await userEvent.click(screen.getByRole("button", { name: "Actions for How does ReAct work?" }));
    expect(screen.queryByText("Chat page")).not.toBeInTheDocument();
  });

  it("a busy row's menu is disabled", () => {
    renderTable([thread()], { busy: new Set(["t1"]) });
    expect(screen.getByRole("button", { name: "Actions for How does ReAct work?" })).toBeDisabled();
  });
});
