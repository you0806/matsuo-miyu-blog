// docs/index/app.js
// GitHub Pages で「パスが壊れない」ことを最優先にしたビューア。
// - posts一覧: ./index/posts.json
// - 記事md:     ./posts/.../index.md
// - 本文:       ./posts/.../page.html（index.md内に「本文: page.html」など）
//
// 重要な安定化（今回）:
// 1) viewer を何度も全面 innerHTML 上書きしない（骨格は1回だけ作る）
// 2) 読み込みトークンで “最新以外の結果” を破棄（レース対策）
// 3) fallback 直表示時に page.html の相対URLを絶対URLへ書き換え

// =============================
// DOM取得（IDが変わっても拾えるように）
// =============================
function pickEl(...selectors) {
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) return el;
  }
  return null;
}

const listEl = pickEl(
  "#list",
  "#posts",
  "#postsList",
  "#postList",
  "[data-role='list']",
  "[data-list]"
);

const viewerEl = pickEl(
  "#viewer",
  "#content",
  "#article",
  "#post",
  "[data-role='viewer']",
  "[data-role='content']",
  "[data-viewer]"
);

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fatal(msg) {
  console.error(msg);
  const box = document.createElement("pre");
  box.style.whiteSpace = "pre-wrap";
  box.style.wordBreak = "break-word";
  box.style.padding = "12px";
  box.style.margin = "12px";
  box.style.border = "1px solid #f99";
  box.style.background = "#fff5f5";
  box.textContent = msg;
  document.body.prepend(box);
}

if (!listEl || !viewerEl) {
  fatal(
    [
      "app.js: 必要な要素が見つかりません。",
      `listEl: ${listEl ? "OK" : "NOT FOUND"}`,
      `viewerEl: ${viewerEl ? "OK" : "NOT FOUND"}`,
      "",
      "index.html 側の id を確認してね。",
    ].join("\n")
  );
  throw new Error("Required DOM elements not found.");
}

// =============================
// URL基準（<base href="./"> 前提）
// =============================
const SITE_ROOT = new URL(document.baseURI);               // 例: https://you0806.github.io/matsuo-miyu-blog/
const POSTS_INDEX_URL = new URL("./index/posts.json", SITE_ROOT);

// =============================
// Path / Hash
// =============================
function normalizePath(p) {
  if (!p) return "";
  let s = String(p).trim();
  s = s.replaceAll("\\", "/");  // Windowsパス対策
  s = s.replace(/^\.\/+/, "");
  s = s.replace(/^\/+/, "");
  return s;
}

