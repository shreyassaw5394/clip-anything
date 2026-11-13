#!/usr/bin/env node
// Records the app in use for the "how to use it" reel. Deterministic: starts the real local
// server, drives it with Playwright and records the page (no screen-recording permission).
// Usage: node launch-video/capture.mjs <recording.mp4> [--wide]
//   default: 1080x1440 with the page zoomed 1.5x (720x960 layout) -> out/raw/app-tall.webm, framed into 9:16 later
//   --wide:  1920x1080 zoomed 1.5x (1280x720 layout) -> out/raw/app-wide.webm
// Playwright records at CSS pixel size whatever the device scale factor is, hence CSS zoom.
// Writes out/raw/<name>.marks.json with the time of each beat so edit.mjs can cut on them.
// Env: PW_CORE (playwright-core folder), CHROME (browser binary).
import { spawn } from "node:child_process";
import { mkdirSync, existsSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const PW = process.env.PW_CORE || path.join(homedir(), ".local/pwcli/node_modules/playwright-core");
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const { chromium } = require(PW);

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..");
const video = process.argv[2];
const wide = process.argv.includes("--wide");
if (!video || !existsSync(video)) { console.error("usage: capture.mjs <recording.mp4> [--wide]"); process.exit(2); }
const rawDir = path.join(here, "out", "raw");
mkdirSync(rawDir, { recursive: true });
const name = wide ? "app-wide" : "app-tall";
const Z = 1.5;
const size = wide ? { width: 1920, height: 1080 } : { width: 1080, height: 1440 };
const viewport = size;

// The home screen lists recent runs from this machine; park that file so the reel shows a first run.
const dataDir = path.join(homedir(), "Library", "Application Support", "clip-anything");
const recent = path.join(dataDir, "recent.json");
const parked = recent + ".reel-parked";
const hadRecent = existsSync(recent);
if (hadRecent) renameSync(recent, parked);
const restore = () => { if (hadRecent && existsSync(parked)) renameSync(parked, recent); };
process.on("exit", restore);
process.on("SIGINT", () => { restore(); process.exit(130); });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const marks = [];
let t0 = 0;
const mark = (what) => { const t = (Date.now() - t0) / 1000; marks.push({ what, t }); console.log(`${t.toFixed(2).padStart(6)}  ${what}`); };

// 1. the real server, browser mode, free port
const server = spawn("uv", ["run", "python", "-m", "clip_anything.gui", "--browser", "--no-open"], { cwd: repo, stdio: ["ignore", "pipe", "inherit"] });
const url = await new Promise((resolve, reject) => {
  let buf = "";
  server.stdout.on("data", (d) => { buf += d; const m = /running at (http:\/\/127\.0\.0\.1:\d+\/\?t=\S+)/.exec(buf); if (m) resolve(m[1]); });
  server.on("exit", (c) => reject(new Error("server exited " + c)));
  setTimeout(() => reject(new Error("server did not start")), 30000);
});

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const ctx = await browser.newContext({
  viewport, deviceScaleFactor: 1, bypassCSP: true, colorScheme: "light", reducedMotion: "no-preference",
  permissions: ["clipboard-read", "clipboard-write"], recordVideo: { dir: rawDir, size },
});
// "Open folder" would open Finder on this machine; answer it here so the UI shows its confirmation.
await ctx.route("**/api/jobs/*/open", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "{\"ok\":true}" }));
const page = await ctx.newPage();
t0 = Date.now();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

// A drawn cursor and a file chip, so the viewer sees the drag and the clicks.
async function overlay() {
  await page.evaluate((Z) => {
    document.documentElement.style.zoom = String(Z);
    const cur = document.createElement("div");
    cur.id = "reel-cursor";
    cur.innerHTML = '<svg width="34" height="40" viewBox="0 0 17 20"><path d="M1 1 L1 15.5 L4.6 12.2 L7.2 18 L9.6 17 L7 11.4 L12 11.4 Z" fill="#111318" stroke="#fff" stroke-width="1.2" stroke-linejoin="round"/></svg>';
    Object.assign(cur.style, { position: "fixed", left: "0", top: "0", zIndex: "9999", pointerEvents: "none", opacity: "0", zoom: String(1 / Z), filter: "drop-shadow(0 2px 3px rgba(0,0,0,.35))", transform: "translate(620px, 900px)", transition: "transform 700ms cubic-bezier(.2,.7,.2,1), opacity 300ms ease" });
    document.body.append(cur);
    const chip = document.createElement("div");
    chip.id = "reel-chip";
    chip.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#111318" stroke-width="2"><rect x="3" y="5" width="18" height="14"/><path d="M3 9h18M7 5v14M17 5v14"/></svg><span></span>';
    Object.assign(chip.style, { position: "fixed", left: "0", top: "0", zIndex: "9998", zoom: String(1 / Z), pointerEvents: "none", opacity: "0", display: "flex", alignItems: "center", gap: "10px", padding: "12px 16px", background: "#fff", border: "1px solid #cfcbc0", boxShadow: "0 12px 28px rgba(0,0,0,.18)", font: "500 15px Barlow, system-ui, sans-serif", color: "#111318", transform: "translate(660px, 960px) rotate(-3deg)", transition: "transform 700ms cubic-bezier(.2,.7,.2,1), opacity 300ms ease" });
    document.body.append(chip);
  }, Z);
}
async function chipText(text) { await page.evaluate((t) => { document.querySelector("#reel-chip span").textContent = t; }, text); }
async function cursorShow(on) { await page.evaluate((o) => { document.getElementById("reel-cursor").style.opacity = o ? "1" : "0"; }, on); }
async function chipShow(on) { await page.evaluate((o) => { document.getElementById("reel-chip").style.opacity = o ? "1" : "0"; }, on); }
async function glide(x, y, ms = 700, withChip = false) {
  await page.evaluate(([x, y, ms, c]) => {
    const cur = document.getElementById("reel-cursor");
    cur.style.transitionDuration = ms + "ms, 300ms";
    cur.style.transform = `translate(${x}px, ${y}px)`;
    if (c) { const chip = document.getElementById("reel-chip"); chip.style.transitionDuration = ms + "ms, 300ms"; chip.style.transform = `translate(${x + 14}px, ${y + 18}px) rotate(-3deg)`; }
  }, [x, y, ms, withChip]);
  await page.mouse.move(x, y, { steps: Math.max(8, Math.round(ms / 40)) });
  await sleep(ms + 80);
}
async function centre(sel) { const b = await page.locator(sel).first().boundingBox(); return { x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2) }; }
async function press(sel, dx = 0) {
  const c = await centre(sel);
  await glide(c.x + dx, c.y, 650);
  await page.mouse.down(); await sleep(140); await page.mouse.up();
}

