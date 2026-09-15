import { expect, test, type Page } from "@playwright/test";

/**
 * Objective visual and structural gates for the dashboard layout, measured against the seeded
 * synthetic e2e fixtures. Acceptance screenshots are written to the tracked evidence folder.
 */
const password = process.env.SEED_PASSWORD ?? "dev-only-change-me";
// Ordinary runs write to ignored test output. Tracked acceptance evidence changes only when explicitly
// requested with UPDATE_VISUAL_EVIDENCE=1, so a normal run never dirties the working tree.
const EVIDENCE =
  process.env.UPDATE_VISUAL_EVIDENCE === "1" ? "../docs/evidence/screenshots" : "test-results/visual-evidence";

/** Deterministic screenshots: volatile identifiers and timestamps are masked, motion is disabled. */
async function evidence(page: Page, name: string) {
  await page.screenshot({
    path: `${EVIDENCE}/${name}`,
    animations: "disabled",
    caret: "hide",
    mask: [page.locator("[data-volatile]")],
    maskColor: "#dfe8f2",
  });
}
const DESKTOP = { width: 1680, height: 945 };
const MAX_DESKTOP_HEIGHT = Math.round(DESKTOP.height * 1.5);

async function signIn(page: Page, username: string, landing: RegExp) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(landing, { timeout: 30_000 });
  await page.waitForURL(/snapshot=/, { timeout: 30_000 });
}

async function layoutMetrics(page: Page) {
  return page.evaluate(() => {
    const doc = document.documentElement;
    const small: string[] = [];
    const walker = document.querySelectorAll("main p, main td, main th, main li, main label, main button, main a, main span");
    walker.forEach((node) => {
      const element = node as HTMLElement;
      if (element.closest("svg, [aria-hidden='true'], .sr-only") || !element.textContent?.trim()) {
        return;
      }
      const rect = element.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) {
        return;
      }
      const size = parseFloat(getComputedStyle(element).fontSize);
      if (size < 12) {
        small.push(`${element.tagName.toLowerCase()}.${element.className}: ${size}px`);
      }
    });
    return {
      overflow: doc.scrollWidth - window.innerWidth,
      height: doc.scrollHeight,
      smallText: small.slice(0, 10),
    };
  });
}

async function bottomOf(page: Page, selector: string) {
  const box = await page.locator(selector).first().boundingBox();
  expect(box, `${selector} is rendered`).not.toBeNull();
  return { top: box!.y, bottom: box!.y + box!.height };
}

