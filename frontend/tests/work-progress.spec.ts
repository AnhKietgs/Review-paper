import { expect, test } from "@playwright/test";
import type { Run, RunActivity } from "../src/lib/api/types";

function activity(phase: string): RunActivity {
  return {
    phase, resume_action: "repair", agent: "scientific_review", source: "live",
    updated_at: new Date().toISOString(), retry_at: null,
    work: {
      paper_read: { done: 9, total: 9 }, references: { done: 1, total: 2 },
      findings: { total: 10, pending_verification: 3, pending_repairs: 2, repair_attempts: 1 },
      omission_audit: { topics_pending: 4, group_topics: 4, checked_chunks: 2, total_chunks: 9 },
    },
  };
}

const initial: Run = {
  id: "work-run", review_id: "review", status: "running", step_count: 12,
  batch_count: 9, processed: 9, remaining: 0, max_batches: 20, max_turns: 120,
  error_code: null, cooldown_until: null, call_counts: {}, usage: { calls: 16 },
  reference_assessments: {}, activity: activity("analyze"),
};

test("work phases track polling without treating complete reading as a complete review", async ({ page }) => {
  let run = { ...initial, activity: {
    ...activity("analyze"), work: {
      ...activity("analyze").work, token_tasks: { done: 2, total: 5 },
    },
  } } as Run;
  await page.route("**/api/v1/runs/work-run/events?after=*", route => route.fulfill({ json: { items: [] } }));
  await page.route("**/api/v1/runs/work-run", route => route.fulfill({ json: run }));
  await page.goto("/runs/work-run");
  await expect(page.getByTestId("work-phase")).toHaveText("Đang phân tích paper");
  await expect(page.getByTestId("paper-coverage")).toHaveText("9 / 9 đoạn");
  await expect(page.getByText("Đã đọc hết paper chính.", { exact: false })).toBeVisible();
  await expect(page.getByTestId("run-status")).toHaveText("running");
  await expect(page.getByTestId("token-work-progress")).toContainText("2 / 5");
  run = { ...initial, activity: activity("repair") };
  await expect(page.getByTestId("work-phase")).toHaveText("Đang sửa nhận xét");
  run = { ...initial, activity: activity("audit_omission") };
  await expect(page.getByTestId("work-phase")).toHaveText("Đang rà thiếu thông tin");
  await expect(page.getByTestId("omission-progress")).toContainText("2 / 9 đoạn");
  run = { ...initial, status: "completed", activity: { ...activity("completed"), source: "checkpoint" } };
  await expect(page.getByTestId("work-phase")).toHaveText("Review đã hoàn tất");
});

test("quota wait names the paused work and switches back when worker resumes", async ({ page }) => {
  const expired = new Date(Date.now() - 1000).toISOString();
  let run: Run = {
    ...initial, activity: { ...activity("waiting_quota"), retry_at: new Date(Date.now() + 60_000).toISOString() },
  };
  await page.route("**/api/v1/runs/work-run/events?after=*", route => route.fulfill({ json: { items: [] } }));
  await page.route("**/api/v1/runs/work-run", route => route.fulfill({ json: run }));
  await page.goto("/runs/work-run");
  await expect(page.getByTestId("work-phase")).toHaveText("Đang chờ quota Groq");
  await expect(page.getByTestId("run-status")).toHaveText("waiting");
  await expect(page.getByTestId("resume-work")).toContainText("sửa nhận xét");
  await expect(page.getByTestId("cooldown-countdown")).toContainText("trước lần thử tiếp theo");
  run = { ...initial, cooldown_until: expired, activity: activity("repair") };
  await expect(page.getByTestId("work-phase")).toHaveText("Đang sửa nhận xét");
  await expect(page.getByTestId("run-status")).toHaveText("running");
  await expect(page.getByTestId("cooldown-countdown")).toHaveCount(0);
});

test("work counters fit a small screen and retain readable labels", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.route("**/api/v1/runs/work-run/events?after=*", route => route.fulfill({ json: { items: [] } }));
  await page.route("**/api/v1/runs/work-run", route => route.fulfill({ json: { ...initial, activity: activity("audit_omission") } }));
  await page.goto("/runs/work-run");
  await expect(page.getByTestId("omission-progress")).toBeVisible();
  await expect(page.getByRole("progressbar", { name: "Phạm vi đọc paper chính" })).toHaveAttribute("max", "9");
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await page.screenshot({ path: "../tmp/ui-work-progress-mobile.png", fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.screenshot({ path: "../tmp/ui-work-progress-desktop.png", fullPage: true });
});

test("oversized request can be resumed from its saved checkpoint after a fix", async ({ page }) => {
  await page.route("**/api/v1/runs/work-run/events?after=*", route => route.fulfill({ json: { items: [] } }));
  await page.route("**/api/v1/runs/work-run", route => route.fulfill({ json: {
    ...initial, status: "failed", error_code: "quota_request_too_large",
    activity: { ...activity("failed"), source: "checkpoint" },
  } }));
  await page.goto("/runs/work-run");
  await expect(page.getByRole("button", { name: "Tiếp tục từ checkpoint" })).toBeVisible();
});

test("stop review while waiting keeps the review and shows cancelled state", async ({ page }) => {
  let stopped = false;
  await page.route("**/api/v1/runs/work-run/events?after=*", route => route.fulfill({ json: { items: [] } }));
  await page.route("**/api/v1/runs/work-run", route => route.fulfill({ json: stopped ? {
    ...initial, status: "cancelled", error_code: "cancelled_by_user",
    activity: { ...activity("cancelled"), source: "checkpoint" },
  } : { ...initial, activity: { ...activity("waiting_quota"), retry_at: new Date(Date.now() + 60_000).toISOString() } } }));
  await page.route("**/api/v1/runs/work-run/cancel", route => {
    expect(route.request().method()).toBe("POST");
    stopped = true;
    return route.fulfill({ json: { run_id: "work-run", review_id: "review", status: "cancelled" } });
  });
  await page.goto("/runs/work-run");
  await page.getByRole("button", { name: "Dừng review", exact: true }).click();
  await expect(page.getByTestId("run-status")).toHaveText("cancelled");
  await expect(page.getByTestId("work-phase")).toHaveText("Lần chạy đã được hủy");
  await expect(page.getByRole("link", { name: "Mở bản review" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Dừng review", exact: true })).toHaveCount(0);
  await expect(page.getByText("Lần chạy dừng: cancelled_by_user", { exact: false })).toHaveCount(0);
});
