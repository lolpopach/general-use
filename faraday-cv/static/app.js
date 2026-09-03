/* faraday-cv - no-code UI for colour-segmentation video analysis. */

const $ = (id) => document.getElementById(id);

const state = {
  sid: null,
  info: null,
  frame: 0,
  mode: "magnet",
  color: { h_lo: 0, h_hi: 10, s_lo: 80, s_hi: 255, v_lo: 60, v_hi: 255 },
  segment: { blur: 5, open_ksize: 3, close_ksize: 7, min_area: 40, roi: null },
  coil: null,
  ledRoi: null,
  scaleLine: null,
  hasVoltage: false,
  baseImage: null,
  drag: null,
};

const SLIDERS = [
  ["h_lo", "H 하한", 0, 179],
  ["h_hi", "H 상한", 0, 179],
  ["s_lo", "S 하한", 0, 255],
  ["s_hi", "S 상한", 0, 255],
  ["v_lo", "V 하한", 0, 255],
  ["v_hi", "V 상한", 0, 255],
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

function draw() {
  if (!state.baseImage) return;
  ctx.drawImage(state.baseImage, 0, 0, canvas.width, canvas.height);

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
    ctx.stroke();
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

function loadImage(blobOrUrl) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src =
      blobOrUrl instanceof Blob ? URL.createObjectURL(blobOrUrl) : blobOrUrl;
  });
}

let refreshTimer = null;
function scheduleRefresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refreshFrame, 120);
}

async function refreshFrame() {
  if (!state.sid) return;
  try {
    let blob;
    if ($("show-mask").checked) {
      blob = await api(`/api/session/${state.sid}/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          index: state.frame,
          color: state.color,
          segment: state.segment,
        }),
      });
      updateSegStats();
    } else {
      blob = await api(`/api/session/${state.sid}/frame?index=${state.frame}`);
      $("seg-stats").textContent = "";
    }
    state.baseImage = await loadImage(blob);
    draw();
  } catch (err) {
    setHint(`미리보기 실패: ${err.message}`, true);
  }
}

async function updateSegStats() {
  const info = await api(`/api/session/${state.sid}/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      index: state.frame,
      color: state.color,
      segment: state.segment,
      stats: true,
    }),
  });
  const centroid = info.centroid
    ? `중심 (${info.centroid[0].toFixed(1)}, ${info.centroid[1].toFixed(1)})`
    : "검출 없음";
  $("seg-stats").textContent =
    `덩어리 ${info.blobs}개 · 면적 ${info.area}px · ${centroid} · ` +
    `화면의 ${(info.coverage * 100).toFixed(2)}%`;
  if (info.blobs > 1) {
    $("seg-stats").textContent += " · 덩어리가 여러 개면 범위를 좁히세요";
  }
}

/* ------------------------------------------------------------ interaction */

canvas.addEventListener("pointerdown", (event) => {
  if (!state.sid) return;
  const p = canvasPoint(event);
  if (state.mode === "magnet") {
    pickColor(p);
  } else if (state.mode === "coil") {
    state.coil = [p.x, p.y];
    $("coil").value = `${p.x},${p.y}`;
    draw();
  } else {
    state.drag = { start: p, current: p };
    canvas.setPointerCapture(event.pointerId);
  }
});

canvas.addEventListener("pointermove", (event) => {
  if (!state.drag) return;
  state.drag.current = canvasPoint(event);
  draw();
  const { start, current } = state.drag;
  ctx.setLineDash([5, 3]);
  ctx.strokeStyle = "#111";
  ctx.lineWidth = 1.5;
  if (state.mode === "scale") {
    ctx.beginPath();
    ctx.moveTo(start.x, start.y);
    ctx.lineTo(current.x, current.y);
    ctx.stroke();
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
    state.scaleLine = [start.x, start.y, current.x, current.y];
    const px = Math.hypot(current.x - start.x, current.y - start.y);
    const mm = parseFloat($("scale-length").value);
    if (px > 2 && mm > 0) {
      $("mm-per-px").value = (mm / px).toFixed(5);
      setHint(`길이 보정: ${px.toFixed(1)} px = ${mm} mm`);
    }
  } else if (state.mode === "led") {
    state.ledRoi = rect;
    $("led-roi").value = rect.join(",");
  } else if (state.mode === "roi" && rect[2] > 4 && rect[3] > 4) {
    state.segment.roi = rect;
    scheduleRefresh();
  }
  draw();
});

