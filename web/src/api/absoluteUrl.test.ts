import { describe, expect, it } from "vitest";

import { absoluteUrl } from "./absoluteUrl";

describe("absoluteUrl", () => {
  it("resolves a same-origin path against the page origin", () => {
    expect(absoluteUrl("/api", "https://d111.cloudfront.net")).toBe("https://d111.cloudfront.net/api");
  });

  it("keeps an absolute URL without a trailing slash", () => {
    expect(absoluteUrl("http://localhost:10450", "https://d111.cloudfront.net")).toBe("http://localhost:10450");
  });
});
