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

# 松尾美佑のブログ一覧
# NOTE: ct は変わる可能性あり
LIST_URL = "https://www.nogizaka46.com/s/n46/diary/MEMBER/list?ct=55386&cd=MEMBER"

REPO_ROOT = Path(__file__).resolve().parents[1]

# GitHub Pages の公開ルートが docs/ なので、出力も docs 配下に寄せる
DOCS_DIR = REPO_ROOT / "docs"
POSTS_DIR = DOCS_DIR / "posts"
INDEX_DIR = DOCS_DIR / "index"
DEBUG_DIR = DOCS_DIR / "_debug"  # 解析用（必要なら見る）

HEADERS = {
    "User-Agent": "matsuo-miyu-blog/1.0 (personal archive)",
    "Accept-Language": "ja,en;q=0.8",
}

SLEEP_SEC = 1.0
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


@dataclass
class PostIndex:
    id: str
    title: str
    datetime: str
    url: str
    local_dir: str          # docs-root relative (forward slashes)
    images: list[str]       # repo-root relative (forward slashes)
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
    # クエリ等を落とす
    return re.sub(r"\?.*$", "", u)


def load_existing_index() -> tuple[list[PostIndex], set[str]]:
    """既存の posts.json を読み、既存ID集合を返す（無ければ空）。"""
    path = INDEX_DIR / "posts.json"
    if not path.exists():
        return [], set()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        posts: list[PostIndex] = []
        ids: set[str] = set()
        for x in raw:
            pid = str(x.get("id", ""))
            ids.add(pid)
            posts.append(
                PostIndex(
                    id=pid,
                    title=str(x.get("title", "")),
                    datetime=str(x.get("datetime", "")),
                    url=str(x.get("url", "")),
                    local_dir=str(x.get("local_dir", "")),
                    images=list(x.get("images", [])),
                    links_in_post=list(x.get("links_in_post", [])),
                )
            )
        print(f"[SKIP] existing posts.json detected. existing ids: {len(ids)}")
        return posts, ids
    except Exception as e:
        print(f"[WARN] failed to read existing posts.json: {e}")
        return [], set()


def extract_post_urls(max_pages: int = 300, stop_after_empty_pages: int = 5) -> list[str]:
    """
    LIST_URL&page=N を 1 から順に舐める。
    - detailリンクが0のページがあっても、連続 empty が一定数になるまでは止めない
    （君の現象：page1-3が取れないのに page4以降で取れる、みたいなパターンを潰す）
    """
    urls: list[str] = []
    empty_streak = 0

    for page in range(1, max_pages + 1):
        page_url = f"{LIST_URL}&page={page}"
        print(f"[LIST] fetching: {page_url}")

        soup = get_soup(page_url)

        found_this_page: list[str] = []
        for a in soup.select("a[href]"):
            href = a.get("href") or ""
            # /diary/detail/xxxxx を含めばOK（/s/n46 の有無で取りこぼさない）
            if "/diary/detail/" not in href:
                continue
            full = urljoin(BASE, href)
            if "/diary/detail/" in full:
                found_this_page.append(normalize_detail_url(full))

        found_this_page = _dedup_keep(found_this_page)

        if not found_this_page:
            empty_streak += 1
            print(f"[LIST] page={page} found=0 (empty_streak={empty_streak})")
        else:
            empty_streak = 0
            before = len(urls)
            urls.extend(found_this_page)
            urls = _dedup_keep(urls)
            after = len(urls)
            print(f"[LIST] page={page} found={len(found_this_page)} total={after} (added={after - before})")

        if empty_streak >= stop_after_empty_pages:
            print("[LIST] too many empty pages. stop paging.")
            break

        time.sleep(SLEEP_SEC)

    return urls


