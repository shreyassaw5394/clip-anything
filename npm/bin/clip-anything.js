#!/usr/bin/env node
"use strict";
// Thin launcher for the clip-anything Python CLI. No dependencies.
// Order: uvx (uv) -> pipx run -> an installed `clip-anything` on PATH.
// Spawns with an argument array and no shell, so paths with spaces and
// Windows both work. Everything else is the Python tool's job.

const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const PKG = "clip-anything";
const IS_WIN = process.platform === "win32";

function which(cmd) {
  const dirs = (process.env.PATH || "").split(path.delimiter).filter(Boolean);
  const exts = IS_WIN
    ? (process.env.PATHEXT || ".EXE;.CMD;.BAT").split(";").filter(Boolean)
    : [""];
  for (const dir of dirs) {
    for (const ext of exts) {
      const candidate = path.join(dir, cmd + ext);
      try {
        fs.accessSync(candidate, fs.constants.X_OK);
        if (fs.statSync(candidate).isFile()) return candidate;
      } catch {
        /* keep looking */
      }
    }
  }
  return null;
}

function run(file, args) {
  // On Windows a .cmd/.bat shim cannot be spawned without a shell, so only
  // real executables are used here; uv, pipx and the pip console script are.
  const result = spawnSync(file, args, { stdio: "inherit", windowsHide: true });
  if (result.error) {
    process.stderr.write(`clip-anything: could not start ${file}: ${result.error.message}\n`);
    return 127;
  }
  if (result.signal) {
    process.kill(process.pid, result.signal);
    return 128;
  }
  return result.status == null ? 1 : result.status;
}

function uvHint() {
  return IS_WIN
    ? '  winget install astral-sh.uv   (or: powershell -c "irm https://astral.sh/uv/install.ps1 | iex")'
    : "  curl -LsSf https://astral.sh/uv/install.sh | sh   (or: brew install uv)";
}

function ffmpegHint() {
  if (process.platform === "darwin") return "  brew install ffmpeg";
  if (IS_WIN) return "  winget install Gyan.FFmpeg";
  return "  sudo apt install ffmpeg   (or your distro's package)";
}

function main(argv) {
  if (!which("ffmpeg") || !which("ffprobe")) {
    process.stderr.write(
      "clip-anything: ffmpeg/ffprobe not found on PATH. The tool needs both. Install:\n" +
        ffmpegHint() +
        "\n\n"
    );
  }

  const uvx = which("uvx");
  if (uvx) return run(uvx, [PKG, ...argv]);

  const pipx = which("pipx");
  if (pipx) return run(pipx, ["run", PKG, ...argv]);

  const installed = which(PKG);
  if (installed && path.resolve(installed) !== path.resolve(__filename)) {
    return run(installed, argv);
  }

  process.stderr.write(
    [
      "clip-anything: this npm package is only a launcher for the Python tool,",
      "and neither `uvx` (uv) nor `pipx` is on your PATH.",
      "",
      "Install uv (recommended), then run this command again:",
      uvHint(),
      "",
      "Or install the tool directly with pipx or pip:",
      "  pipx install clip-anything",
      "  python3 -m pip install --user clip-anything",
      "",
      "ffmpeg is also required:",
      ffmpegHint(),
      "",
      "Project: https://github.com/shreyassaw5394/clip-anything",
      "",
    ].join("\n")
  );
  return 127;
}

process.exitCode = main(process.argv.slice(2));
