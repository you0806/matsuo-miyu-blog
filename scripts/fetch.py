# scripts/fetch.py
from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://www.nogizaka46.com"
CT = "55386"  # 松尾美佑
CD = "MEMBER"
IMA = "1200"  # あると挙動が安定しやすい（無いと別HTMLになることがある）

# ===== 出力先：GitHub Pages のルートが docs 前提 =====
OUT_DIR = Path(__file__).resolve().parents[1]
SITE_DIR = OUT_DIR / "docs"          # ← Pages の公開ルート
POSTS_DIR = SITE_DIR / "posts"       # ← docs/posts
INDEX_DIR = SITE_DIR / "index"       # ← docs/index

SLEEP_SEC = 1.0
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

# ブラウザ寄りのヘッダ（403/別ページ回避に効くことが多い）
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": BASE + "/",
}


@dataclass
class PostIndex:
    id: str
    title: str
    datetime: str
    url: str
    local_dir: str
    images: list[str]      # docs-root relative paths (POSIX)
    links_in_post: list[str]


def _dedup_keep(seq: list[str]) -> list[str]:
    out = []
    seen = set()
    for x in seq:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def ym_iter(end_ym: str, start_ym: str):
    # "202512" -> 2025-12 から "202505" まで降順
    ey, em = int(end_ym[:4]), int(end_ym[4:6])
    sy, sm = int(start_ym[:4]), int(start_ym[4:6])

    y, m = ey, em
    while (y > sy) or (y == sy and m >= sm):
        yield f"{y:04d}{m:02d}"
        m -= 1
        if m == 0:
            y -= 1
            m = 12


def get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def fetch_html(sess: requests.Session, url: str) -> tuple[int, str]:
    r = sess.get(url, timeout=30, allow_redirects=True)
    return r.status_code, r.text


def normalize_detail_url(u: str) -> str:
    # クエリは落とす
    return re.sub(r"\?.*$", "", u)


def extract_detail_ids_from_html(html: str) -> list[str]:
    # a[href] を探すより強い：HTML全体から /diary/detail/12345 を拾う
    ids = re.findall(r"/s/n46/diary/detail/(\d+)", html)
    return _dedup_keep(ids)


def list_page_url(ym: str, page: int) -> str:
    # 例: .../diary/MEMBER/list?ct=55386&cd=MEMBER&dy=202512&ima=1200&page=1
    return (
        f"{BASE}/s/n46/diary/MEMBER/list"
        f"?ct={CT}&cd={CD}&dy={ym}&ima={IMA}&page={page}"
    )


def parse_post(sess: requests.Session, url: str):
    status, html = fetch_html(sess, url)
    if status != 200:
        raise RuntimeError(f"detail fetch failed: {status} {url}")

    soup = BeautifulSoup(html, "html.parser")

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


def download(sess: requests.Session, url: str, out_path: Path) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = sess.get(url, timeout=60)
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


def load_existing_ids() -> set[str]:
    p = INDEX_DIR / "posts.json"
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {str(x.get("id")) for x in data if isinstance(x, dict) and x.get("id")}
    except Exception:
        pass
    return set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="202001", help="YYYYMM (inclusive)")
    ap.add_argument("--end", default="202512", help="YYYYMM (inclusive)")
    args = ap.parse_args()

    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    existing_ids = load_existing_ids()
    if existing_ids:
        print(f"[SKIP] existing posts.json detected. existing ids: {len(existing_ids)}")

    sess = get_session()

    # ===== 1) 一覧からID収集（見つからない月はHTML保存） =====
    found_ids: list[str] = []

    for ym in ym_iter(args.end, args.start):
        page = 1
        month_ids: list[str] = []

        while True:
            u = list_page_url(ym, page)
            print(f"[LIST] fetching: {u}")
            status, html = fetch_html(sess, u)

            if status != 200:
                (DEBUG_DIR / f"list_{ym}_page{page}_status{status}.html").write_text(
                    html, encoding="utf-8"
                )
                print(f"[LIST] status={status}. saved debug html. stop this month.")
                break

            ids = extract_detail_ids_from_html(html)

            if page == 1 and not ids:
                # ここが “no detail links” の正体。必ず保存して原因を確定できるようにする
                (DEBUG_DIR / f"list_{ym}_page1_no_detail.html").write_text(html, encoding="utf-8")
                print(f"[LIST] dy={ym} page=1 has no detail links. saved debug html. stop this month.")
                break

            if not ids:
                break

            month_ids.extend(ids)

            # 次ページに進むか（同じIDが続く/増えないなら終了）
            before = len(month_ids)
            month_ids = _dedup_keep(month_ids)
            if len(month_ids) == before and page > 1:
                break

            page += 1
            time.sleep(SLEEP_SEC)

        month_ids = _dedup_keep(month_ids)
        if month_ids:
            found_ids.extend(month_ids)

    found_ids = _dedup_keep(found_ids)
    print(f"found {len(found_ids)} post ids in list")

    # ===== 2) 詳細取得（差分だけ） =====
    index: list[PostIndex] = []

    # 既存 posts.json を読み込み、残しながら追記したい場合はここで merge もできるが、
    # まずは「今回取れたぶんだけ」作る形でOK（必要なら後でmerge版にする）
    for i, pid in enumerate(found_ids, 1):
        if pid in existing_ids:
            continue

        url = f"{BASE}/s/n46/diary/detail/{pid}"
        print(f"[{i}/{len(found_ids)}] {url}")

        title, dt, pid, image_urls, links, raw_html = parse_post(sess, url)

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

            if download(sess, img_url, out_path):
                # docs からの相対にする（GitHub Pagesでそのまま使える）
                saved_imgs.append(out_path.relative_to(DOCS_DIR).as_posix())
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

        index.append(
            PostIndex(
                id=pid,
                title=title,
                datetime=dt,
                url=url,
                local_dir=post_dir.relative_to(DOCS_DIR).as_posix(),
                images=saved_imgs,
                links_in_post=links,
            )
        )

        time.sleep(SLEEP_SEC)

    # ===== 3) posts.json 更新（既存 + 今回） =====
    existing_path = INDEX_DIR / "posts.json"
    merged: list[dict] = []
    if existing_path.exists():
        try:
            old = json.loads(existing_path.read_text(encoding="utf-8"))
            if isinstance(old, list):
                merged.extend(old)
        except Exception:
            pass

    # 既存IDと被らないように追記
    old_ids = {str(x.get("id")) for x in merged if isinstance(x, dict)}
    for x in index:
        if x.id not in old_ids:
            merged.append(asdict(x))

    # 新しい順っぽく並べたいなら datetime でソート（unknown は最後）
    def sort_key(d):
        dt = str(d.get("datetime") or "")
        # "2025.04.23 14:09" -> "2025-04-23 14:09"
        dt2 = dt.replace(".", "-")
        return dt2 if dt2 and dt2 != "unknown" else "0000"

    merged.sort(key=sort_key, reverse=True)

    existing_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("done.")
    print(f"updated: {existing_path}")
    print(f"debug (if any): {DEBUG_DIR}")


if __name__ == "__main__":
    main()
