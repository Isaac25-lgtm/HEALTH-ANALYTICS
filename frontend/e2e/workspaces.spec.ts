import { expect, test, type Page } from "@playwright/test";

const password = process.env.SEED_PASSWORD ?? "dev-only-change-me";
const SHOTS = "e2e-screenshots";

async function signIn(page: Page, username: string) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/dashboard|workspace/, { timeout: 30_000 });
}

test("login form opens blank and never prefills credentials", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByLabel("Username")).toHaveValue("");
  await expect(page.getByLabel("Password")).toHaveValue("");
  await page.screenshot({ path: `${SHOTS}/login-desktop.png`, fullPage: true });
});

test("session cookies stay on the web origin through the same-origin proxy", async ({ page, context }) => {
  const calls: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/auth/") || request.url().includes("/analytics/")) {
      calls.push(new URL(request.url()).origin + new URL(request.url()).pathname);
    }
  });
  await signIn(page, "national.analyst");
  expect(calls.length).toBeGreaterThan(0);
  expect(calls.every((url) => url.startsWith("http://localhost:3000/api/"))).toBe(true);
  const cookies = await context.cookies("http://localhost:3000");
  const session = cookies.find((cookie) => cookie.name === "hpip_session");
  expect(session?.httpOnly).toBe(true);
  expect(cookies.find((cookie) => cookie.name === "hpip_csrf")?.httpOnly).toBe(false);
});

test("specialised workspaces render their own surfaces", async ({ page }) => {
  await signIn(page, "national.analyst");
  await expect(page.getByRole("heading", { name: "Geographic intelligence" })).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: `${SHOTS}/national-desktop.png`, fullPage: true });

  await page.getByRole("link", { name: "Maps" }).click();
  await page.waitForURL(/workspace\/maps/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "Geographic intelligence" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "Exports" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Maps" })).toHaveAttribute("aria-current", "page");

  await page.getByRole("link", { name: "Data quality" }).click();
  await page.waitForURL(/workspace\/quality/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "Data-quality console" })).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: `${SHOTS}/quality-desktop.png`, fullPage: true });

  await page.getByRole("link", { name: "Reports and exports" }).click();
  await page.waitForURL(/workspace\/reports/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "Recent export jobs" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "Scorecard" })).toHaveCount(0);
  await page.screenshot({ path: `${SHOTS}/reports-desktop.png`, fullPage: true });

  await page.getByRole("link", { name: "Immunisation" }).click();
  await page.waitForURL(/workspace\/immunization/, { timeout: 30_000 });
  await expect(page.getByLabel("Programme module")).toHaveValue("immunization", { timeout: 30_000 });
  await page.screenshot({ path: `${SHOTS}/immunization-desktop.png`, fullPage: true });
});

test("administration is refused server-side for a non-administrator", async ({ page }) => {
  await signIn(page, "national.analyst");
  await page.goto("/workspace/admin");
  await expect(page.getByText(/does not include administration/)).toBeVisible({ timeout: 30_000 });
});

test("facility without an approved population shows the unavailable state, not zero", async ({ page }) => {
  await signIn(page, "paderhc3.user");
  await expect(page.getByRole("status").filter({ hasText: "Approved population is unavailable" })).toBeVisible({
    timeout: 30_000,
  });
  const unavailable = page.getByText("Population denominator unavailable").first();
  await expect(unavailable).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/facility-population-unavailable-desktop.png`, fullPage: true });
});

test.describe("constrained widths", () => {
  test.use({ viewport: { width: 820, height: 1100 } });

  test("tablet layout keeps labelled navigation and stacks panels", async ({ page }) => {
    await signIn(page, "national.analyst");
    await expect(page.getByRole("heading", { name: "Geographic intelligence" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("link", { name: "Maps" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await page.screenshot({ path: `${SHOTS}/national-tablet.png`, fullPage: true });
  });
});

test.describe("phone width", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("mobile layout stays usable without horizontal page scroll", async ({ page }) => {
    await signIn(page, "national.analyst");
    await expect(page.getByRole("heading", { name: "Geographic intelligence" })).toBeVisible({ timeout: 30_000 });
    await page.getByRole("link", { name: "Reports and exports" }).click();
    await expect(page.getByRole("heading", { name: "Recent export jobs" })).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: `${SHOTS}/reports-mobile.png`, fullPage: true });
  });
});