async function pickColor(p) {
  try {
    const out = await api(`/api/session/${state.sid}/pick`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ index: state.frame, x: p.x, y: p.y }),
    });
    state.color = out.color;
    syncSliders();
    setHint("색 범위를 잡았습니다. 슬라이더로 다듬어 보세요.");
    scheduleRefresh();
  } catch (err) {
    setHint(`색 선택 실패: ${err.message}`, true);
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

/* ---------------------------------------------------------------- uploads */

$("video-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  setHint("영상 업로드 중...");
  const body = new FormData();
  body.append("file", file);
  try {
    const out = await api("/api/video", { method: "POST", body });
    state.sid = out.session;
    state.info = out.video;
    canvas.width = out.video.width;
    canvas.height = out.video.height;
    $("frame-slider").max = Math.max(0, out.video.frame_count - 1);
    $("frame-slider").value = 0;
    state.frame = 0;
    $("video-info").innerHTML = infoRows({
      파일: file.name,
      크기: `${out.video.width} × ${out.video.height}`,
      fps: out.video.fps.toFixed(2),
      프레임: out.video.frame_count,
      길이: `${out.video.duration_s.toFixed(2)} s`,
    });
    setHint("자석을 클릭해 색을 지정하세요.");
    updateRunButton();
    await refreshFrame();
  } catch (err) {
    setHint(`업로드 실패: ${err.message}`, true);
  }
});

$("voltage-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file || !state.sid) {
    if (!state.sid) setHint("영상을 먼저 업로드하세요.", true);
    return;
  }
  const body = new FormData();
  body.append("file", file);
  body.append("voltage_unit", $("voltage-unit").value);
  try {
    const out = await api(`/api/session/${state.sid}/voltage`, {
      method: "POST",
      body,
    });
    const v = out.voltage;
    state.hasVoltage = true;
    $("voltage-info").innerHTML = infoRows({
      파일: v.filename,
      샘플: v.samples,
      샘플레이트: `${v.sample_rate_hz.toFixed(1)} Hz`,
      구간: `${v.t_start_s.toFixed(2)} ~ ${v.t_end_s.toFixed(2)} s`,
      범위: `${v.v_min_mV.toFixed(2)} ~ ${v.v_max_mV.toFixed(2)} mV`,
      "읽은 단위": `${v.time_unit} / ${v.voltage_unit}`,
    });
    updateRunButton();
  } catch (err) {
    $("voltage-info").innerHTML = "";
    setHint(`전압 파일 실패: ${err.message}`, true);
  }
});

function infoRows(obj) {
  return Object.entries(obj)
    .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`)
    .join("");
}

function updateRunButton() {
  $("run").disabled = !(state.sid && state.hasVoltage);
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
  const body = {
    color: state.color,
    segment: state.segment,
    calibration: {
      mm_per_px: parseFloat($("mm-per-px").value) || 1,
      coil_px: parsePair($("coil").value),
      smooth_window: parseInt($("smooth").value, 10) || 0,
    },
    led_roi: parseRect($("led-roi").value),
    t0_video: $("t0-video").value || null,
    voltage_unit: $("voltage-unit").value,
    baseline_seconds: parseFloat($("baseline").value) || 0,
    v_min: $("v-min").value || null,
    title: $("title").value || null,
  };
  $("run").disabled = true;
  $("progress").hidden = false;
  $("status").textContent = "분석 중...";
  try {
    await api(`/api/session/${state.sid}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    poll();
  } catch (err) {
    $("status").innerHTML =
      `<span class="error">실행 실패: ${err.message}</span>`;
    updateRunButton();
  }
});

async function poll() {
  try {
    const out = await api(`/api/session/${state.sid}`);
    $("progress").firstElementChild.style.width = `${out.progress}%`;
    $("status").textContent = out.message;
    if (out.state === "running") {
      setTimeout(poll, 500);
      return;
    }
    updateRunButton();
    if (out.state === "error") {
      $("status").innerHTML = `<span class="error">${out.message}</span>`;
      return;
    }
    showResults(out.result);
  } catch (err) {
    $("status").innerHTML = `<span class="error">${err.message}</span>`;
    updateRunButton();
  }
}

