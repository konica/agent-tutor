import { describe, expect, it } from "vitest";

import { limitTime } from "./time";

describe("limitTime", () => {
  it("shows the time in GMT+7 on a 24-hour clock", () => {
    expect(limitTime(new Date("2026-10-10T04:40:00Z"))).toBe("11:40 (GMT+7)");
    expect(limitTime(new Date("2026-10-10T17:00:00Z"))).toBe("00:00 (GMT+7)");
  });
});
