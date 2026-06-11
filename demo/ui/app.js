import { filesToTarGzBlob } from "./pack-tarball.js";

const API = window.location.origin;

function pillClass(status) {
  return {
    verified: "pill-verified",
    mismatch: "pill-mismatch",
    failed: "pill-failed",
    pending: "pill-pending",
  }[status] || "pill-muted";
}

function statusPill(status) {
  return `<span class="pill ${pillClass(status)}">${status}</span>`;
}

function shortHash(s, n = 8) {
  if (!s) return "—";
  return s.length <= n + 3 ? s : `${s.slice(0, n)}…`;
}

function freshnessPill(freshness) {
  if (!freshness) return "";
  if (freshness === "current") {
    return ` <span class="pill pill-verified">current</span>`;
  }
  return ` <span class="pill pill-mismatch">superseded</span>`;
}

function originPill(origin, repo, commit) {
  if (origin === "github" && repo) {
    const short = commit ? commit.slice(0, 7) : "";
    return `<a href="${repo}/tree/${commit || ""}" target="_blank" rel="noopener">github · ${short}</a>`;
  }
  if (origin === "ipfs") return `<span class="pill pill-muted">ipfs</span>`;
  if (origin === "url") return `<span class="pill pill-muted">url</span>`;
  if (origin === "content-addressed") return `<span class="pill pill-muted">hash</span>`;
  return `<span class="pill pill-muted">upload</span>`;
}

function imagePill(image) {
  if (!image) return `<span class="pill pill-muted">—</span>`;
  const label = image.name || truncate(image.digest, 6);
  if (image.revoked) {
    return `<span class="pill pill-failed" title="${label}">revoked</span>`;
  }
  if (image.allowlisted) {
    const trust = image.sdf_trusted ? "sdf" : "ok";
    return `<span class="pill pill-verified" title="${label}">${trust}</span>`;
  }
  return `<span class="pill pill-mismatch" title="${label}">unknown</span>`;
}

function truncate(s, n = 12) {
  if (!s) return "—";
  if (s.length <= n * 2) return s;
  return `${s.slice(0, n)}…${s.slice(-n)}`;
}

function setResult(el, html, tone) {
  el.classList.remove("hidden", "result--ok", "result--err");
  if (tone === "ok") el.classList.add("result--ok");
  if (tone === "err") el.classList.add("result--err");
  el.innerHTML = html;
}

async function checkHealth() {
  const el = document.getElementById("api-status");
  try {
    const res = await fetch(`${API}/health`);
    if (!res.ok) throw new Error("unhealthy");
    const data = await res.json();
    el.textContent = `${data.service} online`;
    el.className = "status-chip status-chip--ok";
  } catch {
    el.textContent = "API offline";
    el.className = "status-chip status-chip--err";
  }
}

