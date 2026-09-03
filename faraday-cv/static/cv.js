/*
 * faraday-cv/cv.js -- colour segmentation entirely in the browser.
 *
 * This is the client-side twin of faradaycv/segmentation.py: an HSV colour
 * box (same convention as OpenCV -- hue 0..179, saturation/value 0..255),
 * a mask, morphology to clean it up, connected components, and a
 * continuity-first blob picker.  Nothing here touches the network; a video
 * dropped into the page never leaves it.
 */

const H_MAX = 179;
const SV_MAX = 255;

/** RGB (0..255 each) -> OpenCV-convention HSV: h in [0,179], s/v in [0,255]. */
function rgbToHsv(r, g, b) {
  const maxc = Math.max(r, g, b);
  const minc = Math.min(r, g, b);
  const delta = maxc - minc;
  const v = maxc;
  const s = maxc === 0 ? 0 : Math.round((delta / maxc) * 255);
  if (delta === 0) return [0, s, v];
  let h60;
  if (maxc === r) h60 = 60 * (((g - b) / delta) % 6);
  else if (maxc === g) h60 = 60 * ((b - r) / delta + 2);
  else h60 = 60 * ((r - g) / delta + 4);
  if (h60 < 0) h60 += 360;
  let h = Math.round(h60 / 2);
  if (h > H_MAX) h -= 180; // 180 wraps to 0 in OpenCV's 0..179 range
  return [h, s, v];
}

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

/** A colour box; h_lo > h_hi means it wraps past red (like ColorRange in Python). */
function normalizeColor(color) {
  return {
    h_lo: clamp(Math.round(color.h_lo), 0, H_MAX),
    h_hi: clamp(Math.round(color.h_hi), 0, H_MAX),
    s_lo: clamp(Math.round(color.s_lo), 0, SV_MAX),
    s_hi: clamp(Math.round(color.s_hi), 0, SV_MAX),
    v_lo: clamp(Math.round(color.v_lo), 0, SV_MAX),
    v_hi: clamp(Math.round(color.v_hi), 0, SV_MAX),
  };
}

function hueInRange(h, loH, hiH) {
  return loH <= hiH ? h >= loH && h <= hiH : h >= loH || h <= hiH;
}

/**
 * Threshold one frame into a 0/255 mask.  `segment` may carry blur/open/close
 * (kernel sizes, pixels) and a roi [x,y,w,h] to restrict the search window --
 * the same knobs as SegmentConfig on the Python side.
 */
function buildMask(imageData, color, segment) {
  const { width: w, height: h, data } = imageData;
  const c = normalizeColor(color);
  const mask = new Uint8Array(w * h);
  const roi = segment && segment.roi;
  const [rx, ry, rw, rh] = roi || [0, 0, w, h];
  const x0 = roi ? Math.max(0, rx) : 0;
  const y0 = roi ? Math.max(0, ry) : 0;
  const x1 = roi ? Math.min(w, rx + rw) : w;
  const y1 = roi ? Math.min(h, ry + rh) : h;

  for (let y = y0; y < y1; y++) {
    let row = y * w;
    for (let x = x0; x < x1; x++) {
      const i = (row + x) * 4;
      const [hh, s, v] = rgbToHsv(data[i], data[i + 1], data[i + 2]);
      if (
        hueInRange(hh, c.h_lo, c.h_hi) &&
        s >= c.s_lo &&
        s <= c.s_hi &&
        v >= c.v_lo &&
        v <= c.v_hi
      ) {
        mask[row + x] = 255;
      }
    }
  }
  return { mask, width: w, height: h };
}

/**
 * 1D sliding-window min (isMin) or max over `len` samples, O(len) via a
 * monotonic deque -- the classic algorithm behind fast erosion/dilation.
 * The window for output index i spans roughly [i - k/2, i + k/2].
 */
function slidingExtreme1D(src, len, k, isMin) {
  const half = Math.floor(k / 2);
  const out = new Uint8Array(len);
  const dq = new Int32Array(len);
  let head = 0,
    tail = 0;
  for (let i = 0; i < len + half; i++) {
    if (i < len) {
      const val = src[i];
      while (
        tail > head &&
        (isMin ? src[dq[tail - 1]] >= val : src[dq[tail - 1]] <= val)
      ) {
        tail--;
      }
      dq[tail++] = i;
    }
    const outIdx = i - half;
    if (outIdx >= 0 && outIdx < len) {
      while (dq[head] < outIdx - half) head++;
      out[outIdx] = src[dq[head]];
    }
  }
  return out;
}

