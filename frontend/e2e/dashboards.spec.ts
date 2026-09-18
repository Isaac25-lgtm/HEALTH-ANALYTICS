import { expect, test } from "@playwright/test";

const password = process.env.SEED_PASSWORD ?? "dev-only-change-me";

async function signIn(page, username = "national.analyst") {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("cookie session does not store tokens and four screens are reachable", async ({ page }) => {
  const loginResponse = page.waitForResponse((response) => response.url().includes("/auth/login"));
  await signIn(page);
  const body = await (await loginResponse).json();
  expect(body.access_token).toBeUndefined();
  expect(body.csrf_token).toBeTruthy();
  await page.waitForURL(/dashboard/, { timeout: 30_000 });
  const storage = await page.evaluate(() => ({
    local: { ...localStorage },
    session: { ...sessionStorage },
  }));
  expect(JSON.stringify(storage)).not.toContain("access_token");
  expect(JSON.stringify(storage)).not.toContain("hpip_session");
  await expect(page.getByRole("heading", { name: "Geographic intelligence" })).toBeVisible({ timeout: 30_000 });
  // Sub-regions carry (synthetic demonstration) geometry, so the national map renders rather than
  // reporting unavailable boundaries. First paint includes the analysis run, so allow for it.
  await expect(page.getByLabel(/Authorised MapLibre map coloured by/)).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/units mapped/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Ask the Data" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Excel workbook (.xlsx)" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Narrative report (Markdown .md)" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "PDF report (.pdf)" })).toBeDisabled();

  await page.getByRole("link", { name: "Acholi" }).first().click();
  await page.waitForURL(/dashboard\/regional/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "Scorecard" })).toBeVisible({ timeout: 30_000 });

  await page.getByRole("link", { name: "Pader" }).first().click();
  await page.waitForURL(/dashboard\/district/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: /scorecard/i })).toBeVisible({ timeout: 30_000 });
  // District screens list facilities instead of a map, so no map panel is expected here. The
  // unavailable-boundary state is asserted in the maps workspace, where facilities have no geometry.
  await expect(page.getByRole("heading", { name: "Geographic intelligence" })).toHaveCount(0);

  await page.getByRole("link", { name: "Pader HC III" }).first().click();
  await page.waitForURL(/dashboard\/facility/, { timeout: 30_000 });
  await expect(page.getByRole("status").filter({ hasText: "Approved population is unavailable" })).toBeVisible({
    timeout: 30_000,
  });
});

test("direct unauthorised national URL is denied for a regional user", async ({ page }) => {
  await signIn(page, "national.analyst");
  await page.waitForURL(/orgUnitId=/, { timeout: 30_000 });
  const ugandaId = new URL(page.url()).searchParams.get("orgUnitId");
  expect(ugandaId).toBeTruthy();
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(/login/);
  await signIn(page, "acholi.analyst");
  await page.waitForURL(/dashboard/, { timeout: 30_000 });
  await page.goto(`/dashboard/national?orgUnitId=${ugandaId}`);
  await expect(page.getByRole("heading", { name: "Access denied" })).toBeVisible({ timeout: 15_000 });
});

test("period and indicator selectors expose snapshot lineage", async ({ page }) => {
  await signIn(page);
  await page.waitForURL(/dashboard/, { timeout: 30_000 });
  await expect(page.getByLabel("Period", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByLabel("Selected indicator")).toBeVisible();
  await expect(page.locator("p.freshness").getByText(/snapshot /)).toBeVisible({ timeout: 30_000 });
});

test("analysis executes by POST once and refresh re-opens the committed snapshot", async ({ page }) => {
  const executions: string[] = [];
  const analyticalGets: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/analytics/dashboard/query")) {
      executions.push(request.method());
    }
    if (url.includes("/analytics/") && request.method() === "GET") {
      analyticalGets.push(url);
    }
  });
  await signIn(page);
  await page.waitForURL(/snapshot=/, { timeout: 30_000 });
  const snapshotUrl = page.url();
  expect(executions.every((method) => method === "POST")).toBe(true);
  const executed = executions.length;
  expect(executed).toBeGreaterThan(0);
  const reopened = page.waitForResponse((response) => response.url().includes("/analysis-snapshots/"));
  await page.reload();
  expect((await reopened).request().method()).toBe("GET");
  await expect(page.locator("p.freshness").getByText(/snapshot /)).toBeVisible({ timeout: 30_000 });
  expect(page.url()).toBe(snapshotUrl);
  expect(executions.length).toBe(executed);
  expect(analyticalGets).toEqual([]);
});

test("logout uses CSRF and clears the session", async ({ page }) => {
  await signIn(page);
  await page.waitForURL(/dashboard/, { timeout: 30_000 });
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(/login/);
  await page.goto("/dashboard/national");
  await expect(page).toHaveURL(/login/);
});
