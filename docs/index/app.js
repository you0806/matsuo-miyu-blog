// docs/index/app.js
// GitHub Pages で「パスが壊れない」ことを最優先にしたシンプルビューア。
// - posts一覧: ./index/posts.json
// - 記事md:     ./posts/.../index.md
// - 画像:       mdと同じフォルダ内 images/.. を想定
//
// ポイント：
// 1) 先頭スラッシュの絶対パス "/posts/..." は使わない
// 2) new URL("相対パス", "基準URL") で必ずURLを作る
//
// 今回の posts.json は例として以下の形を想定（あなたの貼った形）
// { id, title, datetime, url, local_dir, images, ... }
// ※ path が無いので local_dir から index.md を組み立てる

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
 * Windows の \ 区切りを / に直しつつ、先頭の / を消して相対パス化
 */
function normalizeRelPath(p) {
  let s = String(p ?? "");
  s = s.replaceAll("\\", "/");
  s = s.replace(/^\/+/, "");     // 先頭 / は絶対扱いになるので除去
  s = s.replace(/^\.\//, "");    // ./ を消す
  return s;
}

/**
 * posts.json の1件を、このビューア用の共通形式にする
 * - title
 * - date/datetime
 * - path (必須): "posts/.../index.md" の形に揃える
 */
function normalizePostItem(p) {
  const title = p?.title ?? "(no title)";
  const datetime = p?.datetime ?? p?.date ?? "";
  const id = p?.id ?? "";
  const originalUrl = p?.url ?? "";

  // 優先順位：
  // 1) p.path があるならそれを使う（将来対応）
  // 2) p.local_dir があるなら local_dir/index.md を組み立てる
  // 3) それも無いなら null
  let path = null;

  if (p?.path) {
    path = normalizeRelPath(p.path);
  } else if (p?.local_dir) {
    // 例: "posts\\2025\\2025-04-23_1409_103378"
    const dir = normalizeRelPath(p.local_dir);
    path = `${dir}/index.md`;
  }

  return { title, datetime, id, originalUrl, path };
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
  location.hash = params.toString();
}

/**
 * Markdownを“最低限”HTMLっぽく表示（凝った変換はしない）
 * - 見出し(#) / 画像(![]) / リンク([]()) だけ軽く対応
 * - 本格的にやりたいなら marked.js 等を入れるのが定番
 */
function renderMarkdownRough(mdText, mdFileUrl) {
  // mdFileUrl = 記事のindex.mdのURL
  // 画像などの相対パスの基準（記事のフォルダ）を作る
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
        try {
          const imgUrl = new URL(src, mdDir);
          return `<img alt="${escapeHtml(alt)}" src="${imgUrl.href}">`;
        } catch {
          return `<span class="hint">[image parse error: ${escapeHtml(src)}]</span>`;
        }
      });

      // リンク [text](url)
      line = line.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, text, href) => {
        try {
          const linkUrl = new URL(href, mdDir);
          return `<a href="${linkUrl.href}" target="_blank" rel="noreferrer">${escapeHtml(text)}</a>`;
        } catch {
          return `<span class="hint">[link parse error: ${escapeHtml(href)}]</span>`;
        }
      });

      // 空行は段落区切りっぽく
      if (line.trim() === "") return "<br>";

      // 通常行
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
  const json = await res.json();
  if (!Array.isArray(json)) {
    throw new Error("posts.json は配列(JSON Array)である必要があります。");
  }
  return json;
}

function renderPostList(rawPosts) {
  listEl.innerHTML = "";

  const posts = rawPosts.map(normalizePostItem);

  posts.forEach((p, idx) => {
    const div = document.createElement("div");
    div.className = "post";

    const pathView = p.path ?? "(no local path)";
    div.innerHTML = `
      <div><strong>${escapeHtml(p.title)}</strong></div>
      <div class="meta">${escapeHtml(p.datetime)}${p.id ? ` / id:${escapeHtml(p.id)}` : ""}</div>
      <div class="meta">${escapeHtml(pathView)}</div>
      ${
        p.originalUrl
          ? `<div class="meta">orig: <a href="${escapeHtml(p.originalUrl)}" target="_blank" rel="noreferrer">${escapeHtml(p.originalUrl)}</a></div>`
          : ""
      }
    `;

    div.addEventListener("click", () => {
      if (!p.path) {
        viewerEl.innerHTML = `<p>この項目は表示できません（path が作れません）。</p>`;
        return;
      }
      setPostPathToHash(p.path);
      openPostByPath(p.path);
    });

    // 先頭に軽く目印（任意）
    if (idx === 0) {
      div.style.borderTop = "1px solid #eee";
    }

    listEl.appendChild(div);
  });

  return posts;
}

async function openPostByPath(postPath) {
  if (!postPath) return;

  // 絶対扱いを避けるため、先頭 / を除去して相対化
  const safePath = normalizeRelPath(postPath);

  // postPath をサイトルートからの相対としてURL化（これで /repo/ でも壊れない）
  const mdUrl = new URL(safePath, SITE_ROOT);

  viewerEl.innerHTML = `<p class="hint">読み込み中...<br><code>${escapeHtml(mdUrl.href)}</code></p>`;

  const res = await fetch(mdUrl.href, { cache: "no-store" });
  if (!res.ok) {
    viewerEl.innerHTML = `
      <p>記事の読み込みに失敗しました。</p>
      <pre>${escapeHtml(`${res.status} ${res.statusText}\n${mdUrl.href}`)}</pre>
      <p class="hint">posts.json の local_dir（or path）と実ファイルの場所が一致しているか確認してね。</p>
    `;
    return;
  }

  const mdText = await res.text();
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
    listEl.innerHTML = `<pre>${escapeHtml(String(e))}</pre>`;
  }
}

// hash が変わったら記事切り替え（ブラウザの戻る/進むにも対応）
window.addEventListener("hashchange", () => {
  const p = getPostPathFromHash();
  if (p) openPostByPath(p);
});

main();
