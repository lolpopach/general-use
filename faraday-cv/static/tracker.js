/*
 * faraday-cv/tracker.js -- walks a local video frame by frame in the
 * browser, running static/cv.js's colour segmentation on each one.
 *
 * The video never leaves the machine: it is opened from a local File via
 * a blob: URL, decoded by the browser's own <video> element, and only the
 * resulting numbers (a centroid and an LED brightness per frame) are ever
 * sent to the server.
 */

/**
 * Settle what stretch of the clip to analyse, in seconds.
 *
 * Anything missing, unparseable, or out of order falls back to the whole
 * video rather than silently analysing nothing: an empty box in the UI means
 * "no limit", and a range whose end is not after its start is not a request
 * to track zero frames, it is a range the user has not finished setting.
 */
function resolveRange(duration, startTime, endTime) {
  const span = Number.isFinite(duration) && duration > 0 ? duration : 0;
  const asTime = (value, fallback) =>
    Number.isFinite(value) ? Math.min(Math.max(value, 0), span) : fallback;
  const start = asTime(startTime, 0);
  const end = asTime(endTime, span);
  return end > start ? { start, end } : { start: 0, end: span };
}

class VideoTracker {
  /** `canvas` is optional -- pass the page's visible canvas to draw there
   * directly, or omit it to get an off-DOM one (used by headless callers). */
  constructor(file, canvas) {
    this.file = file;
    this.video = document.createElement("video");
    this.video.muted = true;
    this.video.playsInline = true;
    this.video.preload = "auto";
    this.url = URL.createObjectURL(file);
    this.video.src = this.url;
    this.canvas = canvas || document.createElement("canvas");
    this.ctx = this.canvas.getContext("2d", { willReadFrequently: true });
  }

  async load() {
    await new Promise((resolve, reject) => {
      this.video.addEventListener("loadedmetadata", resolve, { once: true });
      this.video.addEventListener(
        "error",
        () => {
          this._loadError().then(reject);
        },
        { once: true },
      );
    });
    this.canvas.width = this.video.videoWidth;
    this.canvas.height = this.video.videoHeight;
    if (!this.canvas.width || !this.canvas.height) {
      throw new Error(
        "no video track was found in this file (check that it really is a video)",
      );
    }
    // Force a decode of the first frame -- some browsers leave the canvas
    // blank until playback has touched the video at least once.
    await this.seekTo(0);
    return {
      width: this.canvas.width,
      height: this.canvas.height,
      duration: this.video.duration,
    };
  }

  /**
   * Turn a MediaError into a message the user can act on.
   *
   * MEDIA_ERR_SRC_NOT_SUPPORTED covers two very different problems: a codec
   * the browser genuinely cannot decode, and a file that never finished
   * copying (common with large phone videos sent through email/KakaoTalk --
   * MP4 keeps its index at the end of the file, so a transfer that stops
   * early leaves a plausible-sized file nothing can open).  "Try another
   * format" is wrong advice for the second case, so this checks the file's
   * own box structure first -- the same check the CLI's `doctor` command
   * runs server-side -- before falling back to the generic message.
   */
  async _loadError() {
    const specific = await window.faradayFileCheck
      .diagnoseVideoFile(this.file)
      .catch(() => null);
    if (specific) return new Error(`Cannot open this video: ${specific}`);

    const code = this.video.error && this.video.error.code;
    const reasons = {
      1: "playback was aborted",
      2: "a network error",
      3: "the format could not be decoded (possibly a codec problem)",
      4: "a format this browser does not support",
    };
    return new Error(
      `Cannot open this video: ${reasons[code] || "an unknown error"}. ` +
        "Try exporting it again in another format (mp4/H.264, for example).",
    );
  }

  /**
   * Seek to `t`, paint the resulting frame, and return its true timestamp.
   *
   * This waits for 'seeked' and reads back `video.currentTime`, which lands
   * within microseconds of the requested time in testing.  We also tried
   * confirming the paint with requestVideoFrameCallback (guarding against
   * 'seeked' firing on decode rather than composite); in this headless
   * Chromium it made accuracy measurably *worse* under the rapid
   * seek-per-frame pattern trackAll uses, almost certainly a callback/seek
   * race specific to this environment, and was reverted rather than shipped
   * on the strength of one browser's behaviour on synthetic test video --
   * see tests/browser/README.md for the measurements behind that call.
   */
  async seekTo(t) {
    const target = Math.max(0, Math.min(t, this.video.duration || t));
    await new Promise((resolve) => {
      const onSeeked = () => {
        this.video.removeEventListener("seeked", onSeeked);
        resolve();
      };
      this.video.addEventListener("seeked", onSeeked);
      this.video.currentTime = target;
    });
    this.ctx.drawImage(this.video, 0, 0, this.canvas.width, this.canvas.height);
    return this.video.currentTime;
  }

  imageDataAt(t) {
    // Caller must have already seeked; this just reads the current canvas.
    return this.ctx.getImageData(0, 0, this.canvas.width, this.canvas.height);
  }

  async frameImageData(t) {
    await this.seekTo(t);
    return this.imageDataAt();
  }

  async pickColorAt(t, x, y, opts) {
    const img = await this.frameImageData(t);
    return window.faradayCV.sampleColorRange(img, x, y, opts);
  }

  async previewAt(t, color, segment) {
    const img = await this.frameImageData(t);
    const { mask, blobs, blob } = window.faradayCV.segmentFrame(
      img,
      color,
      segment,
      null,
    );
    return { image: img, mask, blobs, blob };
  }

  dispose() {
    URL.revokeObjectURL(this.url);
  }

  /**
   * Walk the video, segmenting every frame.  `fps` is the nominal rate to
   * step at; the timestamp actually recorded is what the browser reports
   * after each seek, so a variable frame rate does not distort the physics.
   *
   * `startTime`/`endTime` (seconds) restrict the walk to part of the clip --
   * the browser twin of the CLI's --start-frame/--end-frame.  Timestamps
   * stay absolute video time, so the LED sync downstream is unaffected as
   * long as the LED flash itself is inside the range.
   */
  async trackAll({
    color,
    segment,
    ledRoi,
    fps,
    startTime,
    endTime,
    onProgress,
  }) {
    const { start, end } = resolveRange(
      this.video.duration,
      startTime,
      endTime,
    );
    const nEst = Math.max(1, Math.round((end - start) * fps));
    const t = [],
      x = [],
      y = [],
      area = [],
      led = ledRoi ? [] : null;
    let previous = null;
    let lastT = -Infinity;

    for (let i = 0; i < nEst; i++) {
      const requested = start + i / fps;
      if (requested > end + 1e-3) break;
      const actual = await this.seekTo(requested);
      if (actual <= lastT) continue; // the video has no new frame here
      lastT = actual;

      const img = this.imageDataAt();
      const { blob } = window.faradayCV.segmentFrame(
        img,
        color,
        segment,
        previous,
      );
      t.push(actual);
      if (blob) {
        x.push(blob.cx);
        y.push(blob.cy);
        area.push(blob.area);
        previous = [blob.cx, blob.cy];
      } else {
        x.push(null);
        y.push(null);
        area.push(0);
      }
      if (led) led.push(window.faradayCV.ledLevel(img, ledRoi));

      if (onProgress && i % 3 === 0) onProgress(i, nEst);
    }
    if (onProgress) onProgress(nEst, nEst);

    return {
      t,
      x,
      y,
      area,
      led,
      width: this.canvas.width,
      height: this.canvas.height,
      fps,
      name: this.file.name,
    };
  }
}

window.VideoTracker = VideoTracker;
window.faradayTracker = { resolveRange };
