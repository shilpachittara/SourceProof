/**
 * Pack browser File objects into a gzip-compressed tar archive (ustar).
 */

function pad512(n) {
  return (512 - (n % 512)) % 512;
}

function tarHeader(path, size) {
  const header = new Uint8Array(512);
  const enc = new TextEncoder();
  const nameBytes = enc.encode(path);
  if (nameBytes.length > 100) {
    throw new Error(`Path too long for tar: ${path}`);
  }
  header.set(nameBytes, 0);
  writeOctal(header, 124, size, 11);
  writeOctal(header, 136, 0, 8);
  for (let i = 148; i < 156; i++) header[i] = 0x20;
  header[156] = "0".charCodeAt(0);
  const ustar = new TextEncoder().encode("ustar\0");
  header.set(ustar, 257);
  let sum = 0;
  for (let i = 0; i < 512; i++) sum += header[i];
  writeOctal(header, 148, sum, 8);
  return header;
}

function writeOctal(buf, offset, value, length) {
  const str = value.toString(8).padStart(length - 1, "0") + "\0";
  for (let i = 0; i < str.length; i++) {
    buf[offset + i] = str.charCodeAt(i);
  }
}

function normalizeTarPath(file) {
  const raw = file.webkitRelativePath || file.name;
  return raw.replace(/^\.?\//, "").replace(/\\/g, "/");
}

// Build artifacts / VCS noise that must never enter the source tarball — they
// would change the hash and are not part of the verifiable source tree.
const EXCLUDE_RE = /(^|\/)(target|\.git|node_modules)\//;
const EXCLUDE_FILE_RE = /(^|\/)\.DS_Store$/;

/**
 * Strip the common leading directory shared by every file, so a selected
 * project FOLDER (paths like "demo-contract/Cargo.toml") is rooted at the
 * project root ("Cargo.toml") — which is what `stellar contract build` expects.
 */
function stripCommonRoot(paths) {
  if (paths.length === 0) return (p) => p;
  const split = paths.map((p) => p.split("/"));
  if (split.some((parts) => parts.length < 2)) return (p) => p; // a file at root already
  let prefixLen = 0;
  const first = split[0];
  outer: for (let i = 0; i < first.length - 1; i++) {
    const seg = first[i];
    for (const parts of split) {
      if (parts.length - 1 <= i || parts[i] !== seg) break outer;
    }
    prefixLen = i + 1;
  }
  if (prefixLen === 0) return (p) => p;
  return (p) => p.split("/").slice(prefixLen).join("/");
}

export async function filesToTarGzBlob(files) {
  if (!files.length) {
    throw new Error("No files selected");
  }

  const kept = files
    .map((file) => ({ file, path: normalizeTarPath(file) }))
    .filter(({ path }) => path && !path.endsWith("/"))
    .filter(({ path }) => !EXCLUDE_RE.test(path) && !EXCLUDE_FILE_RE.test(path));

  if (!kept.length) {
    throw new Error("No usable source files (everything was a build artifact?)");
  }

  const reroot = stripCommonRoot(kept.map((k) => k.path));
  const entries = kept
    .map((k) => ({ file: k.file, path: reroot(k.path) }))
    .filter((k) => k.path);

  if (!entries.some((e) => e.path.endsWith("Cargo.toml"))) {
    throw new Error("Selection has no Cargo.toml — choose the contract project root");
  }

  const chunks = [];
  for (const { file, path } of entries) {
    const data = new Uint8Array(await file.arrayBuffer());
    chunks.push(tarHeader(path, data.length));
    chunks.push(data);
    const pad = pad512(data.length);
    if (pad) chunks.push(new Uint8Array(pad));
  }
  chunks.push(new Uint8Array(512));
  chunks.push(new Uint8Array(512));
  const tar = concatUint8(chunks);
  const gz = await gzipBytes(tar);
  return new Blob([gz], { type: "application/gzip" });
}

function concatUint8(parts) {
  const total = parts.reduce((n, p) => n + p.length, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}

async function gzipBytes(data) {
  if (typeof CompressionStream === "undefined") {
    throw new Error("This browser cannot compress tarballs; use .tar.gz or .tgz instead");
  }
  const stream = new Blob([data]).stream().pipeThrough(new CompressionStream("gzip"));
  const buf = await new Response(stream).arrayBuffer();
  return new Uint8Array(buf);
}
