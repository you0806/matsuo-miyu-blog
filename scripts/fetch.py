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

# 松尾美佑のブログ一覧（ct は公式側で変わる可能性あり）
LIST_URL = "https://www.nogizaka46.com/s/n46/diary/MEMBER/list?ct=55386&cd=MEMBER"

OUT_DIR = Path(__file__).resolve().parents[1]
POSTS_DIR = OUT_DIR / "posts"
INDEX_DIR = OUT_DIR / "index"

HEADERS = {"User-Agent": "matsuo-miyu-blog/1.0 (personal archive)"}

SLEEP_SEC = 1.0  # 待ち時間（画質は変わらない）
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


@dataclass
class PostIndex:
    id: str
    title: str
    datetime: str
    url: str
    local_dir: str
    images: list[str]      # repo-root relative paths
    links_in_post: list[str]


def _dedup_keep(seq: list[str]) -> list[str]:
    out = []
    seen = set()
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
        print(f"[LIST] urls so far: {after}")

        # 方法B：増えなくなったら終端
        if after == before:
            print("[LIST] no new posts found. stop paging.")
            break

        page += 1
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
        full = urljoin(BASE, src)
        full_n = re.sub(r"\?.*$", "", full)
        if full_n in mapping:
            img["src"] = mapping[full_n]
    return str(soup)


def main():
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    post_urls = extract_post_urls()
    print(f"found {len(post_urls)} post urls")

    index: list[PostIndex] = []

    for i, url in enumerate(post_urls, 1):
        print(f"[{i}/{len(post_urls)}] {url}")

        title, dt, pid, image_urls, links, raw_html = parse_post(url)

        year = dt.split(".")[0] if dt != "unknown" else "unknown"
        dt_folder = dt.replace(".", "-").replace(" ", "_").replace(":", "")
        folder_name = safe_folder(f"{dt_folder}_{pid}") if dt != "unknown" else safe_folder(pid)

        post_dir = POSTS_DIR / year / folder_name
        img_dir = post_dir / "images"
        post_dir.mkdir(parents=True, exist_ok=True)

        (post_dir / "page_raw.html").write_text(raw_html, encoding="utf-8")

        mapping_for_html = {}
        saved_imgs = []

        for n, img_url in enumerate(image_urls, 1):
            path = urlparse(img_url).path
            ext = Path(path).suffix or ".jpg"
            rel = f"images/{n:02d}{ext}"
            out_path = post_dir / rel

            if download(img_url, out_path):
                saved_imgs.append(str(out_path.relative_to(OUT_DIR)))
                mapping_for_html[re.sub(r"\?.*$", "", img_url)] = rel

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

        index.append(
            PostIndex(
                id=pid,
                title=title,
                datetime=dt,
                url=url,
                local_dir=str(post_dir.relative_to(OUT_DIR)),
                images=saved_imgs,
                links_in_post=links,
            )
        )

        time.sleep(SLEEP_SEC)

    (INDEX_DIR / "posts.json").write_text(
        json.dumps([asdict(x) for x in index], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("done.")


if __name__ == "__main__":
    main()
