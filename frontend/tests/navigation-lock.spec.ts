import { expect, test } from "@playwright/test";

test("active review keeps app navigation available", async ({ page }) => {
  await page.route("**/api/v1/runs/test-run/events?after=*", (route) => route.fulfill({ json: { items: [] } }));
  await page.route("**/api/v1/runs/test-run", (route) => route.fulfill({ json: {
    id: "test-run", review_id: "test-review", status: "running", step_count: 3,
    batch_count: 1, processed: 1, remaining: 1, max_batches: 20,
    max_turns: 120, error_code: null, cooldown_until: null,
    call_counts: {}, usage: { calls: 2 }, reference_assessments: {},
  } }));

  await page.goto("/runs/test-run");
  await expect(page.getByTestId("run-status")).toHaveText("running");
  const navigation=page.getByRole("navigation",{name:"Điều hướng chính"});
  await expect(navigation.getByRole("link",{name:"Tổng quan"})).toBeVisible();
  await expect(navigation.getByRole("link",{name:"Thư viện paper"})).toBeVisible();
  await expect(navigation.getByRole("link",{name:"Rubric đánh giá"})).toBeVisible();
  await expect(navigation.getByRole("link",{name:"Bản review"})).toBeVisible();
  await navigation.getByRole("link",{name:"Thư viện paper"}).click();
  await expect(page).toHaveURL(/\/papers$/);
});

test("rate limit wait shows a live countdown and backend heartbeat", async ({ page }) => {
  const cooldown = new Date(Date.now() + 65_000).toISOString();
  await page.route("**/api/v1/runs/waiting-run/events?after=*", (route) => route.fulfill({
    json: { items: [{
      id: "event-1", sequence: 1, agent: "harness", action: "provider_cooldown",
      tool: null, permission_result: null, input_summary: "",
      output_summary: "Groq limit reached; resuming in 300s",
      payload: { retry_after_seconds: 300, cooldown_until: cooldown },
      timestamp: new Date(Date.now() - 235_000).toISOString(),
    }] },
  }));
  await page.route("**/api/v1/runs/waiting-run", (route) => route.fulfill({ json: {
    id: "waiting-run", review_id: "test-review", status: "running", step_count: 26,
    batch_count: 7, processed: 7, remaining: 2, max_batches: 20,
    max_turns: 120, error_code: null, cooldown_until: cooldown,
    call_counts: {}, usage: { calls: 76 }, reference_assessments: {},
  } }));

  await page.goto("/runs/waiting-run");
  await expect(page.getByTestId("run-status")).toHaveText("waiting");
  await expect(page.getByTestId("cooldown-countdown")).toContainText(/Còn 01:0[0-5]/);
  await expect(page.getByTestId("run-heartbeat")).toContainText("Kết nối backend: hoạt động");
  await expect(page.getByTestId("last-provider-attempt")).toContainText("Lần thử Groq gần nhất");
});