def parse_post(url: str):
    soup = get_soup(url)

    # title
    title = ""
    for sel in ["h1", "h2", ".c-blog-article__title", ".c-title"]:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            title = el.get_text(strip=True)
            break
    if not title:
        title = "no-title"

    # datetime
    # まずは本文テキストから yyyy.mm.dd hh:mm を探す（堅め）
    text_all = soup.get_text("\n", strip=True)
    m = re.search(r"(\d{4}\.\d{2}\.\d{2}\s+\d{2}:\d{2})", text_all)
    dt = m.group(1) if m else "unknown"

    # id
    m2 = re.search(r"/diary/detail/(\d+)", url)
    pid = m2.group(1) if m2 else "unknown"

    # images
    image_urls: list[str] = []
    for img in soup.select("img[src]"):
        src = img.get("src") or ""
        full = urljoin(BASE, src)
        path = urlparse(full).path.lower()
        if any(path.endswith(ext) for ext in IMG_EXTS):
            image_urls.append(re.sub(r"\?.*$", "", full))
    image_urls = _dedup_keep(image_urls)

    # links
    links: list[str] = []
    for a in soup.select("a[href]"):
        links.append(urljoin(BASE, a["href"]))
    links = _dedup_keep(links)

    raw_html = str(soup)
    return title, dt, pid, image_urls, links, raw_html


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


def safe_folder(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:140] if s else "untitled"


def rewrite_html_images_to_local(raw_html: str, mapping: dict[str, str]) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    for img in soup.select("img[src]"):
        src = img.get("src") or ""
        full = re.sub(r"\?.*$", "", urljoin(BASE, src))
        if full in mapping:
            img["src"] = mapping[full]
    return str(soup)


def to_forward_slashes(p: str) -> str:
    return p.replace("\\", "/")


def main():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    existing_posts, existing_ids = load_existing_index()

    post_urls = extract_post_urls()
    print(f"[LIST] found {len(post_urls)} post urls")

    # 新規だけ処理
    new_posts: list[PostIndex] = []

    for i, url in enumerate(post_urls, 1):
        m = re.search(r"/diary/detail/(\d+)", url)
        pid = m.group(1) if m else "unknown"
        if pid in existing_ids:
            continue

        print(f"[NEW {len(new_posts)+1}] ({i}/{len(post_urls)}) {url}")

        title, dt, pid, image_urls, links, raw_html = parse_post(url)

        year = dt.split(".")[0] if dt != "unknown" else "unknown"
        dt_folder = dt.replace(".", "-").replace(" ", "_").replace(":", "")
        folder_name = safe_folder(f"{dt_folder}_{pid}") if dt != "unknown" else safe_folder(pid)

        post_dir = POSTS_DIR / year / folder_name
        post_dir.mkdir(parents=True, exist_ok=True)

        (post_dir / "page_raw.html").write_text(raw_html, encoding="utf-8")

        mapping_for_html: dict[str, str] = {}
        saved_imgs: list[str] = []

        for n, img_url in enumerate(image_urls, 1):
            path = urlparse(img_url).path
            ext = Path(path).suffix or ".jpg"
            rel = f"images/{n:02d}{ext}"
            out_path = post_dir / rel

            if download(img_url, out_path):
                # 画像は repo-root 相対で保存
                saved_imgs.append(to_forward_slashes(str(out_path.relative_to(REPO_ROOT))))
                mapping_for_html[img_url] = rel

            time.sleep(SLEEP_SEC)

        cooked = rewrite_html_images_to_local(raw_html, mapping_for_html)
        (post_dir / "page.html").write_text(cooked, encoding="utf-8")

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

        local_dir_docs_rel = to_forward_slashes(str(post_dir.relative_to(DOCS_DIR)))

        new_posts.append(
            PostIndex(
                id=pid,
                title=title,
                datetime=dt,
                url=url,
                local_dir=local_dir_docs_rel,   # docs-root 相対
                images=saved_imgs,
                links_in_post=links,
            )
        )

        time.sleep(SLEEP_SEC)

    # 既存 + 新規 を統合（新しい順にしたいなら datetime でソート）
    merged = existing_posts + new_posts

    def sort_key(p: PostIndex):
        # "2025.10.23 12:00" -> "202510231200" っぽく
        s = re.sub(r"[^\d]", "", p.datetime or "")
        return s or "0"

    merged.sort(key=sort_key, reverse=True)

    (INDEX_DIR / "posts.json").write_text(
        json.dumps([asdict(x) for x in merged], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[DONE] added={len(new_posts)} total={len(merged)}")
    print(f"[DONE] wrote: {INDEX_DIR / 'posts.json'}")


if __name__ == "__main__":
    main()
