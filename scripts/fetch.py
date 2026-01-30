# scripts/fetch.py
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://www.nogizaka46.com"
# 松尾美佑 ブログ一覧（dy は使わず、page で辿るのが安定）
LIST_URL = "https://www.nogizaka46.com/s/n46/diary/MEMBER/list?ct=55386&cd=MEMBER"

# ★重要：GitHub Pages の docs 構成に合わせる
REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "docs"
POSTS_DIR = OUT_DIR / "posts"
INDEX_DIR = OUT_DIR / "index"

HEADERS = {"User-Agent": "matsuo-miyu-blog/1.0 (personal archive)"}
SLEEP_SEC = 0.8
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


@dataclass
class PostIndex:
    id: str
    title: str
    datetime: str
    url: str
    local_dir: str
    images: list[str]      # docs からの相対パス (posix)
    links_in_post: list[str]


def _dedup_keep(seq: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in seq:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def get_soup(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def normalize_detail_url(u: str) -> str:
    return re.sub(r"\?.*$", "", u)


def extract_post_urls() -> list[str]:
    urls: list[str] = []
    page = 1

    while True:
        page_url = f"{LIST_URL}&page={page}"
        print(f"[LIST] fetching: {page_url}")
        soup = get_soup(page_url)

        before = len(urls)

        for a in soup.select('a[href*="/s/n46/diary/detail/"]'):
            href = a.get("href")
            if not href:
                continue
            full = urljoin(BASE, href)
            if "/s/n46/diary/detail/" in full:
                urls.append(normalize_detail_url(full))

        urls = _dedup_keep(urls)
        after = len(urls)
        found = after - before
        print(f"[LIST] page={page} found={found} total={after}")

        # このページで増えなかったら終わり
        if after == before:
            print("[LIST] no new posts found. stop paging.")
            break

        page += 1
        time.sleep(SLEEP_SEC)

    return urls


def safe_folder(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:140] if s else "untitled"


def download(url: str, out_path: Path) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        out_path.write_bytes(r.content)
        return True
    except Exception as e:
        print(f"[WARN] download failed: {url} ({e})")
        return False


def _pick_first(soup: BeautifulSoup, selectors: list[str]):
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            return el
    return None


def parse_post(url: str):
    soup = get_soup(url)

    # id
    m2 = re.search(r"/diary/detail/(\d+)", url)
    pid = m2.group(1) if m2 else "unknown"

    # title（ページ内h1優先）
    title = ""
    h1 = soup.select_one("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True)
    if not title:
        title = "no-title"

    # datetime（テキストから拾う）
    text_all = soup.get_text("\n", strip=True)
    m = re.search(r"(\d{4}\.\d{2}\.\d{2}\s+\d{2}:\d{2})", text_all)
    dt = m.group(1) if m else "unknown"

    # ★本文だけ抽出（不要な言語選択/フッター/握手案内をそもそも入れない）
    body = _pick_first(
        soup,
        [
            ".c-blog-article__body",
            ".c-blog-article",
            ".p-blog__article",
            ".p-blog__detail",
            "article",
        ],
    )

    if body is None:
        # 最悪フォールバック
        body = soup.body or soup

    # 余計なタグは除去（保険）
    for sel in [
        "script", "style", "noscript",
        "header", "footer", "nav",
        "form", "select", "option", "button",
    ]:
        for x in body.select(sel):
            x.decompose()

    # 画像URL抽出（本文部分だけを見る）
    image_urls: list[str] = []
    for img in body.select("img[src]"):
        src = img.get("src") or ""
        full = urljoin(BASE, src)
        if full.lower().endswith(IMG_EXTS):
            image_urls.append(re.sub(r"\?.*$", "", full))
    image_urls = _dedup_keep(image_urls)

    # リンク抽出（本文部分だけ）
    links: list[str] = []
    for a in body.select("a[href]"):
        links.append(urljoin(BASE, a["href"]))
    links = _dedup_keep(links)

    body_html = str(body)
    return title, dt, pid, image_urls, links, body_html


def rewrite_html_images_to_local(raw_html: str, mapping: dict[str, str]) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    for img in soup.select("img[src]"):
        src = img.get("src") or ""
        full = urljoin(BASE, src)
        full_n = re.sub(r"\?.*$", "", full)
        if full_n in mapping:
            img["src"] = mapping[full_n]
    return str(soup)


def wrap_minimal_html(title: str, dt: str, body_html: str) -> str:
    # ビューア内で見やすいように最小のHTMLに包む
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans JP", sans-serif; margin: 0; padding: 18px; }}
    img {{ max-width: 100%; height: auto; border-radius: 12px; }}
    a {{ word-break: break-word; }}
    .meta {{ color: #666; margin: 6px 0 18px; font-size: 13px; }}
  </style>
</head>
<body>
  <h1 style="margin: 0 0 6px;">{title}</h1>
  <div class="meta">{dt}</div>
  {body_html}
</body>
</html>
"""


def load_existing_ids() -> set[str]:
    p = INDEX_DIR / "posts.json"
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        ids = set()
        for x in data:
            pid = str(x.get("id", "")).strip()
            if pid:
                ids.add(pid)
        return ids
    except Exception:
        return set()


def main():
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    existing_ids = load_existing_ids()
    if existing_ids:
        print(f"[SKIP] existing posts.json detected. existing ids: {len(existing_ids)}")

    post_urls = extract_post_urls()
    print(f"[LIST] found {len(post_urls)} post urls")

    index: list[PostIndex] = []
    added = 0

    for i, url in enumerate(post_urls, 1):
        # 先にIDだけ抜く（skip判定を早く）
        m2 = re.search(r"/diary/detail/(\d+)", url)
        pid = m2.group(1) if m2 else "unknown"

        if pid in existing_ids:
            continue

        print(f"[{i}/{len(post_urls)}] NEW {url}")
        title, dt, pid, image_urls, links, body_html = parse_post(url)

        year = dt.split(".")[0] if dt != "unknown" else "unknown"
        dt_folder = dt.replace(".", "-").replace(" ", "_").replace(":", "")
        folder_name = safe_folder(f"{dt_folder}_{pid}") if dt != "unknown" else safe_folder(pid)

        post_dir = POSTS_DIR / year / folder_name
        post_dir.mkdir(parents=True, exist_ok=True)

        # 画像DL → ローカル置換
        mapping_for_html: dict[str, str] = {}
        saved_imgs: list[str] = []

        for n, img_url in enumerate(image_urls, 1):
            path = urlparse(img_url).path
            ext = Path(path).suffix or ".jpg"
            rel = f"images/{n:02d}{ext}"
            out_path = post_dir / rel

            if download(img_url, out_path):
                # docs からの相対パスにする（viewerでそのまま使える）
                saved_imgs.append(out_path.relative_to(OUT_DIR).as_posix())
                mapping_for_html[img_url] = rel

            time.sleep(SLEEP_SEC)

        cooked_body = rewrite_html_images_to_local(body_html, mapping_for_html)
        page_html = wrap_minimal_html(title, dt, cooked_body)
        (post_dir / "page.html").write_text(page_html, encoding="utf-8")

        # index.md（viewerが本文: page.html を拾う）
        (post_dir / "index.md").write_text(
            f"""---
id: "{pid}"
title: "{title.replace('"', "'")}"
datetime: "{dt}"
source_url: "{url}"
---

# {title}
- 更新日時: {dt}
- 元URL: {url}

本文: page.html
""",
            encoding="utf-8",
        )

        index.append(
            PostIndex(
                id=pid,
                title=title,
                datetime=dt,
                url=url,
                local_dir=str(post_dir.relative_to(OUT_DIR).as_posix()),
                images=saved_imgs,
                links_in_post=links,
            )
        )

        added += 1
        time.sleep(SLEEP_SEC)

    # 既存index + 新規index を結合して保存（新しいものが先に来るように）
    old = []
    p = INDEX_DIR / "posts.json"
    if p.exists():
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            old = []

    merged = index + old
    # idで重複排除
    seen = set()
    merged2 = []
    for x in merged:
        pid = str(x.get("id") if isinstance(x, dict) else x.id)
        if pid in seen:
            continue
        seen.add(pid)
        merged2.append(x if isinstance(x, dict) else asdict(x))

    p.write_text(json.dumps(merged2, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[DONE] added={added} total={len(merged2)} -> {p}")


if __name__ == "__main__":
    main()
