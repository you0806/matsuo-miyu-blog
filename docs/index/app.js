// docs/index/app.js
// GitHub Pages で「パスが壊れない」ことを最優先にしたシンプルビューア。
// - posts一覧: ./index/posts.json
// - 記事md:     ./posts/.../index.md
// - 本文HTML:   ./posts/.../page.html（あれば優先表示）
// - 画像:       記事フォルダ内 images/.. を想定
//
// ポイント：
// 1) 先頭スラッシュの絶対パス "/posts/..." は使わない
// 2) new URL("相対パス", "基準URL") で必ずURLを作る

const listEl = document.getElementById("list");
const viewerEl = document.getElementById("viewer");
const listMetaEl = document.getElementById("listMeta");

// <base href="./"> があると、document.baseURI が GitHub Pages の /<repo>/ を基準にしてくれる
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

function normalizeSlash(p) {
  // Windows の \ を / に統一
  return String(p ?? "").replaceAll("\\", "/");
}

function getPostPathFromHash() {
  const h = location.hash.replace(/^#/, "");
  const params = new URLSearchParams eliminates(h);
  return params.get("p");
}

function setPostPathToHash(path) {
  const params = new URLSearchParams(location.hash.replace(/^#/, ""));
  params.set("p", path);
  location.hash = params.toString();
}

/**
 * frontmatter っぽい --- で挟まれたブロックを除去（あれば）
 */
function stripFrontMatter(mdText) {
  const text = String(mdText ?? "");
  // 先頭が --- で始まる場合だけ対応
  if (!text.startsWith("---")) return text;

  // 2つ目の --- を探す
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

  const lines = String(mdText ?? "").split("\n");
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
        return `<a href="${linkUrl.href}" target="_blank" rel="noreferrer">${escapeHtml(text)}</a>`;
      });

      if (line.trim() === "") return "<br>";
      return `<p>${escapeHtml(line)}</p>`;
    })
    .join("");

  return html;
}

/**
 * HTMLをDOMとして読み、script等を落として、リンク/画像の相対パスを絶対URLへ解決
 */
function sanitizeAndFixHtml(htmlText, baseUrl) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(String(htmlText ?? ""), "text/html");

  // 危険寄りの要素を削除
  doc.querySelectorAll("script, iframe, object, embed").forEach((el) => el.remove());

  // 相対URLを解決する（img/src, a/href, source/srcset など）
  const fixUrlAttr = (el, attr) => {
    const v = el.getAttribute(attr);
    if (!v) return;
    // javascript: は無効化
    if (/^\s*javascript:/i.test(v)) {
      el.removeAttribute(attr);
      return;
    }
    try {
      el.setAttribute(attr, new URL(v, baseUrl).href);
    } catch {
      // 変なURLはそのまま
    }
  };

  doc.querySelectorAll("a[href]").forEach((a) => {
    fixUrlAttr(a, "href");
    a.setAttribute("target", "_blank");
    a.setAttribute("rel", "noreferrer");
  });

  doc.querySelectorAll("img[src]").forEach((img) => fixUrlAttr(img, "src"));

  // srcset対応（あれば）
  doc.querySelectorAll("[srcset]").forEach((el) => {
    const v = el.getAttribute("srcset");
    if (!v) return;
    const parts = v.split(",").map((s) => s.trim()).filter(Boolean);
    const fixed = parts
      .map((part) => {
        const [u, size] = part.split(/\s+/, 2);
        try {
          const abs = new URL(u, baseUrl).href;
          return size ? `${abs} ${size}` : abs;
        } catch {
          return part;
        }
      })
      .join(", ");
    el.setAttribute("srcset", fixed);
  });

  // bodyの中身だけ返す（styleはCSSで統一したいので基本捨てる）
  return doc.body ? doc.body.innerHTML : escapeHtml(htmlText);
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

/**
 * posts.json の1件を、ビューア用の形に整形
 * - p.path があればそれを使う
 * - なければ local_dir から index.md を推測
 */
