// docs/index/app.js
// GitHub Pages で「パスが壊れない」ことを最優先にしたシンプルビューア。
// - posts一覧: ./index/posts.json
// - 記事md:     ./posts/.../index.md
// - 記事本文:   ./posts/.../page.html（index.md に「本文: page.html」等で指定）
// - 画像:       page.html / md と同じフォルダ内 images/.. を想定
//
// ポイント：
// 1) 先頭スラッシュの絶対パス "/posts/..." は使わない
// 2) new URL("相対パス", "基準URL") で必ずURLを作る
// 3) Windowsパス "\" は必ず "/" に直す

const listEl = document.getElementById("list");
const viewerEl = document.getElementById("viewer");

// <base href="./"> がある前提で、Pagesの /<repo>/ を壊さない基準URLになる
const SITE_ROOT = new URL(document.baseURI);

// docs/index/posts.json → 公開URLでも /index/posts.json
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

/** Windowsの \ を / に、先頭の ./ と / を除去して「サイトルート基準の相対」に寄せる */
function normalizePath(p) {
  if (!p) return "";
  let s = String(p).trim();
  s = s.replaceAll("\\", "/");
  s = s.replace(/^\.\/+/, "");
  s = s.replace(/^\/+/, "");
  return s;
}

/** hash から p を取り出す: 例 #p=posts/2025/.../index.md */
function getPostPathFromHash() {
  const h = location.hash.replace(/^#/, "");
  const params = new URLSearchParams(h);
  const p = params.get("p");
  return p ? normalizePath(p) : null;
}

/** hash に p を入れる */
function setPostPathToHash(path) {
  const params = new URLSearchParams(location.hash.replace(/^#/, ""));
  params.set("p", normalizePath(path));
  location.hash = params.toString();
}

/** frontmatterっぽい先頭 --- ... --- を除去 */
function stripFrontMatter(mdText) {
  const text = String(mdText ?? "");
  if (!text.startsWith("---")) return text;
  const idx = text.indexOf("\n---", 3);
  if (idx === -1) return text;
  const after = text.indexOf("\n", idx + 1);
  return after === -1 ? "" : text.slice(after + 1);
}

/**
 * index.md の中から「本文: page.html」みたいな指定を拾う（強化版）
 * 対応する例:
 *  - 本文: page.html
 *  - 本文：page.html   （全角コロン）
 *  -   本文 : page.html（先頭スペース）
 *  - - 本文: page.html （箇条書き）
 *  - body: page.html
 */
function findBodyFileRef(mdText) {
  const t = String(mdText ?? "");

  // 行ごとに見る（正規表現1発より堅い）
  const lines = t.split("\n");
  for (const line of lines) {
    const s = line.trim();

    // 先頭の "- " や "・" を許容
    const cleaned = s.replace(/^[-•・]\s*/, "");

    // "本文" or "body" + ":" or "：" を許容
    const m = cleaned.match(/^(本文|body)\s*[:：]\s*(.+)\s*$/i);
    if (m) {
      const ref = m[2]?.trim();
      if (ref) return ref;
    }
  }
  return null;
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
        return `<a href="${linkUrl.href}" target="_blank" rel="noreferrer">${escapeHtml(
          text
        )}</a>`;
      });

      if (line.trim() === "") return "<br>";
      return `<p>${escapeHtml(line)}</p>`;
    })
    .join("");

  return html;
}

// =============================
// posts.json 読み込み＆整形
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

/**
 * posts.json の1件を「表示用の標準形」に変換
 * あなたのJSON例:
 * { id, title, datetime, url, local_dir, images: [...] }
 */
function toViewModel(raw) {
  const title = raw.title ?? "(no title)";
  const date = raw.datetime ?? raw.date ?? "";
  const orig = raw.url ?? raw.source_url ?? "";

  // 最優先：raw.path があればそれを使う（すでに相対になってる想定）
  let path = raw.path ? normalizePath(raw.path) : "";

  // 次：local_dir から index.md を組み立てる
  // 例: "posts\\2025\\2025-04-23_1409_103378" → "posts/2025/2025-04-23_1409_103378/index.md"
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

  // ちょいデバッグ（消したければ消してOK）
  const info = document.createElement("div");
  info.className = "hint";
  info.innerHTML = `
    <div>posts: ${posts.length}</div>
    <div>index: <a href="${POSTS_INDEX_URL.href}" target="_blank" rel="noreferrer">${POSTS_INDEX_URL.href}</a></div>
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
// 記事オープン
// =============================

async function openPostByPath(postPath) {
  const rel = normalizePath(postPath);
  if (!rel) return;

  const mdUrl = new URL(rel, SITE_ROOT);

  viewerEl.innerHTML = `<p class="hint">読み込み中...<br><code>${escapeHtml(
    mdUrl.href
  )}</code></p>`;

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

  // index.md に本文ファイル指定があるなら、それを優先して表示
  const bodyRef = findBodyFileRef(mdText);

  if (bodyRef) {
    const bodyUrl = new URL(normalizePath(bodyRef), mdDir);

    viewerEl.innerHTML = `
      <div class="meta">source: <a href="${mdUrl.href}" target="_blank" rel="noreferrer">${escapeHtml(
        rel
      )}</a></div>
      <div class="meta">body: <a href="${bodyUrl.href}" target="_blank" rel="noreferrer">${escapeHtml(
        bodyRef
      )}</a></div>
      <hr>
      <iframe
        src="${bodyUrl.href}"
        style="width:100%; height: calc(100vh - 160px); border:0; border-radius:12px; background:#fff;"
        loading="lazy"
      ></iframe>
    `;
    return;
  }

  // 見つからなければ Markdown を雑表示
  const bodyHtml = renderMarkdownRough(mdText, mdUrl);

  viewerEl.innerHTML = `
    <div class="meta">source: <a href="${mdUrl.href}" target="_blank" rel="noreferrer">${escapeHtml(
      rel
    )}</a></div>
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

    // hash が無い場合は先頭の記事を自動で開く（サンプル表示）
    const first = posts[0];
    if (first?.path) {
      setPostPathToHash(first.path);
      openPostByPath(first.path);
    }
  } catch (e) {
    listEl.innerHTML = `<pre>${escapeHtml(String(e))}</pre>`;
  }
}

window.addEventListener("hashchange", () => {
  const p = getPostPathFromHash();
  if (p) openPostByPath(p);
});

main();