const STAT_LABELS = {
  t_max_speed_s: ["최대 속도 시각", "s"],
  max_speed_m_s: ["최대 속도", "m/s"],
  t_max_abs_voltage_s: ["최대 |전압| 시각", "s"],
  max_abs_voltage_mV: ["최대 |전압|", "mV"],
  speed_at_max_voltage_m_s: ["전압 최대일 때 속도", "m/s"],
  voltage_at_max_speed_mV: ["속도 최대일 때 전압", "mV"],
  peak_separation_s: ["두 정점의 시간차", "s"],
  distance_at_max_voltage_mm: ["전압 최대일 때 거리", "mm"],
  min_distance_mm: ["최소 거리", "mm"],
};

function showResults(result) {
  $("results").hidden = false;
  const rows = Object.entries(STAT_LABELS)
    .filter(([key]) => result.stats && result.stats[key] !== undefined)
    .map(
      ([key, [label, unit]]) =>
        `<tr><td>${label}</td><td>${result.stats[key].toFixed(3)} ${unit}</td></tr>`,
    );
  rows.push(
    `<tr><td>검출률</td><td>${(result.detection_rate * 100).toFixed(1)} %</td></tr>`,
  );
  if (result.led_frame !== null && result.led_frame !== undefined) {
    rows.push(
      `<tr><td>LED 점등 프레임</td><td>${result.led_frame} (t₀ = ${result.t0_video_s.toFixed(3)} s)</td></tr>`,
    );
  }
  $("stats-table").innerHTML = rows.join("");
  $("notes").innerHTML = (result.notes || [])
    .map((n) => `<div class="note">${n}</div>`)
    .join("");

  const stamp = Date.now();
  const url = (name) => `/api/session/${state.sid}/file/${name}?t=${stamp}`;
  const figures = [
    "fig2_motion_and_voltage.png",
    "fig3_emf_over_velocity.png",
    "diagnostics.png",
  ];
  $("figures").innerHTML = figures
    .filter((f) => Object.values(result.files || {}).includes(f))
    .map((f) => `<img src="${url(f)}" alt="${f}">`)
    .join("");
  $("downloads").innerHTML = [
    "synced.csv",
    "motion.csv",
    "track.csv",
    "summary.json",
  ]
    .filter((f) => Object.values(result.files || {}).includes(f))
    .map((f) => `<a href="${url(f)}" download>${f}</a>`)
    .join("");
}

/* ---------------------------------------------------------------- wiring */

document.querySelectorAll("button.mode").forEach((btn) => {
  btn.addEventListener("click", () => {
    document
      .querySelectorAll("button.mode")
      .forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.mode = btn.dataset.mode;
    const hints = {
      magnet: "자석 위를 클릭하면 HSV 범위가 잡힙니다.",
      coil: "코일 중심을 클릭하세요.",
      scale: "길이를 아는 구간을 드래그한 뒤 mm 값을 확인하세요.",
      led: "LED가 보이는 사각형을 드래그하세요 (동기화용).",
      roi: "자석이 지나가는 영역만 드래그로 지정하면 오검출이 줄어듭니다.",
    };
    setHint(hints[state.mode] || "");
  });
});

$("clear-roi").addEventListener("click", () => {
  state.segment.roi = null;
  scheduleRefresh();
});

$("frame-slider").addEventListener("input", (event) => {
  state.frame = parseInt(event.target.value, 10);
  $("frame-label").textContent = `프레임 ${state.frame}`;
  scheduleRefresh();
});

$("show-mask").addEventListener("change", scheduleRefresh);

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

$("scale-length").addEventListener("change", () => {
  if (!state.scaleLine) return;
  const [x0, y0, x1, y1] = state.scaleLine;
  const px = Math.hypot(x1 - x0, y1 - y0);
  const mm = parseFloat($("scale-length").value);
  if (px > 2 && mm > 0) $("mm-per-px").value = (mm / px).toFixed(5);
});

buildSliders();
