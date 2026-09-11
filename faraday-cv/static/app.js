/* faraday-cv - no-code UI for colour-segmentation video analysis.
 *
 * The video is decoded and segmented entirely in this page (see cv.js and
 * tracker.js); only the resulting track and the separately-chosen voltage
 * file are ever sent to the server, at "run" time.
 */

const $ = (id) => document.getElementById(id);

const state = {
  tracker: null,
  duration: 0,
  frame: 0, // seconds
  mode: "magnet",
  color: { h_lo: 0, h_hi: 10, s_lo: 80, s_hi: 255, v_lo: 60, v_hi: 255 },
  segment: {
    blur: 5,
    open_ksize: 3,
    close_ksize: 7,
    min_area: 40,
    max_jump_px: null,
    roi: null,
  },
  coil: null,
  ledRoi: null,
  scaleLine: null,
  // Whether mm/px means anything yet.  It starts at 1, which is not a
  // measurement -- it just means "no scale set, so a pixel counts as a mm".
  calibrated: false,
  trimStart: null, // seconds; null means "from the start"
  trimEnd: null, //   seconds; null means "to the end"
  voltageFile: null,
  sid: null,
  lastPainted: null,
  drag: null,
};

const SLIDERS = [
  ["h_lo", "H min", 0, 179],
  ["h_hi", "H max", 0, 179],
  ["s_lo", "S min", 0, 255],
  ["s_hi", "S max", 0, 255],
  ["v_lo", "V min", 0, 255],
  ["v_hi", "V max", 0, 255],
];

/* ------------------------------------------------------------------ api */

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const type = res.headers.get("content-type") || "";
  if (!res.ok) {
    const detail = type.includes("json")
      ? (await res.json()).error
      : await res.text();
    throw new Error(detail || res.statusText);
  }
  return type.includes("json") ? res.json() : res.blob();
}

/* --------------------------------------------------------------- canvas */

const canvas = $("canvas");
const ctx = canvas.getContext("2d");

function canvasPoint(event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: Math.round(((event.clientX - rect.left) / rect.width) * canvas.width),
    y: Math.round(((event.clientY - rect.top) / rect.height) * canvas.height),
  };
}

/** A readable caption on the canvas, on its own plate so it survives any
 * background the frame happens to have under it. */
function drawLengthLabel(x, y, text) {
  ctx.font = "13px sans-serif";
  const width = ctx.measureText(text).width;
  const px = Math.min(Math.max(x + 8, 2), canvas.width - width - 8);
  const py = Math.min(Math.max(y - 10, 16), canvas.height - 6);
  ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
  ctx.fillRect(px - 4, py - 13, width + 8, 18);
  ctx.fillStyle = "#2e7d32";
  ctx.fillText(text, px, py);
}

/** Redraw the ROI/LED/scale/coil markers on top of whatever is on canvas now. */
function drawMarkers() {
  if (state.segment.roi) {
    const [x, y, w, h] = state.segment.roi;
    ctx.setLineDash([6, 4]);
    ctx.strokeStyle = "#1f4e79";
    ctx.lineWidth = 2;
    ctx.strokeRect(x, y, w, h);
    ctx.setLineDash([]);
  }
  if (state.ledRoi) {
    const [x, y, w, h] = state.ledRoi;
    ctx.strokeStyle = "#e0a300";
    ctx.lineWidth = 2;
    ctx.strokeRect(x, y, w, h);
    ctx.fillStyle = "#e0a300";
    ctx.font = "13px sans-serif";
    ctx.fillText("LED", x, Math.max(12, y - 4));
  }
  if (state.scaleLine) {
    const [x0, y0, x1, y1] = state.scaleLine;
    ctx.strokeStyle = "#2e7d32";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    // end caps, so what was measured is unambiguous at both ends
    for (const [cx, cy] of [
      [x0, y0],
      [x1, y1],
    ]) {
      ctx.moveTo(cx - 4, cy - 4);
      ctx.lineTo(cx + 4, cy + 4);
      ctx.moveTo(cx + 4, cy - 4);
      ctx.lineTo(cx - 4, cy + 4);
    }
    ctx.stroke();
    drawLengthLabel(x1, y1, lengthLabel(scaleLinePx()));
  }
  if (state.coil) {
    const [x, y] = state.coil;
    ctx.strokeStyle = "#b3261e";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, y, 14, 0, Math.PI * 2);
    ctx.moveTo(x - 20, y);
    ctx.lineTo(x + 20, y);
    ctx.moveTo(x, y - 20);
    ctx.lineTo(x, y + 20);
    ctx.stroke();
  }
}

