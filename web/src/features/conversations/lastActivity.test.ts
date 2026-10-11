import { describe, expect, it } from "vitest";

import { lastActivity } from "./lastActivity";

// 05:00 UTC is 12:00 in GMT+7.
const now = new Date("2026-10-11T05:00:00Z");

describe("lastActivity", () => {
  it("today", () => expect(lastActivity("2026-10-11T02:48:00Z", now)).toBe("Today, 09:48"));
  it("yesterday in the app time zone", () => expect(lastActivity("2026-10-10T09:20:00Z", now)).toBe("Yesterday, 16:20"));
  it("crosses midnight in GMT+7, not UTC", () => expect(lastActivity("2026-10-10T17:30:00Z", now)).toBe("Today, 00:30"));
  it("this year", () => expect(lastActivity("2026-09-30T03:00:00Z", now)).toBe("30 Sep"));
  it("another year", () => expect(lastActivity("2025-09-30T03:00:00Z", now)).toBe("30 Sep 2025"));
});
