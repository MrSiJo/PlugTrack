/**
 * screenshots.mjs — capture demo screenshots of PlugTrack for README/docs.
 *
 * Prerequisites (handled by controller, NOT this script):
 *   npx playwright install chromium
 *
 * Usage:
 *   PLUGTRACK_URL=http://localhost:5173 \
 *   PLUGTRACK_USER=demo \
 *   PLUGTRACK_PASS=demo-plugtrack \
 *   node scripts/screenshots.mjs
 *
 * Env vars:
 *   PLUGTRACK_URL   Base URL of the running PlugTrack UI (default: http://localhost:5173)
 *   PLUGTRACK_USER  Login username (default: demo)
 *   PLUGTRACK_PASS  Login password (default: demo-plugtrack)
 *
 * Output:
 *   ../../assets/screenshots/*.png  (2× scale, 1440×900 viewport)
 */

import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

const BASE_URL = process.env.PLUGTRACK_URL ?? "http://localhost:5173";
const USERNAME = process.env.PLUGTRACK_USER ?? "demo";
const PASSWORD = process.env.PLUGTRACK_PASS ?? "demo-plugtrack";

const OUT_DIR = resolve(__dirname, "../../assets/screenshots");

const VIEWPORT = { width: 1440, height: 900 };
const SCALE = 2;

/** Pages to screenshot in order. */
const STATIC_PAGES = [
  { path: "/dashboard",  file: "dashboard.png",  settle: 2000 },
  { path: "/sessions",   file: "sessions.png",   settle: 1500 },
  { path: "/insights",   file: "insights.png",   settle: 2500 },
  { path: "/planner",    file: "planner.png",    settle: 2000 },
  { path: "/locations",  file: "locations.png",  settle: 6000 },
  { path: "/cars",       file: "cars.png",       settle: 1500 },
  { path: "/admin",      file: "admin.png",      settle: 1500 },
];

async function main() {
  await mkdir(OUT_DIR, { recursive: true });

  // The backend may have COOKIE_SECURE=true which prevents Secure cookies
  // over plain HTTP.  The flag below lets Chromium store them anyway —
  // screenshot-only workaround; not a deployment recommendation.
  const browser = await chromium.launch({
    headless: true,
    args: [`--unsafely-treat-insecure-origin-as-secure=${BASE_URL}`],
  });

  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: SCALE,
  });

  const page = await context.newPage();

  // ---- Login via the JSON API (cookie-based) ----
  // PlugTrack uses a double-submit CSRF cookie: the server sets `plugtrack_csrf`
  // on any response, and mutating requests (incl. login) must echo it in the
  // `X-CSRF-Token` header. So we GET once to receive the cookie, then send it back.
  console.log(`Logging in to ${BASE_URL} as ${USERNAME}…`);
  // `/api/health` is auth-exempt and a safe GET, so the CSRF middleware
  // issues the `plugtrack_csrf` cookie on its response (auth-gated paths 401
  // before CSRF runs, so they don't).
  await context.request.get(`${BASE_URL}/api/health`).catch(() => {});
  const preCookies = await context.cookies();
  const csrf = preCookies.find((c) => c.name === "plugtrack_csrf")?.value;
  const loginResp = await context.request.post(`${BASE_URL}/api/auth/login`, {
    data: { username: USERNAME, password: PASSWORD },
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
  });

  if (!loginResp.ok()) {
    const body = await loginResp.text();
    throw new Error(`Login failed (${loginResp.status()}): ${body}`);
  }
  const cookies = await context.cookies();
  console.log(`  auth ok — ${cookies.length} cookie(s) set`);

  // ---- Static pages ----
  for (const { path, file, settle } of STATIC_PAGES) {
    const url = `${BASE_URL}${path}`;
    process.stdout.write(`  ${path.padEnd(14)} → ${file} … `);
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(settle);
    await page.screenshot({ path: resolve(OUT_DIR, file), fullPage: false });
    console.log("ok");
  }

  // ---- Session detail — resolve a session id with a power_curve ----
  await screenshotSessionDetail(context, page, BASE_URL, OUT_DIR);

  // ---- Car detail ----
  await screenshotCarDetail(page, BASE_URL, OUT_DIR);

  await browser.close();
  console.log(`\nDone. Screenshots saved to ${OUT_DIR}`);
}

/**
 * GET /api/sessions, find a session with a non-null power_curve (or fall back
 * to the first session), then screenshot /sessions/{id}.
 */
async function screenshotSessionDetail(context, page, baseUrl, outDir) {
  process.stdout.write(`  /sessions/:id      → session-detail.png … `);
  try {
    const resp = await context.request.get(`${baseUrl}/api/sessions`, {
      params: { limit: 50 },
    });
    if (!resp.ok()) {
      console.log(`SKIP (sessions API returned ${resp.status()})`);
      return;
    }
    const data = await resp.json();
    // API may return { sessions: [...] } or [...] directly
    const list = Array.isArray(data) ? data : (data.sessions ?? data.items ?? []);

    if (!list.length) {
      console.log("SKIP (no sessions found)");
      return;
    }

    // Prefer a session that has a power_curve
    const withCurve = list.find((s) => s.power_curve != null && s.power_curve !== undefined);
    const target = withCurve ?? list[0];
    const id = target.id;

    await page.goto(`${baseUrl}/sessions/${id}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2500);
    await page.screenshot({ path: resolve(outDir, "session-detail.png"), fullPage: false });
    console.log(`ok (id=${id}${withCurve ? ", has curve" : ""})`);
  } catch (err) {
    console.log(`SKIP (${err.message})`);
  }
}

/**
 * Screenshot /cars/1 (first car, assumed id=1 in a fresh demo seed).
 */
async function screenshotCarDetail(page, baseUrl, outDir) {
  process.stdout.write(`  /cars/1            → car-detail.png … `);
  try {
    await page.goto(`${baseUrl}/cars/1`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);
    await page.screenshot({ path: resolve(outDir, "car-detail.png"), fullPage: false });
    console.log("ok");
  } catch (err) {
    console.log(`SKIP (${err.message})`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
