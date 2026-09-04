/*
 * faraday-cv/filecheck.js -- tell a broken file from an unsupported one.
 *
 * When a browser refuses to play a video, MEDIA_ERR_SRC_NOT_SUPPORTED covers
 * two very different problems: a codec the browser genuinely cannot decode,
 * and a file that never finished copying (MP4 keeps its index, the `moov`
 * box, at the end, so a transfer that stops early leaves a plausible-sized
 * file nothing can open). Telling a user to "try another format" is wrong
 * advice for the second case -- no re-encode fixes a file whose frame data
 * already ends mid-copy; what they need is a clean copy of the original.
 *
 * This walks the file's top-level MP4/MOV boxes straight from the local
 * File object (via `.slice()`, never loading the whole file into memory) --
 * the same check faradaycv.decode.diagnose() does server-side in the CLI.
 */

/** Top-level box names in an MP4/MOV file, read without loading it fully. */
async function readTopLevelBoxes(file, limit = 64) {
  const boxes = [];
  const size = file.size;
  let offset = 0;
  while (offset < size && boxes.length < limit) {
    const header = await file.slice(offset, offset + 8).arrayBuffer();
    if (header.byteLength < 8) break;
    const view = new DataView(header);
    let boxSize = view.getUint32(0, false);
    const name = String.fromCharCode(
      view.getUint8(4),
      view.getUint8(5),
      view.getUint8(6),
      view.getUint8(7),
    );
    if (!/^[\x20-\x7e]{4}$/.test(name)) break; // not a plausible box name

    let headerLen = 8;
    if (boxSize === 1) {
      const ext = await file.slice(offset + 8, offset + 16).arrayBuffer();
      if (ext.byteLength < 8) break;
      const extView = new DataView(ext);
      // Files here are well under 2^53 bytes, so this stays exact.
      boxSize =
        extView.getUint32(0, false) * 4294967296 + extView.getUint32(4, false);
      headerLen = 16;
    } else if (boxSize === 0) {
      boxSize = size - offset;
    }
    if (boxSize < headerLen) break;

    boxes.push(name);
    offset += boxSize;
  }
  return boxes;
}

function indexOfBytes(haystack, needle) {
  outer: for (let i = 0; i <= haystack.length - needle.length; i++) {
    for (let j = 0; j < needle.length; j++) {
      if (haystack[i + j] !== needle[j]) continue outer;
    }
    return i;
  }
  return -1;
}

/**
 * Safety net for `readTopLevelBoxes`: a box that declares its size as `0`
 * ("runs to the end of the file", legal per the spec) makes the sequential
 * walk jump straight to EOF -- but some real-world muxers write that box
 * mid-file anyway and still append a real `moov` after it, which the walk
 * then never sees. Rather than trust the walk alone, look for the literal
 * `moov` bytes in the regions a box actually lives in: near the front
 * ("fast start" layouts) or near the end (camera-native captures, where the
 * device does not know moov's contents until recording stops). A file whose
 * copy genuinely stopped early has no `moov` bytes anywhere, so this cannot
 * turn a real truncation into a false negative -- it only rescues files the
 * simple walk was wrong about.
 */
async function hasMoovSignature(file) {
  const pattern = [0x6d, 0x6f, 0x6f, 0x76]; // "moov"
  const headSize = Math.min(file.size, 4 * 1024 * 1024);
  const tailSize = Math.min(file.size, 20 * 1024 * 1024);
  const regions = [
    file.slice(0, headSize),
    file.slice(Math.max(0, file.size - tailSize), file.size),
  ];
  for (const region of regions) {
    const bytes = new Uint8Array(await region.arrayBuffer());
    if (indexOfBytes(bytes, pattern) !== -1) return true;
  }
  return false;
}

/**
 * Diagnose why a video file will not load, using only its box structure --
 * no network, no upload. Returns a Korean message ready to show the user,
 * or null if this file does not look like a recognisable MP4/MOV at all
 * (in which case the generic "unsupported format" message is the right one).
 */
async function diagnoseVideoFile(file) {
  if (file.size === 0) {
    return "파일 크기가 0바이트입니다. 다시 복사해서 올려보세요.";
  }
  let boxes;
  try {
    boxes = await readTopLevelBoxes(file);
  } catch {
    return null;
  }
  if (!boxes.includes("ftyp")) {
    return null; // not an MP4/MOV we recognise -- let the generic message stand
  }
  if (!boxes.includes("moov")) {
    const rescued = await hasMoovSignature(file).catch(() => false);
    if (rescued) {
      return null; // the walk missed it -- a real codec/format issue, not this
    }
    return (
      "이 파일은 재생에 필요한 색인(moov)이 없습니다 -- 옮기다가 끊긴, " +
      "불완전한 파일입니다. 코덱 문제가 아니라서 다른 형식으로 바꿔도 " +
      "소용없습니다. 원본을 다시 받아보세요 (에어드랍이나 아이클라우드 " +
      "링크가 카카오톡·문자보다 안전합니다)."
    );
  }
  return null; // structurally fine -- a genuine codec/format issue
}

window.faradayFileCheck = {
  readTopLevelBoxes,
  diagnoseVideoFile,
  hasMoovSignature,
};
