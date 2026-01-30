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
CT = "55386"  # 松尾美佑 ct

# ここが重要：dy=YYYYMM（月）を渡して月ごとに一覧を取る
LIST_URL = "https://www.nogizaka46.com/s/n46/diary/MEMBER/list?cd=MEMBER&ct={ct}&dy={ym}&page={page}"

# リポジトリ構成：repo/scripts/fetch.py なので repo は parents[1]
REPO_DIR = Path(__file__).resolve().parents[1]
SITE_DIR = REPO_DIR / "docs"          # GitHub Pages 公開ルート
POSTS_DIR = SITE_DIR / "posts"
INDEX_DIR = SITE_DIR / "index"
DEBUG_DIR = SITE_DIR / "_debug_fetch"  # 任意（調査用）

# ふつうのブラウザUAに寄せる（これでリンク0になる系がかなり減る）
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
}

SLEEP_SEC = 1.0
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


@dataclass
class PostIndex:
    id: str
    title: str
    datetime: str
    url: str
    local_dir: str        # docs からの相対（= GitHub Pages ルート相対にする）
    images: list[str]     # docs からの相対
    links_in_post: list[str]


def _dedup_keep(seq: list[str]) -> list[str]:
    out = []
    seen = set()
    for x in seq:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def get(url: str) -> requests.Response:
    r = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    r.raise_for_status()
    return r


def get_soup(url: str) -> BeautifulSoup:
    return BeautifulSoup(get(url).text, "html.parser")


def normalize_detail_url(u: str) -> str:
    # ?ima=... 等を落とす
    return re.sub(r"\?.*$", "", u)


def ym_range_desc(start_ym: int, end_ym: int) -> list[int]:
    """
    start_ym=202601, end_ym=202001 のように、YYYYMM を降順で列挙
    """
    y, m = divmod(start_ym, 100)
    ey, em = divmod(end_ym, 100)

    out = []
    while True:
        out.append(y * 100 + m)
        if y == ey and m == em:
            break
        m -= 1
        if m == 0:
            y -= 1
            m = 12
    return out


def extract_detail_links_from_list_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")

    urls = []
    for a in soup.select('a[href*="/s/n46/diary/detail/"]'):
        href = a.get("href")
        if not href:
            continue
        full = urljoin(BASE, href)
        if "/s/n46/diary/detail/" in full:
            urls.append(normalize_detail_url(full))

    return _dedup_keep(urls)


def extract_post_urls_monthly(start_ym: int, end_ym: int) -> list[str]:
    """
    月ごとにページ送りしながら detail URL を集める。
    「リンクが0」の月はスキップする。
    """
    all_urls: list[str] = []

    for ym in ym_range_desc(start_ym, end_ym):
        page = 1
        month_urls: list[str] = []
        empty_streak = 0

        while True:
            url = LIST_URL.format(ct=CT, ym=ym, page=page)
            print(f"[LIST] ym={ym} page={page} -> {url}")
            r = get(url)
            html = r.text

            found = extract_detail_links_from_list_html(html)
            print(f"[LIST] ym={ym} page={page} status={r.status_code} found={len(found)}")

            if page == 1:
                # 調査用に保存（「found=0」が続くとき原因追える）
                DEBUG_DIR.mkdir(parents=True, exist_ok=True)
                (DEBUG_DIR / f"list_{ym}_p{page}.html").write_text(html, encoding="utf-8")

            if not found:
                empty_streak += 1
                # 1ページ目から0なら、その月に記事が無い可能性が高いので月を終了
                if page == 1:
                    break
                # 途中ページで0が続いたら終端
                if empty_streak >= 2:
                    break
            else:
                empty_streak = 0
                month_urls.extend(found)

            page += 1
            time.sleep(SLEEP_SEC)

        month_urls = _dedup_keep(month_urls)
        if month_urls:
            print(f"[LIST] ym={ym} total month urls: {len(month_urls)}")
            all_urls.extend(month_urls)
        else:
            print(f"[LIST] ym={ym} no posts")

    return _dedup_keep(all_urls)


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


def load_existing_index() -> tuple[list[dict], set[str]]:
    p = INDEX_DIR / "posts.json"
    if not p.exists():
        return [], set()
    data = json.load(open(p, "r", encoding="utf-8"))
    ids = set()
    for x in data:
        if isinstance(x, dict) and "id" in x:
            ids.add(str(x["id"]))
    print(f"[SKIP] existing posts.json detected. existing ids: {len(ids)}")
    return data, ids


def main():
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    existing_data, existing_ids = load_existing_index()

    # 2020年以降ぜんぶ取りたいなら end_ym を 202001 に。
    # いま「2025/12 まで欲しい」なら start_ym を 202601（最新付近）にして降順で集めるのが安定。
    post_urls = extract_post_urls_monthly(start_ym=202601, end_ym=202001)
    print(f"[LIST] found {len(post_urls)} post urls")

    index: list[PostIndex] = []

    # 既存の posts.json を引き継ぐ（= 追加分だけ取る）
    # ただし local_dir/path は docs ルート相対に直す
    for x in existing_data:
        try:
            # docs/ が混ざってたら除去
            local_dir = str(x.get("local_dir", "")).replace("\\", "/")
            if local_dir.startswith("docs/"):
                local_dir = local_dir[5:]
            images = x.get("images", [])
            if isinstance(images, list):
                images = [s.replace("\\", "/")[5:] if isinstance(s, str) and s.replace("\\", "/").startswith("docs/") else s for s in images]
            index.append(
                PostIndex(
                    id=str(x.get("id", "")),
                    title=str(x.get("title", "")),
                    datetime=str(x.get("datetime", "")),
                    url=str(x.get("url", "")),
                    local_dir=local_dir,
                    images=images if isinstance(images, list) else [],
                    links_in_post=x.get("links_in_post", []) if isinstance(x.get("links_in_post", []), list) else [],
                )
            )
        except Exception:
            pass

    added = 0

    for i, url in enumerate(post_urls, 1):
        m2 = re.search(r"/diary/detail/(\d+)", url)
        pid = m2.group(1) if m2 else "unknown"
        if pid in existing_ids:
            continue

        print(f"[{i}/{len(post_urls)}] NEW {url}")

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
                # docs ルート相対
                saved_imgs.append(str(out_path.relative_to(SITE_DIR)).replace("\\", "/"))
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

        # docs ルート相対（重要）
        local_dir_rel = str(post_dir.relative_to(SITE_DIR)).replace("\\", "/")

        index.append(
            PostIndex(
                id=pid,
                title=title,
                datetime=dt,
                url=url,
                local_dir=local_dir_rel,
                images=saved_imgs,
                links_in_post=links,
            )
        )

        existing_ids.add(pid)
        added += 1
        time.sleep(SLEEP_SEC)

    # datetime の新しい順に並べたいならここでソート（文字列でもだいたい効く）
    def sort_key(x: PostIndex):
        return x.datetime

    index_sorted = sorted(index, key=sort_key, reverse=True)

    (INDEX_DIR / "posts.json").write_text(
        json.dumps([asdict(x) for x in index_sorted], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[DONE] added={added} total={len(index_sorted)}")
    print(f"[DONE] wrote: {INDEX_DIR / 'posts.json'}")


if __name__ == "__main__":
    main()