test.describe("desktop 1680x945", () => {
  test.use({ viewport: DESKTOP });

  test("national overview fits about one screen with key panels above the fold", async ({ page }) => {
    await signIn(page, "national.analyst", /dashboard\/national/);
    await expect(page.getByRole("heading", { name: "Geographic intelligence" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("heading", { name: "Priority insights" })).toBeVisible();
    await expect(page.getByRole("heading", { name: /scorecard/i }).first()).toBeVisible();
    const metrics = await layoutMetrics(page);
    expect(metrics.overflow).toBeLessThanOrEqual(1);
    expect(metrics.height).toBeLessThanOrEqual(MAX_DESKTOP_HEIGHT);
    expect(metrics.smallText).toEqual([]);
    const kpis = await bottomOf(page, ".kpi-strip");
    expect(kpis.bottom).toBeLessThanOrEqual(DESKTOP.height);
    for (const selector of [".area-map", ".area-insights", ".area-scorecard"]) {
      const panel = await bottomOf(page, selector);
      expect(panel.bottom, `${selector} ends above the fold`).toBeLessThanOrEqual(DESKTOP.height);
    }
    expect(await page.locator(".kpi-strip .kpi-card").count()).toBeLessThanOrEqual(6);
    // Long lists are bounded: the insight panel shows a short list with a path to all of them.
    expect(await page.locator(".area-insights .insight").count()).toBeLessThanOrEqual(4);
    await expect(page.locator(".area-insights").getByRole("link", { name: /View all/ })).toBeVisible();
    await evidence(page, "national-desktop-1680x945.png");
  });

  test("regional, district and facility views keep the same density", async ({ page }) => {
    await signIn(page, "acholi.analyst", /dashboard\/regional/);
    await expect(page.getByRole("heading", { name: "Unit scorecard" })).toBeVisible({ timeout: 30_000 });
    let metrics = await layoutMetrics(page);
    expect(metrics.overflow).toBeLessThanOrEqual(1);
    expect(metrics.height).toBeLessThanOrEqual(MAX_DESKTOP_HEIGHT);
    await evidence(page, "regional-desktop-1680x945.png");

    await page.getByRole("link", { name: "Pader" }).first().click();
    await page.waitForURL(/dashboard\/district.*snapshot=/, { timeout: 30_000 });
    await expect(page.getByRole("heading", { name: "Facility performance scorecard" })).toBeVisible({ timeout: 30_000 });
    metrics = await layoutMetrics(page);
    expect(metrics.overflow).toBeLessThanOrEqual(1);
    expect(metrics.height).toBeLessThanOrEqual(MAX_DESKTOP_HEIGHT);
    const primary = await bottomOf(page, ".area-primary");
    expect(primary.bottom).toBeLessThanOrEqual(DESKTOP.height);
    await evidence(page, "district-desktop-1680x945.png");
  });

  test("facility profile shows the missing population inside its panels", async ({ page }) => {
    await signIn(page, "paderhc3.user", /dashboard\/facility/);
    await expect(page.getByRole("heading", { name: "Indicator scorecard" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("status").filter({ hasText: "Approved population is unavailable" })).toBeVisible();
    const metrics = await layoutMetrics(page);
    expect(metrics.overflow).toBeLessThanOrEqual(1);
    expect(metrics.height).toBeLessThanOrEqual(MAX_DESKTOP_HEIGHT);
    await expect(page.locator(".kpi-strip").getByText("Population denominator unavailable").first()).toBeVisible();
    await evidence(page, "facility-desktop-1680x945.png");
  });

  test("MPDSR workspace is its own composition", async ({ page }) => {
    await signIn(page, "mpdsr.analyst", /dashboard/);
    await page.goto("/workspace/mpdsr");
    await page.waitForURL(/workspace\/mpdsr.*snapshot=/, { timeout: 30_000 });
    await expect(page.getByRole("heading", { name: "Notification and review scorecard" })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByRole("heading", { name: "Cause patterns and reviews" })).toBeVisible();
    const metrics = await layoutMetrics(page);
    expect(metrics.overflow).toBeLessThanOrEqual(1);
    expect(metrics.height).toBeLessThanOrEqual(MAX_DESKTOP_HEIGHT);
    await evidence(page, "mpdsr-desktop-1680x945.png");
  });
});

test.describe("tablet 820x1180", () => {
  test.use({ viewport: { width: 820, height: 1180 } });

  test("readable navigation and stacked panels without horizontal scroll", async ({ page }) => {
    await signIn(page, "national.analyst", /dashboard\/national/);
    await expect(page.getByRole("heading", { name: "Geographic intelligence" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("link", { name: "Maps" })).toBeVisible();
    const metrics = await layoutMetrics(page);
    expect(metrics.overflow).toBeLessThanOrEqual(1);
    expect(metrics.smallText).toEqual([]);
    await evidence(page, "national-tablet-820x1180.png");
  });
});

test.describe("mobile 390x844", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("stacked layout, usable filters and locally scrolling tables", async ({ page }) => {
    await signIn(page, "national.analyst", /dashboard\/national/);
    await expect(page.getByRole("heading", { name: "Geographic intelligence" })).toBeVisible({ timeout: 30_000 });
    const metrics = await layoutMetrics(page);
    expect(metrics.overflow).toBeLessThanOrEqual(1);
    for (const label of ["Period", "Comparison period", "Geography", "Programme module", "Selected indicator"]) {
      const box = await page.getByLabel(label, { exact: true }).boundingBox();
      expect(box, label).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(390 + 0.5);
      expect(box!.height).toBeGreaterThanOrEqual(28);
    }
    const apply = await page.getByRole("button", { name: "Apply" }).boundingBox();
    expect(apply!.x + apply!.width).toBeLessThanOrEqual(390 + 0.5);
    // Wide tables scroll inside their own container; the container itself never exceeds the screen.
    const tables = await page.locator(".table-wrap").evaluateAll((nodes) =>
      nodes.map((node) => node.getBoundingClientRect().right),
    );
    expect(tables.length).toBeGreaterThan(0);
    for (const right of tables) {
      expect(right).toBeLessThanOrEqual(390 + 0.5);
    }
    await evidence(page, "national-mobile-390x844.png");
  });
});

test.describe("every workspace at every breakpoint keeps its panels on screen", () => {
  for (const viewport of [
    { width: 1680, height: 945 },
    { width: 820, height: 1180 },
    { width: 390, height: 844 },
  ]) {
    test(`no zero-width panels or horizontal overflow at ${viewport.width}x${viewport.height}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await signIn(page, "national.analyst", /dashboard\/national/);
      for (const slug of ["anc", "intrapartum", "immunization", "mpdsr", "maps", "trends", "quality", "reports", "ai"]) {
        await page.goto(`/workspace/${slug}`);
        await page.waitForURL(new RegExp(`workspace/${slug}.*snapshot=`), { timeout: 30_000 });
        await expect(page.locator(".layout .panel").first()).toBeVisible({ timeout: 30_000 });
        const panels = await page.locator(".layout .panel").evaluateAll((nodes) =>
          nodes.map((node) => {
            const rect = node.getBoundingClientRect();
            return { width: rect.width, height: rect.height, heading: node.querySelector("h2")?.textContent ?? "" };
          }),
        );
        for (const panel of panels) {
          expect(panel.width, `${slug}: ${panel.heading} width`).toBeGreaterThan(200);
          expect(panel.height, `${slug}: ${panel.heading} height`).toBeGreaterThan(80);
        }
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(overflow, `${slug} horizontal overflow`).toBeLessThanOrEqual(1);
      }
    });
  }
});
