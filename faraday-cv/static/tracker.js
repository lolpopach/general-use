/*
 * faraday-cv/tracker.js -- walks a local video frame by frame in the
 * browser, running static/cv.js's colour segmentation on each one.
 *
 * The video never leaves the machine: it is opened from a local File via
 * a blob: URL, decoded by the browser's own <video> element, and only the
 * resulting numbers (a centroid and an LED brightness per frame) are ever
 * sent to the server.
 */

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
      this.video.addEventListener("error", () => reject(this._loadError()), {
        once: true,
      });
    });
    this.canvas.width = this.video.videoWidth;
    this.canvas.height = this.video.videoHeight;
    if (!this.canvas.width || !this.canvas.height) {
      throw new Error(
        "이 파일에서 영상 트랙을 찾지 못했습니다 (영상 파일이 맞는지 확인하세요)",
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

  _loadError() {
    const code = this.video.error && this.video.error.code;
    const reasons = {
      1: "재생이 중단되었습니다",
      2: "네트워크 오류",
      3: "디코딩할 수 없는 형식입니다 (코덱 문제일 수 있습니다)",
      4: "브라우저가 지원하지 않는 형식입니다",
    };
    return new Error(
      `영상을 열 수 없습니다: ${reasons[code] || "알 수 없는 오류"}. ` +
        "다른 형식(mp4/H.264 등)으로 다시 내보내 보세요.",
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
   * Walk the whole video, segmenting every frame.  `fps` is the nominal rate
   * to step at; the timestamp actually recorded is what the browser reports
   * after each seek, so a variable frame rate does not distort the physics.
   */
  async trackAll({ color, segment, ledRoi, fps, onProgress }) {
    const duration = this.video.duration;
    const nEst = Math.max(1, Math.round(duration * fps));
    const t = [],
      x = [],
      y = [],
      area = [],
      led = ledRoi ? [] : null;
    let previous = null;
    let lastT = -Infinity;

    for (let i = 0; i < nEst; i++) {
      const requested = i / fps;
      if (requested > duration + 1e-3) break;
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
