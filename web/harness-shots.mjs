// TEMPORARY: screenshots of the #190 harness in installed Chrome — not committed.
import { chromium } from "playwright";

const out = process.argv[2];
const browser = await chromium.launch({ channel: "chrome" });
for (const scheme of ["light", "dark"]) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, colorScheme: scheme });
  await page.goto("http://localhost:10473/visual-harness.html");
  await page.getByRole("link", { name: "How does ReAct combine reasoning and acting?" }).first().waitFor();
  await page.screenshot({ path: `${out}/list.${scheme}.png` });
  await page.getByLabel("Subject").selectOption({ label: "AI Agents" });
  await page.getByText("1 conversation").waitFor();
  await page.screenshot({ path: `${out}/filtered.${scheme}.png` });
  await page.getByLabel("Subject").selectOption({ label: "Reinforcement Learning" });
  await page.getByRole("button", { name: /^Date/ }).click();
  await page.getByLabel("From").fill("2026-10-01");
  await page.keyboard.press("Escape");
  await page.getByText("No conversations match these filters").waitFor();
  await page.screenshot({ path: `${out}/no-results.${scheme}.png` });
  await page.getByRole("button", { name: "Clear filters" }).first().click();
  await page.getByPlaceholder("Search titles").fill("SELF-attention");
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${out}/search.${scheme}.png` });
  await page.close();
}
await browser.close();
console.log("ok");
