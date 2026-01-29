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

// document.baseURI は <base href="./"> があると「サイトのルート」を基準にできる
// 例: https://user.github.io/repo/ みたいな感じ
const SITE_ROOT = new URL(document.baseURI);

// posts.json は docs/index/posts.json → 公開URLでは /index/posts.json
const POSTS_INDEX_URL = new URL("./index/posts.json", SITE_ROOT);

// =============================
// 便利関数
// =============================

/**
 * 文字列をHTMLに入れても安全な形に変換（最低限）
 */
function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

/**
 * hash から p を取り出す
 * 例: #p=posts/2025/.../index.md
 */
function getPostPathFromHash() {
  const h = location.hash.replace(/^#/, "");
  const params = new URLSearchParams(h);
  return params.get("p"); // なければ null
}

/**
 * hash に p を入れる
 */
function setPostPathToHash(path) {
  const params = new URLSearchParams(location.hash.replace(/^#/, ""));
  params.set("p", path);
  location.hash = params.toString(); // 例: #p=posts/...
}

/**
 * パスの区切りを / に統一（Windowsの \ 対策）
 */
function normalizeSlashes(path) {
  return String(path ?? "").replaceAll("\\", "/");
}

/**
 * posts.json(あなたの形式) → viewer用の形式へ正規化
 * 入力例:
 *  {
 *    "id": "103378",
 *    "title": "...",
 *    "datetime": "2025.04.23 14:09",
 *    "url": "https://...",
 *    "local_dir": "posts\\2025\\2025-04-23_1409_103378",
 *    ...
 *  }
 *
 * 出力:
 *  { title, date, path, id, url }
 *  path は "posts/....../index.md" の形に揃える
 */
function normalizePosts(rawPosts) {
  if (!Array.isArray(rawPosts)) return [];

  return rawPosts
    .map((p) => {
      const title = p.title ?? "(no title)";
      const date = p.datetime ?? p.date ?? "";
      const id = p.id ?? "";
      const url = p.url ?? p.source_url ?? "";

      // 既に path があるならそれ優先。なければ local_dir から作る
      let path = p.path ?? "";
      if (!path && p.local_dir) {
        // local_dir はディレクトリ想定なので /index.md を付ける
        path = `${p.local_dir}/index.md`;
      }

      path = normalizeSlashes(path);

      // もし "docs/posts/..." みたいに docs が混ざってたら消しておく（保険）
      path = path.replace(/^docs\//, "");

      return { title, date, path, id, url };
    })
    .filter((p) => p.path); // path 無いものは除外
}

/**
 * Markdownを“最低限”HTMLっぽく表示（凝った変換はしない）
 * - 見出し(#) / 画像(![]) / リンク([]()) だけ軽く対応
 */
function renderMarkdownRough(mdText, mdFileUrl) {
  const mdDir = new URL("./", mdFileUrl);

  const lines = String(mdText ?? "").split("\n");
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
  return await res.json();
}

function renderPostList(posts) {
  listEl.innerHTML = "";

  posts.forEach((p) => {
    const div = document.createElement("div");
    div.className = "post";

    div.innerHTML = `
      <div><strong>${escapeHtml(p.title ?? "(no title)")}</strong></div>
      <div class="meta">${escapeHtml(p.date ?? "")} ${p.id ? ` / id:${escapeHtml(p.id)}` : ""}</div>
      <div class="meta">${escapeHtml(p.path ?? "")}</div>
      ${
        p.url
          ? `<div class="meta">orig: <a href="${escapeHtml(p.url)}" target="_blank" rel="noreferrer">${escapeHtml(p.url)}</a></div>`
          : ""
      }
    `;

    div.addEventListener("click", () => {
      setPostPathToHash(p.path);
      openPostByPath(p.path);
    });

    listEl.appendChild(div);
  });

  return posts; // 呼び出し元で先頭を開くのに使える
}

async function openPostByPath(postPath) {
  if (!postPath) return;

  const mdUrl = new URL(postPath, SITE_ROOT);

  viewerEl.innerHTML = `<p class="hint">読み込み中...<br><code>${escapeHtml(mdUrl.href)}</code></p>`;

  const res = await fetch(mdUrl.href, { cache: "no-store" });
  if (!res.ok) {
    viewerEl.innerHTML = `
      <p>記事の読み込みに失敗しました。</p>
      <pre>${escapeHtml(`${res.status} ${res.statusText}\n${mdUrl.href}`)}</pre>
      <p class="hint">posts.json の path（または local_dir）と、Pagesに公開されている実ファイルの場所が一致しているか確認してね。</p>
    `;
    return;
  }

  const mdText = await res.text();
  const bodyHtml = renderMarkdownRough(mdText, mdUrl);

  viewerEl.innerHTML = `
    <div class="meta">source: <a href="${mdUrl.href}" target="_blank" rel="noreferrer">${escapeHtml(postPath)}</a></div>
    <hr>
    ${bodyHtml}
  `;
}

async function main() {
  try {
    const rawPosts = await loadPostsIndex();
    const posts = normalizePosts(rawPosts);
    renderPostList(posts);

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
    listEl.innerHTML = `<pre>${escapeHtml(String(e))}</pre>`;
  }
}

// hash が変わったら記事切り替え（ブラウザの戻る/進むにも対応）
window.addEventListener("hashchange", () => {
  const p = getPostPathFromHash();
  if (p) openPostByPath(p);
});

main();
