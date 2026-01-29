// docs/index/app.js
// GitHub Pages で「パスが壊れない」ことを最優先にしたビューア。
// - posts一覧: ./index/posts.json
// - 記事md:     ./posts/.../index.md
// - 本文:       ./posts/.../page.html（index.md内に「本文: page.html」など）
//
// 目的（今回）:
// - page.html をそのまま見せるのではなく「本文だけ」抽出して表示
// - 言語選択/ヘッダ/フッタ/他ページリンクなど“余計な部分”を消す
// - iframe由来の謎スペースや環境差の不安定さを無くす

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
// 本文抽出（page.html → 本文だけ）
// =============================

// できるだけ「本文」を掴むための候補セレクタ（上ほど優先）
const ARTICLE_SELECTORS = [
  "article",
  "main article",
  ".c-article",
  ".p-article",
  ".p-blog",
  ".p-blogDetail",
  ".p-diary",
  ".diary",
  "#diary",
  ".content",
  "#content",
  "main",
];

// 余計なものを消す（サイトのヘッダ/フッタ/ナビ/言語/シェア等）
const REMOVE_SELECTORS = [
  "header",
  "footer",
  "nav",
  "aside",
  "form",
  "select",
  ".language",
  ".lang",
  ".gNav",
  ".globalNav",
  ".breadcrumb",
  ".c-breadcrumb",
  ".share",
  ".sns",
  ".social",
  ".c-header",
  ".c-footer",
  ".l-header",
  ".l-footer",
  ".p-header",
  ".p-footer",
  ".c-nav",
  ".c-footer__nav",
  ".c-header__nav",
  ".p-sns",
  ".p-share",
  ".js-share",
  ".js-language",
];

function scoreNode(node) {
  if (!node) return 0;
  const textLen = (node.textContent || "").trim().length;
  const imgCount = node.querySelectorAll ? node.querySelectorAll("img").length : 0;
  // 文章が多い＋画像が少しあるとスコア高め
  return textLen + imgCount * 200;
}

function pickBestArticleRoot(doc) {
  let best = null;
  let bestScore = 0;

  for (const sel of ARTICLE_SELECTORS) {
    const nodes = Array.from(doc.querySelectorAll(sel));
    for (const n of nodes) {
      const sc = scoreNode(n);
      if (sc > bestScore) {
        bestScore = sc;
        best = n;
      }
    }
    if (best && bestScore > 800) break; // それっぽいの見つけたら早期終了
  }

  // どうしても無ければ body
  return best || doc.body;
}

function absolutizeLinks(rootEl, baseUrl) {
  const fixAttr = (el, attr) => {
    const v = el.getAttribute(attr);
    if (!v) return;
    const s = v.trim();
    // 触らないもの
    if (
      s.startsWith("http://") ||
      s.startsWith("https://") ||
      s.startsWith("data:") ||
      s.startsWith("mailto:") ||
      s.startsWith("tel:") ||
      s.startsWith("#")
    ) {
      return;
    }
    try {
      el.setAttribute(attr, new URL(s, baseUrl).href);
    } catch (_) {}
  };

  // a, img, source 等
  rootEl.querySelectorAll("a[href]").forEach((a) => fixAttr(a, "href"));
  rootEl.querySelectorAll("img[src]").forEach((img) => fixAttr(img, "src"));
  rootEl.querySelectorAll("source[src]").forEach((s) => fixAttr(s, "src"));

  // srcset は簡易対応（カンマ区切りのURL部分だけ解決）
  rootEl.querySelectorAll("[srcset]").forEach((el) => {
    const v = el.getAttribute("srcset");
    if (!v) return;
    const parts = v
      .split(",")
      .map((p) => p.trim())
      .filter(Boolean)
      .map((chunk) => {
        const [urlPart, sizePart] = chunk.split(/\s+/, 2);
        if (!urlPart) return chunk;
        if (
          urlPart.startsWith("http://") ||
          urlPart.startsWith("https://") ||
          urlPart.startsWith("data:")
        ) {
          return chunk;
        }
        try {
          const abs = new URL(urlPart, baseUrl).href;
          return sizePart ? `${abs} ${sizePart}` : abs;
        } catch (_) {
          return chunk;
        }
      });
    el.setAttribute("srcset", parts.join(", "));
  });
}