/** Square-kernel erosion (min) or dilation (max), separable row then column pass. */
function boxExtreme(mask, w, h, k, isMin) {
  if (k < 2) return mask;
  const tmp = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    tmp.set(
      slidingExtreme1D(mask.subarray(y * w, y * w + w), w, k, isMin),
      y * w,
    );
  }
  const col = new Uint8Array(h);
  const out = new Uint8Array(w * h);
  for (let x = 0; x < w; x++) {
    for (let y = 0; y < h; y++) col[y] = tmp[y * w + x];
    const colOut = slidingExtreme1D(col, h, k, isMin);
    for (let y = 0; y < h; y++) out[y * w + x] = colOut[y];
  }
  return out;
}

/** Opening (erode then dilate) then closing (dilate then erode), like Python's clean_mask. */
function cleanMask(mask, w, h, segment) {
  let m = mask;
  const openK = (segment && segment.open_ksize) || 0;
  const closeK = (segment && segment.close_ksize) || 0;
  if (openK >= 2) {
    m = boxExtreme(m, w, h, openK, true);
    m = boxExtreme(m, w, h, openK, false);
  }
  if (closeK >= 2) {
    m = boxExtreme(m, w, h, closeK, false);
    m = boxExtreme(m, w, h, closeK, true);
  }
  return m;
}

/** Connected components (4-connectivity) via an iterative flood fill. */
function findBlobs(mask, w, h, minArea) {
  const visited = new Uint8Array(w * h);
  const stack = new Int32Array(w * h);
  const blobs = [];
  for (let start = 0; start < w * h; start++) {
    if (mask[start] === 0 || visited[start]) continue;
    let sp = 0;
    stack[sp++] = start;
    visited[start] = 1;
    let area = 0,
      sumX = 0,
      sumY = 0,
      minX = w,
      minY = h,
      maxX = 0,
      maxY = 0;
    while (sp > 0) {
      const idx = stack[--sp];
      const x = idx % w;
      const y = (idx / w) | 0;
      area++;
      sumX += x;
      sumY += y;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
      if (x > 0 && mask[idx - 1] && !visited[idx - 1]) {
        visited[idx - 1] = 1;
        stack[sp++] = idx - 1;
      }
      if (x < w - 1 && mask[idx + 1] && !visited[idx + 1]) {
        visited[idx + 1] = 1;
        stack[sp++] = idx + 1;
      }
      if (y > 0 && mask[idx - w] && !visited[idx - w]) {
        visited[idx - w] = 1;
        stack[sp++] = idx - w;
      }
      if (y < h - 1 && mask[idx + w] && !visited[idx + w]) {
        visited[idx + w] = 1;
        stack[sp++] = idx + w;
      }
    }
    if (area >= (minArea || 1)) {
      blobs.push({
        cx: sumX / area,
        cy: sumY / area,
        area,
        bbox: [minX, minY, maxX - minX + 1, maxY - minY + 1],
      });
    }
  }
  blobs.sort((a, b) => b.area - a.area);
  return blobs;
}

/** Nearest to `previous` wins (continuity), else the largest -- mirrors select_blob. */
function selectBlob(blobs, previous, maxJumpPx) {
  if (!blobs.length) return null;
  if (!previous) return blobs[0];
  let best = null,
    bestD = Infinity;
  for (const b of blobs) {
    const d = (b.cx - previous[0]) ** 2 + (b.cy - previous[1]) ** 2;
    if (d < bestD) {
      bestD = d;
      best = b;
    }
  }
  if (maxJumpPx != null && Math.sqrt(bestD) > maxJumpPx) return null;
  return best;
}

