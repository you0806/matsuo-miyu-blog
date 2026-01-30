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
LIST_URL = "https://www.nogizaka46.com/s/n46/diary/MEMBER/list?ct=55386&cd=MEMBER"

HEADERS = {
    "User-Agent": "matsuo-miyu-blog/1.0 (personal archive)",
    "Accept-Language": "ja,en;q=0.8",
}

SLEEP_SEC = 0.7
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
POSTS_DIR = DOCS_DIR / "posts"
INDEX_DIR = DOCS_DIR / "index"


@dataclass
class PostIndex:
    id: str
    title: str
    datetime: str
    url: str
    local_dir: str
    images: list[str]      # repo-root relative paths (posix)
    links_in_post: list[str]


def _dedup_keep(seq: list[str]) -> list[str]:
    out = []
    seen = set()
    for x in seq:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def get_soup(session: requests.Session, url: str) -> BeautifulSoup:
    r = session.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def normalize_detail_url(u: str) -> str:
    return re.sub(r"\?.*$", "", u)


def extract_detail_links(soup: BeautifulSoup) -> list[str]:
    urls: list[str] = []
    for a in soup.select('a[href*="/s/n46/diary/detail/"]'):
        href = a.get("href")
        if not href:
            continue
        full = urljoin(BASE, href)
        if "/s/n46/diary/detail/" in full:
            urls.append(normalize_detail_url(full))
    return _dedup_keep(urls)


def extract_post_urls(session: requests.Session) -> list[str]:
    urls: list[str] = []
    page = 1
    no_new_streak = 0

    while True:
        page_url = f"{LIST_URL}&page={page}"
        print(f"[LIST] fetching: {page_url}")
        soup = get_soup(session, page_url)

        before = len(urls)
        urls.extend(extract_detail_links(soup))
        urls = _dedup_keep(urls)
        after = len(urls)

        found = after - before
        print(f"[LIST] page={page} found={found} total={after}")

        if found == 0:
            no_new_streak += 1
        else:
            no_new_streak = 0

        # 2ページ連続で増えなければ終わり（末尾到達 or 同じページが返ってきてる）
        if no_new_streak >= 2:
            print("[LIST] no new posts. stop paging.")
            break

        page += 1
        time.sleep(SLEEP_SEC)

    return urls


def parse_post(session: requests.Session, url: str):
    soup = get_soup(session, url)

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
    text_all = soup.get_text("\n", strip=True)
    m = re.search(r"(\d{4}\.\d{2}\.\d{2}\s+\d{2}:\d{2})", text_all)
    dt = m.group(1) if m else "unknown"

    # id
    m2 = re.search(r"/diary/detail/(\d+)", url)
    pid = m2.group(1) if m2 else "unknown"

    # images
    image_urls = []
    for img in soup.select("img[src]"):
        src = img.get("src") or ""
        full = urljoin(BASE, src)
        full = re.sub(r"\?.*$", "", full)
        if full.lower().endswith(IMG_EXTS):
            image_urls.append(full)
    image_urls = _dedup_keep(image_urls)

    # links
    links = []
    for a in soup.select("a[href]"):
        links.append(urljoin(BASE, a["href"]))
    links = _dedup_keep(links)

    raw_html = str(soup)
    return title, dt, pid, image_urls, links, raw_html


def download(session: requests.Session, url: str, out_path: Path) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = session.get(url, headers=HEADERS, timeout=60)
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
        full = urljoin(BASE, src)
        full_n = re.sub(r"\?.*$", "", full)
        if full_n in mapping:
            img["src"] = mapping[full_n]
    return str(soup)


def load_existing_index() -> list[dict]:
    p = INDEX_DIR / "posts.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def dt_sort_key(dt: str) -> tuple:
    # "2025.12.31 23:59" -> sortable
    m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})", dt or "")
    if not m:
        return (0, 0, 0, 0, 0)
    y, mo, d, hh, mm = map(int, m.groups())
    return (y, mo, d, hh, mm)


def main():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    existing = load_existing_index()
    existing_ids = {str(x.get("id", "")) for x in existing if x.get("id")}

    session = requests.Session()

    post_urls = extract_post_urls(session)
    print(f"[LIST] found {len(post_urls)} post urls")

    added = 0
    new_items: list[PostIndex] = []

    for i, url in enumerate(post_urls, 1):
        m = re.search(r"/diary/detail/(\d+)", url)
        pid = m.group(1) if m else "unknown"
        if pid in existing_ids:
            continue

        print(f"[NEW {added+1}] ({i}/{len(post_urls)}) {url}")

        title, dt, pid, image_urls, links, raw_html = parse_post(session, url)

        year = dt.split(".")[0] if dt != "unknown" else "unknown"
        dt_folder = dt.replace(".", "-").replace(" ", "_").replace(":", "")
        folder_name = safe_folder(f"{dt_folder}_{pid}") if dt != "unknown" else safe_folder(pid)

        post_dir = POSTS_DIR / year / folder_name
        post_dir.mkdir(parents=True, exist_ok=True)

        (post_dir / "page_raw.html").write_text(raw_html, encoding="utf-8")

        mapping_for_html = {}
        saved_imgs = []

        for n, img_url in enumerate(image_urls, 1):
            path = urlparse(img_url).path
            ext = Path(path).suffix or ".jpg"
            rel = f"images/{n:02d}{ext}"
            out_path = post_dir / rel

            if download(session, img_url, out_path):
                # posts.json は repo root 相対にしたいので REPO_ROOT からの相対
                saved_imgs.append(out_path.relative_to(REPO_ROOT).as_posix())
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

        new_items.append(
            PostIndex(
                id=pid,
                title=title,
                datetime=dt,
                url=url,
                local_dir=post_dir.relative_to(REPO_ROOT).as_posix(),
                images=saved_imgs,
                links_in_post=links,
            )
        )
        added += 1
        time.sleep(SLEEP_SEC)

    merged = existing + [asdict(x) for x in new_items]
    merged.sort(key=lambda x: dt_sort_key(str(x.get("datetime", ""))), reverse=True)

    (INDEX_DIR / "posts.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[DONE] added={added} total={len(merged)}")
    print(f"[DONE] wrote: {INDEX_DIR / 'posts.json'}")


if __name__ == "__main__":
    main()
