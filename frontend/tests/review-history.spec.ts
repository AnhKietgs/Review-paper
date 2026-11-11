import { expect, test } from "@playwright/test";

test("history links completed revisions to their own runs", async ({ page }) => {
  const rows = [
    { id: "complete", revision: 1, status: "completed", latest_run_id: "run-one" },
    { id: "approved", revision: 2, status: "approved", latest_run_id: "run-two" },
    { id: "draft", revision: 3, status: "draft", latest_run_id: "run-three" },
    { id: "legacy", revision: 4, status: "completed", latest_run_id: null },
    { id: "failed", revision: 5, status: "failed", latest_run_id: "run-five" },
  ].map(row => ({ ...row, paper_id: "paper", findings: [] }));
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    const items = path.endsWith("/reviews") ? rows : [];
    return route.fulfill({ json: path.endsWith("/runtime")
      ? { llm_mode: "fixture" }
      : { items, total: items.length, limit: 20, offset: 0 } });
  });
  await page.goto("/reviews");
  const links = page.getByRole("link", { name: /Xem tiến trình revision/ });
  await expect(links).toHaveCount(2);
  await expect(links.nth(0)).toHaveAttribute("href", "/runs/run-one");
  await expect(links.nth(1)).toHaveAttribute("href", "/runs/run-two");
  await links.nth(0).click();
  await expect(page).toHaveURL(/\/runs\/run-one$/);
});
