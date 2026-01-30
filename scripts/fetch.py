# scripts/fetch.py
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://www.nogizaka46.com"

# ✅ cd=MEMBER は付けない（dy付き一覧で安定して detail が取れる）
LIST_BASE = "https://www.nogizaka46.com/s/n46/diary/MEMBER/list?ct=55386"

OUT_DIR = Path(__file__).resolve().parents[1]
DOCS_DIR = OUT_DIR / "docs"
POSTS_DIR = DOCS_DIR / "posts"
INDEX_DIR = DOCS_DIR / "index"
DEBUG_DIR = DOCS_DIR / "_debug_fetch"

HEADERS = {
    "User-Agent": "matsuo-miyu-blog/1.0 (personal archive)",
}

SLEEP_SEC = 1.0
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


@dataclass
class PostIndex:
    id: str
    title: str
    datetime: str
    url: str
    local_dir: str          # "posts/2025/...."
    path: str               # "posts/2025/..../index.md"
    images: list[str]       # "posts/2025/.../images/01.jpg"
    links_in_post: list[str]


def _dedup_keep(seq: list[str]) -> list[str]:
    out: list[str] = []
    seen = set()
    for x in seq:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def get_text(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    r.raise_for_status()
    return r.text


def get_soup(url: str) -> BeautifulSoup:
    return BeautifulSoup(get_text(url), "html.parser")


def normalize_detail_url(u: str) -> str:
    # ?ima=... などを落としてIDのURLを固定
    return re.sub(r"\?.*$", "", u)


def ym_iter(start_ym: int, end_ym: int) -> list[int]:
    """YYYYMM を start から end まで（降順）"""
    out = []
    y, m = divmod(start_ym, 100)
    if m == 0:
        y -= 1
        m = 12
    ey, em = divmod(end_ym, 100)
    if em == 0:
        ey -= 1
        em = 12

    while (y > ey) or (y == ey and m >= em):
        out.append(y * 100 + m)
        m -= 1
        if m == 0:
            y -= 1
            m = 12
    return out


def extract_detail_links_from_list_html(html: str) -> list[str]:
    # BeautifulSoup selector が壊れても regex で拾えるように二段構え
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []

    for a in soup.select('a[href*="/s/n46/diary/detail/"]'):
        href = a.get("href")
        if not href:
            continue
        full = urljoin(BASE, href)
        if "/s/n46/diary/detail/" in full:
            urls.append(normalize_detail_url(full))

    if not urls:
        # fallback: regex
        for m in re.findall(r'(/s/n46/diary/detail/\d+)', html):
            urls.append(urljoin(BASE, m))

    return _dedup_keep(urls)


def fetch_month_urls(ym: int, max_empty_pages: int = 3) -> list[str]:
    """dy=YYYYMM & page= でその月の一覧を全部拾う"""
    urls: list[str] = []
    empty_streak = 0

    for page in range(1, 50):  # さすがに50もあれば足りる
        url = f"{LIST_BASE}&dy={ym}&page={page}&ts={int(time.time())}"
        print(f"[LIST] ym={ym} page={page} fetching: {url}")

        html = get_text(url)

        # デバッグ用に保存（必要ないなら消してOK）
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        (DEBUG_DIR / f"list_{ym}_p{page}.html").write_text(html, encoding="utf-8")

        found = extract_detail_links_from_list_html(html)
        print(f"[LIST] ym={ym} page={page} found={len(found)} total_before={len(urls)}")

        if not found:
            empty_streak += 1
            if empty_streak >= max_empty_pages:
                break
        else:
            empty_streak = 0
            urls.extend(found)
            urls = _dedup_keep(urls)

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


def load_existing_index() -> tuple[list[dict], set[str]]:
    p = INDEX_DIR / "posts.json"
    if not p.exists():
        return [], set()
    try:
        data = json.load(open(p, "r", encoding="utf-8"))
        ids = {str(x.get("id", "")) for x in data if isinstance(x, dict)}
        return data, ids
    except Exception:
        return [], set()


def main():
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    existing_data, existing_ids = load_existing_index()
    print(f"[SKIP] existing posts.json detected. existing ids: {len(existing_ids)}")

    # いまから過去へ（必要なら end_ym を 202001 などに）
    now = datetime.now()
    start_ym = now.year * 100 + now.month
    end_ym = 202001

    all_urls: list[str] = []
    for ym in ym_iter(start_ym, end_ym):
        month_urls = fetch_month_urls(ym)
        print(f"[LIST] ym={ym} month_urls={len(month_urls)}")
        all_urls.extend(month_urls)
        all_urls = _dedup_keep(all_urls)

    print(f"[LIST] found {len(all_urls)} post urls (unique)")

    new_index: list[PostIndex] = []
    added = 0

    for i, url in enumerate(all_urls, 1):
        m2 = re.search(r"/diary/detail/(\d+)", url)
        pid = m2.group(1) if m2 else "unknown"

        if pid in existing_ids:
            continue

        print(f"[NEW {added+1}] ({i}/{len(all_urls)}) {url}")

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
                # docs/ からの相対にしたいので "posts/..." で保持
                saved_imgs.append(str(out_path.relative_to(DOCS_DIR)).replace("\\", "/"))
                mapping_for_html[re.sub(r"\?.*$", "", img_url)] = rel

            time.sleep(SLEEP_SEC)

        cooked = rewrite_html_images_to_local(raw_html, mapping_for_html)
        (post_dir / "page.html").write_text(cooked, encoding="utf-8")

        local_dir = str(post_dir.relative_to(DOCS_DIR)).replace("\\", "/")   # posts/2025/...
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

        new_index.append(
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

        existing_ids.add(pid)
        added += 1
        time.sleep(SLEEP_SEC)

    # 既存 + 新規 を結合して保存（viewer が読むのは docs/index/posts.json）
    merged = []
    for x in existing_data:
        if isinstance(x, dict):
            # path 無い過去データも吸収
            if "path" not in x and "local_dir" in x:
                ld = str(x["local_dir"]).replace("\\", "/")
                x["local_dir"] = ld
                x["path"] = f"{ld}/index.md"
            merged.append(x)

    merged.extend([asdict(x) for x in new_index])

    # datetime でざっくり降順（unknown は最後）
    def sort_key(item: dict):
        dt = str(item.get("datetime", ""))
        # "2025.12.31 23:59" を比較しやすく
        dt2 = dt.replace(".", "").replace(" ", "").replace(":", "")
        return dt2 if dt2 != "unknown" else "000000000000"

    merged.sort(key=sort_key, reverse=True)

    outp = INDEX_DIR / "posts.json"
    outp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[DONE] added={added} total={len(merged)}")
    print(f"[DONE] wrote: {outp}")


if __name__ == "__main__":
    main()
