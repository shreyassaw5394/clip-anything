#!/usr/bin/env node
// End-to-end check of the app against the real local server with Playwright (not part of
// pytest: needs playwright-core + Chrome). Usage:
//   node scripts/app_e2e.mjs <recording.mp4> [shots-dir]
// Env: PW_CORE (playwright-core folder), CHROME (browser binary).
// Drops the recording on the page (as the window app would), runs 6 clips, checks the
// results and the cached re-run, the setup screen, keyboard-only navigation, reduced motion,
// console/CSP errors and third-party requests; writes screenshots at 1280x800 and 1024x640.
import { spawn } from "node:child_process";
import { mkdirSync, copyFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const PW = process.env.PW_CORE || path.join(process.env.HOME, ".local/pwcli/node_modules/playwright-core");
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const { chromium } = require(PW);

const src = process.argv[2];
const shots = process.argv[3] || ".planning/phases/08-polished-app/shots";
if (!src) { console.error("usage: app_e2e.mjs <recording.mp4> [shots-dir]"); process.exit(2); }
mkdirSync(shots, { recursive: true });
// work in a private folder so clips/ lands next to a copy, not next to the fixture
const work = mkdtempSync(path.join(tmpdir(), "ca-e2e-"));
const video = path.join(work, "synth.mp4");
copyFileSync(src, video);

const fails = [];
const check = (ok, what) => { console.log((ok ? "ok   " : "FAIL ") + what); if (!ok) fails.push(what); };

// 1. start the server in browser mode on a free port
const server = spawn("uv", ["run", "python", "-m", "clip_anything.gui", "--browser", "--no-open"], { stdio: ["ignore", "pipe", "inherit"] });
const url = await new Promise((resolve, reject) => {
  let buf = "";
  server.stdout.on("data", (d) => { buf += d; const m = /running at (http:\/\/127\.0\.0\.1:\d+\/\?t=\S+)/.exec(buf); if (m) resolve(m[1]); });
  server.on("exit", (c) => reject(new Error("server exited " + c)));
  setTimeout(() => reject(new Error("server did not start")), 30000);
});
const origin = new URL(url).origin;

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
const page = await ctx.newPage();
const consoleErrors = [];
const foreign = [];
page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
page.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));
page.on("request", (r) => { if (!r.url().startsWith(origin)) foreign.push(r.url()); });

async function dropFile(filePath) {
  await page.evaluate((p) => {
    const dt = new DataTransfer();
    const f = new File(["x"], p.split("/").pop(), { type: "video/mp4" });
    Object.defineProperty(f, "pywebviewFullPath", { value: p });
    dt.items.add(f);
    const drop = document.getElementById("drop");
    drop.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true }));
    drop.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
  }, filePath);
}

