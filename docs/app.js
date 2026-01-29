/* =========================================================
   Blog Archive Viewer (GitHub Pages用)
   - 重要：GitHub Pagesは /matsuo-miyu-blog/ のような “サブパス” で動く
   - そのため「/index/posts.json」みたいな “先頭/” の絶対パスは 404 になりがち
   - なので必ず「./index/posts.json」のように相対パスで読む
   ========================================================= */

"use strict";

/* =========================
   1) 設定（ここだけ触ればOK）
   ========================= */

// posts.json の場所（docs/ の中に index/posts.json がある想定）
const INDEX_URL = "./index/posts.json";

// 記事HTMLのファイル名（あなたのfetch.pyが吐いている名前に合わせる）
const DEFAULT_PAGE_HTML = "page.html";       // できればこれを表示
const DEFAULT_PAGE_RAW_HTML = "page_raw.html"; // 生HTML（あれば）

/* =========================
   2) 画面の要素を取得
   index.html 側に以下の要素がある前提：
   - #searchInput
   - #postList
   - #postTitle
   - #postMeta
   - #postBody
   - #postImages
   ========================= */

// もしIDが違っても、ここを変えれば動く
const el = {
  search: document.getElementById("searchInput"),
  list: document.getElementById("postList"),
  title: document.getElementById("postTitle"),
  meta: document.getElementById("postMeta"),
  body: document.getElementById("postBody"),
  images: document.getElementById("postImages"),
};

// 画面が想定と違うときに落ちないように最低限チェック
for (const [k, v] of Object.entries(el)) {
  if (!v) {
    console.warn(`[WARN] element not found: ${k}. index.html のIDを確認してね`);
  }
}

/* =========================
   3) 便利関数
   ========================= */

function escapeHtml(str) {
  // タイトル等を安全に表示するための最低限エスケープ
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toDateText(value) {
  // posts.jsonの日時表現が色々でもなるべく表示する
  if (!value) return "";
  try {
    // 例： "2025-04-23 14:09" や "2025/04/23 14:09" などを雑に対応
    const s = String(value).replaceAll("/", "-");
    const d = new Date(s);
    if (Number.isNaN(d.getTime())) return String(value);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `${y}-${m}-${day} ${hh}:${mm}`;
  } catch {
    return String(value);
  }
}

function pick(obj, keys) {
  // objから keys のどれか最初に見つかった値を返す
  for (const k of keys) {
    if (obj && obj[k] != null && obj[k] !== "") return obj[k];
  }
  return null;
}

/* =========================
   4) posts.json を “ある程度どんな形式でも” 受け取れるよう正規化
   ========================= */

function normalizePost(raw) {
  // rawは posts.json の1要素（1記事）
  // fetch.py の実装が違っても動くように “候補キーを複数” で拾う

  const id = pick(raw, ["id", "post_id", "diary_id"]) ?? "";
  const title = pick(raw, ["title", "subject", "headline"]) ?? "(no title)";
  const datetime = pick(raw, ["datetime", "date", "published_at", "updated_at", "time"]) ?? "";

  // 記事フォルダのパス候補（例： posts/2025/2025-04-23_1409_103378）
  const folder =
    pick(raw, ["folder", "dir", "local_dir", "path_dir"]) ??
    pick(raw, ["local_path"]) ??
    "";

  // 記事のHTMLパス候補
  // 例： posts/.../page.html を指しているならそれを使う
  const pageHtml =
    pick(raw, ["page_html", "page", "html", "local_html"]) ??
    (folder ? `${folder}/${DEFAULT_PAGE_HTML}` : "");

  const pageRawHtml =
    pick(raw, ["page_raw_html", "raw_html"]) ??
    (folder ? `${folder}/${DEFAULT_PAGE_RAW_HTML}` : "");

  // 画像リスト候補（例： ["posts/.../images/01.jpg", ...]）
  const images = pick(raw, ["images", "image_paths", "photos"]) ?? [];

  // ブログ内URL（オリジナル）
  const originalUrl = pick(raw, ["url", "original_url", "source_url"]) ?? "";

  // 年（一覧でグルーピング用）
  // datetimeがあればそこから、なければ folder から推測
  let year = "";
  if (datetime) {
    const m = String(datetime).match(/(19|20)\d{2}/);
    if (m) year = m[0];
  }
  if (!year && folder) {
    const m = String(folder).match(/(19|20)\d{2}/);
    if (m) year = m[0];
  }

  return {
    id: String(id),
    title: String(title),
    datetime: String(datetime),
    dateText: toDateText(datetime),
    year: String(year || "----"),
    folder: String(folder),
    pageHtml: String(pageHtml),
    pageRawHtml: String(pageRawHtml),
    images: Array.isArray(images) ? images : [],
    originalUrl: String(originalUrl),
    _raw: raw, // デバッグ用（必要なら見る）
  };
}

/* =========================
   5) 読み込み（index）→ 一覧描画 → クリックで本文表示
   ========================= */

let ALL_POSTS = [];
let FILTERED_POSTS = [];

async function loadIndex() {
  // posts.jsonを読み込む
  const res = await fetch(INDEX_URL, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`posts.json fetch failed: ${res.status} ${res.statusText} (${INDEX_URL})`);
  }
  const data = await res.json();

  // dataが配列でも、{posts:[...]}でも対応
  const list = Array.isArray(data) ? data : (data.posts ?? data.items ?? []);
  ALL_POSTS = list.map(normalizePost);

  // 新しい順っぽく並べたい：datetimeがあるならそれを使う（なければそのまま）
  ALL_POSTS.sort((a, b) => (b.datetime || "").localeCompare(a.datetime || ""));

  FILTERED_POSTS = [...ALL_POSTS];
}

