import { act, render, renderHook, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RecentConversation } from "../../app/nav";
import { SessionContext } from "../../auth/SessionProvider";
import { SideNav } from "./SideNav";
import { useNavCollapsed } from "./useNavCollapsed";

function renderNav({
  path = "/library",
  collapsed = false,
  onToggle = vi.fn(),
  recent = [],
}: { path?: string; collapsed?: boolean; onToggle?: () => void; recent?: RecentConversation[] } = {}) {
  render(
    <SessionContext.Provider value={{ name: "Ada Lovelace", signOut: vi.fn() }}>
      <MemoryRouter initialEntries={[path]}>
        <SideNav collapsed={collapsed} onToggle={onToggle} recent={recent} />
      </MemoryRouter>
    </SessionContext.Provider>,
  );
}

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("SideNav", () => {
  it("groups the items and marks the current page", () => {
    renderNav({ path: "/library" });
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: "Library" })).toHaveAttribute("aria-current", "page");
    expect(nav.querySelectorAll("hr")).toHaveLength(2);
  });

  it("lists up to three recent conversations under Conversations", () => {
    renderNav({ recent: [1, 2, 3, 4].map((n) => ({ id: `t${n}`, title: `Question ${n}`, path: `/conversations/t${n}` })) });
    const list = screen.getByRole("list", { name: "Recent conversations" });
    expect(within(list).getAllByRole("link")).toHaveLength(3);
  });

  it("collapses to the icon rail with names as accessible names and tooltips", async () => {
    const onToggle = vi.fn();
    renderNav({ collapsed: true, onToggle });
    const chat = screen.getByRole("link", { name: "Chat" });
    expect(chat).toHaveAttribute("data-tip", "Chat");
    await userEvent.click(screen.getByRole("button", { name: "Expand navigation" }));
    expect(onToggle).toHaveBeenCalled();
  });

  it("puts the collapse toggle at the top, after the brand and before the items", () => {
    renderNav();
    const nav = screen.getByRole("navigation", { name: "Main" });
    const brand = within(nav).getByRole("link", { name: "Smart Tutor, Library" });
    const toggle = within(nav).getByRole("button", { name: "Collapse navigation" });
    const library = within(nav).getByRole("link", { name: "Library" });
    const user = within(nav).getByRole("button", { name: /Ada Lovelace/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(brand.compareDocumentPosition(toggle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(toggle.compareDocumentPosition(library) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(library.compareDocumentPosition(user) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("tabs from the brand to the toggle, then to the first item", async () => {
    renderNav();
    await userEvent.tab();
    expect(screen.getByRole("link", { name: "Smart Tutor, Library" })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Collapse navigation" })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole("link", { name: "Library" })).toHaveFocus();
  });

  it("keeps focus on the toggle after it changes state", async () => {
    function Harness() {
      const [collapsed, toggle] = useNavCollapsed();
      return <SideNav collapsed={collapsed} onToggle={toggle} />;
    }
    render(
      <SessionContext.Provider value={{ name: "Ada Lovelace", signOut: vi.fn() }}>
        <MemoryRouter initialEntries={["/library"]}>
          <Harness />
        </MemoryRouter>
      </SessionContext.Provider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Collapse navigation" }));
    const expand = screen.getByRole("button", { name: "Expand navigation" });
    expect(expand).toHaveFocus();
    expect(expand).toHaveAttribute("aria-expanded", "false");
  });

  it("hides the recent conversations on the rail", () => {
    renderNav({ collapsed: true, recent: [{ id: "t1", title: "Q", path: "/conversations/t1" }] });
    expect(screen.queryByRole("list", { name: "Recent conversations" })).toBeNull();
  });
});

describe("useNavCollapsed", () => {
  it("starts expanded and remembers the choice across a reload", () => {
    const first = renderHook(() => useNavCollapsed());
    expect(first.result.current[0]).toBe(false);
    act(() => first.result.current[1]());
    expect(first.result.current[0]).toBe(true);
    expect(localStorage.getItem("smart-tutor.nav-collapsed")).toBe("1");
    expect(renderHook(() => useNavCollapsed()).result.current[0]).toBe(true);
  });

  it("still works when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { result } = renderHook(() => useNavCollapsed());
    expect(result.current[0]).toBe(false);
    act(() => result.current[1]());
    expect(result.current[0]).toBe(true);
  });
});