function normalizePostItem(p) {
  const title = p.title ?? "(no title)";
  const datetime = p.datetime ?? p.date ?? "";
  const id = p.id ?? "";
  const origUrl = p.url ?? p.source_url ?? "";

  let path = p.path;
  if (!path && p.local_dir) {
    path = normalizeSlash(p.local_dir).replace(/\/+$/, "") + "/index.md";
  }
  path = normalizeSlash(path ?? "");

  return { title, datetime, id, origUrl, path, raw: p };
}

function renderPostList(rawPosts) {
  const posts = Array.isArray(rawPosts) ? rawPosts.map(normalizePostItem) : [];
  listEl.innerHTML = "";

  if (listMetaEl) {
    listMetaEl.textContent = `全 ${posts.length} 件`;
  }

  posts.forEach((p) => {
    const div = document.createElement("div");
    div.className = "post";

    div.innerHTML = `
      <div><strong>${escapeHtml(p.title)}</strong></div>
      <div class="meta">${escapeHtml(p.datetime)}${p.id ? ` / id:${escapeHtml(p.id)}` : ""}</div>
      <div class="meta">${escapeHtml(p.path)}</div>
      ${
        p.origUrl
          ? `<div class="meta">orig: <a href="${escapeHtml(p.origUrl)}" target="_blank" rel="noreferrer">${escapeHtml(
              p.origUrl
            )}</a></div>`
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

  // postPath をサイトルートからの相対としてURL化
  const mdUrl = new URL(postPath, SITE_ROOT);
  const postDir = new URL("./", mdUrl); // 記事フォルダ

  viewerEl.innerHTML = `<p class="hint">読み込み中...<br><code>${escapeHtml(mdUrl.href)}</code></p>`;

  // 1) まず index.md を読む（メタやフォールバック用）
  const mdRes = await fetch(mdUrl.href, { cache: "no-store" });
  if (!mdRes.ok) {
    viewerEl.innerHTML = `
      <p>記事の読み込みに失敗しました。</p>
      <pre>${escapeHtml(`${mdRes.status} ${mdRes.statusText}\n${mdUrl.href}`)}</pre>
      <p class="hint">posts.json の path と実ファイルの場所が一致しているか確認してね。</p>
    `;
    return;
  }
  const mdTextRaw = await mdRes.text();
  const mdText = stripFrontMatter(mdTextRaw);

  // 2) 同じフォルダの page.html があれば本文として表示（完成形に近い）
  const pageHtmlUrl = new URL("./page.html", postDir);
  const pageRes = await fetch(pageHtmlUrl.href, { cache: "no-store" });

  let bodyHtml = "";
  if (pageRes.ok) {
    const htmlText = await pageRes.text();
    bodyHtml = sanitizeAndFixHtml(htmlText, pageHtmlUrl);
    viewerEl.innerHTML = `
      <div class="meta">source:
        <a href="${mdUrl.href}" target="_blank" rel="noreferrer">${escapeHtml(postPath)}</a>
        / html:
        <a href="${pageHtmlUrl.href}" target="_blank" rel="noreferrer">page.html</a>
      </div>
      <hr>
      ${bodyHtml}
    `;
    return;
  }

  // 3) page.html が無ければ、index.md を雑Markdownとして表示
  const mdBodyHtml = renderMarkdownRough(mdText, mdUrl);
  viewerEl.innerHTML = `
    <div class="meta">source: <a href="${mdUrl.href}" target="_blank" rel="noreferrer">${escapeHtml(postPath)}</a></div>
    <hr>
    ${mdBodyHtml}
    <p class="hint">※ page.html が無かったので index.md をそのまま表示しています。</p>
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

    // サンプル表示：hashが無い場合は先頭の記事を自動で開く
    const first = posts.find((p) => p.path);
    if (first?.path) {
      setPostPathToHash(first.path);
      openPostByPath(first.path);
    }
  } catch (e) {
    listEl.innerHTML = `<pre>${escapeHtml(String(e))}</pre>`;
  }
}

// hash が変わったら記事切り替え（戻る/進む対応）
window.addEventListener("hashchange", () => {
  const p = getPostPathFromHash();
  if (p) openPostByPath(p);
});

main();