function renderList(posts) {
  if (!el.list) return;

  // 年ごとにまとめる
  const byYear = new Map();
  for (const p of posts) {
    if (!byYear.has(p.year)) byYear.set(p.year, []);
    byYear.get(p.year).push(p);
  }

  // 年を降順に
  const years = Array.from(byYear.keys()).sort((a, b) => b.localeCompare(a));

  // HTML生成（クリック可能なリスト）
  const html = years
    .map((y) => {
      const items = byYear.get(y)
        .map((p) => {
          const label = `${escapeHtml(p.title)} <span class="muted">${escapeHtml(p.dateText)}</span>`;
          // data-key に index を入れてクリック時に取り出す
          return `<li class="post-item" data-id="${escapeHtml(p.id)}" data-folder="${escapeHtml(p.folder)}">${label}</li>`;
        })
        .join("");
      return `<div class="year-block">
                <div class="year-title">${escapeHtml(y)}</div>
                <ul class="year-list">${items}</ul>
              </div>`;
    })
    .join("");

  el.list.innerHTML = html;

  // クリックイベント（イベント委譲）
  el.list.addEventListener("click", async (ev) => {
    const li = ev.target.closest(".post-item");
    if (!li) return;

    // idかfolderで記事を特定
    const id = li.getAttribute("data-id") || "";
    const folder = li.getAttribute("data-folder") || "";
    const post = FILTERED_POSTS.find((p) => p.id === id && id) || FILTERED_POSTS.find((p) => p.folder === folder);
    if (!post) return;

    await showPost(post);
  }, { once: true }); // 二重登録防止（renderListが何度も走るのでonce）
}