/** Repaint the cached frame/mask (no video seek) then the markers on top. */
function redrawFromCache() {
  if (state.lastPainted) ctx.putImageData(state.lastPainted, 0, 0);
  drawMarkers();
}

/* ----------------------------------------------------------- length scale */

function mmPerPx() {
  const value = parseFloat($("mm-per-px").value);
  return Number.isFinite(value) && value > 0 ? value : null;
}

/** Length of the drawn scale line in pixels, or 0 if there is none. */
function scaleLinePx() {
  if (!state.scaleLine) return 0;
  const [x0, y0, x1, y1] = state.scaleLine;
  return Math.hypot(x1 - x0, y1 - y0);
}

/**
 * How wide the whole frame is at this scale.
 *
 * A mistyped length is the one calibration mistake with no visible symptom:
 * every distance and speed comes out wrong by the same factor, the curves
 * keep their shape, and the figures look perfectly healthy. The frame width
 * is the one number the student can check against the room in front of them.
 */
function frameWidthNote(scale) {
  const width = canvas.width * scale; // mm
  if (!Number.isFinite(width) || width <= 0) return "";
  const shown =
    width >= 1000 ? `${(width / 1000).toFixed(2)} m` : `${width.toFixed(0)} mm`;
  return `  ·  whole frame ≈ ${shown} wide`;
}

/** How a dragged length reads: pixels, plus millimetres once calibrated. */
function lengthLabel(px) {
  const scale = state.calibrated ? mmPerPx() : null;
  return scale
    ? `${px.toFixed(1)} px · ${(px * scale).toFixed(1)} mm`
    : `${px.toFixed(1)} px`;
}

/**
 * Show what was measured, and turn it into a scale once the user says what
 * the line really is.
 *
 * Nothing is applied until they type a length. A line by itself carries no
 * scale, and the previous default of "assume 100 mm" quietly multiplied every
 * distance and speed in the results by however wrong that guess was.
 */
function updateScalePanel() {
  const panel = $("scale-panel");
  panel.hidden = !state.scaleLine;
  if (!state.scaleLine) return;

  const px = scaleLinePx();
  $("scale-px").textContent = `${px.toFixed(1)} px`;

  const mm = parseFloat($("scale-mm").value);
  if (Number.isFinite(mm) && mm > 0 && px > 2) {
    const scale = mm / px;
    $("mm-per-px").value = scale.toFixed(5);
    state.calibrated = true;
    $("scale-result").textContent =
      `→ ${scale.toFixed(5)} mm/px${frameWidthNote(scale)}`;
  } else if (state.calibrated) {
    // already calibrated, so this drag is just a measurement
    $("scale-result").textContent =
      `≈ ${(px * mmPerPx()).toFixed(1)} mm at the current scale`;
  } else {
    $("scale-result").textContent = "type the real length to set the scale";
  }
}

let refreshTimer = null;
function scheduleRefresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refreshFrame, 120);
}

async function refreshFrame() {
  if (!state.tracker) return;
  try {
    const img = await state.tracker.frameImageData(state.frame); // paints the raw frame
    if ($("show-mask").checked) {
      const { mask, blobs, blob } = window.faradayCV.segmentFrame(
        img,
        state.color,
        state.segment,
        null,
      );
      window.faradayCV.overlayPreview(ctx, img, mask, blob);
      updateSegStats(blobs, blob, mask);
    } else {
      $("seg-stats").textContent = "";
    }
    state.lastPainted = ctx.getImageData(0, 0, canvas.width, canvas.height);
    drawMarkers();
  } catch (err) {
    setHint(`Preview failed: ${err.message}`, true);
  }
}

function updateSegStats(blobs, blob, mask) {
  let on = 0;
  for (let i = 0; i < mask.length; i++) if (mask[i]) on++;
  const centroid = blob
    ? `centre (${blob.cx.toFixed(1)}, ${blob.cy.toFixed(1)})`
    : "nothing detected";
  $("seg-stats").textContent =
    `${blobs.length} blob(s) · area ${blob ? blob.area : 0} px · ${centroid} · ` +
    `${((on / mask.length) * 100).toFixed(2)}% of the frame`;
  if (blobs.length > 1) {
    $("seg-stats").textContent += " · more than one blob: narrow the range";
  }
}

