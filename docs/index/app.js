// docs/index/app.js
// GitHub Pages で「パスが壊れない」ことを最優先にしたシンプルビューア。
// - posts一覧: ./index/posts.json
// - 記事md:     ./posts/.../index.md
// - 画像:       mdと同じフォルダ内 images/.. を想定
//
// ポイント：
// 1) 先頭スラッシュの絶対パス "/posts/..." は使わない
// 2) new URL("相対パス", "基準URL") で必ずURLを作る

const listEl = document.getElementById("list");
const viewerEl = document.getElementById("viewer");

// <base href="./"> がある前提で、ここは /<repo>/ を基準にできる
const SITE_ROOT = new URL(document.baseURI);

// posts.json は docs/index/posts.json → 公開URLでは /index/posts.json
const POSTS_INDEX_URL = new URL("./index/posts.json", SITE_ROOT);

// =============================
// 便利関数
// =============================

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function getPostPathFromHash() {
  const h = location.hash.replace(/^#/, "");
  const params = new URLSearchParams(h);
  return params.get("p"); // なければ null
}

function setPostPathToHash(path) {
  const params = new URLSearchParams(location.hash.replace(/^#/, ""));
  params.set("p", path);
  location.hash = params.toString();
}

// Windowsパスっぽい "\" を "/" に、先頭の "./" などを軽く正規化
function normalizePath(p) {
  let s = String(p ?? "");
  s = s.replaceAll("\\", "/");
  s = s.replace(/^\.\/+/, ""); // "./posts/.." -> "posts/.."
  return s;
}

/**
 * posts.json の1件を「表示に必要な形」に寄せる
 * - 期待キー: title, date, datetime, path, local_dir, url/source_url
 * - path が無ければ local_dir から "posts/.../index.md" を生成
 */
function normalizePostItem(raw) {
  const title = raw.title ?? raw.name ?? "(no title)";
  const date = raw.date ?? raw.datetime ?? raw.updated ?? "";

  // 1) 既に path があるならそれを優先
  let path = raw.path ? normalizePath(raw.path) : "";

  // 2) path が無い場合は local_dir から作る（君のJSON形式対応）
  // local_dir: "posts\\2025\\2025-04-23_1409_103378"
  if (!path && raw.local_dir) {
    const dir = normalizePath(raw.local_dir);
    path = `${dir}/index.md`;
  }

  // 3) それでも無ければ id と日付などから推測はしない（事故るので空）
  const orig = raw.url ?? raw.source_url ?? raw.sourceUrl ?? "";

  return { title, date, path, orig, raw };
}

/**
 * frontmatter(--- ... ---) を消す
 */
function stripFrontMatter(mdText) {
  const text = String(mdText ?? "");
  if (!text.startsWith("---")) return text;

  // 2つ目の "---" を探す
  const idx = text.indexOf("\n---", 3);
  if (idx === -1) return text;

  // "\n---" の行末まで飛ばす
  const after = text.indexOf("\n", idx + 1);
  if (after === -1) return "";
  return text.slice(after + 1);
}

/**
 * Markdownを“最低限”HTMLっぽく表示（凝った変換はしない）
 * - 見出し(#) / 画像(![]) / リンク([]()) だけ軽く対応
 */
function renderMarkdownRough(mdText, mdFileUrl) {
  const mdDir = new URL("./", mdFileUrl);
  const lines = mdText.split("\n");

  const html = lines
    .map((line) => {
      // 見出し
      if (line.startsWith("### ")) return `<h3>${escapeHtml(line.slice(4))}</h3>`;
      if (line.startsWith("## ")) return `<h2>${escapeHtml(line.slice(3))}</h2>`;
      if (line.startsWith("# ")) return `<h1>${escapeHtml(line.slice(2))}</h1>`;

      // 画像 ![alt](path)
      line = line.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, src) => {
        const imgUrl = new URL(src, mdDir);
        return `<img alt="${escapeHtml(alt)}" src="${imgUrl.href}">`;
      });

      // リンク [text](url)
      line = line.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, text, href) => {
        const linkUrl = new URL(href, mdDir);
        return `<a href="${linkUrl.href}" target="_blank" rel="noreferrer">${escapeHtml(text)}</a>`;
      });

      // 空行
      if (line.trim() === "") return "<br>";

      return `<p>${escapeHtml(line)}</p>`;
    })
    .join("");

  return html;
}