async function loadRegistry() {
  const tbody = document.getElementById("registry-body");
  tbody.innerHTML = `<tr><td colspan="8" class="table-empty">Loading…</td></tr>`;
  try {
    const res = await fetch(`${API}/v1/verifications?limit=50`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    const items = data.verifications || [];
    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="table-empty">No verifications yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = items
      .map((v) => {
        const src = v.source || {};
        return `
      <tr>
        <td>${statusPill(v.status)}</td>
        <td>${v.network}</td>
        <td class="mono">${truncate(v.contract_id, 8)}</td>
        <td class="mono">${truncate(v.wasm_hash, 8)}</td>
        <td>${originPill(src.origin, src.repo_url, src.commit_sha)}</td>
        <td>${imagePill(v.build_image)}</td>
        <td>${v.verified_at ? new Date(v.verified_at).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" }) : "—"}</td>
        <td><a class="link-quiet" href="${v.source_tarball_url}" target="_blank" rel="noopener">tarball</a></td>
      </tr>`;
      })
      .join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" class="table-empty">${err.message}</td></tr>`;
  }
}

function originLabelText(src) {
  if (!src) return "upload";
  if (src.origin === "github" && src.repo_url) {
    const short = src.commit_sha ? src.commit_sha.slice(0, 7) : "";
    return `GitHub · ${src.repo_url} @ ${short}`;
  }
  return {
    ipfs: "IPFS (hash-pinned)",
    url: "Hosted URL (hash-pinned)",
    "content-addressed": "Hash-only (from content store)",
  }[src.origin] || "Direct upload";
}

function buildImageText(image) {
  if (!image) return "—";
  const label = image.name || truncate(image.digest, 6);
  if (image.revoked) return `${label} (revoked)`;
  if (image.allowlisted) return `${label} (${image.sdf_trusted ? "SDF-trusted" : "allowlisted"})`;
  return `${label} (not allowlisted)`;
}

function kv(label, value, mono = false) {
  if (value == null || value === "") return "";
  const v = mono ? `<code>${value}</code>` : escapeHtml(String(value));
  return `<div class="detail-row"><span class="detail-key">${label}</span><span class="detail-val">${v}</span></div>`;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function metaBlock(title, obj) {
  if (!obj) return "";
  const rows = Object.entries(obj)
    .filter(([, val]) => val != null && val !== "")
    .map(([k, val]) => kv(k, String(val), true))
    .join("");
  if (!rows) return "";
  return `<div class="detail-group"><div class="detail-group-title">${title}</div>${rows}</div>`;
}

const CONSENSUS_LABEL = {
  verified: "Source verified",
  mixed: "Source verified (partial)",
  divergent: "Verification disputed",
  mismatch: "Not verified",
  pending: "Verification pending",
};

function consensusPillClass(consensus) {
  return {
    verified: "pill-verified",
    mixed: "pill-verified",
    divergent: "pill-mismatch",
    mismatch: "pill-failed",
    pending: "pill-pending",
  }[consensus] || "pill-muted";
}

function renderVerifierRow(vr) {
  const status = vr.status;
  const icon = { verified: "✓", mismatch: "✕", failed: "✕", pending: "…" }[status] || "?";
  const tone = status === "verified" ? "ok" : status === "pending" ? "muted" : "warn";
  const bm = vr.build_metadata || {};
  const lines = [];

  const env = [];
  if (bm.docker_image) env.push(`image <code>${escapeHtml(bm.docker_image)}</code>`);
  if (bm.stellar_cli_version) env.push(`cli ${escapeHtml(bm.stellar_cli_version)}`);
  if (bm.rustc_version) env.push(`rustc ${escapeHtml(bm.rustc_version)}`);
  if (env.length) lines.push(`<div class="verifier-detail-line">${env.join(" · ")}</div>`);

  if (status === "verified" && vr.tarball_content_hash) {
    const fresh = vr.freshness ? ` · freshness ${vr.freshness}` : "";
    lines.push(
      `<div class="verifier-detail-line">source <a class="link-quiet" href="${API}/v1/source/${vr.tarball_content_hash}" target="_blank" rel="noopener">tarball ${shortHash(vr.tarball_content_hash)}</a>${fresh}</div>`
    );
  } else if (status === "mismatch") {
    if (vr.mismatch_reason) {
      lines.push(`<div class="verifier-detail-line verifier-detail-line--warn">reason: ${escapeHtml(vr.mismatch_reason)}</div>`);
    }
    lines.push(
      `<div class="verifier-detail-line">expected <code>${shortHash(vr.expected_wasm_hash || vr.wasm_hash)}</code> · built <code>${shortHash(vr.built_wasm_hash)}</code></div>`
    );
  }

  return `
  <li class="verifier-row verifier-row--${tone}">
    <div class="verifier-row-head">
      <span class="verifier-mark">${icon}</span>
      <code class="verifier-id">${escapeHtml(vr.verifier_instance_id)}</code>
      <span class="pill ${pillClass(status)}">${status}</span>
      ${vr.trust_level ? `<span class="verifier-trust">${escapeHtml(vr.trust_level)}</span>` : ""}
    </div>
    ${lines.length ? `<div class="verifier-row-detail">${lines.join("")}</div>` : ""}
  </li>`;
}

function renderConsensus(data) {
  const verifiers = data.verifiers || [];
  if (!verifiers.length) return "";
  const consensus = data.consensus || "—";
  const label = CONSENSUS_LABEL[consensus] || consensus;
  const rows = verifiers.map(renderVerifierRow).join("");

  // Default consumer trust policy: trusted set = every verifier shown,
  // threshold = ≥1 verified AND 0 mismatch. The API returns every signed,
  // attributable signal; the badge decision is applied here, client-side.
  const anyVerified = verifiers.some((v) => v.status === "verified");
  const anyMismatch = verifiers.some((v) => v.status === "mismatch");
  const badged = anyVerified && !anyMismatch;
  const verdict = badged
    ? "BADGED — a trusted verifier verified, none report mismatch"
    : anyMismatch
    ? "NOT BADGED — a trusted verifier reports mismatch"
    : "NOT BADGED — no trusted verifier has verified yet";

  const chain = data.current_wasm_hash
    ? `<div class="consensus-chain">On-chain Wasm <code>${shortHash(data.current_wasm_hash, 10)}</code></div>`
    : "";

  return `
  <div class="consensus-panel consensus-panel--${consensus}">
    <div class="consensus-head">
      <div class="consensus-head-main">
        <span class="consensus-title">Multi-verifier result</span>
        <span class="pill ${consensusPillClass(consensus)}">${label}</span>
        <span class="consensus-count">${data.verifier_count} verifier(s)</span>
      </div>
      ${chain}
    </div>
    <ul class="verifier-list">${rows}</ul>
    <div class="trust-policy trust-policy--${badged ? "ok" : "warn"}">
      <div class="trust-policy-title">Your trust policy (default)</div>
      <div class="trust-policy-rule">☑ ≥1 trusted verifier verified&nbsp;&nbsp;☑ 0 trusted verifiers mismatch</div>
      <div class="trust-policy-verdict">→ ${verdict}</div>
    </div>
  </div>`;
}

function renderVerification(v) {
  const src = v.source || {};
  const status = v.status;
  const reason = (v.build_metadata && v.build_metadata.mismatch_reason) || v.error_message;
  const calloutTone = status === "verified" ? "ok" : status === "pending" ? "muted" : "warn";
  const callout = reason ? `<div class="callout callout--${calloutTone}">${escapeHtml(reason)}</div>` : "";
  const hash = v.tarball_content_hash || src.tarball_content_hash || "";
  const build = v.build_metadata
    ? {
        image: v.build_metadata.docker_image,
        rustc: v.build_metadata.rustc_version,
        stellar_cli: v.build_metadata.stellar_cli_version,
      }
    : null;

  return `
  <div class="verif-card">
    <div class="verif-head">
      ${statusPill(status)}
      <span class="verif-trust">trust: ${v.trust_level || "sep58_rebuild"}</span>
      ${freshnessPill(v.freshness)}
    </div>
    <div class="detail-list">
      ${kv("Contract", v.contract_id ? truncate(v.contract_id, 8) : "—", true)}
      ${kv("Network", v.network)}
      ${kv("On-chain Wasm", truncate(v.wasm_hash, 10), true)}
      ${status === "mismatch" ? kv("Rebuilt Wasm", truncate(v.built_wasm_hash, 10), true) : ""}
      ${kv("Source origin", originLabelText(src))}
      ${kv("Builder image", buildImageText(v.build_image))}
      ${kv("Verified at", v.verified_at ? new Date(v.verified_at).toLocaleString() : "—")}
    </div>
    ${metaBlock("On-chain build metadata (read from deployed Wasm)", v.onchain_meta)}
    ${metaBlock("Verifier rebuild environment", build)}
    ${callout}
    ${hash ? renderSourceBlock(v.source_tarball_url, hash) : ""}
  </div>`;
}

function renderSourceBlock(tarballUrl, hash) {
  return `
  <div class="source-block" data-hash="${hash}">
    <div class="source-actions">
      <a class="btn btn-secondary btn-sm" href="${tarballUrl}" download>Download source (.tar.gz)</a>
      <button type="button" class="btn btn-secondary btn-sm js-view-files">View original source files</button>
    </div>
    <div class="source-files hidden"></div>
  </div>`;
}

function wireSourceViewer(rootEl) {
  const block = rootEl.querySelector(".source-block");
  if (!block) return;
  const btn = block.querySelector(".js-view-files");
  const panel = block.querySelector(".source-files");
  const hash = block.dataset.hash;
  if (!btn || !panel || !hash) return;

  btn.addEventListener("click", async () => {
    if (!panel.classList.contains("hidden")) {
      panel.classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden");
    panel.innerHTML = `<div class="files-empty">Loading source listing…</div>`;
    try {
      const res = await fetch(`${API}/v1/source/${hash}/files`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not list files");
      const files = data.files || [];
      if (!files.length) {
        panel.innerHTML = `<div class="files-empty">Tarball has no files.</div>`;
        return;
      }
      panel.innerHTML = `
        <div class="files-head">${files.length} file(s) in the verified source tree</div>
        <ul class="files-list">
          ${files.map((f) => `<li><button type="button" class="file-link js-preview" data-path="${escapeHtml(f.path)}">${escapeHtml(f.path)}</button><span class="file-size">${f.size} B</span></li>`).join("")}
        </ul>
        <pre class="file-preview hidden"></pre>`;
      const preview = panel.querySelector(".file-preview");
      panel.querySelectorAll(".js-preview").forEach((link) => {
        link.addEventListener("click", async () => {
          preview.classList.remove("hidden");
          preview.textContent = "Loading…";
          try {
            const r = await fetch(`${API}/v1/source/${hash}/file?path=${encodeURIComponent(link.dataset.path)}`);
            preview.textContent = await r.text();
          } catch (err) {
            preview.textContent = `Could not load file: ${err.message}`;
          }
        });
      });
    } catch (err) {
      panel.innerHTML = `<div class="files-empty">${escapeHtml(err.message)}</div>`;
    }
  });
}

async function pollVerification(id, resultEl) {
  for (let i = 0; i < 60; i++) {
    const res = await fetch(`${API}/v1/verifications/${id}`);
    const data = await res.json();
    const tone = data.status === "verified" ? "ok" : data.status === "failed" ? "err" : null;
    if (data.status === "pending") {
      setResult(resultEl, `<div class="verif-head">${statusPill("pending")} <span class="verif-trust">rebuilding in pinned image…</span></div>`, null);
    } else {
      setResult(resultEl, renderVerification(data), tone);
      wireSourceViewer(resultEl);
      loadRegistry();
      return data;
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
}

let activeTab = "upload";
document.querySelectorAll(".seg").forEach((tab) => {
  tab.addEventListener("click", () => {
    activeTab = tab.dataset.tab;
    document.querySelectorAll(".seg").forEach((t) => {
      const on = t === tab;
      t.classList.toggle("seg-active", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.querySelectorAll(".tab-panel").forEach((p) => {
      p.classList.toggle("hidden", p.dataset.panel !== activeTab);
    });
  });
});

const SOURCE_HINT = ".tar.gz, .tgz, or project sources (.rs, Cargo.toml, …)";
const TARBALL_RE = /\.(tar\.gz|tgz)$/i;

/** @type {File[]} */
let selectedSourceFiles = [];

function isTarballFile(file) {
  return file && TARBALL_RE.test(file.name);
}

function describeSelection(files) {
  if (!files.length) return SOURCE_HINT;
  if (files.length === 1) return files[0].name;
  const names = files.slice(0, 3).map((f) => f.name);
  const more = files.length > 3 ? ` +${files.length - 3} more` : "";
  return `${files.length} files: ${names.join(", ")}${more}`;
}

function setSelectedSourceFiles(files) {
  selectedSourceFiles = files;
  const fileHint = document.getElementById("file-drop-text");
  if (fileHint) fileHint.textContent = describeSelection(files);
}

function assignFilesToInput(input, files) {
  const dt = new DataTransfer();
  for (const f of files) dt.items.add(f);
  input.files = dt.files;
}

async function resolveSourceUpload(files) {
  if (!files.length) throw new Error("Choose a source tarball, .rs files, or a project folder");
  if (files.length === 1 && isTarballFile(files[0])) {
    return files[0];
  }
  return filesToTarGzBlob(files);
}

const fileInput = document.getElementById("source-file");
const folderInput = document.getElementById("source-folder");
const fileDropZone = document.getElementById("file-drop-zone");
const fileBrowseBtn = document.getElementById("source-file-btn");
const folderBrowseBtn = document.getElementById("source-folder-btn");

if (fileInput && fileDropZone) {
  fileInput.addEventListener("change", () => {
    setSelectedSourceFiles(Array.from(fileInput.files));
  });

  if (folderInput) {
    folderInput.addEventListener("change", () => {
      const files = Array.from(folderInput.files);
      assignFilesToInput(fileInput, files);
      setSelectedSourceFiles(files);
    });
  }

  const openFilePicker = () => fileInput.click();
  const openFolderPicker = () => folderInput?.click();

  if (fileBrowseBtn) {
    fileBrowseBtn.addEventListener("click", (e) => {
      e.preventDefault();
      openFilePicker();
    });
  }
  if (folderBrowseBtn) {
    folderBrowseBtn.addEventListener("click", (e) => {
      e.preventDefault();
      openFolderPicker();
    });
  }

  fileDropZone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openFilePicker();
    }
  });

  ["dragenter", "dragover"].forEach((ev) => {
    fileDropZone.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      fileDropZone.classList.add("file-drop--over");
    });
  });
  ["dragleave", "drop"].forEach((ev) => {
    fileDropZone.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      fileDropZone.classList.remove("file-drop--over");
    });
  });
  fileDropZone.addEventListener("drop", (e) => {
    const files = Array.from(e.dataTransfer?.files || []);
    if (!files.length) return;
    assignFilesToInput(fileInput, files);
    setSelectedSourceFiles(files);
  });
}

function inputValue(panel, name) {
  const el = document.querySelector(`.tab-panel[data-panel="${panel}"] [name="${name}"]`);
  return el ? el.value.trim() : "";
}

document.getElementById("submit-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const resultEl = document.getElementById("submit-result");

  const contractId = form.contract_id.value.trim();
  const wasmHash = form.wasm_hash.value.trim();
  if (!contractId && !wasmHash) {
    alert("Provide contract ID or Wasm hash");
    return;
  }

  const fd = new FormData();
  fd.set("network", form.network.value);
  if (contractId) fd.set("contract_id", contractId);
  if (wasmHash) fd.set("wasm_hash", wasmHash);

  if (activeTab === "upload") {
    const files = selectedSourceFiles.length
      ? selectedSourceFiles
      : Array.from(form.source.files || []);
    try {
      setResult(resultEl, "Preparing source…", null);
      const source = await resolveSourceUpload(files);
      const name = source instanceof File ? source.name : "source.tar.gz";
      fd.set("source", source, name);
    } catch (err) {
      alert(err.message);
      return;
    }
  } else if (activeTab === "github") {
    const url = inputValue("github", "github_url");
    if (!url) {
      alert("Enter a GitHub repo URL");
      return;
    }
    fd.set("github_url", url);
    const ref = inputValue("github", "git_ref");
    if (ref) fd.set("git_ref", ref);
  } else if (activeTab === "hosted") {
    const url = inputValue("hosted", "tarball_url");
    const sha = inputValue("hosted", "tarball_sha256");
    if (!url || !sha) {
      alert("Enter both a tarball URL and tarball_sha256");
      return;
    }
    fd.set("tarball_url", url);
    fd.set("tarball_sha256", sha);
  } else if (activeTab === "hash") {
    const sha = inputValue("hash", "tarball_sha256");
    if (!sha) {
      alert("Enter tarball_sha256");
      return;
    }
    fd.set("tarball_sha256", sha);
  }

  setResult(resultEl, "Submitting…", null);
  try {
    const res = await fetch(`${API}/v1/verify`, { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);
    const originLabel = {
      github: `GitHub · ${(data.source_commit || "").slice(0, 7)}`,
      ipfs: "IPFS",
      url: "hosted URL",
      "content-addressed": "content-addressed",
    }[data.source_origin] || "upload";
    setResult(resultEl, `<strong>Queued</strong> · <code>${data.verification_id}</code> · ${originLabel}<br/>Polling…`, null);
    await pollVerification(data.verification_id, resultEl);
  } catch (err) {
    setResult(resultEl, err.message, "err");
  }
});

document.getElementById("lookup-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const network = fd.get("network");
  const contractId = fd.get("contract_id");
  const resultEl = document.getElementById("lookup-result");
  setResult(resultEl, "Looking up…", null);
  try {
    const res = await fetch(`${API}/v1/${network}/contracts/${contractId}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Not found");
    const verifs = data.verifications || [];
    const consensusHtml = renderConsensus(data);
    if (!verifs.length) {
      setResult(resultEl, consensusHtml || "No verified source on record", consensusHtml ? null : "err");
      return;
    }
    setResult(resultEl, consensusHtml + verifs.map(renderVerification).join(""), "ok");
    wireSourceViewer(resultEl);
  } catch (err) {
    setResult(resultEl, `Not verified — ${escapeHtml(err.message)}`, "err");
  }
});

const DEMO_DIVERGENCE_CONTRACT_ID = "CDEMODIVERGENCE" + "A".repeat(41);
const sampleBtn = document.getElementById("lookup-sample");
if (sampleBtn) {
  sampleBtn.addEventListener("click", () => {
    const form = document.getElementById("lookup-form");
    form.querySelector('[name="network"]').value = "testnet";
    form.querySelector('[name="contract_id"]').value = DEMO_DIVERGENCE_CONTRACT_ID;
    if (form.requestSubmit) form.requestSubmit();
    else form.dispatchEvent(new Event("submit", { cancelable: true }));
  });
}

document.getElementById("refresh-registry").addEventListener("click", loadRegistry);

checkHealth();
loadRegistry();
setInterval(loadRegistry, 15000);
setInterval(checkHealth, 30000);