/* ------------------------------------------------------------ interaction */

canvas.addEventListener("pointerdown", (event) => {
  if (!state.tracker) return;
  const p = canvasPoint(event);
  if (state.mode === "magnet") {
    pickColor(p);
  } else if (state.mode === "coil") {
    state.coil = [p.x, p.y];
    $("coil").value = `${p.x},${p.y}`;
    redrawFromCache();
  } else {
    state.drag = { start: p, current: p };
    canvas.setPointerCapture(event.pointerId);
  }
});

canvas.addEventListener("pointermove", (event) => {
  if (!state.drag) return;
  state.drag.current = canvasPoint(event);
  redrawFromCache();
  const { start, current } = state.drag;
  ctx.setLineDash([5, 3]);
  ctx.strokeStyle = "#111";
  ctx.lineWidth = 1.5;
  if (state.mode === "scale") {
    ctx.beginPath();
    ctx.moveTo(start.x, start.y);
    ctx.lineTo(current.x, current.y);
    ctx.stroke();
    ctx.setLineDash([]);
    drawLengthLabel(
      current.x,
      current.y,
      lengthLabel(Math.hypot(current.x - start.x, current.y - start.y)),
    );
  } else {
    ctx.strokeRect(
      Math.min(start.x, current.x),
      Math.min(start.y, current.y),
      Math.abs(current.x - start.x),
      Math.abs(current.y - start.y),
    );
  }
  ctx.setLineDash([]);
});

canvas.addEventListener("pointerup", () => {
  if (!state.drag) return;
  const { start, current } = state.drag;
  state.drag = null;
  const rect = [
    Math.min(start.x, current.x),
    Math.min(start.y, current.y),
    Math.abs(current.x - start.x),
    Math.abs(current.y - start.y),
  ];
  if (state.mode === "scale") {
    const px = Math.hypot(current.x - start.x, current.y - start.y);
    // a stray click is not a measurement
    state.scaleLine = px > 2 ? [start.x, start.y, current.x, current.y] : null;
    // The length belonged to the previous line; carrying it over would let a
    // new drag re-scale everything off a number that was never about it.
    $("scale-mm").value = "";
    updateScalePanel();
    if (state.scaleLine) {
      $("scale-mm").focus();
      $("scale-mm").select();
    }
  } else if (state.mode === "led") {
    state.ledRoi = rect;
    $("led-roi").value = rect.join(",");
  } else if (state.mode === "roi" && rect[2] > 4 && rect[3] > 4) {
    state.segment.roi = rect;
    scheduleRefresh();
  }
  redrawFromCache();
});

async function pickColor(p) {
  try {
    state.color = await state.tracker.pickColorAt(state.frame, p.x, p.y, {
      radius: 6,
      hTol: 10,
      sTol: 70,
      vTol: 80,
    });
    syncSliders();
    setHint("Colour range picked. Fine-tune it with the sliders.");
    scheduleRefresh();
  } catch (err) {
    setHint(`Colour pick failed: ${err.message}`, true);
  }
}

function buildSliders() {
  const box = $("color-sliders");
  box.innerHTML = "";
  for (const [key, label, min, max] of SLIDERS) {
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML =
      `<span>${label}</span>` +
      `<input type="range" min="${min}" max="${max}" value="${state.color[key]}" data-key="${key}">` +
      `<span id="val-${key}">${state.color[key]}</span>`;
    box.appendChild(row);
    row.querySelector("input").addEventListener("input", (event) => {
      state.color[key] = parseInt(event.target.value, 10);
      $(`val-${key}`).textContent = state.color[key];
      scheduleRefresh();
    });
  }
}

function syncSliders() {
  for (const [key] of SLIDERS) {
    const input = document.querySelector(`input[data-key="${key}"]`);
    if (input) input.value = state.color[key];
    const out = $(`val-${key}`);
    if (out) out.textContent = state.color[key];
  }
}

function setHint(text, isError = false) {
  const el = $("hint");
  el.textContent = text;
  el.className = isError ? "hint error" : "hint";
}

/* ------------------------------------------------------------------ video */

function updateFpsStep() {
  const fps = parseFloat($("track-fps").value) || 30;
  $("frame-slider").step = (1 / fps).toFixed(4);
}

