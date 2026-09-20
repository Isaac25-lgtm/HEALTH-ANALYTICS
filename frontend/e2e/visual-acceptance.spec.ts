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
  // A map lazy-loads and paints on its own canvas after the snapshot renders. Wait for it to
  // report itself drawn so the evidence shows the cohort, not an empty or half-loaded canvas.
  if (await page.getByRole("heading", { name: "Geographic intelligence" }).count()) {
    await page
      .locator("[data-map-ready='true']")
      .first()
      .waitFor({ state: "attached", timeout: 30_000 });
  }
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

test.describe("reference layout contract at 1680x945", () => {
  test.use({ viewport: DESKTOP });

  test("header, navigation, filter strip and panel placement follow the reference anatomy", async ({ page }) => {
    await signIn(page, "national.analyst", /dashboard\/national/);
    await expect(page.getByRole("heading", { name: "Geographic intelligence" })).toBeVisible({ timeout: 30_000 });

    // Sidebar: reserved crest slot, two labelled navigation groups, an icon on every item.
    await expect(page.getByRole("img", { name: "Reserved for the approved Ministry of Health crest" })).toBeVisible();
    const geography = page.getByRole("navigation", { name: "Geography screens" });
    await expect(geography.getByRole("link")).toHaveText([
      "National",
      "Regional",
      "District facilities",
      "Sub-county facilities",
      "Facility",
    ]);
    const workspaces = page.getByRole("navigation", { name: "Programme workspaces" });
    await expect(workspaces.getByRole("link")).toHaveCount(9);
    for (const nav of [geography, workspaces]) {
      const links = await nav.getByRole("link").count();
      await expect(nav.locator("a svg[data-icon]")).toHaveCount(links);
    }
    const active = geography.locator('a[aria-current="page"]');
    await expect(active).toHaveText("National");
    await expect(active.locator('svg[data-icon="national"]')).toBeVisible();

    // Header: title and subtitle left; alerts, profile, sign-out and tagline right.
    const banner = page.getByRole("banner");
    await expect(banner.getByRole("heading", { level: 1, name: "Health Performance Intelligence" })).toBeVisible();
    await expect(banner.locator(".topbar-subtitle")).toContainText("National overview");
    const alerts = banner.getByRole("link", { name: /Data-quality alerts: \d+ open flag/ });
    await expect(alerts).toHaveAttribute("href", /\/workspace\/quality/);
    await expect(banner.getByRole("button", { name: "Sign out" })).toBeVisible();
    await expect(banner.locator(".topbar-tagline")).toBeVisible();
    const title = await banner.getByRole("heading", { level: 1 }).boundingBox();
    const user = await banner.locator(".topbar-user").boundingBox();
    expect(title!.x + title!.width).toBeLessThan(user!.x);
    expect(title!.height).toBeGreaterThanOrEqual(30);

    // Filter strip: scope and role chips, five labelled selects with icons, apply, authorised search.
    const strip = page.getByRole("form", { name: "Scope and period" });
    await expect(strip.locator('svg[data-icon="scope"]')).toBeVisible();
    await expect(strip.locator('svg[data-icon="role"]')).toBeVisible();
    for (const icon of ["calendar", "compare", "pin", "programme", "indicator"]) {
      await expect(strip.locator(`.filter-field svg[data-icon="${icon}"]`)).toBeVisible();
    }
    await expect(strip.getByRole("combobox", { name: "Search authorised places and indicators" })).toBeVisible();
    const stripBox = await strip.boundingBox();
    expect(stripBox!.height).toBeLessThanOrEqual(90);

    // Panels: KPI strip above a three-panel main row, lower analytical row, downloads last.
    const box = async (selector: string) => (await page.locator(selector).first().boundingBox())!;
    const kpis = await box(".kpi-strip");
    const [map, insights, scorecard] = [await box(".area-map"), await box(".area-insights"), await box(".area-scorecard")];
    const [trend, ranking, ask] = [await box(".area-trend"), await box(".area-ranking"), await box(".area-ask")];
    const downloads = await box(".downloads-bar");
    expect(await page.locator(".kpi-strip .kpi-card").count()).toBe(6);
    expect(kpis.y + kpis.height).toBeLessThanOrEqual(map.y);
    expect(Math.abs(map.y - insights.y)).toBeLessThan(2);
    expect(Math.abs(insights.y - scorecard.y)).toBeLessThan(2);
    expect(map.x).toBeLessThan(insights.x);
    expect(insights.x).toBeLessThan(scorecard.x);
    expect(trend.y).toBeGreaterThanOrEqual(map.y + map.height);
    expect(trend.x).toBeLessThan(ranking.x);
    expect(ranking.x).toBeLessThan(ask.x);
    expect(downloads.y).toBeGreaterThanOrEqual(ask.y + ask.height);
    expect(downloads.width).toBeGreaterThan(kpis.width - 2);
    for (const [area, icon] of [
      [".area-map", "maps"],
      [".area-insights", "ai"],
      [".area-scorecard", "table"],
      [".area-trend", "trends"],
      [".area-ranking", "chart"],
      [".area-ask", "ai"],
    ] as const) {
      await expect(page.locator(`${area} .panel-head svg[data-icon="${icon}"]`)).toBeVisible();
    }
    await expect(page.locator(".downloads-bar button svg[data-icon]").first()).toBeVisible();
    await expect(page.locator(".kpi-strip .status-pill .status-dot").first()).toBeVisible();
  });

  test("header search returns only authorised places and navigates to them", async ({ page }) => {
    await signIn(page, "national.analyst", /dashboard\/national/);
    const search = page.getByRole("combobox", { name: "Search authorised places and indicators" });
    await search.fill("kitg");
    const option = page.getByRole("option", { name: "Kitgum district" });
    await expect(option).toBeVisible({ timeout: 15_000 });
    await search.press("Enter");
    await page.waitForURL(/dashboard\/district.*orgUnitId=/, { timeout: 30_000 });

    await page.getByRole("button", { name: "Sign out" }).click();
    await page.waitForURL(/login/);
    await signIn(page, "pader.focal", /dashboard/);
    const scoped = page.getByRole("combobox", { name: "Search authorised places and indicators" });
    await scoped.fill("kitgum");
    await expect(page.getByRole("option", { name: "No authorised matches." })).toBeVisible({ timeout: 15_000 });
    await scoped.fill("pader hc");
    await expect(page.getByRole("option", { name: /Pader HC III/ })).toBeVisible({ timeout: 15_000 });
  });
});
