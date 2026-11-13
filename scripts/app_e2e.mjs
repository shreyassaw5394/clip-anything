#!/usr/bin/env node
// End-to-end check of the app against the real local server with Playwright (not part of
// pytest: needs playwright-core + Chrome). Usage:
//   node scripts/app_e2e.mjs <recording.mp4> [shots-dir] [quiet-recording.mp4]
// Env: PW_CORE (playwright-core folder), CHROME (browser binary).
// Drops the recording on the page (as the window app would), runs 6 clips, checks the
// results and the cached re-run, the setup screen, keyboard-only navigation, the first-run
// hints, empty and error states, dark mode, reduced motion, console/CSP errors and
// third-party requests; writes screenshots (light + dark) at 1280x800 and 1024x640.
import { spawn } from "node:child_process";
import { mkdirSync, copyFileSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const PW = process.env.PW_CORE || path.join(process.env.HOME, ".local/pwcli/node_modules/playwright-core");
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const { chromium } = require(PW);

const src = process.argv[2];
const shots = process.argv[3] || ".planning/phases/08-polished-app/shots";
const quietSrc = process.argv[4] || "";
if (!src) { console.error("usage: app_e2e.mjs <recording.mp4> [shots-dir] [quiet-recording.mp4]"); process.exit(2); }
mkdirSync(shots, { recursive: true });
// work in a private folder so clips/ lands next to a copy, not next to the fixture
const work = mkdtempSync(path.join(tmpdir(), "ca-e2e-"));
const video = path.join(work, "synth.mp4");
copyFileSync(src, video);
const notes = path.join(work, "notes.txt");
writeFileSync(notes, "not a video");
const emptyDir = path.join(work, "empty");
mkdirSync(emptyDir);
const darkVideo = path.join(work, "dark", "synth.mp4");
mkdirSync(path.dirname(darkVideo));
copyFileSync(src, darkVideo);
let quiet = "";
if (quietSrc) { quiet = path.join(work, "quiet", "quiet.mp4"); mkdirSync(path.dirname(quiet)); copyFileSync(quietSrc, quiet); }

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
const consoleErrors = [];
const foreign = [];
function watch(page) {
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));
  page.on("request", (r) => { if (!r.url().startsWith(origin)) foreign.push(r.url()); });
}
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
const page = await ctx.newPage();
watch(page);

async function dropFile(pg, filePath) {
  await pg.evaluate((p) => {
    const dt = new DataTransfer();
    const f = new File(["x"], p.split("/").pop(), { type: "video/mp4" });
    Object.defineProperty(f, "pywebviewFullPath", { value: p });
    dt.items.add(f);
    const drop = document.getElementById("drop");
    drop.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true }));
    drop.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
  }, filePath);
  await pg.waitForFunction(() => { const m = document.getElementById("drop-meta").textContent; return m !== "Reading…"; }, null, { timeout: 15000 });
}
const ready = async (pg) => { await pg.waitForSelector("#ready-dot.ok, #ready-dot.off"); await pg.waitForTimeout(300); };

