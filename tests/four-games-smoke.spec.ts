import { test, expect } from "@playwright/test";

const BASE = process.env.MULLM_URL || "https://127.0.0.1:8100";

const games = [
  { path: "/code/ready/culinary-divinity.html", title: "Culinary Divinity" },
  { path: "/code/ready/isometric-fortress.html", title: "Isometric Fortress" },
  { path: "/code/ready/viking-voyage.html", title: "Viking Voyage" },
  { path: "/code/ready/forge-empires.html", title: "Forge" },
];

for (const g of games) {
  test(`${g.title} loads without console errors`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(`console.error: ${msg.text()}`);
    });
    await page.goto(BASE + g.path, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);
    expect(errors, `Errors in ${g.title}:\n${errors.join("\n")}`).toEqual([]);
    const html = await page.content();
    expect(html.toLowerCase()).toContain(g.title.toLowerCase().split(" ")[0]);
  });
}