function getPostPathFromHash() {
  const h = location.hash.replace(/^#/, "");
  const params = new URLSearchParams(h);
  const p = params.get("p");
  return p ? normalizePath(p) : null;
}

function setPostPathToHash(path) {
  const params = new URLSearchParams(location.hash.replace(/^#/, ""));
  params.set("p", normalizePath(path(path));
  location.hash = params.toString();
}

// 上の setPostPathToHash の typo 防止
function normalizePathSafe(p) {
  return normalizePath(p);
}
function setPostPathToHash(path) {
  const params = new URLSearchParams(location.hash.replace(/^#/, ""));
  params.set("p", normalizePathSafe(path));
  location.hash = params.toString();
}

// =============================
// md helper
// =============================
function stripFrontMatter(mdText) {
  const text = String(mdText ?? "");
  if (!text.startsWith("---")) return text;
  const idx = text.indexOf("\n---", 3);
  if (idx === -1) return text;
  const after = text.indexOf("\n", idx + 1);
  return after === -1 ? "" : text.slice(after + 1);
}

function findBodyFileRef(mdText) {
  const lines = String(mdText ?? "").split("\n");
  for (const line of lines) {
    const s = line.trim();
    const cleaned = s.replace(/^[-•・]\s*/, "");
    const m = cleaned.match(/^(本文|body)\s*[:：]\s*(.+)\s*$/i);
    if (m) {
      const ref = m[2]?.trim();
      if (ref) return ref;
    }
  }
  return null;
}

function renderMarkdownRough(mdText, mdFileUrl) {
  const mdDir = new URL("./", mdFileUrl);

  const lines = mdText.split("\n");
  return lines
    .map((line) => {
      if (line.startsWith("### ")) return `<h3>${escapeHtml(line.slice(4))}</h3>`;
      if (line.startsWith("## "))  return `<h2>${escapeHtml(line.slice(3))}</h2>`;
      if (line.startsWith("# "))   return `<h1>${escapeHtml(line.slice(2))}</h1>`;

      // 画像 ![alt](path)
      line = line.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, src) => {
        const imgUrl = new URL(src, mdDir);
        return `<img alt="${escapeHtml(alt)}" src="${imgUrl.href}">`;
      });

      // リンク [text](url)
      line = line.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, text, href) => {
        const linkUrl = new URL(href, mdDir);
        return `<a href="${linkUrl.href}" target="_blank" rel="noreferrer">${escapeHtml(
          text
        )}</a>`;
      });

      if (line.trim() === "") return "<br>";
      return `<p>${escapeHtml(line)}</p>`;
    })
    .join("");
}

// =============================
// page.html fallback 用: 相対URLを絶対URLへ
// =============================
function rebaseHtml(htmlText, baseUrl) {
  try {
    const parser = new DOMParser();
    const doc = parser.parseFromString(String(htmlText ?? ""), "text/html");

    // script は念のため除去
    doc.querySelectorAll("script").forEach((s) => s.remove());

    // href/src を絶対化
    const attrs = [
      ["a", "href"],
      ["img", "src"],
      ["link", "href"],
      ["source", "src"],
      ["video", "src"],
      ["audio", "src"],
      ["iframe", "src"],
    ];

    for (const [sel, attr] of attrs) {
      doc.querySelectorAll(`${sel}[${attr}]`).forEach((el) => {
        const v = el.getAttribute(attr);
        if (!v) return;
        // data:, mailto:, javascript: は触らない
        if (/^(data:|mailto:|javascript:|#)/i.test(v)) return;
        try {
          el.setAttribute(attr, new URL(v, baseUrl).href);
        } catch {}
      });
    }

    return doc.body ? doc.body.innerHTML : String(htmlText ?? "");
  } catch (e) {
    console.warn("rebaseHtml failed:", e);
    return String(htmlText ?? "");
  }
}

// =============================
// posts.json
// =============================
async function loadPostsIndex() {
  const res = await fetch(POSTS_INDEX_URL.href, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(
      `posts.json の読み込み失敗: ${res.status} ${res.statusText}\nURL: ${POSTS_INDEX_URL.href}`
    );
  }
  return await res.json();
}

function toViewModel(raw) {
  const title = raw.title ?? "(no title)";
  const date = raw.datetime ?? raw.date ?? "";
  const orig = raw.url ?? raw.source_url ?? "";

  let path = raw.path ? normalizePath(raw.path) : "";
  if (!path && raw.local_dir) {
    const dir = normalizePath(raw.local_dir);
    path = normalizePath(`${dir}/index.md`);
  }

  return {
    id: raw.id ?? "",
    title,
    date,
    orig,
    path,
    raw,
  };
}

function renderPostList(posts) {
  listEl.innerHTML = "";

  const info = document.createElement("div");
  info.className = "hint";
  info.innerHTML = `
    <div>posts: ${posts.length}</div>
    <div>index: <a href="${POSTS_INDEX_URL.href}" target="_blank" rel="noreferrer">${escapeHtml(
      POSTS_INDEX_URL.href
    )}</a></div>
    <hr>
  `;
  listEl.appendChild(info);

  posts.forEach((p) => {
    const div = document.createElement("div");
    div.className = "post";
    div.innerHTML = `
      <div><strong>${escapeHtml(p.title)}</strong></div>
      <div class="meta">${escapeHtml(p.date)} / id:${escapeHtml(p.id)}</div>
      <div class="meta">${escapeHtml(p.path)}</div>
      ${
        p.orig
          ? `<div class="meta">orig: <a href="${escapeHtml(
              p.orig
            )}" target="_blank" rel="noreferrer">${escapeHtml(p.orig)}</a></div>`
          : ""
      }
    `;

    div.addEventListener("click", () => {
      setPostPathToHash(p.path);
      openPostByPath(p.path);
    });

    listEl.appendChild(div);
  });
}

// =============================
// viewer レンダー骨格（1回で作る）
// =============================
function renderViewerShell({ sourceUrl, sourceLabel, bodyUrl, bodyLabel }) {
  viewerEl.innerHTML = `
    <div class="meta" id="metaSource"></div>
    <div class="meta" id="metaBody"></div>
    <div class="meta" id="metaStatus"></div>
    <hr>
    <div id="viewerMain" class="viewerMain"></div>
    <div id="viewerExtra" class="hint" style="margin-top:8px;"></div>
  `;

  const metaSource = viewerEl.querySelector("#metaSource");
  const metaBody = viewerEl.querySelector("#metaBody");

  metaSource.innerHTML = sourceUrl
    ? `source: <a href="${sourceUrl}" target="_blank" rel="noreferrer">${escapeHtml(sourceLabel ?? sourceUrl)}</a>`
    : "";

  metaBody.innerHTML = bodyUrl
    ? `body: <a href="${bodyUrl}" target="_blank" rel="noreferrer">${escapeHtml(bodyLabel ?? bodyUrl)}</a>`
    : "";
}

function setStatus(text) {
  const el = viewerEl.querySelector("#metaStatus");
  if (el) el.textContent = `status: ${text}`;
}

function setMainHtml(html) {
  const el = viewerEl.querySelector("#viewerMain");
  if (el) el.innerHTML = html;
}

function setExtraHtml(html) {
  const el = viewerEl.querySelector("#viewerExtra");
  if (el) el.innerHTML = html;
}

// =============================
// 本文表示（iframe + fetch fallback）
// =============================
function mountIframe(bodyUrl) {
  setMainHtml(`
    <iframe
      id="bodyFrame"
      src="${bodyUrl}"
      style="width:100%; height:78vh; border:1px solid #eee; border-radius:12px; background:#fff;"
      loading="lazy"
    ></iframe>
  `);
}

async function runFallback(token, bodyUrlObj) {
  // tokenが古ければ何もしない
  if (token !== openToken) return;

  try {
    const res = await fetch(bodyUrlObj.href, { cache: "no-store" });
    if (!res.ok) {
      setExtraHtml(`<pre>${escapeHtml(
        `fallback fetch failed: ${res.status} ${res.statusText}\n${bodyUrlObj.href}`
      )}</pre>`);
      return;
    }
    const htmlText = await res.text();
    if (token !== openToken) return;

    const rebased = rebaseHtml(htmlText, bodyUrlObj);

    setExtraHtml(`
      <details>
        <summary>フォールバックで本文を直表示（クリックで開く）</summary>
        <div style="border:1px solid #eee; border-radius:12px; padding:12px; margin-top:8px; background:#fff;">
          ${rebased}
        </div>
      </details>
    `);
  } catch (e) {
    if (token !== openToken) return;
    setExtraHtml(`<pre>${escapeHtml(`fallback error: ${String(e)}`)}</pre>`);
  }
}

// =============================
// 記事オープン（レース対策トークン）
// =============================
let openToken = 0;

async function openPostByPath(postPath) {
  const rel = normalizePath(postPath);
  if (!rel) return;

  const token = ++openToken; // これが “今回の読み込み” の番号

  const mdUrl = new URL(rel, SITE_ROOT);

  renderViewerShell({
    sourceUrl: mdUrl.href,
    sourceLabel: rel,
    bodyUrl: "",
    bodyLabel: "",
  });
  setStatus("loading markdown...");
  setMainHtml(`<p class="hint">読み込み中...<br><code>${escapeHtml(mdUrl.href)}</code></p>`);
  setExtraHtml("");

  const res = await fetch(mdUrl.href, { cache: "no-store" });
  if (token !== openToken) return;

  if (!res.ok) {
    setStatus("markdown fetch failed");
    setMainHtml(`
      <p>記事の読み込みに失敗しました。</p>
      <pre>${escapeHtml(`${res.status} ${res.statusText}\n${mdUrl.href}`)}</pre>
      <p class="hint">posts.json の path / local_dir と実ファイルの場所が一致しているか確認してね。</p>
    `);
    return;
  }

  const rawMd = await res.text();
  if (token !== openToken) return;

  const mdText = stripFrontMatter(rawMd);
  const mdDir = new URL("./", mdUrl);

  const bodyRef = findBodyFileRef(mdText);

  if (bodyRef) {
    const bodyUrlObj = new URL(normalizePath(bodyRef), mdDir);

    // シェルを “一回だけ” 作り直して、メタだけ固定
    renderViewerShell({
      sourceUrl: mdUrl.href,
      sourceLabel: rel,
      bodyUrl: bodyUrlObj.href,
      bodyLabel: bodyRef,
    });

    setStatus("iframe loading...");
    mountIframe(bodyUrlObj.href);
    setExtraHtml(`<span class="hint">もし本文が真っ白なら、数秒後にフォールバックが出ます。</span>`);

    const iframe = viewerEl.querySelector("#bodyFrame");
    if (iframe) {
      iframe.addEventListener("load", () => {
        // 最新の読み込みだけ反映
        if (token !== openToken) return;
        setStatus("iframe loaded");
      });
      iframe.addEventListener("error", () => {
        if (token !== openToken) return;
        setStatus("iframe error (fallback soon)");
      });
    }

    // 少し待ってから fallback（Safari等でiframeが微妙でも本文出す）
    setTimeout(() => {
      runFallback(token, bodyUrlObj);
    }, 800);

    return;
  }

  // 本文指定が無ければMarkdownを雑表示
  setStatus("render markdown");
  const bodyHtml = renderMarkdownRough(mdText, mdUrl);
  setMainHtml(bodyHtml);
  setExtraHtml("");
}

// =============================
// main
// =============================
async function main() {
  try {
    const rawPosts = await loadPostsIndex();
    const arr = Array.isArray(rawPosts) ? rawPosts : rawPosts.posts ?? [];
    const posts = arr.map(toViewModel).filter((p) => p.path);

    renderPostList(posts);

    const fromHash = getPostPathFromHash();
    if (fromHash) {
      openPostByPath(fromHash);
      return;
    }

    const first = posts[0];
    if (first?.path) {
      setPostPathToHash(first.path);
      openPostByPath(first.path);
    } else {
      renderViewerShell({ sourceUrl: "", bodyUrl: "" });
      setStatus("no posts");
      setMainHtml(`<p class="hint">記事が見つかりません（posts.json の中身確認してね）</p>`);
    }
  } catch (e) {
    listEl.innerHTML = `<pre>${escapeHtml(String(e))}</pre>`;
    console.error(e);
  }
}

window.addEventListener("hashchange", () => {
  const p = getPostPathFromHash();
  if (p) openPostByPath(p);
});

window.addEventListener("DOMContentLoaded", () => {
  main();
});
