#!/usr/bin/env node
// Cuts a take on its beat marks, time-lapses the run, frames it, burns the captions and adds
// the end card. Usage: node launch-video/edit.mjs tall|wide
//   tall -> out/howto-reel.mp4 (1080x1920, app framed on paper)   wide -> out/howto-16x9.mp4 (1920x1080)
// Then: poster, gif (from wide) and a 1 fps contact sheet (from the reel). ffmpeg from PATH or FFMPEG.
import { execFileSync } from "node:child_process";
import { readFileSync, mkdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.join(here, "out");
const FF = process.env.FFMPEG || "/opt/homebrew/bin/ffmpeg";
const ff = (args) => execFileSync(FF, ["-hide_banner", "-v", "error", "-y", ...args], { stdio: ["ignore", "inherit", "inherit"] });
const kind = process.argv[2] === "wide" ? "wide" : "tall";
const take = JSON.parse(readFileSync(path.join(out, "raw", `app-${kind}.marks.json`), "utf8"));
const m = Object.fromEntries(take.marks.map((x) => [x.what, x.t]));
const FPS = 30;

// Edit list in source time. A: home → the press (real time). Then the run in pieces: the
// stage title (1.6x), the wait for the curve (whatever it takes → 1.5 s), the curve drawing and
// the markers (1.6x), the renders (whatever it takes → 2.6 s). C: results → end (real time).
const A = [m.home - 1.4, m.start + 0.45];
const pieces = [
  { from: A[0], to: A[1], speed: 1 },
  { from: A[1], to: Math.min(A[1] + 2.0, m.markers - 0.6), speed: 1.6 },
  { from: Math.min(A[1] + 2.0, m.markers - 0.6), to: m.markers - 0.6, len: 1.5 },
  { from: m.markers - 0.6, to: m.markers + 3.2, speed: 1.6 },
  { from: m.markers + 3.2, to: m.results - 0.05, len: 2.6 },
  { from: m.results - 0.05, to: m.end - 0.1, speed: 1 },
].filter((p) => p.to - p.from > 0.05);
for (const p of pieces) p.out = p.len ?? (p.to - p.from) / p.speed;
const endLen = 3.6, xf = 0.5;
const dA = pieces[0].out;
const dC = pieces[pieces.length - 1].out;
const appLen = pieces.reduce((a, p) => a + p.out, 0);
const dB = appLen - dA - dC;
const total = appLen + endLen - xf;
// caption windows in output time
const tChosen = dA - (A[1] - m.chosen);
const caps = [
  [0.5, tChosen + 0.9],
  [tChosen + 0.9, dA + 0.3],
  [dA + 0.3, dA + dB],
  [dA + dB + 0.4, appLen - 0.3],
];
console.log(`segments A ${dA.toFixed(1)}s  run ${dB.toFixed(1)}s (${(m.results - A[1]).toFixed(0)}s real)  C ${dC.toFixed(1)}s  end ${endLen}s  total ${total.toFixed(1)}s`);

const W = kind === "tall" ? 1080 : 1920, H = kind === "tall" ? 1920 : 1080;
const frame = kind === "tall"
  ? "scale=1008:1344:flags=lanczos,pad=1080:1920:36:420:color=0xf1efe9,drawbox=x=35:y=419:w=1010:h=1346:color=0x111318:t=1"
  : "scale=1920:1080:flags=lanczos";
const inputs = ["-i", take.video];
for (let i = 1; i <= 4; i++) inputs.push("-loop", "1", "-framerate", String(FPS), "-t", (caps[i - 1][1] - caps[i - 1][0]).toFixed(3), "-i", path.join(out, "cards", `cap-${kind}-${i}.png`));
inputs.push("-loop", "1", "-framerate", String(FPS), "-t", String(endLen), "-i", path.join(out, "cards", `end-${kind}.png`));
inputs.push("-f", "lavfi", "-t", total.toFixed(3), "-i", "anullsrc=r=48000:cl=stereo");
const f = pieces.map((p, i) => `[0:v]trim=${p.from.toFixed(3)}:${p.to.toFixed(3)},setpts=(PTS-STARTPTS)*${(p.out / (p.to - p.from)).toFixed(6)}[s${i}]`);
f.push(`${pieces.map((_, i) => `[s${i}]`).join("")}concat=n=${pieces.length}:v=1:a=0,fps=${FPS},${frame},format=yuv420p,settb=AVTB[app]`);
let cur = "app";
caps.forEach(([s, e], i) => {
  const d = e - s;
  f.push(`[${i + 1}:v]format=rgba,fade=in:st=0:d=0.28:alpha=1,fade=out:st=${(d - 0.28).toFixed(3)}:d=0.28:alpha=1,setpts=PTS-STARTPTS+${s.toFixed(3)}/TB[cp${i}]`);
  f.push(`[${cur}][cp${i}]overlay=0:0:eof_action=pass[o${i}]`);
  cur = `o${i}`;
});
f.push(`[5:v]fps=${FPS},format=yuv420p,settb=AVTB[end]`);
f.push(`[${cur}][end]xfade=transition=fade:duration=${xf}:offset=${(appLen - xf).toFixed(3)}[v]`);
const target = path.join(out, kind === "tall" ? "howto-reel.mp4" : "howto-16x9.mp4");
ff([...inputs, "-filter_complex", f.join(";"), "-map", "[v]", "-map", "6:a", "-c:v", "libx264", "-profile:v", "high", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p", "-r", String(FPS), "-g", String(FPS * 2), "-c:a", "aac", "-b:a", "64k", "-shortest", "-movflags", "+faststart", target]);
const mb = (p) => (statSync(p).size / 1048576).toFixed(1) + " MB";
console.log(`wrote ${target} ${mb(target)}`);

// poster at the results beat, gif from the wide cut, contact sheet from the reel
const tPoster = dA + dB + 2.4;
if (kind === "wide") {
  ff(["-ss", tPoster.toFixed(2), "-i", target, "-frames:v", "1", "-q:v", "3", path.join(out, "howto-poster.jpg")]);
  const gif = path.join(out, "howto.gif");
  ff(["-i", target, "-filter_complex", "fps=10,scale=540:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle", "-loop", "0", gif]);
  console.log(`wrote ${gif} ${mb(gif)}  poster ${mb(path.join(out, "howto-poster.jpg"))}`);
} else {
  const shots = path.resolve(here, "../.planning/phases/09-howto-reel/shots");
  mkdirSync(shots, { recursive: true });
  const sheet = path.join(shots, "howto-reel-contact-sheet.jpg");
  ff(["-i", target, "-vf", `fps=1,scale=270:-1,tile=6x${Math.ceil(total / 6)}:padding=4:margin=4:color=0x111318`, "-frames:v", "1", "-q:v", "3", sheet]);
  console.log("wrote " + sheet);
}
