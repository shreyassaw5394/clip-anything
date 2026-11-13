/* Clip Anything app: plain JS over the local JSON API + Server-Sent Events. No build step. */
(() => {
  "use strict";

  const TOKEN = new URLSearchParams(location.search).get("t") || "";
  const $ = (id) => document.getElementById(id);
  const screens = ["home", "run", "results", "setup", "error", "about"];
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const FIRST_RUN_KEY = "clip-anything.first-run";

  const state = {
    caps: null,
    inputs: [],
    inspect: null,
    inputProblem: "",
    outDir: "",
    outDirCustom: false,
    job: null,
    jobId: "",
    sse: null,
    started: 0,
    durationS: 0,
    levels: [], // live audio trace: [t, 0..1]
    curve: null,
    stepsBusy: false,
    stage: "",
    curveAnim: 0,
  };

  // ---------------------------------------------------------------- api
  async function api(path, opts = {}) {
    const headers = { Authorization: "Bearer " + TOKEN };
    let body;
    if (opts.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(opts.body);
    }
    const res = await fetch(path, { method: opts.method || (body ? "POST" : "GET"), headers, body });
    let data = {};
    try { data = await res.json(); } catch (e) { data = {}; }
    if (!res.ok) throw new Error(data.error || ("Request failed (" + res.status + ")"));
    return data;
  }
  const tokened = (path) => path + (path.includes("?") ? "&" : "?") + "t=" + encodeURIComponent(TOKEN);

  // ---------------------------------------------------------------- helpers
  function show(name) {
    for (const s of screens) $("screen-" + s).hidden = s !== name;
    for (const b of document.querySelectorAll(".nav-btn")) {
      const current = (name === "setup" || name === "results" ? name : "home") === b.dataset.nav;
      if (current) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    }
    const h = $("screen-" + name).querySelector("h1, .stage");
    if (h) { h.setAttribute("tabindex", "-1"); h.focus({ preventScroll: false }); }
    window.scrollTo({ top: 0, behavior: "instant" });
  }
  let toastTimer = 0;
  function toast(text) {
    const t = $("toast");
    t.textContent = text;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
  }
  let dockTimer = 0;
  function dockSay(text) {
    const d = $("dock-status");
    d.textContent = text;
    clearTimeout(dockTimer);
    dockTimer = setTimeout(() => { d.textContent = ""; }, 3200);
  }
  const mmss = (s) => { s = Math.max(0, Math.floor(s)); return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0"); };
  const basename = (p) => p.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || p;
  function dirname(p) {
    const sep = p.includes("\\") && !p.includes("/") ? "\\" : "/";
    const parts = p.replace(/[\\/]+$/, "").split(/[\\/]/);
    parts.pop();
    return parts.join(sep) || sep;
  }
  function join(dir, name) {
    const sep = dir.includes("\\") && !dir.includes("/") ? "\\" : "/";
    return dir.replace(/[\\/]+$/, "") + sep + name;
  }
  const isVideoName = (n) => /\.(mp4|mkv|mov|webm|ts|m4v|avi|flv|mts)$/i.test(n);
  function minutes(sec) {
    if (sec < 50) return "under a minute";
    const m = Math.round(sec / 60);
    return "about " + m + (m === 1 ? " minute" : " minutes");
  }
  function length(sec) {
    sec = Math.round(sec || 0);
    if (sec < 60) return sec + " s";
    const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
    if (h) return h + " h" + (m ? " " + m + " min" : "");
    return m + " min";
  }
  function size(bytes) {
    if (!bytes) return "";
    if (bytes >= 1e9) return (bytes / 1e9).toFixed(bytes >= 1e10 ? 0 : 1) + " GB";
    if (bytes >= 1e6) return Math.round(bytes / 1e6) + " MB";
    return Math.max(1, Math.round(bytes / 1e3)) + " kB";
  }
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode: the hint just shows again */ } },
  };

  // ---------------------------------------------------------------- first-run hints
  function hints() {
    $("hints").hidden = store.get(FIRST_RUN_KEY) === "done";
  }
  function hintsDone() {
    store.set(FIRST_RUN_KEY, "done");
    $("hints").hidden = true;
  }

  // ---------------------------------------------------------------- caps + ready line
  async function loadCaps() {
    const dot = $("ready-dot"), text = $("ready-text");
    try { state.caps = await api("/api/caps"); } catch (e) { dot.className = "dot off"; text.textContent = e.message; return; }
    const c = state.caps;
    const ready = $("ready");
    for (const b of ready.querySelectorAll("button")) b.remove();
    const missing = [];
    if (!(c.captions && c.whisper === "ready")) missing.push("captions");
    if (!c.ai.ok) missing.push("AI");
    if (!c.ffmpeg.ok) {
      dot.className = "dot off";
      text.textContent = "Video tools missing";
      ready.append(setupLink("Set up"));
    } else {
      dot.className = "dot ok";
      text.textContent = "Ready";
      if (missing.length) ready.append(setupLink("Set up " + missing.join(" / ")));
    }
    $("captions").disabled = !c.captions;
    if (!c.captions) { $("captions").checked = false; $("captions-note").textContent = "Not in this install. Set up adds it."; }
    else if (c.whisper === "download") $("captions-note").textContent = "Words appear on screen as they are said. The first captioned run downloads a 150 MB speech model once.";
    $("count").max = String(c.max_count || 20);
    $("version").textContent = "v" + c.version;
    $("about-version").textContent = "Version " + c.version + (c.window === "webview" ? ", desktop window" : ", in your browser") + ". Served from 127.0.0.1 with a per-launch token.";
    $("quit").hidden = c.window !== "browser";
    if (c.ai.ok && c.ai.cloud) {
      $("ai-cloud").hidden = false;
      $("ai-cloud").textContent = "An API key for " + c.ai.host + " is set: with this on, frames and spoken lines of the candidate moments leave this computer and your key is used for the run.";
      $("ai-note").textContent = "Every clip gets a title and a hook, and the picks get a second opinion.";
    } else if (!c.ai.ok) {
      $("ai-note").textContent = "Titles, hooks and a second opinion on the picks from a local model. Not set up yet: Set up installs Ollama and a model.";
      $("ai").disabled = true;
    }
    briefState();
    homeProblem();
    renderRecent(c.recent || []);
  }

  function setupLink(label) {
    const b = el("button", "link", label);
    b.type = "button";
    b.addEventListener("click", () => openSetup());
    return b;
  }

  /** The home screen's one problem line: tools missing beats a bad input beats nothing. */
  function homeProblem(text) {
    const p = $("home-problem");
    p.textContent = "";
    const c = state.caps;
    if (c && !c.ffmpeg.ok) {
      p.append("The video tools (ffmpeg) are missing, so nothing can run yet. ");
      p.append(setupLink("Set up takes a minute"));
    } else if (text || state.inputProblem) {
      p.textContent = text || state.inputProblem;
    }
    $("start").disabled = !!(c && !c.ffmpeg.ok) || !!state.inputProblem;
  }

  function renderRecent(items) {
    const list = $("recent");
    list.textContent = "";
    $("recent-section").hidden = items.length === 0;
    for (const r of items) {
      const li = el("li");
      const b = el("button", "recent-btn");
      b.type = "button";
      const name = r.inputs.length === 1 ? basename(r.inputs[0]) : r.inputs.length + " recordings";
      b.append(el("span", "r-name", name));
      const when = r.when ? new Date(r.when * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";
      b.append(el("span", "r-meta", (r.clips || 0) + (r.clips === 1 ? " clip" : " clips") + (when ? " · " + when : "")));
      b.append(el("span", "r-path", r.out_dir));
      b.setAttribute("aria-label", "Use " + name + " again, " + (r.clips || 0) + " clips last time");
      b.addEventListener("click", () => {
        setInputs(r.inputs);
        state.outDir = r.out_dir; state.outDirCustom = true; $("out-dir").textContent = r.out_dir;
        $("count").value = r.count; countChanged();
        const len = document.querySelector('input[name=length][value="' + r.length + '"]');
        if (len) len.checked = true;
        const bar = document.querySelector('input[name=bar][value="' + (r.bar || "normal") + '"]');
        if (bar) bar.checked = true;
        $("captions").checked = !!r.captions && !$("captions").disabled;
        $("facecam").checked = r.facecam !== "off";
        $("follow").checked = r.crop !== "center";
        $("ai").checked = !!r.ai && !$("ai").disabled;
        setPreset(r.preset || "");
        briefState();
        $("start").focus();
      });
      li.append(b);
      list.append(li);
    }
  }

  // ---------------------------------------------------------------- inputs
  function setInputs(paths) {
    state.inputs = paths.filter(Boolean);
    state.inspect = null;
    state.inputProblem = "";
    const drop = $("drop");
    const list = $("chosen");
    list.textContent = "";
    const n = state.inputs.length;
    drop.dataset.state = n ? "chosen" : "empty";
    $("drop-empty").hidden = n > 0;
    $("drop-chosen").hidden = n === 0;
    if (n) {
      const first = state.inputs[0];
      $("drop-kicker").textContent = n === 1 ? (isVideoName(first) ? "Recording" : "Folder") : n + " recordings, one session";
      $("drop-name").textContent = n === 1 ? basename(first) : basename(first) + " + " + (n - 1) + " more";
      $("drop-meta").textContent = "Reading…";
      if (n > 1) {
        for (const p of state.inputs.slice(0, 6)) {
          const li = el("li");
          li.append(el("span", "name", basename(p)), el("span", "path", dirname(p)));
          list.append(li);
        }
        if (n > 6) list.append(el("li", "path", "and " + (n - 6) + " more"));
      }
    }
    if (!state.outDirCustom) {
      const first = state.inputs[0] || "";
      state.outDir = first ? join(isVideoName(first) ? dirname(first) : first, "clips") : "";
    }
    $("out-dir").textContent = state.outDir || "a clips folder next to the recording";
    $("home-note").textContent = "";
    homeProblem();
    if (n) inspectInputs(state.inputs);
  }

  async function inspectInputs(paths) {
    let r;
    try { r = await api("/api/inspect", { body: { inputs: paths } }); } catch (e) { $("drop-meta").textContent = ""; return; }
    if (paths !== state.inputs) return; // the user changed their mind meanwhile
    state.inspect = r;
    const items = r.items || [];
    const one = items.length === 1 ? items[0] : null;
    const bits = [];
    if (one && one.kind === "file") {
      if (one.duration_s) bits.push(length(one.duration_s));
      if (one.size_bytes) bits.push(size(one.size_bytes));
      if (one.width && one.height) bits.push(one.width + "×" + one.height);
      if (one.has_audio === false) bits.push("no audio track");
    } else if (one && one.kind === "folder") {
      bits.push(one.videos + (one.videos === 1 ? " recording" : " recordings"));
      if (one.size_bytes) bits.push(size(one.size_bytes));
    } else if (items.length > 1) {
      bits.push(r.videos + " recordings");
      if (r.total_duration_s) bits.push(length(r.total_duration_s));
      if (r.total_size_bytes) bits.push(size(r.total_size_bytes));
    }
    $("drop-meta").textContent = bits.join(" · ");
    if (r.problem) {
      state.inputProblem = r.problem;
      $("drop-kicker").textContent = "Not this one";
    }
    homeProblem();
  }

  async function pick(kind) {
    try {
      const r = await api("/api/pick", { body: { kind } });
      if (r.unsupported) { toast("No file picker is available in this mode. Drop files onto the window app instead."); return; }
      if (!r.paths || !r.paths.length) return;
      if (kind === "out") {
        state.outDir = r.paths[0]; state.outDirCustom = true; $("out-dir").textContent = state.outDir;
        api("/api/prefs", { body: { out_dir: state.outDir } }).catch(() => {});
        return;
      }
      setInputs(r.paths);
    } catch (e) { toast(e.message); }
  }

  function wireDrop() {
    const drop = $("drop");
    const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
    const settle = () => { drop.dataset.state = state.inputs.length ? "chosen" : "empty"; };
    for (const ev of ["dragenter", "dragover"]) drop.addEventListener(ev, (e) => { stop(e); drop.dataset.state = "over"; });
    drop.addEventListener("dragleave", (e) => { stop(e); settle(); });
    let nativeDrop = 0;
    window.caDrop = (paths) => { nativeDrop = Date.now(); if (Array.isArray(paths) && paths.length) setInputs(paths.map(String)); };
    drop.addEventListener("drop", (e) => {
      stop(e);
      const files = Array.from((e.dataTransfer && e.dataTransfer.files) || []);
      const paths = files.map((f) => f.pywebviewFullPath || f.path || "").filter(Boolean);
      if (paths.length) { setInputs(paths); return; }
      settle();
      if (state.caps && state.caps.window === "webview") {
        // the native window hands the paths to caDrop a moment later
        const at = Date.now();
        setTimeout(() => { if (nativeDrop < at) toast("Could not read where those files live. Use Choose instead."); }, 1500);
        return;
      }
      toast("This browser hides where dropped files live. Use Choose instead.");
      pick("files");
    });
    document.addEventListener("dragover", (e) => e.preventDefault());
    document.addEventListener("drop", (e) => e.preventDefault());
  }

  // ---------------------------------------------------------------- settings
  function settings() {
    return {
      count: parseInt($("count").value, 10) || 10,
      length: (document.querySelector("input[name=length]:checked") || {}).value || "normal",
      bar: (document.querySelector("input[name=bar]:checked") || {}).value || "normal",
      captions: $("captions").checked,
      facecam: $("facecam").checked ? "auto" : "off",
      crop: $("follow").checked ? "follow" : "center",
      ai: $("ai").checked,
      preset: (document.querySelector(".chip[aria-pressed=true]") || {}).dataset ? (document.querySelector(".chip[aria-pressed=true]").dataset.preset || "") : "",
      brief: $("ai").checked ? $("brief").value.trim() : "",
    };
  }
  /** Chips: at most one pressed; pressing it again clears. The brief box follows the AI toggle. */
  function setPreset(name) {
    for (const b of document.querySelectorAll(".chip")) b.setAttribute("aria-pressed", String(!!name && b.dataset.preset === name));
  }
  function briefState() {
    const on = $("ai").checked && !$("ai").disabled;
    $("brief").disabled = !on;
    $("brief-note").textContent = on
      ? "The model scores every moment on how well it matches, and the clips say what matched."
      : "Needs AI on: the model scores every moment on how well it matches, and the clips say what matched.";
  }
  function wireLookingFor() {
    for (const b of document.querySelectorAll(".chip")) {
      b.addEventListener("click", () => setPreset(b.getAttribute("aria-pressed") === "true" ? "" : b.dataset.preset));
    }
    $("ai").addEventListener("change", briefState);
    briefState();
  }
  function countChanged() {
    const n = parseInt($("count").value, 10) || 1;
    $("count-out").value = String(n);
    $("start").textContent = "Make " + n + (n === 1 ? " clip" : " clips");
  }

  // ---------------------------------------------------------------- run
  async function start() {
    const s = settings();
    if (!state.inputs.length) { homeProblem("Choose a recording (or a folder of recordings) first."); $("choose-file").focus(); return; }
    if ($("start").disabled) return;
    $("start").disabled = true;
    try {
      const r = await api("/api/jobs", { body: { inputs: state.inputs, out_dir: state.outDir, ...s } });
      state.jobId = r.id;
      state.started = Date.now();
      state.durationS = (state.inspect && state.inspect.total_duration_s) || 0;
      state.levels = [];
      state.curve = null;
      $("disclosure").hidden = !r.disclosure;
      $("disclosure").textContent = r.disclosure || "";
      resetRun();
      show("run");
      listen(r.id);
    } catch (e) {
      homeProblem(e.message);
    } finally {
      $("start").disabled = false;
    }
  }

  function resetRun() {
    state.stage = "";
    setStage("Starting");
    $("eta").textContent = "";
    $("detail").textContent = "";
    $("fill").style.width = "0%";
    $("progress").classList.remove("done");
    $("progress").setAttribute("aria-valuenow", "0");
    $("curve-line").setAttribute("points", "");
    $("curve-spans").textContent = "";
    $("curve-head").setAttribute("x1", "0"); $("curve-head").setAttribute("x2", "0");
    $("curve-dot").hidden = true;
    cancelAnimationFrame(state.curveAnim);
    $("curve-caption").textContent = "Listening for action";
    $("cancel").disabled = false;
    $("cancel").textContent = "Cancel";
  }

  function setStage(text) {
    if (text === state.stage) return;
    state.stage = text;
    const s = $("stage");
    s.textContent = text;
    if (!reduced.matches) { s.classList.remove("swap"); void s.offsetWidth; s.classList.add("swap"); }
  }

  function listen(id) {
    if (state.sse) state.sse.close();
    const es = new EventSource(tokened("/api/jobs/" + id + "/events"));
    state.sse = es;
    const handle = (e) => {
      let ev;
      try { ev = JSON.parse(e.data); } catch (err) { return; }
      onEvent(ev);
    };
    for (const kind of ["start", "progress", "done", "cached", "skipped", "warn", "finished"]) es.addEventListener(kind, handle);
    es.onerror = () => { /* EventSource reconnects with Last-Event-ID; a closed job ends the stream */ };
  }

  function onEvent(ev) {
    if (ev.kind === "finished") {
      state.sse.close(); state.sse = null;
      finish(ev.state, ev.error);
      return;
    }
    const pct = Math.round((ev.fraction || 0) * 100);
    if (ev.label) setStage(ev.label);
    $("fill").style.width = pct + "%";
    $("progress").setAttribute("aria-valuenow", String(pct));
    $("detail").textContent = ev.detail || "";
    if (ev.stage === "probe" && ev.kind === "done") {
      const m = /^(\d+)s/.exec(ev.message || "");
      if (m) state.durationS = parseInt(m[1], 10);
    }
    if (ev.stage === "audio" && ev.kind === "progress" && ev.total) {
      state.durationS = state.durationS || ev.total;
      const db = (ev.extra && typeof ev.extra.level_db === "number") ? ev.extra.level_db : -60;
      const norm = Math.min(1, Math.max(0, (db + 60) / 60));
      state.levels.push([ev.done / ev.total, norm]);
      drawLevels();
    }
    if (ev.stage === "video" && ev.kind === "progress" && ev.total) {
      $("curve-head").setAttribute("x1", String(1000 * ev.done / ev.total));
      $("curve-head").setAttribute("x2", String(1000 * ev.done / ev.total));
      $("curve-caption").textContent = "Watching for motion";
    }
    if (ev.stage === "score" && ev.kind === "done" && ev.extra && ev.extra.curve) {
      state.curve = ev.extra;
      drawCurve(ev.extra);
    }
    if (ev.stage === "render" && ev.kind === "progress") $("curve-caption").textContent = "Making the clips: " + (ev.detail || "");
    updateEta(ev.fraction || 0);
  }

  function updateEta(fraction) {
    const s = settings();
    const guess = (state.durationS / 3600) * 45 + s.count * (s.captions ? 7 : 4) + 3;
    const elapsed = (Date.now() - state.started) / 1000;
    let text;
    if (fraction < 0.08 || elapsed < 4) text = state.durationS ? "Usually " + minutes(guess) + " for a recording this long" : "";
    else {
      const measured = elapsed / fraction - elapsed;
      const w = Math.min(1, fraction * 1.5);
      text = minutes(w * measured + (1 - w) * Math.max(0, guess - elapsed)) + " left";
    }
    $("eta").textContent = text;
  }

  function drawLevels() {
    if (state.curve) return;
    const pts = state.levels.map(([x, y]) => (x * 1000).toFixed(1) + "," + (215 - y * 200).toFixed(1));
    $("curve-line").setAttribute("points", pts.join(" "));
    const last = state.levels[state.levels.length - 1];
    if (last) { $("curve-head").setAttribute("x1", String(last[0] * 1000)); $("curve-head").setAttribute("x2", String(last[0] * 1000)); }
  }

  /** Place the leading dot over the curve at viewBox point (x 0..1000, y 0..220). */
  function dotAt(x, y) {
    const dot = $("curve-dot");
    const svg = $("curve");
    dot.hidden = false;
    dot.style.left = (x / 1000 * svg.clientWidth) + "px";
    dot.style.top = (y / 220 * svg.clientHeight) + "px";
  }

  function drawCurve(data) {
    const n = data.curve.length;
    const total = n * data.step_s || 1;
    const pts = data.curve.map((v, i) => [(i + 0.5) * data.step_s / total * 1000, 215 - Math.min(1, Math.max(0, v)) * 200]);
    const line = $("curve-line");
    const fmt = (k) => pts.slice(0, k).map(([x, y]) => x.toFixed(1) + "," + y.toFixed(1)).join(" ");
    const g = $("curve-spans");
    g.textContent = "";
    const addSpans = () => {
      data.spans.forEach((sp, i) => {
        const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        rect.setAttribute("class", "span");
        rect.setAttribute("x", String(sp.start / total * 1000));
        rect.setAttribute("width", String(Math.max(2, (sp.end - sp.start) / total * 1000)));
        rect.setAttribute("y", "0"); rect.setAttribute("height", "220");
        if (!reduced.matches) rect.style.animationDelay = (i * 90) + "ms";
        const peak = document.createElementNS("http://www.w3.org/2000/svg", "line");
        peak.setAttribute("class", "span-peak");
        const x = String(sp.peak_t / total * 1000);
        peak.setAttribute("x1", x); peak.setAttribute("x2", x);
        peak.setAttribute("y1", String(215 - Math.min(1, sp.score) * 200)); peak.setAttribute("y2", "220");
        g.append(rect, peak);
      });
      const k = data.spans.length;
      $("curve-caption").textContent = k ? k + (k === 1 ? " moment" : " moments") + " cleared the action bar" : "No moment cleared the action bar";
    };
    $("curve-head").setAttribute("x1", "1000"); $("curve-head").setAttribute("x2", "1000");
    cancelAnimationFrame(state.curveAnim);
    if (reduced.matches || n < 2) {
      line.setAttribute("points", fmt(n));
      $("curve-dot").hidden = true;
      addSpans();
      return;
    }
    // the curve draws itself left to right behind a leading dot, then the spans pop in
    const t0 = performance.now(), dur = 900;
    const step = (now) => {
      const f = Math.min(1, (now - t0) / dur);
      const e = 1 - Math.pow(1 - f, 3);
      const k = Math.max(2, Math.round(e * n));
      line.setAttribute("points", fmt(k));
      dotAt(pts[k - 1][0], pts[k - 1][1]);
      if (f < 1) state.curveAnim = requestAnimationFrame(step);
      else { $("curve-dot").hidden = true; addSpans(); }
    };
    state.curveAnim = requestAnimationFrame(step);
  }

  async function cancel() {
    if (!state.jobId) return;
    $("cancel").disabled = true;
    $("cancel").textContent = "Stopping after the current step…";
    try { await api("/api/jobs/" + state.jobId + "/cancel", { body: {} }); } catch (e) { toast(e.message); }
  }

  async function finish(result, error) {
    if (result === "cancelled") { show("home"); $("home-note").textContent = "Stopped. Nothing was left half-written; the analysis so far is saved for next time."; return; }
    if (result === "error") { $("error-text").textContent = error || "Unknown problem."; show("error"); return; }
    // the done moment: the bar sweeps to magenta and the title changes before the cards arrive
    $("fill").style.width = "100%";
    $("progress").setAttribute("aria-valuenow", "100");
    $("progress").classList.add("done");
    setStage("Your clips");
    $("eta").textContent = "";
    $("cancel").disabled = true;
    const settle = reduced.matches ? 0 : 650;
    const [job] = await Promise.all([
      api("/api/jobs/" + state.jobId).catch((e) => e),
      new Promise((r) => setTimeout(r, settle)),
    ]);
    if (job instanceof Error) { $("error-text").textContent = job.message; show("error"); return; }
    state.job = job;
    hintsDone();
    renderResults(job);
    $("nav-results").hidden = false;
    show("results");
    loadCaps();
  }

  // ---------------------------------------------------------------- results
  function renderResults(job) {
    const r = job.result;
    const t = r.timings || {};
    const secs = Math.round(t.total_s || job.elapsed || 0);
    const total = r.total;
    const name = r.input.name || "the recording";
    let sub = total === 0 ? "From " + name : r.ok + " of " + total + (total === 1 ? " clip" : " clips") + " from " + name;
    if (r.input.duration_s) sub += " (" + length(r.input.duration_s) + ")";
    sub += ", in " + (secs < 60 ? secs + " s" : Math.round(secs / 60) + " min") + (r.cached ? " using the saved analysis" : "") + (r.kept ? " (" + r.kept + " unchanged from last time)" : "") + ".";
    $("results-sub").textContent = sub;
    const notes = $("result-notes");
    notes.textContent = "";
    for (const w of (r.warnings || []).concat(job.warnings || [])) {
      if (notes.children.length >= 4) break;
      if (total === 0 && /no action peaks/.test(w)) continue; // the empty state says it in plain words
      if (!Array.from(notes.children).some((c) => c.textContent === w)) notes.append(el("li", "", w));
    }
    const empty = $("empty-results");
    empty.hidden = total !== 0;
    $("grid-help").hidden = total === 0;
    if (total === 0) {
      const low = r.bar === "low";
      $("empty-title").textContent = low ? "Still nothing stood out." : "Nothing stood out.";
      $("empty-text").textContent = low
        ? "Even the low bar found no burst of sound and motion together. A calm recording can be like that; a different stretch of play may do better."
        : "Try a lower bar: quieter moments get through.";
      $("lower-bar").hidden = low;
    }
    const grid = $("grid");
    grid.textContent = "";
    grid.classList.remove("enter");
    const tpl = $("card-tpl");
    let i = 0;
    for (const c of r.clips) {
      const node = tpl.content.firstElementChild.cloneNode(true);
      node.dataset.file = c.file;
      node.style.setProperty("--i", String(Math.min(i, 12)));
      node.tabIndex = i === 0 ? 0 : -1;
      if (c.status === "failed" || !c.file) node.classList.add("failed");
      const video = node.querySelector(".card-video");
      if (c.file) video.src = tokened("/clips/" + job.id + "/" + encodeURIComponent(c.file));
      else { video.remove(); node.querySelector(".card-play").remove(); }
      node.querySelector(".rank").textContent = String(c.rank);
      if (i === 0 && c.file && total > 1) { node.classList.add("best"); node.querySelector(".best").hidden = false; }
      node.querySelector(".time").textContent = mmss(c.start) + "–" + mmss(c.end);
      node.querySelector(".score").textContent = "Score " + c.score.toFixed(2) + " · " + Math.round(c.duration_s || (c.end - c.start)) + " s";
      node.querySelector(".card-title").textContent = c.title || "";
      node.querySelector(".why").textContent = c.why || "";
      node.dataset.peak = String(c.peak_offset || 0);
      node.querySelector(".card-hook").textContent = c.hook || "";
      const match = node.querySelector(".card-match");
      if (c.matches) { match.hidden = false; match.textContent = "Matches: " + c.matches; }
      const label = "Clip " + c.rank + ", " + mmss(c.start) + " to " + mmss(c.end) + (c.why ? ", " + c.why : "") + (c.title ? ", " + c.title : "");
      node.setAttribute("aria-label", label);
      if (c.file) wireCard(node, video);
      else { node.querySelector('[data-act="open"]').hidden = true; node.querySelector('[data-act="reveal"]').hidden = true; node.querySelector('[data-act="delete"]').hidden = true; }
      node.querySelector(".card-body").addEventListener("click", (e) => {
        const b = e.target.closest("[data-act]");
        if (b) cardAction(b.dataset.act, c, node);
      });
      grid.append(node);
      i++;
    }
    if (!reduced.matches) {
      // entrance once: the class comes off afterwards so re-showing the screen does not replay it
      void grid.offsetWidth; grid.classList.add("enter");
      setTimeout(() => grid.classList.remove("enter"), 480 + 50 * Math.min(i, 12) + 100);
    }
    $("export").href = tokened("/clips/" + job.id + "/report.json");
    $("export").hidden = !r.report_file;
    $("dock-status").textContent = "";
  }

  function wireCard(node, video) {
    const play = node.querySelector(".card-play");
    const media = node.querySelector(".card-media");
    const setPlayed = () => { if (video.duration) media.style.setProperty("--played", (video.currentTime / video.duration * 100) + "%"); };
    video.addEventListener("timeupdate", setPlayed);
    // the poster is the clip's own peak frame
    const peak = parseFloat(node.dataset.peak || "0");
    const toPeak = () => { if (video.duration) video.currentTime = Math.min(video.duration - 0.1, Math.max(0.1, peak)); };
    video.addEventListener("loadedmetadata", () => { if (video.paused) toPeak(); }, { once: true });
    let dragging = false;
    media.addEventListener("pointerenter", () => { if (!node.classList.contains("playing") && !reduced.matches) { video.muted = true; video.currentTime = 0; video.play().catch(() => {}); } });
    media.addEventListener("pointerleave", () => { dragging = false; if (!node.classList.contains("playing")) { video.pause(); toPeak(); setPlayed(); } });
    const scrub = (e) => {
      const rect = media.getBoundingClientRect();
      const f = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
      if (video.duration) { video.currentTime = f * video.duration; setPlayed(); }
    };
    media.addEventListener("pointerdown", (e) => { if (e.target === video) { dragging = true; video.pause(); scrub(e); } });
    media.addEventListener("pointermove", (e) => { if (dragging) scrub(e); });
    media.addEventListener("pointerup", () => { dragging = false; });
    const stopOthers = () => {
      for (const other of document.querySelectorAll(".card.playing")) { other.classList.remove("playing"); const v = other.querySelector("video"); v.pause(); v.muted = true; other.querySelector(".card-play").setAttribute("aria-label", "Play with sound"); }
    };
    const soundOn = () => { stopOthers(); node.classList.add("playing"); video.muted = false; video.play().catch(() => {}); play.setAttribute("aria-label", "Pause"); };
    const soundOff = () => { node.classList.remove("playing"); video.pause(); video.muted = true; play.setAttribute("aria-label", "Play with sound"); };
    const toggleSound = () => (node.classList.contains("playing") ? soundOff() : soundOn());
    video.addEventListener("click", toggleSound);
    play.addEventListener("click", toggleSound);
    node.soundOn = soundOn; node.soundOff = soundOff;
    node.addEventListener("keydown", (e) => {
      if (e.target.closest("[data-act], .card-confirm")) return;
      if (e.key === "Enter") { e.preventDefault(); toggleSound(); }
      else if (e.key === " ") { e.preventDefault(); if (!video.paused) soundOff(); else soundOn(); }
      else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        if (e.target !== play) return;
        e.preventDefault(); video.currentTime = Math.max(0, video.currentTime + (e.key === "ArrowRight" ? 2 : -2)); setPlayed();
      }
    });
    video.addEventListener("ended", () => soundOff());
  }

  /** Arrow keys move between cards (roving tabindex); Enter/Space are handled per card. */
  function wireGridKeys() {
    const grid = $("grid");
    grid.addEventListener("keydown", (e) => {
      if (!e.key.startsWith("Arrow")) return;
      if (e.target.matches(".card-play, [data-act]")) return;
      const cards = Array.from(grid.querySelectorAll(".card"));
      const cur = e.target.closest(".card");
      const i = cards.indexOf(cur);
      if (i < 0) return;
      const cols = (getComputedStyle(grid).gridTemplateColumns.match(/\d/g) ? getComputedStyle(grid).gridTemplateColumns.split(" ").length : 1);
      const delta = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols, ArrowUp: -cols }[e.key];
      if (!delta) return;
      const next = cards[Math.min(cards.length - 1, Math.max(0, i + delta))];
      if (next && next !== cur) {
        e.preventDefault();
        cur.tabIndex = -1; next.tabIndex = 0; next.focus();
      }
    });
    grid.addEventListener("focusin", (e) => {
      const card = e.target.closest(".card");
      if (!card) return;
      for (const c of grid.querySelectorAll(".card")) c.tabIndex = c === card ? 0 : -1;
    });
  }

  async function cardAction(act, clip, node) {
    const id = state.jobId;
    try {
      if (act === "open") { await api("/api/jobs/" + id + "/open", { body: { what: "file", file: clip.file } }); dockSay("Opened " + clip.file); }
      else if (act === "reveal") { await api("/api/jobs/" + id + "/open", { body: { what: "reveal", file: clip.file } }); dockSay("Shown in its folder"); }
      else if (act === "copy") { await copyText(clip.post || ""); dockSay("Post text copied"); }
      else if (act === "delete") { node.querySelector(".card-actions").hidden = true; const c = node.querySelector(".card-confirm"); c.hidden = false; c.querySelector('[data-act="delete-yes"]').focus(); }
      else if (act === "delete-no") { node.querySelector(".card-confirm").hidden = true; node.querySelector(".card-actions").hidden = false; node.querySelector('[data-act="delete"]').focus(); }
      else if (act === "delete-yes") {
        node.querySelector(".card-confirm").hidden = true; node.querySelector(".card-actions").hidden = false;
        await api("/api/jobs/" + id + "/delete", { body: { file: clip.file } });
        node.classList.add("gone");
        const v = node.querySelector("video"); if (v) { v.pause(); v.removeAttribute("src"); v.load(); }
        for (const b of node.querySelectorAll("[data-act]")) b.disabled = true;
        node.querySelector(".why").textContent = "Deleted.";
        dockSay("Deleted " + clip.file);
      }
    } catch (e) { toast(e.message); }
  }

  async function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) { await navigator.clipboard.writeText(text); return; }
    const ta = document.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.className = "skip";
    document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }

  // ---------------------------------------------------------------- setup
  async function openSetup() {
    show("setup");
    const list = $("steps");
    list.setAttribute("aria-busy", "true");
    list.textContent = "";
    $("setup-problem").textContent = "";
    try {
      const r = await api("/api/setup");
      list.textContent = "";
      for (const s of r.steps) list.append(stepRow(s));
    } catch (e) { $("setup-problem").textContent = e.message; }
    list.setAttribute("aria-busy", "false");
  }

  function stepRow(s) {
    const node = $("step-tpl").content.firstElementChild.cloneNode(true);
    fillStep(node, s);
    return node;
  }

  function fillStep(node, s) {
    node.classList.toggle("ok", !!s.ok);
    node.dataset.key = s.key;
    node.querySelector(".step-name").textContent = s.label + (s.required ? "" : " (optional)");
    node.querySelector(".step-mark").textContent = "";
    node.querySelector(".step-why").textContent = s.why || "";
    node.querySelector(".step-detail").textContent = (s.ok ? "Ready: " : "") + (s.detail || "");
    node.querySelector(".step-note").textContent = s.ok ? "" : (s.note || "");
    node.querySelector(".step-label").setAttribute("aria-label", (s.ok ? "Ready: " : "Not ready: ") + s.label);
    const btn = node.querySelector(".step-btn");
    const confirmBox = node.querySelector(".step-confirm");
    btn.hidden = true; confirmBox.hidden = true;
    if (!s.ok && (s.fix || s.download)) {
      btn.hidden = false;
      btn.textContent = s.download ? "Download…" : "Install…";
      node.querySelector(".step-cmd").textContent = s.fix ? "Will run: " + s.fix : "Will download " + s.label + " from huggingface.co";
      btn.onclick = () => { btn.hidden = true; confirmBox.hidden = false; node.querySelector(".step-yes").focus(); };
      node.querySelector(".step-no").onclick = () => { confirmBox.hidden = true; btn.hidden = false; btn.focus(); };
      node.querySelector(".step-yes").onclick = () => install(node, s);
    }
  }

  async function install(node, s) {
    if (state.stepsBusy) return;
    state.stepsBusy = true;
    node.classList.add("busy");
    node.querySelector(".step-confirm").hidden = true;
    node.querySelector(".step-detail").textContent = s.download ? "Downloading… this can take a few minutes." : "Installing… this can take a few minutes.";
    try {
      const r = await api("/api/setup/install", { body: { key: s.key } });
      const out = node.querySelector(".step-out");
      out.hidden = !r.output; out.textContent = r.output || "";
      fillStep(node, { ...s, ok: r.ok, detail: r.detail });
      if (r.ok) toast(s.label + " is ready.");
      loadCaps();
    } catch (e) {
      node.querySelector(".step-detail").textContent = e.message;
      node.querySelector(".step-btn").hidden = false;
    } finally {
      node.classList.remove("busy");
      state.stepsBusy = false;
    }
  }

  // ---------------------------------------------------------------- wiring
  function wire() {
    wireDrop();
    wireGridKeys();
    $("choose-file").addEventListener("click", () => pick("files"));
    $("choose-folder").addEventListener("click", () => pick("folder"));
    $("change-file").addEventListener("click", () => pick("files"));
    $("change-out").addEventListener("click", () => pick("out"));
    $("clear-inputs").addEventListener("click", () => { state.outDirCustom = false; setInputs([]); $("choose-file").focus(); });
    $("count").addEventListener("input", countChanged);
    $("start").addEventListener("click", start);
    $("settings").addEventListener("submit", (e) => { e.preventDefault(); start(); });
    $("cancel").addEventListener("click", cancel);
    $("hints-dismiss").addEventListener("click", hintsDone);
    $("open-folder").addEventListener("click", () => api("/api/jobs/" + state.jobId + "/open", { body: { what: "folder" } }).then(() => dockSay("Folder opened")).catch((e) => toast(e.message)));
    $("rerun").addEventListener("click", () => { show("home"); $("count").focus(); });
    $("lower-bar").addEventListener("click", () => { document.querySelector('input[name=bar][value="low"]').checked = true; start(); });
    $("error-back").addEventListener("click", () => show("home"));
    $("error-setup").addEventListener("click", () => openSetup());
    $("about").addEventListener("click", () => show("about"));
    $("hint-about").addEventListener("click", () => show("about"));
    $("about-back").addEventListener("click", () => show("home"));
    $("forget").addEventListener("click", async () => { try { await api("/api/recent/clear", { body: {} }); renderRecent([]); } catch (e) { toast(e.message); } });
    $("quit").addEventListener("click", async () => { try { await api("/api/quit", { body: {} }); } catch (e) { /* server is gone */ } document.body.textContent = "Clip Anything has quit. You can close this tab."; });
    for (const b of document.querySelectorAll(".nav-btn")) b.addEventListener("click", () => {
      if (b.dataset.nav === "setup") openSetup();
      else if (b.dataset.nav === "results" && state.job) show("results");
      else show("home");
    });
    window.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("screen-run").hidden) cancel(); else if (e.key === "Escape" && !$("screen-about").hidden) show("home"); });
    window.addEventListener("resize", () => { if (!$("curve-dot").hidden) $("curve-dot").hidden = true; });
  }

  wire();
  wireLookingFor();
  hints();
  countChanged();
  setInputs([]);
  loadCaps();
})();
