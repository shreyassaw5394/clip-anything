/* Clip Anything app: plain JS over the local JSON API + Server-Sent Events. No build step. */
(() => {
  "use strict";

  const TOKEN = new URLSearchParams(location.search).get("t") || "";
  const $ = (id) => document.getElementById(id);
  const screens = ["home", "run", "results", "setup", "error"];
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");

  const state = {
    caps: null,
    inputs: [],
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
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  // ---------------------------------------------------------------- caps + ready line
  async function loadCaps() {
    try { state.caps = await api("/api/caps"); } catch (e) { $("ready").textContent = e.message; return; }
    const c = state.caps;
    const ready = $("ready");
    ready.textContent = "";
    const item = (label, ok, fixText) => {
      const li = el("span", "ready-item" + (ok ? "" : " off"));
      li.append(label + " ", el("b", "", ok ? "ready" : "not ready"));
      if (!ok && fixText) {
        li.append(" ");
        const b = el("button", "link", fixText);
        b.type = "button";
        b.addEventListener("click", () => openSetup());
        li.append(b);
      }
      ready.append(li);
    };
    item("Video tools", c.ffmpeg.ok, "Set up");
    item("Captions", c.captions && c.whisper === "ready", c.captions ? "Download" : "Set up");
    item("AI", c.ai.ok, "Set up");
    $("captions").disabled = !c.captions;
    if (!c.captions) $("captions").checked = false;
    $("count").max = String(c.max_count || 20);
    $("version").textContent = "v" + c.version;
    $("quit").hidden = c.window !== "browser";
    if (c.ai.ok && c.ai.cloud) {
      $("ai-cloud").hidden = false;
      $("ai-cloud").textContent = "An API key for " + c.ai.host + " is set: with AI on, frames and spoken lines of the candidate moments leave this computer and your key is used for the run.";
      $("ai-note").textContent = "Titles, hooks and a second opinion on the picks.";
    } else if (!c.ai.ok) {
      $("ai-note").textContent = "Titles, hooks and a second opinion on the picks from a local model. Not set up yet: " + c.ai.reason;
    }
    renderRecent(c.recent || []);
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
        $("count").value = r.count; $("count-out").value = r.count;
        const len = document.querySelector('input[name=length][value="' + r.length + '"]');
        if (len) len.checked = true;
        $("captions").checked = !!r.captions && !$("captions").disabled;
        $("facecam").checked = r.facecam !== "off";
        $("follow").checked = r.crop !== "center";
        $("ai").checked = !!r.ai;
        $("start").focus();
      });
      li.append(b);
      list.append(li);
    }
  }

  // ---------------------------------------------------------------- inputs
  function setInputs(paths) {
    state.inputs = paths.filter(Boolean);
    const drop = $("drop");
    const list = $("chosen");
    list.textContent = "";
    for (const p of state.inputs.slice(0, 6)) {
      const li = el("li");
      li.append(el("span", "name", basename(p)), el("span", "path", dirname(p)));
      list.append(li);
    }
    if (state.inputs.length > 6) list.append(el("li", "path", "and " + (state.inputs.length - 6) + " more"));
    drop.dataset.state = state.inputs.length ? "chosen" : "empty";
    $("drop-line").textContent = state.inputs.length ? (state.inputs.length === 1 ? "Ready. Change it, or" : state.inputs.length + " recordings, in one session. Change them, or") : "Drop it here, or";
    $("clear-inputs").hidden = state.inputs.length === 0;
    if (!state.outDirCustom) {
      const first = state.inputs[0] || "";
      state.outDir = first ? join(isVideoName(first) ? dirname(first) : first, "clips") : "";
    }
    $("out-dir").textContent = state.outDir || "—";
    $("home-problem").textContent = "";
  }

  async function pick(kind) {
    try {
      const r = await api("/api/pick", { body: { kind } });
      if (r.unsupported) { toast("No file picker is available in this mode. Drop files onto the window app instead."); return; }
      if (!r.paths || !r.paths.length) return;
      if (kind === "out") { state.outDir = r.paths[0]; state.outDirCustom = true; $("out-dir").textContent = state.outDir; return; }
      setInputs(r.paths);
    } catch (e) { toast(e.message); }
  }

  function wireDrop() {
    const drop = $("drop");
    const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
    for (const ev of ["dragenter", "dragover"]) drop.addEventListener(ev, (e) => { stop(e); drop.dataset.state = "over"; });
    drop.addEventListener("dragleave", (e) => { stop(e); drop.dataset.state = state.inputs.length ? "chosen" : "empty"; });
    drop.addEventListener("drop", (e) => {
      stop(e);
      const files = Array.from((e.dataTransfer && e.dataTransfer.files) || []);
      const paths = files.map((f) => f.pywebviewFullPath || f.path || "").filter(Boolean);
      if (paths.length) { setInputs(paths); return; }
      drop.dataset.state = state.inputs.length ? "chosen" : "empty";
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
      captions: $("captions").checked,
      facecam: $("facecam").checked ? "auto" : "off",
      crop: $("follow").checked ? "follow" : "center",
      ai: $("ai").checked,
    };
  }

  // ---------------------------------------------------------------- run
  async function start() {
    const s = settings();
    if (!state.inputs.length) { $("home-problem").textContent = "Choose a recording (or a folder of recordings) first."; $("choose-file").focus(); return; }
    $("start").disabled = true;
    try {
      const r = await api("/api/jobs", { body: { inputs: state.inputs, out_dir: state.outDir, ...s } });
      state.jobId = r.id;
      state.started = Date.now();
      state.durationS = 0;
      state.levels = [];
      state.curve = null;
      $("disclosure").hidden = !r.disclosure;
      $("disclosure").textContent = r.disclosure || "";
      resetRun();
      show("run");
      listen(r.id);
    } catch (e) {
      $("home-problem").textContent = e.message;
    } finally {
      $("start").disabled = false;
    }
  }

  function resetRun() {
    $("stage").textContent = "Starting";
    $("eta").textContent = "";
    $("detail").textContent = "";
    $("fill").style.width = "0%";
    $("progress").setAttribute("aria-valuenow", "0");
    $("curve-line").setAttribute("points", "");
    $("curve-spans").textContent = "";
    $("curve-head").setAttribute("x1", "0"); $("curve-head").setAttribute("x2", "0");
    $("curve-caption").textContent = "Listening for action";
    $("cancel").disabled = false;
    $("cancel").textContent = "Cancel";
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
    $("stage").textContent = ev.label || "";
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

  function drawCurve(data) {
    const n = data.curve.length;
    const total = n * data.step_s || 1;
    const pts = data.curve.map((v, i) => ((i + 0.5) * data.step_s / total * 1000).toFixed(1) + "," + (215 - Math.min(1, Math.max(0, v)) * 200).toFixed(1));
    $("curve-line").setAttribute("points", pts.join(" "));
    $("curve-head").setAttribute("x1", "1000"); $("curve-head").setAttribute("x2", "1000");
    const g = $("curve-spans");
    g.textContent = "";
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
  }

  async function cancel() {
    if (!state.jobId) return;
    $("cancel").disabled = true;
    $("cancel").textContent = "Stopping after the current step…";
    try { await api("/api/jobs/" + state.jobId + "/cancel", { body: {} }); } catch (e) { toast(e.message); }
  }

  async function finish(result, error) {
    if (result === "cancelled") { toast("Stopped. Nothing was left half-written."); show("home"); return; }
    if (result === "error") { $("error-text").textContent = error || "Unknown problem."; show("error"); return; }
    try {
      state.job = await api("/api/jobs/" + state.jobId);
    } catch (e) { $("error-text").textContent = e.message; show("error"); return; }
    renderResults(state.job);
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
    let sub = total === 0 ? "No moment in " + (r.input.name || "this recording") + " cleared the action bar."
      : r.ok + " of " + total + (total === 1 ? " clip" : " clips") + " from " + (r.input.name || "the recording");
    if (r.input.duration_s) sub += " (" + mmss(r.input.duration_s) + ")";
    sub += ", in " + (secs < 60 ? secs + " s" : Math.round(secs / 60) + " min") + (r.cached ? " using the saved analysis" : "") + ".";
    $("results-sub").textContent = sub;
    const notes = $("result-notes");
    notes.textContent = "";
    for (const w of (r.warnings || []).concat(job.warnings || [])) {
      if (notes.children.length >= 4) break;
      if (!Array.from(notes.children).some((c) => c.textContent === w)) notes.append(el("li", "", w));
    }
    const grid = $("grid");
    grid.textContent = "";
    const tpl = $("card-tpl");
    for (const c of r.clips) {
      const node = tpl.content.firstElementChild.cloneNode(true);
      node.dataset.file = c.file;
      if (c.status === "failed" || !c.file) node.classList.add("failed");
      const video = node.querySelector(".card-video");
      if (c.file) video.src = tokened("/clips/" + job.id + "/" + encodeURIComponent(c.file));
      else { video.remove(); node.querySelector(".card-play").remove(); }
      node.querySelector(".rank").textContent = String(c.rank).padStart(2, "0");
      node.querySelector(".time").textContent = mmss(c.start) + "–" + mmss(c.end);
      node.querySelector(".score").textContent = "score " + c.score.toFixed(2);
      node.querySelector(".card-title").textContent = c.title || "";
      node.querySelector(".card-why").textContent = c.why || "";
      node.querySelector(".card-hook").textContent = c.hook || "";
      const label = "Clip " + c.rank + ", " + mmss(c.start) + " to " + mmss(c.end) + (c.title ? ", " + c.title : "");
      node.setAttribute("aria-label", label);
      if (c.file) wireCard(node, video);
      else { node.querySelector('[data-act="open"]').hidden = true; node.querySelector('[data-act="reveal"]').hidden = true; node.querySelector('[data-act="delete"]').hidden = true; }
      node.querySelector(".card-actions").addEventListener("click", (e) => {
        const b = e.target.closest("[data-act]");
        if (b) cardAction(b.dataset.act, c, node);
      });
      grid.append(node);
    }
    $("export").href = tokened("/clips/" + job.id + "/report.json");
    $("export").hidden = !r.report_file;
  }

  function wireCard(node, video) {
    const play = node.querySelector(".card-play");
    const media = node.querySelector(".card-media");
    const setPlayed = () => { if (video.duration) media.style.setProperty("--played", (video.currentTime / video.duration * 100) + "%"); };
    video.addEventListener("timeupdate", setPlayed);
    let dragging = false;
    media.addEventListener("pointerenter", () => { if (!node.classList.contains("playing")) { video.muted = true; video.play().catch(() => {}); } });
    media.addEventListener("pointerleave", () => { dragging = false; if (!node.classList.contains("playing")) { video.pause(); video.currentTime = 0; setPlayed(); } });
    const scrub = (e) => {
      const rect = media.getBoundingClientRect();
      const f = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
      if (video.duration) { video.currentTime = f * video.duration; setPlayed(); }
    };
    media.addEventListener("pointerdown", (e) => { if (e.target === video) { dragging = true; video.pause(); scrub(e); } });
    media.addEventListener("pointermove", (e) => { if (dragging) scrub(e); });
    media.addEventListener("pointerup", () => { dragging = false; });
    video.addEventListener("click", () => toggleSound());
    const toggleSound = () => {
      if (node.classList.contains("playing")) { node.classList.remove("playing"); video.pause(); video.muted = true; play.setAttribute("aria-label", "Play with sound"); return; }
      for (const other of document.querySelectorAll(".card.playing")) { other.classList.remove("playing"); const v = other.querySelector("video"); v.pause(); v.muted = true; other.querySelector(".card-play").setAttribute("aria-label", "Play with sound"); }
      node.classList.add("playing"); video.muted = false; video.play().catch(() => {}); play.setAttribute("aria-label", "Pause");
    };
    play.addEventListener("click", toggleSound);
    play.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); video.currentTime = Math.max(0, video.currentTime + (e.key === "ArrowRight" ? 2 : -2)); setPlayed(); }
    });
    video.addEventListener("ended", () => { node.classList.remove("playing"); video.muted = true; play.setAttribute("aria-label", "Play with sound"); });
  }

  async function cardAction(act, clip, node) {
    const id = state.jobId;
    try {
      if (act === "open") await api("/api/jobs/" + id + "/open", { body: { what: "file", file: clip.file } });
      else if (act === "reveal") await api("/api/jobs/" + id + "/open", { body: { what: "reveal", file: clip.file } });
      else if (act === "copy") { await copyText(clip.post || ""); toast("Copied."); }
      else if (act === "delete") {
        if (!confirm("Delete clip " + clip.rank + " (" + clip.file + ")? This removes the file.")) return;
        await api("/api/jobs/" + id + "/delete", { body: { file: clip.file } });
        node.classList.add("gone");
        const v = node.querySelector("video"); if (v) { v.pause(); v.removeAttribute("src"); v.load(); }
        for (const b of node.querySelectorAll("[data-act]")) b.disabled = true;
        node.querySelector(".card-why").textContent = "Deleted.";
        toast("Deleted " + clip.file);
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
    $("choose-file").addEventListener("click", () => pick("files"));
    $("choose-folder").addEventListener("click", () => pick("folder"));
    $("change-out").addEventListener("click", () => pick("out"));
    $("clear-inputs").addEventListener("click", () => { state.outDirCustom = false; setInputs([]); $("choose-file").focus(); });
    $("count").addEventListener("input", () => { $("count-out").value = $("count").value; });
    $("start").addEventListener("click", start);
    $("settings").addEventListener("submit", (e) => { e.preventDefault(); start(); });
    $("cancel").addEventListener("click", cancel);
    $("open-folder").addEventListener("click", () => api("/api/jobs/" + state.jobId + "/open", { body: { what: "folder" } }).catch((e) => toast(e.message)));
    $("rerun").addEventListener("click", () => { show("home"); $("count").focus(); });
    $("error-back").addEventListener("click", () => show("home"));
    $("forget").addEventListener("click", async () => { try { await api("/api/recent/clear", { body: {} }); renderRecent([]); } catch (e) { toast(e.message); } });
    $("quit").addEventListener("click", async () => { try { await api("/api/quit", { body: {} }); } catch (e) { /* server is gone */ } document.body.textContent = "Clip Anything has quit. You can close this tab."; });
    for (const b of document.querySelectorAll(".nav-btn")) b.addEventListener("click", () => {
      if (b.dataset.nav === "setup") openSetup();
      else if (b.dataset.nav === "results" && state.job) show("results");
      else show("home");
    });
    window.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("screen-run").hidden) cancel(); });
  }

  wire();
  setInputs([]);
  loadCaps();
})();