/** Echo the chosen file next to our own label-button, as the native file
 * control used to do before we replaced it to control its wording. */
function showFileName(spanId, file) {
  $(spanId).textContent = file ? file.name : "No file chosen";
}

/* ------------------------------------------------------------ trim range */

/** Read a trim box: blank (or nonsense) means "no limit", i.e. null. */
function readTrimField(id) {
  const value = parseFloat($(id).value);
  return Number.isFinite(value) && value >= 0 ? value : null;
}

/** Restate the range the run will actually use, resolved the same way the
 * tracker resolves it -- so what is shown is what will happen, including
 * the fallback to the full clip when the two ends are the wrong way round. */
function updateRangeInfo() {
  const info = $("range-info");
  if (!state.tracker) {
    info.textContent = "";
    return;
  }
  const { start, end } = window.faradayTracker.resolveRange(
    state.duration,
    state.trimStart,
    state.trimEnd,
  );
  const full = end - start >= state.duration - 1e-3;
  info.textContent = full
    ? `Analysing the whole clip (${state.duration.toFixed(2)} s)`
    : `Analysing ${start.toFixed(2)} s → ${end.toFixed(2)} s ` +
      `(${(end - start).toFixed(2)} s of ${state.duration.toFixed(2)} s)`;
  const backwards =
    state.trimStart !== null &&
    state.trimEnd !== null &&
    state.trimEnd <= state.trimStart;
  if (backwards) {
    info.textContent += " — end is not after start, so the range was ignored";
  }
}

function syncTrimFromFields() {
  state.trimStart = readTrimField("trim-start");
  state.trimEnd = readTrimField("trim-end");
  updateRangeInfo();
}

$("video-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  showFileName("video-file-name", file);
  setHint("Loading the video...");
  if (state.tracker) state.tracker.dispose();
  const tracker = new VideoTracker(file, canvas);
  try {
    const meta = await tracker.load();
    state.tracker = tracker;
    state.duration = meta.duration;
    state.frame = 0;
    // a range picked for the previous clip means nothing for this one
    $("trim-start").value = "";
    $("trim-end").value = "";
    syncTrimFromFields();
    updateFpsStep();
    $("frame-slider").max = meta.duration;
    $("frame-slider").value = 0;
    $("frame-label").textContent = "t = 0.00 s";
    $("video-info").innerHTML = infoRows({
      Size: `${meta.width} × ${meta.height}`,
      Duration: `${meta.duration.toFixed(2)} s`,
    });
    setHint("Click the magnet to pick its colour.");
    updateRunButton();
    await refreshFrame();
  } catch (err) {
    state.tracker = null;
    setHint(`Could not open the video: ${err.message}`, true);
  }
});

$("voltage-file").addEventListener("change", (event) => {
  const file = event.target.files[0] || null;
  state.voltageFile = file;
  showFileName("voltage-file-name", file);
  $("voltage-info").innerHTML = file
    ? infoRows({ Size: `${(file.size / 1024).toFixed(1)} KB` })
    : "";
  updateRunButton();
});