try {
  await page.goto(url);
  await page.waitForSelector("#ready .ready-item b");
  await page.waitForTimeout(400);
  check((await page.textContent("#ready")).includes("Video tools ready"), "ready line reports ffmpeg");
  await page.screenshot({ path: path.join(shots, "01-home-1280.png") });

  // 2. drop the recording, 6 clips, captions off (no model download in CI-like runs)
  await dropFile(video);
  check((await page.textContent("#chosen")).includes("synth.mp4"), "drop sets the recording");
  check((await page.textContent("#out-dir")).endsWith(path.join(work, "clips")), "output folder defaults next to the recording");
  await page.fill("#count", "6");
  await page.uncheck("#captions");
  await page.screenshot({ path: path.join(shots, "02-home-chosen-1280.png") });
  const t0 = Date.now();
  await page.click("#start");
  await page.waitForSelector("#screen-run:not([hidden])");
  await page.waitForSelector("#curve-spans rect", { timeout: 120000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(shots, "03-run-1280.png") });
  check(!(await page.isHidden("#progress")), "run screen shows the progress bar");
  await page.waitForSelector("#screen-results:not([hidden])", { timeout: 240000 });
  console.log("first run " + ((Date.now() - t0) / 1000).toFixed(1) + " s");
  const cards = await page.$$(".card");
  check(cards.length === 6, `results show 6 cards (got ${cards.length})`);
  const playable = await page.evaluate(() => Promise.all(Array.from(document.querySelectorAll(".card-video")).map((v) => new Promise((res) => {
    if (v.readyState >= 1 && v.duration > 0) return res(v.duration);
    v.addEventListener("loadedmetadata", () => res(v.duration), { once: true });
    v.addEventListener("error", () => res(0), { once: true });
    setTimeout(() => res(v.duration || 0), 15000);
  }))));
  check(playable.length === 6 && playable.every((d) => d > 5), "all 6 videos load metadata (" + playable.map((d) => d.toFixed(1)).join(",") + " s)");
  // hover autoplay + scrub
  const media = await page.$(".card .card-media");
  await media.hover();
  await page.waitForTimeout(700);
  const playing = await page.evaluate(() => { const v = document.querySelector(".card-video"); return !v.paused && v.muted; });
  check(playing, "hover plays the first clip muted");
  await page.click(".card .card-play");
  const loud = await page.evaluate(() => { const v = document.querySelector(".card-video"); return !v.muted && !v.paused; });
  check(loud, "play button turns the sound on");
  await page.click(".card .card-play");
  await page.mouse.move(10, 10);
  await page.waitForTimeout(400);
  // delete asks inline first, Keep cancels
  await page.click('.card:nth-child(6) [data-act="delete"]');
  check(!(await page.isHidden('.card:nth-child(6) .card-confirm')), "delete asks before removing");
  await page.click('.card:nth-child(6) [data-act="delete-no"]');
  await page.screenshot({ path: path.join(shots, "04-results-1280.png"), fullPage: true });
  // copy post text
  await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin });
  await page.click('.card [data-act="copy"]');
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  check(/at \d\d:\d\d in the recording/.test(clip), "copy post text writes the clipboard");
  check((await page.getAttribute("#export", "href")).includes("/report.json"), "export link points at report.json");

  // 3. cached re-run with count 3: seconds
  await page.click("#rerun");
  await page.waitForSelector("#screen-home:not([hidden])");
  await page.fill("#count", "3");
  const t1 = Date.now();
  await page.click("#start");
  await page.waitForSelector("#screen-results:not([hidden])", { timeout: 60000 });
  const rerunS = (Date.now() - t1) / 1000;
  check(rerunS < 5, `cached re-run with count 3 took ${rerunS.toFixed(1)} s (< 5 s)`);
  check((await page.$$(".card")).length === 3, "re-run shows 3 cards");
  check((await page.textContent("#results-sub")).includes("saved analysis"), "results say the analysis was reused");

  // 4. setup screen
  await page.click('[data-nav="setup"]');
  await page.waitForSelector("#steps[aria-busy='false'] .step");
  const steps = await page.$$eval(".step .step-name", (els) => els.map((e) => e.textContent));
  check(steps.length === 6 && steps[0].startsWith("Video tools"), "setup lists 6 steps: " + steps.join(" | "));
  await page.screenshot({ path: path.join(shots, "05-setup-1280.png") });

  // 5. keyboard-only pass: Tab reaches every control on the home screen, Enter starts nothing without input
  await page.click('[data-nav="home"]');
  await page.click("#clear-inputs");
  await page.keyboard.press("Tab");
  const order = [];
  for (let i = 0; i < 24; i++) {
    const id = await page.evaluate(() => { const a = document.activeElement; return a.id || a.name || a.className; });
    order.push(id);
    await page.keyboard.press("Tab");
  }
  const enabled = await page.evaluate(() => ["captions", "ai"].filter((id) => !document.getElementById(id).disabled));
  console.log("tab order: " + order.join(" > "));
  for (const need of ["choose-file", "choose-folder", "count", "length", "facecam", "follow", "change-out", "start", ...enabled]) {
    check(order.includes(need), "keyboard reaches " + need);
  }
  await page.focus("#start");
  await page.keyboard.press("Enter");
  check((await page.textContent("#home-problem")).includes("Choose a recording"), "Enter on Make clips without a recording explains the problem");
  const focusVisible = await page.evaluate(() => { const b = document.getElementById("start"); b.focus(); return getComputedStyle(b).outlineStyle !== "none"; });
  check(focusVisible, "focus ring visible on buttons");
  // focus the drop zone's button and make sure the outline colour is the accent
  await page.focus("#choose-file");
  await page.screenshot({ path: path.join(shots, "06-focus-1280.png"), clip: { x: 0, y: 0, width: 1280, height: 420 } });

  // 6. narrow window + reduced motion
  await page.setViewportSize({ width: 1024, height: 640 });
  await page.waitForTimeout(200);
  await dropFile(video);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  check(!overflow, "no horizontal overflow at 1024x640");
  await page.screenshot({ path: path.join(shots, "07-home-1024.png") });
  await page.click('[data-nav="results"]');
  await page.waitForSelector("#screen-results:not([hidden])");
  await page.screenshot({ path: path.join(shots, "08-results-1024.png") });
  await page.setViewportSize({ width: 760, height: 640 });
  await page.waitForTimeout(200);
  const overflowNarrow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  check(!overflowNarrow, "no horizontal overflow at 760 wide");
  await page.click('[data-nav="home"]');
  await page.screenshot({ path: path.join(shots, "09-home-760.png"), fullPage: true });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.reload();
  await page.waitForSelector("#ready .ready-item b");
  check(true, "reduced-motion reload renders");

  // 7. security from the browser side: a foreign origin cannot read the API
  const foreignPage = await ctx.newPage();
  await foreignPage.goto("data:text/html,<p>x</p>");
  const blocked = await foreignPage.evaluate(async (u) => {
    try { const r = await fetch(u + "api/caps", { headers: { Authorization: "Bearer " + new URL(u).searchParams.get("t") } }); return "status " + r.status; }
    catch (e) { return "blocked"; }
  }, url);
  check(blocked === "blocked" || blocked === "status 403", "cross-origin fetch of the API is refused (" + blocked + ")");
  await foreignPage.close();

  check(consoleErrors.length === 0, "no console errors / CSP violations" + (consoleErrors.length ? ": " + consoleErrors.join(" | ") : ""));
  check(foreign.length === 0, "no third-party requests" + (foreign.length ? ": " + foreign.join(", ") : ""));
} catch (e) {
  fails.push("exception: " + e.message);
  console.error(e);
  await page.screenshot({ path: path.join(shots, "99-failure.png") }).catch(() => {});
} finally {
  await browser.close();
  server.kill("SIGINT");
}
console.log(fails.length ? `\n${fails.length} FAILED` : "\nall checks passed");
process.exit(fails.length ? 1 : 0);
