import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

const password = process.env.SEED_PASSWORD ?? "dev-only-change-me";

test("login, CSRF-protected export POST and file download all flow through the same-origin proxy", async ({
  page,
  context,
}) => {
  const apiOrigins = new Set<string>();
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/") || /:(8000|8010)$/.test(url.host)) {
      apiOrigins.add(url.origin);
    }
  });

  await page.goto("/login");
  await page.getByLabel("Username").fill("national.analyst");
  await page.getByLabel("Password").fill(password);
  const login = page.waitForResponse((response) => response.url().endsWith("/api/auth/login"));
  await page.getByRole("button", { name: "Sign in" }).click();
  expect((await login).status()).toBe(200);
  await page.waitForURL(/dashboard|workspace/, { timeout: 30_000 });
  const cookies = await context.cookies("http://localhost:3000");
  const csrfCookie = cookies.find((cookie) => cookie.name === "hpip_csrf");
  expect(cookies.find((cookie) => cookie.name === "hpip_session")?.httpOnly).toBe(true);
  expect(csrfCookie?.value).toBeTruthy();

  await page.goto("/workspace/reports");
  const excel = page.getByRole("button", { name: /Excel workbook/ });
  await expect(excel).toBeEnabled({ timeout: 45_000 });

  const exportRequest = page.waitForRequest(
    (request) => request.method() === "POST" && new URL(request.url()).pathname === "/api/exports/excel",
  );
  const downloadRequest = page.waitForRequest(
    (request) => request.method() === "POST" && /\/api\/exports\/jobs\/[^/]+\/download$/.test(request.url()),
    { timeout: 60_000 },
  );
  const download = page.waitForEvent("download", { timeout: 60_000 });
  await excel.click();

  const created = await exportRequest;
  expect(created.headers()["x-csrf-token"]).toBe(csrfCookie?.value);
  const createdResponse = await created.response();
  expect(createdResponse?.status()).toBe(202);

  const fetched = await downloadRequest;
  expect(fetched.headers()["x-csrf-token"]).toBe(csrfCookie?.value);
  expect((await fetched.response())?.status()).toBe(200);

  const file = await download;
  expect(file.suggestedFilename()).toMatch(/\.xlsx$/);
  const saved = test.info().outputPath(file.suggestedFilename());
  await file.saveAs(saved);
  const bytes = readFileSync(saved);
  expect(bytes.length).toBeGreaterThan(1000);
  // An .xlsx file is a ZIP container.
  expect(bytes.subarray(0, 2).toString("latin1")).toBe("PK");

  // The browser only ever spoke to the web origin.
  expect([...apiOrigins]).toEqual(["http://localhost:3000"]);
});