async function showPost(post) {
  if (el.title) el.title.textContent = post.title;
  if (el.meta) {
    // メタ表示：日時 / ID / 元URL
    const parts = [];
    if (post.dateText) parts.push(`日時: ${post.dateText}`);
    if (post.id) parts.push(`ID: ${post.id}`);
    if (post.originalUrl) parts.push(`元URL: ${post.originalUrl}`);
    el.meta.textContent = parts.join(" / ");
  }

  // 画像ギャラリー
  if (el.images) {
    if (post.images.length === 0) {
      el.images.innerHTML = "";
    } else {
      el.images.innerHTML = post.images
        .map((src) => {
          // ここが超重要：絶対パスにしない（/images/.. はNG）
          // posts.json内の画像パスが "posts/..." なら "./posts/..." に直す
          const safeSrc = String(src).startsWith("/") ? `.${src}` : `./${String(src).replace(/^\.\//, "")}`;
          return `<img class="post-img" src="${escapeHtml(safeSrc)}" loading="lazy" alt="">`;
        })
        .join("");
    }
  }

  // 本文（page.htmlを読み込んで表示）
  if (el.body) {
    el.body.innerHTML = `<div class="muted">読み込み中...</div>`;

    // pageHtml も絶対パスを避ける（/posts/... はNG）
    const pagePath = post.pageHtml.startsWith("/") ? `.${post.pageHtml}` : `./${post.pageHtml.replace(/^\.\//, "")}`;

    try {
      const res = await fetch(pagePath, { cache: "no-store" });
      if (!res.ok) throw new Error(`page fetch failed: ${res.status}`);

      const htmlText = await res.text();

      // 取得したHTMLを安全めに埋める：
      // - <script> は落とす（念のため）
      const doc = new DOMParser().parseFromString(htmlText, "text/html");
      doc.querySelectorAll("script").forEach((s) => s.remove());

      // 本文っぽい部分を探す（サイト構造が違っても多少拾えるように）
      const candidate =
        doc.querySelector(".md--body") ||
        doc.querySelector(".blog--content") ||
        doc.querySelector("article") ||
        doc.body;

      // candidate内の img/src が絶対URLだったらそのままになりがちなので、
      // ローカル画像を “上でギャラリーとして表示” している前提で、本文は文章中心にする
      el.body.innerHTML = candidate ? candidate.innerHTML : htmlText;
    } catch (e) {
      console.error(e);
      el.body.innerHTML = `
        <div class="error">
          本文HTMLの読み込みに失敗しました。<br>
          読みに行ったパス: <code>${escapeHtml(pagePath)}</code><br>
          Console(F12)にエラーが出ているはずです。
        </div>`;
    }
  }

  // URLハッシュに覚える（リロードしても同じ記事を開ける）
  if (post.id) location.hash = `#id=${encodeURIComponent(post.id)}`;
  else if (post.folder) location.hash = `#folder=${encodeURIComponent(post.folder)}`;
}

function applySearch(text) {
  const q = (text || "").trim().toLowerCase();
  if (!q) {
    FILTERED_POSTS = [...ALL_POSTS];
  } else {
    FILTERED_POSTS = ALL_POSTS.filter((p) => {
      return (
        p.title.toLowerCase().includes(q) ||
        p.id.toLowerCase().includes(q) ||
        p.folder.toLowerCase().includes(q)
      );
    });
  }
  renderList(FILTERED_POSTS);
}

/* =========================
   6) 初期化
   ========================= */

async function init() {
  try {
    await loadIndex();
    renderList(FILTERED_POSTS);

    // 検索
    if (el.search) {
      el.search.addEventListener("input", () => applySearch(el.search.value));
    }

    // ハッシュから復元（#id=... or #folder=...）
    const hash = location.hash || "";
    const mId = hash.match(/id=([^&]+)/);
    const mFolder = hash.match(/folder=([^&]+)/);

    if (mId) {
      const id = decodeURIComponent(mId[1]);
      const p = ALL_POSTS.find((x) => x.id === id);
      if (p) await showPost(p);
    } else if (mFolder) {
      const folder = decodeURIComponent(mFolder[1]);
      const p = ALL_POSTS.find((x) => x.folder === folder);
      if (p) await showPost(p);
    } else {
      // 何も選ばれてないときの表示
      if (el.title) el.title.textContent = "記事を選択してください";
      if (el.meta) el.meta.textContent = "";
      if (el.body) el.body.innerHTML = "";
      if (el.images) el.images.innerHTML = "";
    }
  } catch (e) {
    console.error(e);
    if (el.body) {
      el.body.innerHTML = `
        <div class="error">
          初期化に失敗しました。<br>
          posts.json を取得できていない可能性が高いです。<br>
          読みに行ったURL: <code>${escapeHtml(INDEX_URL)}</code><br>
          Console(F12)を見てください。
        </div>`;
    }
  }
}

// 実行
init();
