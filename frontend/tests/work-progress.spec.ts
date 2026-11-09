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

test("review budget stop explains partial results without prompting a costly restart", async ({ page }) => {
  const run = {
    ...initial, status: "incomplete", error_code: "review_token_budget_exhausted",
    token_budget: { limit: 50000, spent: 48000, remaining: 2000 },
    activity: activity("incomplete"),
  };
  await page.route("**/api/v1/runs/work-run/events?after=*", route => route.fulfill({ json: { items: [] } }));
  await page.route("**/api/v1/runs/work-run", route => route.fulfill({ json: run }));
  await page.goto("/runs/work-run");
  await expect(page.getByTestId("review-token-budget")).toContainText("48.000 / 50.000");
  await expect(page.getByText("Không đủ ngân sách token cho yêu cầu tiếp theo.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Tiếp tục từ checkpoint" })).toHaveCount(0);
  await expect(page.getByText("hãy chạy một revision mới", { exact: false })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Mở bản review →" })).toBeVisible();
});

test("economy policy explains why verification follows reading", async ({ page }) => {
  await page.route("**/api/v1/runs/work-run/events?after=*", route => route.fulfill({ json: { items: [] } }));
  await page.route("**/api/v1/runs/work-run", route => route.fulfill({ json: { ...initial, efficient_review: true } }));
  await page.goto("/runs/work-run");
  await expect(page.getByTestId("review-strategy")).toContainText("kiểm chứng sau khi đọc và đối chiếu xong");
});

test("two phase scientific progress distinguishes extraction from synthesis", async ({ page }) => {
  let run: Run = { ...initial, two_phase_review: true, efficient_review: true,
    activity: { ...activity("extract"), scientific_phase: "extract", work: {
      ...activity("extract").work, scientific: { note_count: 4, synthesized: false },
    } } };
  await page.route("**/api/v1/runs/work-run/events?after=*", route => route.fulfill({ json: { items: [] } }));
  await page.route("**/api/v1/runs/work-run", route => route.fulfill({ json: run }));
  await page.goto("/runs/work-run");
  await expect(page.getByTestId("work-phase")).toHaveText("Đang đọc và trích xuất thông tin");
  await expect(page.getByTestId("scientific-notes-progress")).toContainText("4 ghi chú");
  run = { ...run, activity: { ...run.activity!, phase: "synthesize", scientific_phase: "synthesize" } };
  await expect(page.getByTestId("work-phase")).toHaveText("Đang tổng hợp phản biện khoa học");
});

test("explicit70k continuation preserves recorded spending and uses one resume request", async ({ page }) => {
  let run: Run = { ...initial, status: "incomplete", error_code: "review_token_budget_exhausted",
    token_budget: { limit: 50000, spent: 45917, remaining: 4083 }, activity: activity("incomplete") };
  const requests: unknown[] = [];
  await page.route("**/api/v1/runs/work-run/events?after=*", route => route.fulfill({ json: { items: [] } }));
  await page.route("**/api/v1/runs/work-run", route => route.fulfill({ json: run }));
  await page.route("**/api/v1/runs/work-run/resume", route => {
    requests.push(route.request().postDataJSON());
    run = { ...run, status: "queued", error_code: null,
      token_budget: { limit: 90000, spent: 45917, remaining: 24083 } };
    return route.fulfill({ json: { run_id: "work-run", review_id: "review", status: "queued" } });
  });
  await page.goto("/runs/work-run");
  await page.getByRole("button", { name: "Nâng lên 90.000 token và tiếp tục" }).click();
  await expect(page.getByTestId("review-token-budget")).toContainText("45.917 / 90.000");
  expect(requests).toEqual([{ token_budget: 90000 }]);
  await expect(page.getByRole("button", { name: "Nâng lên 90.000 token và tiếp tục" })).toHaveCount(0);
});

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

test("provider failure keeps subtask progress and offers explicit checkpoint resume", async ({ page }) => {
  await page.route("**/api/v1/runs/work-run/events?after=*", route => route.fulfill({ json: { items: [] } }));
  await page.route("**/api/v1/runs/work-run", route => route.fulfill({ json: {
    ...initial, status: "failed", error_code: "provider_unavailable",
    activity: { ...activity("failed"), source: "checkpoint", work: {
      ...activity("failed").work, token_tasks: { done: 1, total: 3 },
    } },
  } }));
  await page.goto("/runs/work-run");
  await expect(page.getByRole("button", { name: "Tiếp tục từ checkpoint" })).toBeVisible();
  await expect(page.getByTestId("token-work-progress")).toContainText("1 / 3");
  await expect(page.getByText("Chưa hoàn tất được yêu cầu tới Groq.", { exact: false })).toBeVisible();
});