try {
  await page.goto(url);
  await page.waitForSelector("#ready-dot.ok, #ready-dot.off");
  await overlay();
  await chipText(path.basename(video));
  await page.uncheck("#captions").catch(() => {});
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.mouse.move(640, 900);
  await sleep(400);
  await page.evaluate((home) => {
    const el = document.getElementById("out-dir");
    const tidy = () => { if (el.textContent.startsWith(home)) el.textContent = "~" + el.textContent.slice(home.length); };
    new MutationObserver(tidy).observe(el, { childList: true, characterData: true, subtree: true });
    tidy();
  }, homedir());
  await sleep(1400);
  mark("home");

  // 1. drag the recording in: the chip glides to the drop zone, the border marches, then it lands
  await cursorShow(true); await chipShow(true);
  await sleep(350);
  const drop = await centre("#drop");
  await glide(drop.x - 40, drop.y - 10, 1000, true);
  await page.evaluate(() => {
    const dt = new DataTransfer();
    const d = document.getElementById("drop");
    d.dispatchEvent(new DragEvent("dragenter", { dataTransfer: dt, bubbles: true, cancelable: true }));
    d.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true }));
  });
  mark("dragover");
  await sleep(700);
  await page.evaluate((p) => {
    const dt = new DataTransfer();
    const f = new File(["x"], p.split("/").pop(), { type: "video/mp4" });
    Object.defineProperty(f, "pywebviewFullPath", { value: p });
    dt.items.add(f);
    document.getElementById("drop").dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
  }, video);
  await chipShow(false);
  mark("dropped");
  await page.waitForFunction(() => document.getElementById("drop-meta").textContent && document.getElementById("drop-meta").textContent !== "Reading…", null, { timeout: 20000 });
  mark("chosen");
  await sleep(1700);

  // 2. press Make 10 clips
  await press("#start");
  mark("start");
  await page.waitForSelector("#screen-run:not([hidden])");
  mark("run");
  await cursorShow(false);

  // 3. the run: progress bar + live curve (time-lapsed in the edit)
  await page.waitForSelector("#curve-spans rect", { timeout: 180000 });
  mark("markers");
  await page.waitForSelector("#screen-results:not([hidden])", { timeout: 600000 });
  mark("results");
  await sleep(1500);

  // 4. results: hover-play the best moment
  const media = await centre(".card:first-child .card-media");
  await page.mouse.move(media.x - 200, media.y + 300);
  await page.evaluate(([x, y]) => { const c = document.getElementById("reel-cursor"); c.style.transitionDuration = "0ms"; c.style.transform = `translate(${x}px, ${y}px)`; }, [media.x - 200, media.y + 300]);
  await sleep(60);
  await cursorShow(true);
  await glide(media.x - 20, media.y + 40, 800);
  mark("hover");
  await sleep(2800);

  // 5. copy post text, open folder
  await page.evaluate(() => document.querySelector(".card:first-child [data-act=copy]").scrollIntoView({ behavior: "smooth", block: "center" }));
  await sleep(700);
  await press(".card:first-child [data-act=copy]");
  mark("copy");
  await page.waitForFunction(() => document.getElementById("dock-status").textContent.includes("copied"), null, { timeout: 5000 }).catch(() => {});
  await sleep(1300);
  await press("#open-folder");
  mark("open");
  await page.waitForFunction(() => document.getElementById("dock-status").textContent.includes("Folder"), null, { timeout: 5000 }).catch(() => {});
  await sleep(1800);
  mark("end");
} finally {
  const v = page.video();
  await ctx.close();
  const p = await v.path();
  const out = path.join(rawDir, name + ".webm");
  renameSync(p, out);
  writeFileSync(path.join(rawDir, name + ".marks.json"), JSON.stringify({ video: out, viewport, size, marks, errors }, null, 1));
  await browser.close();
  server.kill("SIGTERM");
  restore();
  console.log("wrote " + out + (errors.length ? "\nconsole errors: " + errors.join(" | ") : ""));
}