// =============================
// メイン処理
// =============================

async function loadPostsIndex() {
  const res = await fetch(POSTS_INDEX_URL.href, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(
      `posts.json の読み込み失敗: ${res.status} ${res.statusText}\nURL: ${POSTS_INDEX_URL.href}`
    );
  }
  // JSON壊れてるとここで落ちる（末尾カンマとか）
  return await res.json();
}

function renderPostList(rawPosts) {
  const posts = (Array.isArray(rawPosts) ? rawPosts : [])
    .map(normalizePostItem)
    .filter((p) => p.path); // path が作れたものだけ表示

  listEl.innerHTML = "";

  const head = document.createElement("div");
  head.className = "meta";
  head.style.margin = "6px 0 10px";
  head.innerHTML = `posts: <strong>${posts.length}</strong><br><span class="hint">index: <code>${escapeHtml(
    POSTS_INDEX_URL.href
  )}</code></span>`;
  listEl.appendChild(head);

  posts.forEach((p) => {
    const div = document.createElement("div");
    div.className = "post";

    div.innerHTML = `
      <div><strong>${escapeHtml(p.title)}</strong></div>
      <div class="meta">${escapeHtml(p.date)}</div>
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

  return posts;
}

async function openPostByPath(postPath) {
  if (!postPath) return;

  const safePath = normalizePath(postPath);
  const mdUrl = new URL(safePath, SITE_ROOT);

  viewerEl.innerHTML = `<p class="hint">読み込み中...<br><code>${escapeHtml(mdUrl.href)}</code></p>`;

  const res = await fetch(mdUrl.href, { cache: "no-store" });
  if (!res.ok) {
    viewerEl.innerHTML = `
      <p>記事の読み込みに失敗しました。</p>
      <pre>${escapeHtml(`${res.status} ${res.statusText}\n${mdUrl.href}`)}</pre>
      <p class="hint">確認ポイント：<br>
        1) 実ファイルが <code>docs/${escapeHtml(safePath)}</code> にあるか<br>
        2) GitHub Pages の公開元が <code>docs/</code> になっているか
      </p>
    `;
    return;
  }

  const mdTextRaw = await res.text();
  const mdText = stripFrontMatter(mdTextRaw);

  const bodyHtml = renderMarkdownRough(mdText, mdUrl);

  viewerEl.innerHTML = `
    <div class="meta">
      source: <a href="${mdUrl.href}" target="_blank" rel="noreferrer">${escapeHtml(safePath)}</a>
    </div>
    <hr>
    ${bodyHtml}
  `;
}

async function main() {
  try {
    const rawPosts = await loadPostsIndex();
    const posts = renderPostList(rawPosts);

    // URLハッシュに #p=... が入ってたら、その記事を開く
    const fromHash = getPostPathFromHash();
    if (fromHash) {
      openPostByPath(fromHash);
      return;
    }

    // ★ サンプル表示：hash が無い場合は先頭の記事を自動で開く
    const first = posts.find((p) => p.path);
    if (first?.path) {
      setPostPathToHash(first.path);
      openPostByPath(first.path);
    }
  } catch (e) {
    // ここが出るなら「posts.json 取得 or JSON壊れ」が濃厚
    listEl.innerHTML = `<pre>${escapeHtml(String(e))}</pre>
<div class="hint">URLを直に開いて確認：<br><code>${escapeHtml(
      POSTS_INDEX_URL.href
    )}</code></div>`;
    viewerEl.innerHTML = `<p class="hint">エラーのため表示できません。</p>`;
  }
}

window.addEventListener("hashchange", () => {
  const p = getPostPathFromHash();
  if (p) openPostByPath(p);
});

main();
