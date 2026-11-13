#!/usr/bin/env node
// The explainer reel: "how it finds the action, with no AI", drawn from the real series of a
// run (out/explainer-data.json from explainer_data.py). Deterministic: a canvas scene with
// render(t), one screenshot per frame at 30 fps, then ffmpeg. No game footage.
// Usage: node launch-video/explainer.mjs tall|wide   -> out/explainer-reel.mp4 | out/explainer-16x9.mp4
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const PW = process.env.PW_CORE || path.join(homedir(), ".local/pwcli/node_modules/playwright-core");
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const FF = process.env.FFMPEG || "/opt/homebrew/bin/ffmpeg";
const { chromium } = require(PW);
const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.join(here, "out");
const kind = process.argv[2] === "wide" ? "wide" : "tall";
const W = kind === "tall" ? 1080 : 1920, H = kind === "tall" ? 1920 : 1080;
const FPS = 30;
const data = JSON.parse(readFileSync(path.join(out, "explainer-data.json"), "utf8"));
const fontsDir = path.resolve(here, "../clip_anything/app/static/fonts");
const font = (f) => "data:font/woff2;base64," + readFileSync(path.join(fontsDir, f)).toString("base64");

// beats (seconds): each caption holds >= 1.5 s
const B = { timeline: 0, listen: 3, watch: 7, both: 11, bar: 16, promise: 21, end: 24, total: 27.5 };