function infoRows(obj) {
  return Object.entries(obj)
    .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`)
    .join("");
}

function updateRunButton() {
  $("run").disabled = !(state.tracker && state.voltageFile);
}

/* -------------------------------------------------------------- analysis */

$("run").addEventListener("click", async () => {
  const parsePair = (text) => {
    const parts = text.split(",").map((v) => parseFloat(v.trim()));
    return parts.length === 2 && parts.every(Number.isFinite) ? parts : null;
  };
  const parseRect = (text) => {
    const parts = text.split(",").map((v) => parseFloat(v.trim()));
    return parts.length === 4 && parts.every(Number.isFinite) ? parts : null;
  };
  const ledRoi = parseRect($("led-roi").value);
  const fps = parseFloat($("track-fps").value) || 30;

  $("run").disabled = true;
  $("progress").hidden = false;
  $("progress").firstElementChild.style.width = "0%";
  $("status").textContent = "Tracking the magnet in the browser...";

  let track;
  try {
    track = await state.tracker.trackAll({
      color: state.color,
      segment: state.segment,
      ledRoi,
      fps,
      startTime: state.trimStart,
      endTime: state.trimEnd,
      onProgress: (done, total) => {
        const pct = (100 * done) / Math.max(total, 1);
        $("progress").firstElementChild.style.width = `${pct.toFixed(0)}%`;
        $("status").textContent = `Tracking... ${done}/${total} frames`;
      },
    });
  } catch (err) {
    $("status").innerHTML =
      `<span class="error">Tracking failed: ${err.message}</span>`;
    updateRunButton();
    return;
  }

  $("progress").firstElementChild.style.width = "100%";
  $("status").textContent = "Computing the physics on the server...";

  const config = {
    calibration: {
      mm_per_px: parseFloat($("mm-per-px").value) || 1,
      coil_px: parsePair($("coil").value),
      smooth_window: parseInt($("smooth").value, 10) || 0,
    },
    led_roi: ledRoi,
    t0_video: $("t0-video").value || null,
    voltage_unit: $("voltage-unit").value,
    baseline_seconds: parseFloat($("baseline").value) || 0,
    v_min: $("v-min").value || null,
    title: $("title").value || null,
  };

  const body = new FormData();
  body.append("track", JSON.stringify(track));
  body.append("config", JSON.stringify(config));
  if (state.voltageFile) body.append("voltage", state.voltageFile);

  try {
    const out = await api("/api/analyze", { method: "POST", body });
    state.sid = out.session;
    $("status").textContent = "Done";
    showResults(out.result);
  } catch (err) {
    $("status").innerHTML =
      `<span class="error">Analysis failed: ${err.message}</span>`;
  } finally {
    updateRunButton();
  }
});

/* label, displayed unit, factor from the SI-named key to that unit. The
   figures are drawn in cm and cm/s (the units the paper uses), so the table
   beside them reads in the same ones -- the CSVs stay metres and m/s. */
const STAT_LABELS = {
  t_max_speed_s: ["Time of peak speed", "s", 1],
  max_speed_m_s: ["Peak speed", "cm/s", 100],
  t_max_abs_voltage_s: ["Time of peak |voltage|", "s", 1],
  max_abs_voltage_mV: ["Peak |voltage|", "mV", 1],
  speed_at_max_voltage_m_s: ["Speed at peak voltage", "cm/s", 100],
  voltage_at_max_speed_mV: ["Voltage at peak speed", "mV", 1],
  peak_separation_s: ["Separation between the two peaks", "s", 1],
  distance_at_max_voltage_mm: ["Distance at peak voltage", "cm", 0.1],
  min_distance_mm: ["Minimum distance", "cm", 0.1],
};

const FIGURE_CAPTIONS = {
  "fig2_motion_and_voltage_detail.png":
    "Fig. 2 — distance, speed and induced voltage, three periods around the " +
    "strongest emf peak.",
  "fig2_motion_and_voltage.png":
    "Fig. 2 (whole record) — distance, speed and induced voltage vs time.",
  "fig3_emf_over_velocity_detail.png":
    "Fig. 3 — induced voltage ℰ and ℰ/v, the same window as Fig. 2.",
  "fig3_emf_over_velocity.png":
    "Fig. 3 (whole record) — induced voltage ℰ and ℰ/v ∝ −N dΦ/dx.",
  "diagnostics.png":
    "Diagnostics — centroid, blob area and the LED trace. Check these before " +
    "trusting the figures above.",
};

function showResults(result) {
  $("results").hidden = false;
  const rows = Object.entries(STAT_LABELS)
    .filter(([key]) => result.stats && result.stats[key] !== undefined)
    .map(
      ([key, [label, unit, factor]]) =>
        `<tr><td>${label}</td><td>${(result.stats[key] * factor).toFixed(
          unit === "s" ? 3 : 2,
        )} ${unit}</td></tr>`,
    );
  rows.push(
    `<tr><td>Detection rate</td><td>${(result.detection_rate * 100).toFixed(1)} %</td></tr>`,
  );
  if (result.led_frame !== null && result.led_frame !== undefined) {
    rows.push(
      `<tr><td>LED-on frame</td><td>${result.led_frame} (t₀ = ${result.t0_video_s.toFixed(3)} s)</td></tr>`,
    );
  }
  $("stats-table").innerHTML = rows.join("");
  $("notes").innerHTML = (result.notes || [])
    .map((n) => `<div class="note">${n}</div>`)
    .join("");

  const stamp = Date.now();
  const url = (name) => `/api/session/${state.sid}/file/${name}?t=${stamp}`;
  // Close-ups first: on a record of several swings they are the readable
  // ones, and the whole-record copies below them are the context.
  const written = new Set(Object.values(result.files || {}));
  $("figures").innerHTML = Object.keys(FIGURE_CAPTIONS)
    .filter((f) => written.has(f))
    .map(
      (f) =>
        `<figure><img src="${url(f)}" alt="${FIGURE_CAPTIONS[f]}">` +
        `<figcaption>${FIGURE_CAPTIONS[f]}</figcaption></figure>`,
    )
    .join("");
  $("download-error").hidden = true;
  $("downloads").innerHTML = [
    "synced.csv",
    "motion.csv",
    "track.csv",
    "summary.json",
  ]
    .filter((f) => written.has(f))
    .map((f) => `<a href="${url(f)}" data-file="${f}" download>${f}</a>`)
    .join("");
}

/* Fetch the file rather than letting the browser follow the link, so that a
   result the server no longer has produces a sentence the reader can act on.
   Left to itself the browser downloads the JSON error body instead -- and
   renames it to match, which is where a "synced.json" that will not open
   comes from. */
async function downloadResult(href, name) {
  const problem = $("download-error");
  problem.hidden = true;
  try {
    const response = await fetch(href);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error || `the server answered ${response.status}`);
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    // Revoking straight away cancels the save in some browsers.
    setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
  } catch (err) {
    problem.textContent = `${name} could not be downloaded: ${err.message}`;
    problem.hidden = false;
  }
}

$("downloads").addEventListener("click", (event) => {
  const link = event.target.closest("a[data-file]");
  if (!link) return;
  event.preventDefault();
  downloadResult(link.href, link.dataset.file);
});

/* ---------------------------------------------------------------- wiring */

document.querySelectorAll("button.mode").forEach((btn) => {
  btn.addEventListener("click", () => {
    document
      .querySelectorAll("button.mode")
      .forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.mode = btn.dataset.mode;
    const hints = {
      magnet: "Click on the magnet to pick an HSV range.",
      coil: "Click the centre of the coil.",
      scale:
        "Drag across something whose real size you know (a ruler, the coil), " +
        "then type that length below the canvas.",
      led: "Drag a rectangle over the LED (used for syncing).",
      roi: "Drag around just the area the magnet passes through to cut false detections.",
    };
    setHint(hints[state.mode] || "");
  });
});

$("clear-roi").addEventListener("click", () => {
  state.segment.roi = null;
  scheduleRefresh();
});

$("frame-slider").addEventListener("input", (event) => {
  state.frame = parseFloat(event.target.value);
  $("frame-label").textContent = `t = ${state.frame.toFixed(2)} s`;
  scheduleRefresh();
});

$("show-mask").addEventListener("change", scheduleRefresh);
$("track-fps").addEventListener("change", updateFpsStep);

for (const id of ["trim-start", "trim-end"]) {
  $(id).addEventListener("change", syncTrimFromFields);
}

for (const [buttonId, fieldId] of [
  ["trim-start-here", "trim-start"],
  ["trim-end-here", "trim-end"],
]) {
  $(buttonId).addEventListener("click", () => {
    if (!state.tracker) return;
    $(fieldId).value = state.frame.toFixed(2);
    syncTrimFromFields();
  });
}

for (const [id, key] of [
  ["min-area", "min_area"],
  ["blur", "blur"],
  ["open-k", "open_ksize"],
  ["close-k", "close_ksize"],
]) {
  $(id).addEventListener("change", (event) => {
    state.segment[key] = parseInt(event.target.value, 10) || 0;
    scheduleRefresh();
  });
}

$("max-jump").addEventListener("change", (event) => {
  const value = parseFloat(event.target.value);
  state.segment.max_jump_px =
    Number.isFinite(value) && value > 0 ? value : null;
  scheduleRefresh();
});

// live, so the scale follows each keystroke rather than waiting for a blur
$("scale-mm").addEventListener("input", () => {
  updateScalePanel();
  redrawFromCache();
});

$("scale-clear").addEventListener("click", () => {
  state.scaleLine = null;
  $("scale-mm").value = "";
  updateScalePanel();
  redrawFromCache();
});

// typing mm/px straight in is its own way of calibrating
$("mm-per-px").addEventListener("change", () => {
  state.calibrated = mmPerPx() !== null;
  $("scale-mm").value = "";
  updateScalePanel();
  redrawFromCache();
});

buildSliders();
