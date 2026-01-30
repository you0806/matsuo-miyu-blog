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

# 松尾美佑 ブログ一覧（ct は変わる可能性あり。あなたの repo では 55386）
LIST_URL = "https://www.nogizaka46.com/s/n46/diary/MEMBER/list?cd=MEMBER&ct=55386"

# ==============
# 出力先（GitHub Pages を docs/ 公開にしてる前提）
# ==============
REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
POSTS_DIR = DOCS_DIR / "posts"
INDEX_DIR = DOCS_DIR / "index"
POSTS_JSON = INDEX_DIR / "posts.json"

# できるだけブラウザに寄せる（0リンク判定を避ける）
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SLEEP_SEC = 1.0
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


@dataclass
class PostIndex:
    id: str
    title: str
    datetime: str
    url: str
    local_dir: str
    images: list[str]       # repo-root relative paths (docs/... まで含む)
    links_in_post: list[str]


def _dedup_keep(seq: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in seq:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def normalize_detail_url(u: str) -> str:
    # クエリや ima を落として /detail/NNNNN だけにする
    return re.sub(r"\?.*$", "", u)


def safe_folder(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:140] if s else "untitled"


def get_soup(session: requests.Session, url: str) -> BeautifulSoup:
    r = session.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def load_existing_ids() -> set[str]:
    if not POSTS_JSON.exists():
        return set()
    try:
        data = json.loads(POSTS_JSON.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {str(x.get("id")) for x in data if isinstance(x, dict) and x.get("id")}
    except Exception:
        pass
    return set()


def extract_post_urls(session: requests.Session) -> list[str]:
    """
    dy月別に頼らず、page=1..n を総当たりで detail URL を集める（最安定）
    """
    urls: list[str] = []
    page = 1
    max_pages = 300  # 念のための安全弁

    while page <= max_pages:
        page_url = f"{LIST_URL}&page={page}"
        print(f"[LIST] fetching: {page_url}")

        soup = get_soup(session, page_url)

        found_this_page: list[str] = []
        for a in soup.select('a[href*="/s/n46/diary/detail/"]'):
            href = a.get("href")
            if not href:
                continue
            full = urljoin(BASE, href)
            if "/s/n46/diary/detail/" in full:
                found_this_page.append(normalize_detail_url(full))

        found_this_page = _dedup_keep(found_this_page)

        before = len(urls)
        urls.extend(found_this_page)
        urls = _dedup_keep(urls)
        after = len(urls)

        print(f"[LIST] page={page} found={len(found_this_page)} total={after}")

        # そのページで 1件も拾えない or 総数が増えないなら終端
        if len(found_this_page) == 0 or after == before:
            print("[LIST] no new posts found. stop paging.")
            break

        page += 1
        time.sleep(SLEEP_SEC)

    return urls


def pick_article_root(soup: BeautifulSoup) -> BeautifulSoup:
    """
    記事本文（余計な言語メニュー/フッター/握手案内）を避けるため、
    article 相当だけ切り出して保存する。
    """
    for sel in [
        ".c-blog-article",
        "article",
        "#js-blog-article",
        ".p-blog-article",
    ]:
        node = soup.select_one(sel)
        if node:
            # node を丸ごと soup 化
            return BeautifulSoup(str(node), "html.parser")
    return soup


def parse_post(session: requests.Session, url: str):
    soup_full = get_soup(session, url)
    soup = pick_article_root(soup_full)

    # title
    title = ""
    for sel in ["h1", ".c-blog-article__title", ".c-title"]:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            title = el.get_text(strip=True)
            break
    if not title:
        title = "no-title"

    # datetime
    text_all = soup_full.get_text("\n", strip=True)  # full から拾う方が安定
    m = re.search(r"(\d{4}\.\d{2}\.\d{2}\s+\d{2}:\d{2})", text_all)
    dt = m.group(1) if m else "unknown"

    # id
    m2 = re.search(r"/diary/detail/(\d+)", url)
    pid = m2.group(1) if m2 else "unknown"

    # images（記事内だけ）
    image_urls: list[str] = []
    for img in soup.select("img[src]"):
        src = img.get("src") or ""
        full = urljoin(BASE, src)
        # query落とした拡張子で判定
        path = urlparse(full).path.lower()
        if any(path.endswith(ext) for ext in IMG_EXTS):
            image_urls.append(full)
    image_urls = _dedup_keep(image_urls)

    # links（記事内だけ）
    links: list[str] = []
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        links.append(urljoin(BASE, href))
    links = _dedup_keep(links)

    raw_html = str(soup)  # ★記事部分だけ
    return title, dt, pid, image_urls, links, raw_html


def download(session: requests.Session, url: str, out_path: Path) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = session.get(url, headers=HEADERS, timeout=60, stream=True)
        r.raise_for_status()
        out_path.write_bytes(r.content)
        return True
    except Exception as e:
        print(f"[WARN] download failed: {url} ({e})")
        return False


def rewrite_html_images_to_local(raw_html: str, mapping: dict[str, str]) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    for img in soup.select("img[src]"):
        src = img.get("src") or ""
        full = urljoin(BASE, src)
        full_n = re.sub(r"\?.*$", "", full)
        if full_n in mapping:
            img["src"] = mapping[full_n]
    return str(soup)


def main():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    existing_ids = load_existing_ids()
    if existing_ids:
        print(f"[SKIP] existing posts.json detected. existing ids: {len(existing_ids)}")

    session = requests.Session()

    post_urls = extract_post_urls(session)
    print(f"[LIST] found {len(post_urls)} post urls")

    index: list[PostIndex] = []

    for i, url in enumerate(post_urls, 1):
        title, dt, pid, image_urls, links, raw_html = parse_post(session, url)

        # 既に持ってる記事はスキップ
        if pid in existing_ids:
            continue

        print(f"[{i}/{len(post_urls)}] NEW {pid} {dt} {title}")

        year = dt.split(".")[0] if dt != "unknown" else "unknown"
        dt_folder = dt.replace(".", "-").replace(" ", "_").replace(":", "")
        folder_name = safe_folder(f"{dt_folder}_{pid}") if dt != "unknown" else safe_folder(pid)

        post_dir = POSTS_DIR / year / folder_name
        post_dir.mkdir(parents=True, exist_ok=True)

        # raw（記事部分だけ）
        (post_dir / "page_raw.html").write_text(raw_html, encoding="utf-8")

        mapping_for_html: dict[str, str] = {}
        saved_imgs: list[str] = []

        for n, img_url in enumerate(image_urls, 1):
            path = urlparse(img_url).path
            ext = Path(path).suffix or ".jpg"
            rel = f"images/{n:02d}{ext}"
            out_path = post_dir / rel

            if download(session, img_url, out_path):
                # repo-root relative（GitHub Pagesで参照しやすい）
                saved_imgs.append(str(out_path.relative_to(REPO_ROOT)).replace("\\", "/"))
                mapping_for_html[re.sub(r"\?.*$", "", img_url)] = rel

            time.sleep(SLEEP_SEC)

        cooked = rewrite_html_images_to_local(raw_html, mapping_for_html)
        (post_dir / "page.html").write_text(cooked, encoding="utf-8")

        # index.md
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
                local_dir=str(post_dir.relative_to(REPO_ROOT)).replace("\\", "/"),
                images=saved_imgs,
                links_in_post=links,
            )
        )

        time.sleep(SLEEP_SEC)

    # 既存 posts.json とマージ（新しい分だけ足して、日付で新しい順に）
    merged: list[dict] = []
    if POSTS_JSON.exists():
        try:
            merged = json.loads(POSTS_JSON.read_text(encoding="utf-8"))
            if not isinstance(merged, list):
                merged = []
        except Exception:
            merged = []

    merged.extend([asdict(x) for x in index])

    def key_dt(x: dict) -> str:
        return str(x.get("datetime", ""))

    merged = sorted(_dedup_keep_by_id(merged), key=key_dt, reverse=True)

    POSTS_JSON.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[DONE] added={len(index)} total={len(merged)}")


def _dedup_keep_by_id(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for x in items:
        pid = str(x.get("id", ""))
        if not pid or pid in seen:
            continue
        out.append(x)
        seen.add(pid)
    return out


if __name__ == "__main__":
    main()
