// Node-runnable unit tests for static/filecheck.js -- no browser needed.
//
//     node tests/browser/filecheck.test.mjs
//
// Exercises the same "is the moov atom missing" question as
// faradaycv.decode.diagnose() on the Python side, but reading a mock
// File-like object the way the browser hands us one.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
global.window = {};
new Function(fs.readFileSync(path.join(here, "..", "..", "static", "filecheck.js"), "utf8"))();
const { readTopLevelBoxes, diagnoseVideoFile } = global.window.faradayFileCheck;

let failures = 0;
function assert(cond, msg) {
  if (!cond) {
    failures++;
    console.error("FAIL:", msg);
  } else {
    console.log("ok:", msg);
  }
}

/** Build one MP4 box: 4-byte big-endian size, 4-byte ASCII type, payload. */
function box(type, payloadSize) {
  const buf = Buffer.alloc(8 + payloadSize);
  buf.writeUInt32BE(8 + payloadSize, 0);
  buf.write(type, 4, "ascii");
  return buf;
}

/** A File-like object backed by a Buffer -- only .size and .slice() are used. */
function fakeFile(buffer) {
  return {
    size: buffer.length,
    slice(start, end) {
      const chunk = buffer.subarray(start, end);
      return { arrayBuffer: async () => chunk.buffer.slice(chunk.byteOffset, chunk.byteOffset + chunk.length) };
    },
  };
}

// -- reads a healthy box sequence in order --
{
  const buf = Buffer.concat([box("ftyp", 16), box("free", 4), box("mdat", 1000), box("moov", 200)]);
  const boxes = await readTopLevelBoxes(fakeFile(buf));
  assert(
    boxes.join(",") === "ftyp,free,mdat,moov",
    `expected ftyp,free,mdat,moov, got ${boxes.join(",")}`,
  );
}

// -- a real transfer that stopped mid-copy: ftyp/free/mdat, no moov --
{
  const buf = Buffer.concat([box("ftyp", 16), box("free", 4), box("mdat", 176_000_000)]);
  const file = fakeFile(buf);
  const boxes = await readTopLevelBoxes(file);
  assert(boxes.includes("ftyp") && boxes.includes("mdat"), "should see ftyp and mdat");
  assert(!boxes.includes("moov"), "a cut-short file must not report a moov box");

  const message = await diagnoseVideoFile(file);
  assert(message !== null, "a missing moov must produce a specific message");
  assert(message.includes("색인"), `message should name the missing index, got: ${message}`);
  assert(!message.includes("코덱이"), "must not blame the codec when the file is just incomplete");
}

// -- a healthy file needs no special message (the generic one is fine) --
{
  const buf = Buffer.concat([box("ftyp", 16), box("mdat", 500), box("moov", 100)]);
  const message = await diagnoseVideoFile(fakeFile(buf));
  assert(message === null, `a complete file should get no special message, got: ${message}`);
}

// -- something that is not MP4/MOV at all: no ftyp, so no opinion --
{
  const buf = Buffer.from("not a video file, just some bytes here");
  const message = await diagnoseVideoFile(fakeFile(buf));
  assert(message === null, "a non-MP4 file should defer to the generic browser message");
}

// -- an empty file is named as such, distinctly --
{
  const message = await diagnoseVideoFile(fakeFile(Buffer.alloc(0)));
  assert(message !== null && message.includes("0바이트"), `empty file should say so, got: ${message}`);
}

// -- a 64-bit box size (rare, but must not crash or misread) --
{
  const large = Buffer.alloc(16 + 100);
  large.writeUInt32BE(1, 0); // signals a 64-bit size follows
  large.write("mdat", 4, "ascii");
  large.writeBigUInt64BE(BigInt(16 + 100), 8);
  const buf = Buffer.concat([box("ftyp", 16), large, box("moov", 50)]);
  const boxes = await readTopLevelBoxes(fakeFile(buf));
  assert(
    boxes.join(",") === "ftyp,mdat,moov",
    `64-bit box size must be handled, got ${boxes.join(",")}`,
  );
}

console.log(failures ? `\n${failures} FAILED` : "\nALL FILECHECK UNIT TESTS PASSED");
process.exit(failures ? 1 : 0);
