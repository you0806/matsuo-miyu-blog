// docs/index/app.js
// GitHub Pages で「パスが壊れない」ことを最優先にしたビューア。
// - posts一覧: ./index/posts.json
// - 記事md:     ./posts/.../index.md
// - 本文:       ./posts/.../page.html（index.mdに「本文: page.html」など）
//
// 改良点（今回）:
// 1) body(page.html) があれば iframe で表示
// 2) iframe がダメな環境でも、fetch→innerHTML で本文を直表示（フォールバック）
// 3) どこで詰まったか分かるように viewer にステータスを出す
//
// ★重要修正:
// - showBodyHtml() が viewer 全体を上書きしない（上書き合戦で表示が消えるのを防ぐ）

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
// URL基準
// =============================
const SITE_ROOT = new URL(document.baseURI);
const POSTS_INDEX_URL = new URL("./index/posts.json", SITE_ROOT);

// =============================
// Path / Hash
// =============================
function normalizePath(p) {
  if (!p) return "";
  let s = String(p).trim();
  s = s.replaceAll("\\", "/");
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
  params.set("p", normalizePath(path));
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
      if (line.startsWith("## ")) return `<h2>${escapeHtml(line.slice(3))}</h2>`;
      if (line.startsWith("# ")) return `<h1>${escapeHtml(line.slice(2))}</h1>`;

      line = line.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, src) => {
        const imgUrl = new URL(src, mdDir);
        return `<img alt="${escapeHtml(alt)}" src="${imgUrl.href}">`;
      });

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
// 本文表示（iframe + fetch fallback）
// =============================
function setViewerHtml(html) {
  viewerEl.innerHTML = html;
}

function setText(el, text) {
  if (!el) return;
  el.textContent = text;
}

function removeScripts(html) {
  // 最低限：scriptタグだけ除去（安全寄り）
  return String(html ?? "").replace(/<script[\s\S]*?>[\s\S]*?<\/script>/gi, "");
}

/**
 * viewer全体は触らず、指定の mountEl の中だけ埋める
 */
async function showBodyHtml(bodyUrl, mountEl, statusEl) {
  if (!mountEl) return;

  mountEl.innerHTML = `
    <iframe
      id="bodyFrame"
      src="${bodyUrl.href}"
      style="width:100%; height: 78vh; border:1px solid #eee; border-radius:12px; background:#fff;"
      loading="lazy"
    ></iframe>

    <div class="hint" style="margin-top:8px;">
      もしここが真っ白なら、下のフォールバック（直表示）を試します…
    </div>
    <div id="bodyFallback" class="hint"></div>
  `;

  const iframe = mountEl.querySelector("#bodyFrame");
  const fallback = mountEl.querySelector("#bodyFallback");

  // iframeの状態
  if (iframe) {
    iframe.addEventListener("load", () => {
      setText(statusEl, "status: iframe loaded");
    });
    // すぐ「ロード中」を出す
    setText(statusEl, "status: iframe loading...");
  }

  // 少し待ってフォールバック（iframeが表示できない環境でも本文が出る）
  setTimeout(async () => {
    try {
      const res = await fetch(bodyUrl.href, { cache: "no-store" });
      if (!res.ok) {
        if (fallback) {
          fallback.innerHTML = `<pre>${escapeHtml(
            `fallback fetch failed: ${res.status} ${res.statusText}\n${bodyUrl.href}`
          )}</pre>`;
        }
        return;
      }

      const htmlText = await res.text();
      const safeHtml = removeScripts(htmlText);

      if (fallback) {
        fallback.innerHTML = `
          <details>
            <summary>フォールバックで本文を直表示（クリックで開く）</summary>
            <div style="border:1px solid #eee; border-radius:12px; padding:12px; margin-top:8px; background:#fff;">
              ${safeHtml}
            </div>
          </details>
        `;
      }
    } catch (e) {
      if (fallback) {
        fallback.innerHTML = `<pre>${escapeHtml(`fallback error: ${String(e)}`)}</pre>`;
      }
    }
  }, 500);
}

// =============================
// 記事オープン
// =============================
async function openPostByPath(postPath) {
  const rel = normalizePath(postPath);
  if (!rel) return;

  const mdUrl = new URL(rel, SITE_ROOT);

  setViewerHtml(`<p class="hint">読み込み中...<br><code>${escapeHtml(mdUrl.href)}</code></p>`);

  const res = await fetch(mdUrl.href, { cache: "no-store" });
  if (!res.ok) {
    setViewerHtml(`
      <p>記事の読み込みに失敗しました。</p>
      <pre>${escapeHtml(`${res.status} ${res.statusText}\n${mdUrl.href}`)}</pre>
      <p class="hint">posts.json の path / local_dir と実ファイルの場所が一致しているか確認してね。</p>
    `);
    return;
  }

  const rawMd = await res.text();
  const mdText = stripFrontMatter(rawMd);
  const mdDir = new URL("./", mdUrl);

  const bodyRef = findBodyFileRef(mdText);
  if (bodyRef) {
    const bodyUrl = new URL(normalizePath(bodyRef), mdDir);

    // viewerの枠を先に作る（ここがポイント：この後は枠の中だけ更新する）
    setViewerHtml(`
      <div class="meta">source: <a href="${mdUrl.href}" target="_blank" rel="noreferrer">${escapeHtml(
        rel
      )}</a></div>
      <div class="meta">body: <a href="${bodyUrl.href}" target="_blank" rel="noreferrer">${escapeHtml(
        bodyRef
      )}</a></div>
      <div class="meta" id="statusLine">status: preparing...</div>
      <hr>
      <div id="bodyMount"></div>
    `);

    const mountEl = viewerEl.querySelector("#bodyMount");
    const statusEl = viewerEl.querySelector("#statusLine");

    await showBodyHtml(bodyUrl, mountEl, statusEl);
    return;
  }

  // 本文指定が無ければMarkdownを雑表示
  const bodyHtml = renderMarkdownRough(mdText, mdUrl);
  setViewerHtml(`
    <div class="meta">source: <a href="${mdUrl.href}" target="_blank" rel="noreferrer">${escapeHtml(
      rel
    )}</a></div>
    <hr>
    ${bodyHtml}
  `);
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
      setViewerHtml(`<p class="hint">記事が見つかりません（posts.json の中身確認してね）</p>`);
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

// module scriptはdeferなので、普通に main() でOK（ブレにくい）
main();
