# scripts/fetch_one.py
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
HEADERS = {"User-Agent": "matsuo-miyu-blog/1.0 (personal archive)"}
SLEEP_SEC = 1.0
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

OUT_DIR = Path(__file__).resolve().parents[1]
DOCS_DIR = OUT_DIR / "docs"
POSTS_DIR = DOCS_DIR / "posts"
INDEX_DIR = DOCS_DIR / "index"


@dataclass
class PostIndex:
    id: str
    title: str
    datetime: str
    url: str
    local_dir: str
    path: str
    images: list[str]
    links_in_post: list[str]


def get_soup(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


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


def rewrite_html_images_to_local(raw_html: str, mapping: dict[str, str]) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    for img in soup.select("img[src]"):
        src = img.get("src") or ""
        full = urljoin(BASE, src)
        full_n = re.sub(r"\?.*$", "", full)
        if full_n in mapping:
            img["src"] = mapping[full_n]
    return str(soup)


def normalize_detail_url(u: str) -> str:
    return re.sub(r"\?.*$", "", u)


def load_index() -> tuple[list[dict], set[str]]:
    p = INDEX_DIR / "posts.json"
    if not p.exists():
        return [], set()
    data = json.load(open(p, "r", encoding="utf-8"))
    ids = {str(x.get("id", "")) for x in data if isinstance(x, dict)}
    return data, ids


def save_index(data: list[dict]) -> None:
    # datetime でざっくり降順
    def sort_key(item: dict):
        dt = str(item.get("datetime", ""))
        dt2 = dt.replace(".", "").replace(" ", "").replace(":", "")
        return dt2 if dt2 != "unknown" else "000000000000"

    data.sort(key=sort_key, reverse=True)
    outp = INDEX_DIR / "posts.json"
    outp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DONE] wrote: {outp} (total={len(data)})")


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
        full = re.sub(r"\?.*$", "", full)
        if full.lower().endswith(IMG_EXTS):
            image_urls.append(full)
    image_urls = list(dict.fromkeys(image_urls))

    # links
    links = []
    for a in soup.select("a[href]"):
        links.append(urljoin(BASE, a["href"]))
    links = list(dict.fromkeys(links))

    raw_html = str(soup)
    return title, dt, pid, image_urls, links, raw_html


def fetch_one(detail_url_or_id: str) -> None:
    # 入力がIDだけならURL化
    s = detail_url_or_id.strip()
    if re.fullmatch(r"\d+", s):
        url = f"{BASE}/s/n46/diary/detail/{s}"
    else:
        url = s
    url = normalize_detail_url(url)

    existing_data, existing_ids = load_index()

    m2 = re.search(r"/diary/detail/(\d+)", url)
    pid = m2.group(1) if m2 else "unknown"
    if pid in existing_ids:
        print(f"[SKIP] already exists id={pid}")
        return

    print(f"[ONE] fetching: {url}")
    title, dt, pid, image_urls, links, raw_html = parse_post(url)

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

        if download(img_url, out_path):
            saved_imgs.append(str(out_path.relative_to(DOCS_DIR)).replace("\\", "/"))
            mapping_for_html[img_url] = rel

        time.sleep(SLEEP_SEC)

    cooked = rewrite_html_images_to_local(raw_html, mapping_for_html)
    (post_dir / "page.html").write_text(cooked, encoding="utf-8")

    local_dir = str(post_dir.relative_to(DOCS_DIR)).replace("\\", "/")
    md_path = f"{local_dir}/index.md"

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

    existing_data.append(
        asdict(
            PostIndex(
                id=pid,
                title=title,
                datetime=dt,
                url=url,
                local_dir=local_dir,
                path=md_path,
                images=saved_imgs,
                links_in_post=links,
            )
        )
    )

    save_index(existing_data)
    print(f"[OK] added id={pid} dt={dt} title={title}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python scripts/fetch_one.py <detail_url_or_id>")
        raise SystemExit(1)

    fetch_one(sys.argv[1])