const html = `<!doctype html><html><head><meta charset="utf-8"><style>
@font-face{font-family:"Barlow Condensed";src:url(${font("BarlowCondensed-Bold.woff2")}) format("woff2");font-weight:700}
@font-face{font-family:"Barlow";src:url(${font("Barlow-Medium.woff2")}) format("woff2");font-weight:500}
@font-face{font-family:"Barlow";src:url(${font("Barlow-Regular.woff2")}) format("woff2");font-weight:400}
*{margin:0;box-sizing:border-box}html,body{width:${W}px;height:${H}px;overflow:hidden;background:#f1efe9}
canvas{position:absolute;inset:0}
.t{position:absolute;left:0;right:0;text-align:center;opacity:0;color:#111318;font-family:"Barlow Condensed";font-weight:700;letter-spacing:-.02em;line-height:.95;text-wrap:balance;padding:0 60px}
.s{position:absolute;left:0;right:0;text-align:center;opacity:0;color:#4a4c52;font-family:"Barlow";font-weight:400;line-height:1.3;padding:0 90px;text-wrap:balance}
.end{position:absolute;inset:0;opacity:0;background:#f1efe9;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:40px;text-align:center;font-family:"Barlow";color:#111318}
.brand{display:flex;align-items:center;gap:20px;font-family:"Barlow Condensed";font-weight:700;font-size:72px;letter-spacing:-.01em}
.brand svg{width:96px;height:96px}
.end h1{font-family:"Barlow Condensed";font-weight:700;font-size:128px;line-height:.92;letter-spacing:-.025em;max-width:9em;text-wrap:balance}
.end p{font-size:40px;color:#4a4c52;max-width:28ch}
.end .url{display:inline-block;margin-top:8px;padding:18px 34px;background:#111318;color:#f1efe9;font-family:"Barlow Condensed";font-weight:700;font-size:56px}
.end .url b{color:#ff5c9d}
</style></head><body>
<canvas id="c" width="${W}" height="${H}"></canvas>
<div id="t1" class="t"></div><div id="t2" class="s"></div>
<div class="end" id="end"><div class="brand"><svg viewBox="0 0 512 512"><g fill="#111318" opacity=".45"><rect x="48" y="344" width="20" height="48"/><rect x="80" y="308" width="20" height="84"/><rect x="112" y="328" width="20" height="64"/><rect x="144" y="284" width="20" height="108"/><rect x="336" y="300" width="20" height="92"/><rect x="368" y="336" width="20" height="56"/><rect x="400" y="316" width="20" height="76"/><rect x="432" y="348" width="20" height="44"/></g><rect x="184" y="96" width="144" height="256" fill="#c4105f"/><rect x="246" y="128" width="20" height="192" fill="#111318"/></svg><span>Clip Anything</span></div><h1>Finds the action. No AI needed.</h1><p>Free, open source, everything on your computer. Windows and Mac.</p><span class="url">shipatmidnight.dev/<b>clip-anything</b></span></div>
<script>
const D = ${JSON.stringify(data)}; const W = ${W}, H = ${H}, B = ${JSON.stringify(B)}, TALL = ${kind === "tall"};
const ctx = document.getElementById("c").getContext("2d");
let G = 1; const ga = (x) => { ctx.globalAlpha = Math.max(0, Math.min(1, x)) * G; };
const INK = "#111318", INK2 = "#4a4c52", MUTED = "#8a8982", RULE = "#cfcbc0", ACC = "#c4105f", PAPER = "#f1efe9";
const N = D.points, dur = D.duration_s;
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const ease = (x) => 1 - Math.pow(1 - clamp(x), 3);
const io = (x) => { x = clamp(x); return x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
const seg = (t, a, d) => clamp((t - a) / d);
// layout
const L = TALL
  ? { x0: 80, x1: 1000, title: 250, titleSize: 104, sub: 1440, subSize: 40, rowA: 800, rowB: 1190, rowM: 1000, h: 280, hM: 420, note: 34, shelf: 560 }
  : { x0: 200, x1: 1720, title: 92, titleSize: 88, sub: 1000, subSize: 34, rowA: 520, rowB: 820, rowM: 690, h: 190, hM: 340, note: 30, shelf: 300 };
const PW_ = L.x1 - L.x0;
const X = (i) => L.x0 + (i / (N - 1)) * PW_;
const idx = (sec) => Math.round(clamp(sec / dur) * (N - 1));
// local maxima for the sound spikes
const peaks = (arr, thr, gap) => { const p = []; for (let i = 1; i < N - 1; i++) if (arr[i] >= thr && arr[i] >= arr[i - 1] && arr[i] >= arr[i + 1] && (!p.length || i - p[p.length - 1] > gap)) p.push(i); return p; };
const soundPeaks = peaks(D.audio, 0.5, 4).sort((a, b) => D.audio[b] - D.audio[a]).slice(0, 14).sort((a, b) => a - b);
const clips = D.clips.map((c) => { const a = idx(c.start), b = idx(c.end); let m = a, v = -1; for (let i = a; i <= b; i++) if (D.score[i] > v) { v = D.score[i]; m = i; } return { ...c, i: m, v }; }).sort((a, b) => a.i - b.i);
const bumpI = D.bump ? idx(D.bump.t) : -1;
const bar = D.bar;

function text(id, s, size, y, alpha) { const el = document.getElementById(id); el.textContent = s; el.style.fontSize = size + "px"; el.style.top = y + "px"; el.style.opacity = String(clamp(alpha)); el.style.transform = "translateY(" + (12 * (1 - clamp(alpha))) + "px)"; }
const fade = (t, a, b) => Math.min(seg(t, a, .4), 1 - seg(t, b - .35, .35));

function trace(arr, base, h, prog, color, lw, alpha = 1, fillAlpha = 0) {
  if (prog <= 0 || alpha <= 0) return;
  const n = Math.max(2, Math.floor(prog * N));
  ctx.save(); ga(alpha); ctx.lineJoin = "round"; ctx.lineWidth = lw; ctx.strokeStyle = color;
  ctx.beginPath();
  for (let i = 0; i < n; i++) { const x = X(i), y = base - arr[i] * h; i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
  ctx.stroke();
  if (fillAlpha > 0) { ctx.lineTo(X(n - 1), base); ctx.lineTo(X(0), base); ctx.closePath(); ga(alpha * fillAlpha); ctx.fillStyle = color; ctx.fill(); }
  ctx.restore();
}
function baseline(base, alpha = 1) { ctx.save(); ga(alpha); ctx.strokeStyle = RULE; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(L.x0, base); ctx.lineTo(L.x1, base); ctx.stroke(); ctx.restore(); }
function label(s, x, y, alpha, color = MUTED, size = L.note, align = "left") { ctx.save(); ga(alpha); ctx.fillStyle = color; ctx.font = "500 " + size + "px Barlow"; ctx.textAlign = align; ctx.textBaseline = "alphabetic"; ctx.fillText(s, x, y); ctx.restore(); }
function ticks(base, alpha) {
  ctx.save(); ga(alpha); ctx.strokeStyle = RULE; ctx.lineWidth = 2;
  for (let m = 0; m <= 40; m += 10) { const x = L.x0 + (m * 60 / dur) * PW_; ctx.beginPath(); ctx.moveTo(x, base); ctx.lineTo(x, base + 14); ctx.stroke(); label(m + " min", x, base + 48, alpha, MUTED, L.note, m === 0 ? "left" : m === 40 ? "right" : "center"); }
  ctx.restore();
}
function frame(x, y, w, h, alpha) { // the 9:16 clip motif
  ctx.save(); ga(alpha); ctx.fillStyle = ACC; ctx.fillRect(x - w / 2, y - h, w, h); ctx.fillStyle = PAPER; ctx.fillRect(x - w * 0.07, y - h * 0.86, w * 0.14, h * 0.72); ctx.restore();
}
function cross(x, y, r, alpha) { ctx.save(); ga(alpha); ctx.strokeStyle = INK; ctx.lineWidth = 5; ctx.lineCap = "round"; ctx.beginPath(); ctx.moveTo(x - r, y - r); ctx.lineTo(x + r, y + r); ctx.moveTo(x + r, y - r); ctx.lineTo(x - r, y + r); ctx.stroke(); ctx.restore(); }

window.render = function (t) {
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = PAPER; ctx.fillRect(0, 0, W, H);
  document.getElementById("end").style.opacity = "0";
  let t1 = ["", 0], t2 = ["", 0];
  G = 1 - seg(t, B.promise - .4, .5);
  ctx.save();

  // 1. the flat timeline with a playhead
  if (t < B.both + 1.2) {
    const a = fade(t, B.timeline, B.listen + .6) * (t < B.listen ? 1 : 1);
    const base = L.rowM + 10;
    const tlAlpha = t < B.listen ? ease(seg(t, 0, .6)) : 1 - seg(t, B.listen, .8);
    baseline(base, tlAlpha); ticks(base, tlAlpha);
    const p = io(seg(t, .4, 2.3));
    if (t < B.listen) { ctx.save(); ga(tlAlpha); ctx.fillStyle = ACC; const x = L.x0 + p * PW_; ctx.fillRect(x - 3, base - 40, 6, 80); ctx.restore(); }
    if (t < B.listen) t1 = ["A 40-minute recording", fade(t, 0.2, B.listen)];
  }
  // 2. listen: the sound trace draws, spikes pop
  if (t >= B.listen - .2 && t < B.bar + .6) {
    const mergeP = io(seg(t, B.both + .2, 1.4)); // slide toward the middle and fade
    const base = L.rowA + (L.rowM - L.rowA) * mergeP, h = L.h;
    const a = (1 - mergeP) * (1 - seg(t, B.both + .2, 1.4));
    const prog = ease(seg(t, B.listen, 2.2));
    baseline(base, a); trace(D.audio, base, h, prog, INK, 3, a);
    label("sound", L.x0, base - h - 18, a * seg(t, B.listen, .4), INK2);
    for (const i of soundPeaks) { const when = B.listen + 2.2 * (i / N) + .05; const s = seg(t, when, .35); if (s <= 0) continue; const r = 9 * (1 + .9 * Math.sin(Math.PI * s)); ctx.save(); ga(a); ctx.fillStyle = ACC; ctx.beginPath(); ctx.arc(X(i), base - D.audio[i] * h, r, 0, 7); ctx.fill(); ctx.restore(); }
    if (t < B.watch) t1 = ["It listens for sudden sound", fade(t, B.listen, B.watch)];
  }
  // 3. watch: the motion trace draws under it
  if (t >= B.watch - .2 && t < B.bar + .6) {
    const mergeP = io(seg(t, B.both + .2, 1.4));
    const base = L.rowB + (L.rowM - L.rowB) * mergeP + (TALL ? 60 : 40), h = L.h;
    const a = 1 - mergeP;
    const prog = ease(seg(t, B.watch, 2.2));
    baseline(base, a); trace(D.visual, base, h, prog, INK2, 3, a);
    label("motion across the whole screen", L.x0, base - h - 18, a * seg(t, B.watch, .4), INK2);
    if (t < B.both) t1 = ["It watches for motion across the whole screen", fade(t, B.watch, B.both)];
  }
  // 4. both: the action score, agreement glows, the menu bump crossed out
  if (t >= B.both + .8) {
    const base = L.rowM + (TALL ? 170 : 130), h = L.hM;
    const a = ease(seg(t, B.both + .8, .9));
    const glow = seg(t, B.both + 1.6, 1.0);
    baseline(base, a);
    // magenta fill where sound and motion rise together
    if (glow > 0) { ctx.save(); ga(a * glow * .85); ctx.fillStyle = ACC; for (let i = 0; i < N - 1; i++) { if (D.score[i] >= bar) { const x = X(i), w = Math.max(2, X(i + 1) - x + 1); ctx.fillRect(x, base - D.score[i] * h, w, D.score[i] * h); } } ctx.restore(); }
    trace(D.score, base, h, 1, INK, 2.5, a);
    label("action", L.x0, base - h - 18, a, INK2);
    if (bumpI >= 0) {
      const s = seg(t, B.both + 2.6, .5), s2 = seg(t, B.both + 3.0, .4);
      const x = X(bumpI), yTop = base - h - 70, yb = base - Math.max(D.score[bumpI], .06) * h;
      ctx.save(); ga(a * s); ctx.fillStyle = "#b9b5aa"; ctx.fillRect(x - 26, yb - 44, 52, 44 + 6); ctx.strokeStyle = RULE; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(x, yb - 44); ctx.lineTo(x, yTop + 16); ctx.stroke(); ctx.restore();
      cross(x, yb - 22, 24, a * s2);
      const right = x > (L.x0 + L.x1) / 2;
      label("a menu screen, loud but still: marked down", x + (right ? -14 : 14), yTop + 8, a * s2, INK, L.note, right ? "right" : "left");
    }
    if (t < B.bar) { t1 = ["Action is when both rise together", fade(t, B.both, B.bar)]; t2 = ["Menus and loading screens get marked down.", fade(t, B.both + 2.8, B.bar)]; }
    // 5. the bar and the clips lifting out
    if (t >= B.bar) {
      const bs = ease(seg(t, B.bar, .8)), yb = base - bar * h;
      ctx.save(); ga(a); ctx.strokeStyle = INK; ctx.lineWidth = 4; ctx.setLineDash([14, 10]); ctx.beginPath(); ctx.moveTo(L.x0, yb); ctx.lineTo(L.x0 + bs * PW_, yb); ctx.stroke(); ctx.restore();
      label("the bar", L.x0, yb - 14, bs, INK, L.note, "left");
      clips.forEach((c, k) => { const s = io(seg(t, B.bar + .9 + k * .17, .8)); if (s <= 0) return; const y0 = base - c.v * h, y1 = L.shelf + (TALL ? 60 : 40); const y = y0 + (y1 - y0) * s; const w = 46 + 10 * s, hh = 82 + 18 * s; frame(X(c.i), y, w, hh, 1); if (s < 1) { ctx.save(); ga(.5 * (1 - s)); ctx.strokeStyle = ACC; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(X(c.i), y0); ctx.lineTo(X(c.i), y); ctx.stroke(); ctx.restore(); } });
      label(clips.length + " clips from " + Math.round(dur / 60) + " minutes", (L.x0 + L.x1) / 2, L.shelf - 70, seg(t, B.bar + 2.8, .5), INK2, L.note + 4, "center");
      t1 = ["Every clip has to clear the same bar", fade(t, B.bar, B.promise)];
      t2 = ["A dull hour returns fewer clips, not filler.", fade(t, B.bar + 2.2, B.promise)];
    }
  }
  ctx.restore(); G = 1;
  // 6. the promise
  if (t >= B.promise - .2 && t < B.end + .5) { t1 = ["No upload. No account. No AI needed.", fade(t, B.promise, B.end + .3)]; t2 = ["Smarter picks and titles with AI, if you want them.", fade(t, B.promise + 1.1, B.end + .3)]; }
  text("t1", t1[0], L.titleSize, t >= B.promise - .2 && t < B.end + .5 ? (TALL ? 760 : 380) : L.title, t1[1]);
  text("t2", t2[0], L.subSize, t >= B.promise - .2 && t < B.end + .5 ? (TALL ? 1080 : 620) : L.sub, t2[1]);
  // 7. end card
  document.getElementById("end").style.opacity = String(seg(t, B.end, .6));
};
</script></body></html>`;