/** Circular mean of a set of hues (0..179), robust to wraparound near red. */
function circularHueMean(hues) {
  let sx = 0,
    sy = 0;
  for (const h of hues) {
    const ang = (h * 2 * Math.PI) / (H_MAX + 1);
    sx += Math.cos(ang);
    sy += Math.sin(ang);
  }
  let ang = Math.atan2(sy, sx);
  if (ang < 0) ang += 2 * Math.PI;
  return (ang * (H_MAX + 1)) / (2 * Math.PI);
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Suggest a colour box from a click -- the browser twin of sample_color_range. */
function sampleColorRange(imageData, x, y, opts = {}) {
  const radius = opts.radius ?? 6;
  const hTol = opts.hTol ?? 10;
  const sTol = opts.sTol ?? 70;
  const vTol = opts.vTol ?? 80;
  const { width: w, height: h, data } = imageData;
  const x0 = Math.max(0, x - radius),
    x1 = Math.min(w, x + radius + 1);
  const y0 = Math.max(0, y - radius),
    y1 = Math.min(h, y + radius + 1);
  if (x1 <= x0 || y1 <= y0) {
    throw new Error(`click (${x}, ${y}) is outside the ${w}x${h} frame`);
  }
  const hues = [],
    sats = [],
    vals = [];
  for (let yy = y0; yy < y1; yy++) {
    for (let xx = x0; xx < x1; xx++) {
      const i = (yy * w + xx) * 4;
      const [hh, s, v] = rgbToHsv(data[i], data[i + 1], data[i + 2]);
      hues.push(hh);
      sats.push(s);
      vals.push(v);
    }
  }
  const hue = circularHueMean(hues);
  const sat = median(sats);
  const val = median(vals);
  const wrap = (n) =>
    ((Math.round(n) % (H_MAX + 1)) + (H_MAX + 1)) % (H_MAX + 1);
  return normalizeColor({
    h_lo: wrap(hue - hTol),
    h_hi: wrap(hue + hTol),
    s_lo: clamp(sat - sTol, 30, SV_MAX),
    s_hi: SV_MAX,
    v_lo: clamp(val - vTol, 30, SV_MAX),
    v_hi: SV_MAX,
  });
}

/** Mean brightness (V channel) inside a rectangle -- the LED marker trace. */
function ledLevel(imageData, roi) {
  if (!roi) return NaN;
  const { width: w, height: h, data } = imageData;
  const [rx, ry, rw, rh] = roi;
  const x0 = Math.max(0, rx),
    y0 = Math.max(0, ry);
  const x1 = Math.min(w, rx + rw),
    y1 = Math.min(h, ry + rh);
  if (x1 <= x0 || y1 <= y0) return NaN;
  let sum = 0,
    n = 0;
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      const i = (y * w + x) * 4;
      const [, , v] = rgbToHsv(data[i], data[i + 1], data[i + 2]);
      sum += v;
      n++;
    }
  }
  return n ? sum / n : NaN;
}

/** Segment one frame end to end: mask -> clean -> blobs -> best pick. */
function segmentFrame(imageData, color, segment, previous) {
  const { mask, width, height } = buildMask(imageData, color, segment);
  const cleaned = cleanMask(mask, width, height, segment);
  const blobs = findBlobs(
    cleaned,
    width,
    height,
    (segment && segment.min_area) || 1,
  );
  const blob = selectBlob(blobs, previous, segment && segment.max_jump_px);
  return { mask: cleaned, width, height, blobs, blob };
}

/** Tint masked pixels green and mark the chosen centroid -- a preview overlay. */
function overlayPreview(ctx, imageData, mask, blob) {
  const { width: w, height: h } = imageData;
  const out = ctx.createImageData(w, h);
  out.data.set(imageData.data);
  for (let i = 0; i < w * h; i++) {
    if (mask[i]) {
      const p = i * 4;
      out.data[p] = out.data[p] * 0.55 + 0 * 0.45;
      out.data[p + 1] = out.data[p + 1] * 0.55 + 255 * 0.45;
      out.data[p + 2] = out.data[p + 2] * 0.55 + 0 * 0.45;
    }
  }
  ctx.putImageData(out, 0, 0);
  if (blob) {
    ctx.strokeStyle = "#ff0000";
    ctx.lineWidth = 2;
    const cx = blob.cx,
      cy = blob.cy;
    ctx.beginPath();
    ctx.moveTo(cx - 9, cy);
    ctx.lineTo(cx + 9, cy);
    ctx.moveTo(cx, cy - 9);
    ctx.lineTo(cx, cy + 9);
    ctx.stroke();
  }
}

window.faradayCV = {
  rgbToHsv,
  normalizeColor,
  buildMask,
  cleanMask,
  findBlobs,
  selectBlob,
  sampleColorRange,
  ledLevel,
  segmentFrame,
  overlayPreview,
};