function cleanUp(rootEl) {
  // script/style は混ざると崩れるので消す
  rootEl.querySelectorAll("script, style, link[rel='stylesheet']").forEach((n) => n.remove());

  // 余計な領域を消す
  for (const sel of REMOVE_SELECTORS) {
    rootEl.querySelectorAll(sel).forEach((n) => n.remove());
  }

  // 空っぽのul/olや余計な改行が多いものを軽く間引く（安全な範囲）
  rootEl.querySelectorAll("ul,ol,div,section").forEach((n) => {
    const text = (n.textContent || "").trim();
    const imgs = n.querySelectorAll("img").length;
    if (!text && imgs === 0 && n.children.length === 0) n.remove();
  });
}

async function renderBodyFromPageHtml(bodyUrl, headerHtml) {
  // まずヘッダ＋読み込み表示
  viewerEl.innerHTML = `
    ${headerHtml}
    <div class="meta">body: <a href="${bodyUrl.href}" target="_blank" rel="noreferrer">${escapeHtml(
      bodyUrl.href
    )}</a></div>
    <div class="meta">status: loading body...</div>
    <hr>
    <div class="hint">本文を抽出しています...</div>
  `;

  const res = await fetch(bodyUrl.href, { cache: "no-store" });
  if (!res.ok) {
    viewerEl.innerHTML = `
      ${headerHtml}
      <p>page.html の読み込みに失敗しました。</p>
      <pre>${escapeHtml(`${res.status} ${res.statusText}\n${bodyUrl.href}`)}</pre>
    `;
    return;
  }

  const htmlText = await res.text();
  const doc = new DOMParser().parseFromString(htmlText, "text/html");

  // 本文っぽいところだけ拾う
  const root = pickBestArticleRoot(doc);
  const cloned = root.cloneNode(true);

  cleanUp(cloned);
  absolutizeLinks(cloned, bodyUrl);

  // ここで “謎スペース” の原因だった iframe を使わないので安定する
  viewerEl.innerHTML = `
    ${headerHtml}
    <div class="meta">body: <a href="${bodyUrl.href}" target="_blank" rel="noreferrer">${escapeHtml(
      bodyUrl.href
    )}</a></div>
    <div class="meta">status: extracted</div>
    <hr>
    <div style="background:#fff; border:1px solid #eee; border-radius:12px; padding:16px;">
      ${cloned.innerHTML}
    </div>
  `;
}

// =============================
// 記事オープン
// =============================
async function openPostByPath(postPath) {
  const rel = normalizePath(postPath);
  if (!rel) return;

  const mdUrl = new URL(rel, SITE_ROOT);

  viewerEl.innerHTML = `<p class="hint">読み込み中...<br><code>${escapeHtml(mdUrl.href)}</code></p>`;

  const res = await fetch(mdUrl.href, { cache: "no-store" });
  if (!res.ok) {
    viewerEl.innerHTML = `
      <p>記事の読み込みに失敗しました。</p>
      <pre>${escapeHtml(`${res.status} ${res.statusText}\n${mdUrl.href}`)}</pre>
      <p class="hint">posts.json の path / local_dir と実ファイルの場所が一致しているか確認してね。</p>
    `;
    return;
  }

  const rawMd = await res.text();
  const mdText = stripFrontMatter(rawMd);
  const mdDir = new URL("./", mdUrl);

  const headerHtml = `
    <div class="meta">source: <a href="${mdUrl.href}" target="_blank" rel="noreferrer">${escapeHtml(
      rel
    )}</a></div>
  `;

  const bodyRef = findBodyFileRef(mdText);
  if (bodyRef) {
    const bodyUrl = new URL(normalizePath(bodyRef), mdDir);
    await renderBodyFromPageHtml(bodyUrl, headerHtml);
    return;
  }

  // 本文指定が無ければMarkdownを雑表示
  const bodyHtml = renderMarkdownRough(mdText, mdUrl);
  viewerEl.innerHTML = `
    ${headerHtml}
    <hr>
    ${bodyHtml}
  `;
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
      viewerEl.innerHTML = `<p class="hint">記事が見つかりません（posts.json の中身確認してね）</p>`;
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