try {
  await page.goto(url);
  await ready(page);
  check((await page.textContent("#ready-text")) === "Ready", "ready line is a single Ready dot");
  check(!(await page.isHidden("#hints")), "first-run hints show on a fresh profile");
  check((await page.textContent("#start")) === "Make 10 clips", "primary button names the count");
  await page.fill("#count", "4");
  check((await page.textContent("#start")) === "Make 4 clips", "primary button tracks the slider");
  await page.fill("#count", "1");
  check((await page.textContent("#start")) === "Make 1 clip", "singular at 1");
  await page.screenshot({ path: path.join(shots, "01-home-1280.png") });

  // empty and error states before any run
  await page.focus("#start");
  await page.keyboard.press("Enter");
  check((await page.textContent("#home-problem")).includes("Choose a recording"), "Enter on Make clips without a recording explains the problem");
  await dropFile(page, notes);
  check((await page.textContent("#home-problem")).includes("not a video"), "an unsupported file is explained in plain words");
  check(await page.isDisabled("#start"), "Make clips is off while the input is wrong");
  await page.screenshot({ path: path.join(shots, "02-home-unsupported-1280.png"), clip: { x: 0, y: 160, width: 1280, height: 560 } });
  await dropFile(page, emptyDir);
  check((await page.textContent("#home-problem")).includes("No recordings in that folder"), "a folder with no videos is explained");
  await page.fill("#count", "6");

  // 2. drop the recording, 6 clips, captions off (no model download in CI-like runs)
  await dropFile(page, video);
  check((await page.textContent("#drop-name")).includes("synth.mp4"), "drop sets the recording name in the hero");
  const meta = await page.textContent("#drop-meta");
  check(/min|s/.test(meta) && /MB|kB|GB/.test(meta), "the hero shows length and size (" + meta + ")");
  check((await page.textContent("#home-problem")) === "", "the problem line clears for a good file");
  check((await page.textContent("#out-dir")).endsWith(path.join(work, "clips")), "output folder defaults next to the recording");
  await page.uncheck("#captions").catch(() => {});
  await page.screenshot({ path: path.join(shots, "03-home-chosen-1280.png") });
  const t0 = Date.now();
  await page.click("#start");
  await page.waitForSelector("#screen-run:not([hidden])");
  await page.waitForSelector("#curve-spans rect", { timeout: 120000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(shots, "04-run-1280.png") });
  check(!(await page.isHidden("#progress")), "run screen shows the progress bar");
  await page.waitForSelector("#screen-results:not([hidden])", { timeout: 240000 });
  console.log("first run " + ((Date.now() - t0) / 1000).toFixed(1) + " s");
  check(await page.isHidden("#hints") && (await page.evaluate(() => localStorage.getItem("clip-anything.first-run"))) === "done", "first finished run dismisses the hints for good");
  const cards = await page.$$(".card");
  check(cards.length === 6, `results show 6 cards (got ${cards.length})`);
  check(!(await page.isHidden(".card:first-child .best")) && (await page.$$(".card .best:not([hidden])")).length === 1, "the first card is marked Best moment, only that one");
  const why = await page.textContent(".card:first-child .card-why");
  check(why.length > 8 && /^[A-Z]/.test(why), "the reason line is the card headline (" + why + ")");
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
  // keyboard: arrows move between cards, Enter plays with sound, Space pauses
  await page.focus(".card:first-child");
  await page.keyboard.press("ArrowRight");
  check(await page.evaluate(() => document.activeElement === document.querySelectorAll(".card")[1]), "ArrowRight moves focus to the next card");
  await page.keyboard.press("ArrowLeft");
  check(await page.evaluate(() => document.activeElement === document.querySelector(".card")), "ArrowLeft moves back");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(300);
  check(await page.evaluate(() => { const v = document.querySelector(".card-video"); return !v.muted && !v.paused; }), "Enter plays the focused clip with sound");
  await page.keyboard.press(" ");
  check(await page.evaluate(() => document.querySelector(".card-video").paused), "Space pauses it");
  // delete asks inline first, Keep cancels
  await page.click('.card:nth-child(6) [data-act="delete"]');
  check(!(await page.isHidden('.card:nth-child(6) .card-confirm')), "delete asks before removing");
  await page.click('.card:nth-child(6) [data-act="delete-no"]');
  await page.screenshot({ path: path.join(shots, "05-results-1280.png"), fullPage: true });
  // copy post text: clipboard + the dock's live confirmation
  await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin });
  await page.click('.card [data-act="copy"]');
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  check(/at \d\d:\d\d in the recording/.test(clip), "copy post text writes the clipboard");
  check((await page.textContent("#dock-status")) === "Post text copied", "the sticky bar confirms the copy (aria-live)");
  check((await page.getAttribute("#export", "href")).includes("/report.json"), "export link points at report.json");
  const dockSticky = await page.evaluate(() => getComputedStyle(document.getElementById("dock")).position === "sticky");
  check(dockSticky, "results actions sit in a sticky bottom bar");

  // 3. cached re-run with count 3: seconds
  await page.click("#rerun");
  await page.waitForSelector("#screen-home:not([hidden])");
  check(await page.isHidden("#hints"), "hints stay dismissed on the next visit home");
  await page.fill("#count", "3");
  const t1 = Date.now();
  await page.click("#start");
  await page.waitForSelector("#screen-results:not([hidden])", { timeout: 60000 });
  const rerunS = (Date.now() - t1) / 1000;
  check(rerunS < 6, `cached re-run with count 3 took ${rerunS.toFixed(1)} s (< 6 s)`);
  check((await page.$$(".card")).length === 3, "re-run shows 3 cards");
  check((await page.textContent("#results-sub")).includes("saved analysis"), "results say the analysis was reused");

  // 4. zero moments: a quiet recording ends in the empty state with a one-click lower bar
  if (quiet) {
    await page.click("#rerun");
    await page.waitForSelector("#screen-home:not([hidden])");
    await dropFile(page, quiet);
    await page.click("#start");
    await page.waitForSelector("#screen-results:not([hidden])", { timeout: 240000 });
    const emptyShown = !(await page.isHidden("#empty-results"));
    check(emptyShown, "a recording with no moment above the bar shows the empty state");
    if (emptyShown) {
      await page.screenshot({ path: path.join(shots, "06-results-empty-1280.png") });
      check((await page.textContent("#empty-title")).includes("Nothing stood out"), "empty state is written like a person");
      await page.click("#lower-bar");
      await page.waitForSelector("#screen-run:not([hidden])");
      await page.waitForSelector("#screen-results:not([hidden])", { timeout: 240000 });
      check(await page.isChecked('input[name=bar][value="low"]'), "Lower the bar switches the setting and runs again");
      const again = await page.isHidden("#empty-results");
      console.log("info low bar on the quiet recording: " + (again ? (await page.$$(".card")).length + " clips" : "still nothing (second empty state)"));
      if (!again) check((await page.textContent("#empty-title")).includes("Still"), "second empty state says the bar was already low");
    }
    // back to the normal bar for the remaining checks
    await page.click("#rerun");
    await page.waitForSelector("#screen-home:not([hidden])");
    await page.check('input[name=bar][value="normal"]');
    await dropFile(page, video);
    await page.click("#start");
    await page.waitForSelector("#screen-results:not([hidden])", { timeout: 60000 });
  }

  // 5. setup screen
  await page.click('[data-nav="setup"]');
  await page.waitForSelector("#steps[aria-busy='false'] .step");
  const steps = await page.$$eval(".step .step-name", (els) => els.map((e) => e.textContent));
  check(steps.length === 6 && steps[0].startsWith("Video tools"), "setup lists 6 steps: " + steps.join(" | "));
  await page.screenshot({ path: path.join(shots, "07-setup-1280.png") });

  // 6. keyboard-only pass: Tab reaches every control on the home screen
  await page.click('[data-nav="home"]');
  await page.click("#clear-inputs");
  await page.keyboard.press("Tab");
  const order = [];
  for (let i = 0; i < 26; i++) {
    const id = await page.evaluate(() => { const a = document.activeElement; return a.id || a.name || a.className; });
    order.push(id);
    await page.keyboard.press("Tab");
  }
  const enabled = await page.evaluate(() => ["captions", "ai"].filter((id) => !document.getElementById(id).disabled));
  console.log("tab order: " + order.join(" > "));
  for (const need of ["choose-file", "choose-folder", "start", "change-out", "count", "bar", "length", "facecam", "follow", ...enabled]) {
    check(order.includes(need), "keyboard reaches " + need);
  }
  const focusVisible = await page.evaluate(() => { const b = document.getElementById("start"); b.focus(); return getComputedStyle(b).outlineStyle !== "none"; });
  check(focusVisible, "focus ring visible on buttons");
  const targets = await page.evaluate(() => Array.from(document.querySelectorAll("#screen-home button, #screen-home input, #screen-home a")).filter((e) => e.offsetParent !== null && !e.closest(".seg-item")).map((e) => { const r = e.getBoundingClientRect(); return [e.id || e.className, Math.round(r.height)]; }).filter(([, h]) => h < 24));
  check(targets.length === 0, "every visible home control is at least 24 px tall" + (targets.length ? ": " + JSON.stringify(targets) : ""));

  // 7. narrow window
  await page.setViewportSize({ width: 1024, height: 640 });
  await page.waitForTimeout(200);
  await dropFile(page, video);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  check(!overflow, "no horizontal overflow at 1024x640");
  await page.screenshot({ path: path.join(shots, "08-home-1024.png") });
  await page.click('[data-nav="results"]');
  await page.waitForSelector("#screen-results:not([hidden])");
  await page.waitForTimeout(300);
  const replay = await page.evaluate(() => document.getElementById("grid").classList.contains("enter"));
  check(!replay, "re-showing Results does not replay the entrance");
  await page.screenshot({ path: path.join(shots, "09-results-1024.png") });
  await page.setViewportSize({ width: 760, height: 640 });
  await page.waitForTimeout(200);
  const overflowNarrow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  check(!overflowNarrow, "no horizontal overflow at 760 wide");
  await page.click('[data-nav="home"]');
  await page.screenshot({ path: path.join(shots, "10-home-760.png"), fullPage: true });

  // 8. reduced motion: no stagger, no marching border, state changes still land
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.click('[data-nav="results"]');
  await page.waitForSelector("#screen-results:not([hidden])");
  const stagger = await page.evaluate(() => getComputedStyle(document.querySelector(".card")).animationName);
  check(stagger === "none", "reduced motion disables the card stagger (" + stagger + ")");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.click('[data-nav="home"]');
  await page.click("#start");
  await page.waitForSelector("#screen-results:not([hidden])", { timeout: 60000 });
  const staggerOn = await page.evaluate(() => getComputedStyle(document.querySelector(".card")).animationName);
  check(staggerOn === "rise", "cards stagger in with motion allowed (" + staggerOn + ")");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload();
  await ready(page);
  check(true, "reduced-motion reload renders");

  // 9. dark mode: same flow in a dark context, screenshots of every screen
  const dctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1, colorScheme: "dark" });
  const dark = await dctx.newPage();
  watch(dark);
  await dark.goto(url);
  await ready(dark);
  const bg = await dark.evaluate(() => getComputedStyle(document.body).backgroundColor);
  check(bg === "rgb(21, 22, 26)", "dark mode follows the system (" + bg + ")");
  const contrast = await dark.evaluate(() => {
    const L = (c) => { const [r, g, b] = c.match(/\d+/g).map((v) => v / 255).map((v) => v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
    const ratio = (a, b) => { const x = L(a), y = L(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
    const bgc = getComputedStyle(document.body).backgroundColor;
    const out = [];
    for (const sel of [".note", ".drop-sub", ".settings-lead", ".foot", ".drop-kicker", "#start", ".ready", ".check-note"]) {
      const e = document.querySelector(sel); if (!e) continue;
      const cs = getComputedStyle(e);
      const back = cs.backgroundColor && cs.backgroundColor !== "rgba(0, 0, 0, 0)" ? cs.backgroundColor : bgc;
      out.push([sel, Math.round(ratio(cs.color, back) * 100) / 100]);
    }
    return out;
  });
  check(contrast.every(([, r]) => r >= 4.5), "dark text contrast >= 4.5:1 " + JSON.stringify(contrast));
  await dark.screenshot({ path: path.join(shots, "11-home-dark-1280.png") });
  await dropFile(dark, darkVideo); // a fresh folder: a full run, so the run screen can be captured
  await dark.fill("#count", "6");
  await dark.uncheck("#captions").catch(() => {});
  await dark.screenshot({ path: path.join(shots, "12-home-chosen-dark-1280.png") });
  await dark.click("#start");
  await dark.waitForSelector("#screen-run:not([hidden])");
  await dark.waitForSelector("#curve-spans rect", { timeout: 120000 });
  await dark.waitForTimeout(500);
  await dark.screenshot({ path: path.join(shots, "13-run-dark-1280.png") });
  await dark.waitForSelector("#screen-results:not([hidden])", { timeout: 240000 });
  await dark.waitForTimeout(900);
  await dark.screenshot({ path: path.join(shots, "14-results-dark-1280.png"), fullPage: true });
  await dark.click('[data-nav="setup"]');
  await dark.waitForSelector("#steps[aria-busy='false'] .step");
  await dark.screenshot({ path: path.join(shots, "15-setup-dark-1280.png") });
  await dark.setViewportSize({ width: 1024, height: 640 });
  await dark.click('[data-nav="results"]');
  await dark.waitForTimeout(300);
  await dark.screenshot({ path: path.join(shots, "16-results-dark-1024.png") });
  await dctx.close();

  // 10. light contrast on the same selectors
  await page.emulateMedia({ reducedMotion: "no-preference" });
  const lightContrast = await page.evaluate(() => {
    const L = (c) => { const [r, g, b] = c.match(/\d+/g).map((v) => v / 255).map((v) => v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
    const ratio = (a, b) => { const x = L(a), y = L(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
    const bgc = getComputedStyle(document.body).backgroundColor;
    const out = [];
    for (const sel of [".note", ".drop-sub", ".settings-lead", ".foot", ".drop-kicker", "#start", ".ready", ".check-note"]) {
      const e = document.querySelector(sel); if (!e) continue;
      const cs = getComputedStyle(e);
      const back = cs.backgroundColor && cs.backgroundColor !== "rgba(0, 0, 0, 0)" ? cs.backgroundColor : bgc;
      out.push([sel, Math.round(ratio(cs.color, back) * 100) / 100]);
    }
    return out;
  });
  check(lightContrast.every(([, r]) => r >= 4.5), "light text contrast >= 4.5:1 " + JSON.stringify(lightContrast));

  // 11. security from the browser side: a foreign origin cannot read the API
  const foreignPage = await ctx.newPage();
  await foreignPage.goto("data:text/html,<p>x</p>");
  const blocked = await foreignPage.evaluate(async (u) => {
    try { const r = await fetch(u + "api/caps", { headers: { Authorization: "Bearer " + new URL(u).searchParams.get("t") } }); return "status " + r.status; }
    catch (e) { return "blocked"; }
  }, url);
  check(blocked === "blocked" || blocked === "status 403", "cross-origin fetch of the API is refused (" + blocked + ")");
  await foreignPage.close();

  const html = await (await fetch(url)).text();
  const inline = (html.match(/\sstyle=|<script(?![^>]*\ssrc=)|\son[a-z]+=/gi) || []).length;
  check(inline === 0, "no inline styles, scripts or handlers in the markup (" + inline + ")");
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
