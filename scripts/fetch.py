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

# 松尾美佑のブログ一覧（ctは使える前提。変わったらここを直す）
LIST_URL = "https://www.nogizaka46.com/s/n46/diary/MEMBER/list?ct=55386&cd=MEMBER"

# ★ GitHub Pages が docs/ を公開ルートなら、出力も docs/ に統一
REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "docs"
POSTS_DIR = OUT_DIR / "posts"
INDEX_DIR = OUT_DIR / "index"

HEADERS = {"User-Agent": "matsuo-miyu-blog/1.0 (personal archive)"}

SLEEP_SEC = 1.0
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


@dataclass
class PostIndex:
    id: str
    title: str
    datetime: str
    url: str
    local_dir: str
    images: list[str]      # docs/ からの相対パス
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


def find_month_archives() -> list[str]:
    """
    一覧ページから dy=YYYYMM の月別アーカイブを拾う。
    """
    soup = get_soup(LIST_URL)
    months = set()

    for a in soup.select('a[href*="dy="]'):
        href = a.get("href") or ""
        m = re.search(r"dy=(\d{6})", href)
        if m:
            months.add(m.group(1))

    # 念のため、見つからない場合でも "dyなし" の通常ページは拾えるようにする
    # months が空なら [""] を返す
    if not months:
        return [""]

    # 新しい月から回したいので降順
    return sorted(months, reverse=True)


def extract_post_urls() -> list[str]:
    """
    ★ 改良版：dy=YYYYMM（月別）→ page=1.. を回して全部集める
    """
    urls: list[str] = []
    months = find_month_archives()
    print(f"[LIST] found month archives: {len(months)}")

    for dy in months:
        page = 1
        while True:
            if dy:
                page_url = f"{LIST_URL}&dy={dy}&page={page}"
                tag = f"dy={dy}"
            else:
                page_url = f"{LIST_URL}&page={page}"
                tag = "dy=default"

            print(f"[LIST] fetching: {page_url}")
            soup = get_soup(page_url)

            detail_links = []
            for a in soup.select('a[href*="/s/n46/diary/detail/"]'):
                href = a.get("href")
                if not href:
                    continue
                full = urljoin(BASE, href)
                if "/s/n46/diary/detail/" in full:
                    detail_links.append(normalize_detail_url(full))

            detail_links = _dedup_keep(detail_links)

            # そのページで記事リンクが取れなければ、その月は終わり
            if not detail_links:
                print(f"[LIST] {tag} page={page} has no detail links. stop this month.")
                break

            before = len(urls)
            urls.extend(detail_links)
            urls = _dedup_keep(urls)
            after = len(urls)

            print(f"[LIST] {tag} page={page} urls so far: {after} (+{after-before})")

            # 「増えないページ」があっても即終了しない（＝途中の挙動ブレ耐性）
            # ただし連続で増えないなら終わりにする
            if after == before:
                # もう1ページだけ試してダメなら止める
                page += 1
                time.sleep(SLEEP_SEC)
                if dy:
                    test_url = f"{LIST_URL}&dy={dy}&page={page}"
                else:
                    test_url = f"{LIST_URL}&page={page}"
                print(f"[LIST] retry one more page: {test_url}")
                soup2 = get_soup(test_url)
                detail2 = []
                for a in soup2.select('a[href*="/s/n46/diary/detail/"]'):
                    href = a.get("href")
                    if not href:
                        continue
                    full = urljoin(BASE, href)
                    if "/s/n46/diary/detail/" in full:
                        detail2.append(normalize_detail_url(full))
                detail2 = _dedup_keep(detail2)
                before2 = len(urls)
                urls.extend(detail2)
                urls = _dedup_keep(urls)
                after2 = len(urls)
                print(f"[LIST] retry result: {after2} (+{after2-before2})")
                if after2 == before2:
                    print(f"[LIST] {tag} no new posts on consecutive pages. stop this month.")
                    break
                # 追加できたなら続行（page は既に進んでる）
            else:
                page += 1
                time.sleep(SLEEP_SEC)

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

    # images（記事中のimgだけ拾いたいので、まず本文っぽい範囲を優先）
    image_urls = []
    body = soup.select_one("article") or soup.select_one(".c-blog-article") or soup
    for img in body.select("img[src]"):
        src = img.get("src") or ""
        full = urljoin(BASE, src)
        if full.lower().endswith(IMG_EXTS):
            image_urls.append(re.sub(r"\?.*$", "", full))
    image_urls = _dedup_keep(image_urls)

    # links（多すぎるなら、ここも body 内に限定）
    links = []
    for a in body.select("a[href]"):
        links.append(urljoin(BASE, a["href"]))
    links = _dedup_keep(links)

    raw_html = str(soup)
    return title, dt, pid, image_urls, links, raw_html


def load_existing_ids() -> set[str]:
    """
    既に docs/index/posts.json があれば、そこにあるidを読み込んでスキップできるようにする。
    """
    p = INDEX_DIR / "posts.json"
    if not p.exists():
        return set()
    try:
        arr = json.loads(p.read_text(encoding="utf-8"))
        ids = set()
        for x in arr:
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
    print(f"found {len(post_urls)} post urls")

    index: list[PostIndex] = []

    for i, url in enumerate(post_urls, 1):
        m2 = re.search(r"/diary/detail/(\d+)", url)
        pid_guess = m2.group(1) if m2 else ""

        if pid_guess and pid_guess in existing_ids:
            # 既存分は posts.json に残す必要があるので、後で読み直す方式でもいいが、
            # ここでは「再生成」を優先してスキップしない方が安全。
            # ただし速度重視なら continue に変えてOK。
            pass

        print(f"[{i}/{len(post_urls)}] {url}")

        title, dt, pid, image_urls, links, raw_html = parse_post(url)

        year = dt.split(".")[0] if dt != "unknown" else "unknown"
        dt_folder = dt.replace(".", "-").replace(" ", "_").replace(":", "")
        folder_name = safe_folder(f"{dt_folder}_{pid}") if dt != "unknown" else safe_folder(pid)

        post_dir = POSTS_DIR / year / folder_name
        img_dir = post_dir / "images"
        post_dir.mkdir(parents=True, exist_ok=True)
        img_dir.mkdir(parents=True, exist_ok=True)

        (post_dir / "page_raw.html").write_text(raw_html, encoding="utf-8")

        mapping_for_html = {}
        saved_imgs = []

        for n, img_url in enumerate(image_urls, 1):
            path = urlparse(img_url).path
            ext = Path(path).suffix or ".jpg"
            rel = f"images/{n:02d}{ext}"
            out_path = post_dir / rel

            if download(img_url, out_path):
                # docs/ からの相対で持つ
                saved_imgs.append(str(out_path.relative_to(OUT_DIR)))
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
                local_dir=str(post_dir.relative_to(OUT_DIR)),
                images=saved_imgs,
                links_in_post=links,
            )
        )

        time.sleep(SLEEP_SEC)

    # 新しい順に並べ替え（文字列比較でOKな形式）
    def sort_key(x: PostIndex):
        return x.datetime

    index_sorted = sorted(index, key=sort_key, reverse=True)

    (INDEX_DIR / "posts.json").write_text(
        json.dumps([asdict(x) for x in index_sorted], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("done.")


if __name__ == "__main__":
    main()
