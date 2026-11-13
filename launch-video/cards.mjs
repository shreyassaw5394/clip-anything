#!/usr/bin/env node
// Renders the burned-in captions and the end card as PNGs with the app's own fonts (embedded
// as data URLs, so no server and no network). Usage: node launch-video/cards.mjs
// Writes out/cards/cap-{tall,wide}-N.png (transparent, full canvas) and end-{tall,wide}.png.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const PW = process.env.PW_CORE || path.join(homedir(), ".local/pwcli/node_modules/playwright-core");
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const { chromium } = require(PW);

const here = path.dirname(fileURLToPath(import.meta.url));
const fontsDir = path.resolve(here, "../clip_anything/app/static/fonts");
const outDir = path.join(here, "out", "cards");
mkdirSync(outDir, { recursive: true });

export const CAPTIONS = ["Drop a recording", "Press Make clips", "It finds the action", "Play, pick, post"];
const font = (f) => "data:font/woff2;base64," + readFileSync(path.join(fontsDir, f)).toString("base64");
const css = `
@font-face{font-family:"Barlow Condensed";src:url(${font("BarlowCondensed-Bold.woff2")}) format("woff2");font-weight:700}
@font-face{font-family:"Barlow";src:url(${font("Barlow-Medium.woff2")}) format("woff2");font-weight:500}
*{box-sizing:border-box;margin:0}
html,body{background:transparent}
body{font-family:"Barlow",sans-serif;color:#111318;-webkit-font-smoothing:antialiased}
.cap{position:absolute;left:0;right:0;display:flex;flex-direction:column;align-items:center;gap:18px;text-align:center}
.cap h1{font-family:"Barlow Condensed";font-weight:700;letter-spacing:-.02em;line-height:.95;text-wrap:balance}
.cap i{display:block;width:72px;height:10px;background:#c4105f}
.tall .cap{top:236px}.tall .cap h1{font-size:108px}
.wide .cap{top:auto;bottom:168px;left:0;right:0}.wide .cap h1{font-size:84px;padding:14px 36px 18px;background:rgba(241,239,233,.94)}.wide .cap i{width:56px;height:8px;margin-top:-6px}
.end{position:absolute;inset:0;background:#f1efe9;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:40px;text-align:center}
.brand{display:flex;align-items:center;gap:20px;font-family:"Barlow Condensed";font-weight:700;font-size:72px;letter-spacing:-.01em}
.brand svg{width:96px;height:96px}
.end h1{font-family:"Barlow Condensed";font-weight:700;font-size:136px;line-height:.92;letter-spacing:-.025em;text-wrap:balance;max-width:9em}
.end p{font-size:40px;color:#4a4c52}
.end small{position:absolute;left:0;right:0;bottom:120px;font-size:26px;color:#8a8982;text-align:center}
.wide .end small{bottom:48px}
.end .url{display:inline-block;margin-top:8px;padding:18px 34px;background:#111318;color:#f1efe9;font-family:"Barlow Condensed";font-weight:700;font-size:56px;letter-spacing:.005em}
.end .url b{color:#ff5c9d;font-weight:700}
.wide .end{gap:28px}.wide .end h1{font-size:120px}.wide .brand{font-size:56px}.wide .brand svg{width:72px;height:72px}.wide .end p{font-size:34px}.wide .end .url{font-size:48px;padding:14px 28px}
`;
const mark = `<svg viewBox="0 0 512 512" aria-hidden="true"><g fill="#111318" opacity=".45"><rect x="48" y="344" width="20" height="48"/><rect x="80" y="308" width="20" height="84"/><rect x="112" y="328" width="20" height="64"/><rect x="144" y="284" width="20" height="108"/><rect x="336" y="300" width="20" height="92"/><rect x="368" y="336" width="20" height="56"/><rect x="400" y="316" width="20" height="76"/><rect x="432" y="348" width="20" height="44"/></g><rect x="184" y="96" width="144" height="256" fill="#c4105f"/><rect x="246" y="128" width="20" height="192" fill="#111318"/></svg>`;
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
const page_ = (cls, body) => `<!doctype html><html class="${cls}"><head><meta charset="utf-8"><style>${css}</style></head><body>${body}</body></html>`;
const capHtml = (cls, text) => page_(cls, `<div class="cap"><h1>${esc(text)}</h1><i></i></div>`);
const endHtml = (cls) => page_(cls, `<div class="end"><div class="brand">${mark}<span>Clip Anything</span></div><h1>Free. Windows and Mac.</h1><p>Your recording in, the best moments out, as vertical clips. Everything stays on your computer.</p><span class="url">shipatmidnight.dev/<b>clip-anything</b></span><small>Gameplay: Persona 3 Portable, CC BY 3.0 via archive.org</small></div>`);

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
for (const [cls, w, h] of [["tall", 1080, 1920], ["wide", 1920, 1080]]) {
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
  for (let i = 0; i < CAPTIONS.length; i++) {
    await page.setContent(capHtml(cls, CAPTIONS[i]));
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: path.join(outDir, `cap-${cls}-${i + 1}.png`), omitBackground: true });
  }
  await page.setContent(endHtml(cls));
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: path.join(outDir, `end-${cls}.png`) });
  await page.close();
}
await browser.close();
writeFileSync(path.join(outDir, "captions.json"), JSON.stringify(CAPTIONS));
console.log("wrote " + outDir);