const frames = path.join(out, "explainer-frames", kind);
rmSync(frames, { recursive: true, force: true });
mkdirSync(frames, { recursive: true });
const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
await page.setContent(html);
await page.evaluate(() => document.fonts.ready);
const total = Math.round(B.total * FPS);
const t0 = Date.now();
for (let f = 0; f < total; f++) {
  await page.evaluate((t) => window.render(t), f / FPS);
  await page.screenshot({ path: path.join(frames, `f${String(f).padStart(5, "0")}.png`), type: "png" });
}
await browser.close();
console.log(`${total} frames in ${((Date.now() - t0) / 1000).toFixed(0)} s`);

const target = path.join(out, kind === "tall" ? "explainer-reel.mp4" : "explainer-16x9.mp4");
const ff = (args) => execFileSync(FF, ["-hide_banner", "-v", "error", "-y", ...args], { stdio: ["ignore", "inherit", "inherit"] });
ff(["-framerate", String(FPS), "-i", path.join(frames, "f%05d.png"), "-f", "lavfi", "-t", String(B.total), "-i", "anullsrc=r=48000:cl=stereo",
  "-c:v", "libx264", "-profile:v", "high", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p", "-r", String(FPS), "-g", String(FPS * 2), "-c:a", "aac", "-b:a", "64k", "-shortest", "-movflags", "+faststart", target]);
const mb = (p) => (statSync(p).size / 1048576).toFixed(1) + " MB";
console.log(`wrote ${target} ${mb(target)}`);
if (kind === "wide") {
  ff(["-ss", String(B.bar + 3.2), "-i", target, "-frames:v", "1", "-q:v", "3", path.join(out, "explainer-poster.jpg")]);
} else {
  const shots = path.resolve(here, "../.planning/phases/09-howto-reel/shots");
  mkdirSync(shots, { recursive: true });
  ff(["-i", target, "-vf", `fps=1,scale=270:-1,tile=6x${Math.ceil(B.total / 6)}:padding=4:margin=4:color=0x111318`, "-frames:v", "1", "-q:v", "3", path.join(shots, "explainer-reel-contact-sheet.jpg")]);
}
rmSync(frames, { recursive: true, force: true });
