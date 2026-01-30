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

# 松尾美佑：ct は公式側で変わる可能性あり
CT = "55386"
LIST_BASE = "https://www.nogizaka46.com/s/n46/diary/MEMBER/list?cd=MEMBER"

# ---- 出力先は docs 配下に統一（あなたのリポジトリ構成に合わせる）----
REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
POSTS_DIR = DOCS_DIR / "posts"
INDEX_DIR = DOCS_DIR / "index"
DEBUG_DIR = DOCS_DIR / "debug"

HEADERS = {
    "User-Agent": "matsuo-miyu-blog/1.1 (personal archive)",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

SLEEP_SEC = 1.0
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

# どこまで月別アーカイブを掘るか（必要なら変えてOK）
START_YM = "202601"  # 例：2026年1月から過去へ
END_YM = "202001"    # 例：2020年1月まで


@dataclass
class PostIndex:
    id: str
    title: str
    datetime: str
    url: str
    local_dir: str
    images: list[str]      # docs からの相対パス
    links_in_post: list[str]


def _dedup_keep(seq: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in seq:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def safe_folder(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:140] if s else "untitled"


def normalize_detail_url(u: str) -> str:
    return re.sub(r"\?.*$", "", u)


def get(url: str) -> tuple[int, str, str]:
    """
    returns: (status_code, final_url, text)
    """
    r = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    return r.status_code, str(r.url), r.text


def soup_from_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def extract_detail_links(soup: BeautifulSoup) -> list[str]:
    """
    公式のHTMLが微妙に変わっても拾えるように、
    href に 'diary/detail/' が含まれるリンクを全部拾う
    """
    urls: list[str] = []
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        if "diary/detail/" not in href:
            continue
        full = urljoin(BASE, href)
        urls.append(normalize_detail_url(full))
    return _dedup_keep(urls)


def iter_months_desc(start_ym: str, end_ym: str):
    """
    YYYYMM を start->end へ降順で回す（両端含む）
    """
    sy, sm = int(start_ym[:4]), int(start_ym[4:])
    ey, em = int(end_ym[:4]), int(end_ym[4:])
    y, m = sy, sm
    while True:
        yield f"{y:04d}{m:02d}"
        if (y, m) == (ey, em):
            break
        m -= 1
        if m == 0:
            y -= 1
            m = 12


def load_existing_ids() -> set[str]:
    p = INDEX_DIR / "posts.json"
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {str(x.get("id", "")) for x in data if isinstance(x, dict) and x.get("id")}
        return set()
    except Exception:
        return set()


def parse_post(url: str):
    status, final_url, html = get(url)
    if status != 200:
        raise RuntimeError(f"[DETAIL] status={status} url={url} final={final_url}")

    soup = soup_from_html(html)

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
    m2 = re.search(r"/diary/detail/(\d+)", final_url)
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
        links.append(urljoin(BASE, a.get("href")))
    links = _dedup_keep(links)

    raw_html = html  # そのまま保存（あとで切り出し・加工する）
    return title, dt, pid, normalize_detail_url(final_url), image_urls, links, raw_html


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
    soup = soup_from_html(raw_html)
    for img in soup.select("img[src]"):
        src = img.get("src") or ""
        full = re.sub(r"\?.*$", "", urljoin(BASE, src))
        if full in mapping:
            img["src"] = mapping[full]
    return str(soup)


def extract_article_only(raw_html: str) -> str:
    """
    余計なヘッダ/フッタ/メニュー/言語選択を消したいので、
    できるだけ「記事本文っぽい塊」だけに寄せる。
    見つからない場合は raw のまま返す。
    """
    soup = soup_from_html(raw_html)

    # よくある記事コンテナ候補
    candidates = [
        ".c-blog-article",
        ".p-blog-article",
        "article",
        ".c-article",
        ".content",
        "main",
    ]
    for sel in candidates:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            # その中から不要そうな領域を削除
            for bad in el.select(
                "nav, header, footer, .language, .lang, .c-lang, .c-header, .c-footer, .c-nav"
            ):
                bad.decompose()
            return str(el)

    return raw_html


def extract_post_urls_all_months() -> list[str]:
    """
    月別アーカイブ（dy=YYYYMM）を全部なめて detail URL を集める
    """
    urls: list[str] = []
    for ym in iter_months_desc(START_YM, END_YM):
        page = 1
        month_added = 0

        while True:
            # キャッシュ対策で ts を付ける
            page_url = f"{LIST_BASE}&ct={CT}&dy={ym}&page={page}&ts={int(time.time())}"
            status, final_url, html = get(page_url)
            soup = soup_from_html(html)
            links = extract_detail_links(soup)

            print(f"[LIST] ym={ym} page={page} status={status} links={len(links)} final={final_url}")

            if status != 200:
                DEBUG_DIR.mkdir(parents=True, exist_ok=True)
                (DEBUG_DIR / f"list_{ym}_p{page}_status{status}.html").write_text(
                    html, encoding="utf-8"
                )
                break

            if not links:
                # この月のこのページは空っぽ：デバッグ保存して終了
                DEBUG_DIR.mkdir(parents=True, exist_ok=True)
                (DEBUG_DIR / f"list_{ym}_p{page}_nolinks.html").write_text(html, encoding="utf-8")
                break

            before = len(urls)
            urls.extend(links)
            urls = _dedup_keep(urls)
            added = len(urls) - before
            month_added += max(0, added)

            # 次ページへ
            page += 1
            time.sleep(SLEEP_SEC)

        print(f"[LIST] ym={ym} added={month_added} total={len(urls)}")

    return urls


def main():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    existing_ids = load_existing_ids()
    if existing_ids:
        print(f"[SKIP] existing posts.json detected. existing ids: {len(existing_ids)}")

    post_urls = extract_post_urls_all_months()
    print(f"found {len(post_urls)} post urls")

    index: list[PostIndex] = []

    # 既存 posts.json があれば先に読み込んで引き継ぐ（消さない）
    existing_path = INDEX_DIR / "posts.json"
    if existing_path.exists():
        try:
            old = json.loads(existing_path.read_text(encoding="utf-8"))
            if isinstance(old, list):
                for x in old:
                    if isinstance(x, dict) and x.get("id"):
                        index.append(
                            PostIndex(
                                id=str(x.get("id", "")),
                                title=str(x.get("title", "")),
                                datetime=str(x.get("datetime", "")),
                                url=str(x.get("url", "")),
                                local_dir=str(x.get("local_dir", "")),
                                images=list(x.get("images", []) or []),
                                links_in_post=list(x.get("links_in_post", []) or []),
                            )
                        )
        except Exception:
            pass

    # 既存IDはスキップして「新規だけ」落とす
    for i, url in enumerate(post_urls, 1):
        try:
            title, dt, pid, final_detail_url, image_urls, links, raw_html = parse_post(url)
        except Exception as e:
            print(f"[WARN] parse failed: {url} ({e})")
            continue

        if pid in existing_ids:
            # 既に持ってる
            continue

        print(f"[NEW] [{i}/{len(post_urls)}] id={pid} {dt} {title}")

        year = dt.split(".")[0] if dt != "unknown" else "unknown"
        dt_folder = dt.replace(".", "-").replace(" ", "_").replace(":", "")
        folder_name = safe_folder(f"{dt_folder}_{pid}") if dt != "unknown" else safe_folder(pid)

        post_dir = POSTS_DIR / year / folder_name
        post_dir.mkdir(parents=True, exist_ok=True)

        # raw 保存
        (post_dir / "page_raw.html").write_text(raw_html, encoding="utf-8")

        # 画像DL＋置換
        mapping_for_html: dict[str, str] = {}
        saved_imgs: list[str] = []

        for n, img_url in enumerate(image_urls, 1):
            path = urlparse(img_url).path
            ext = Path(path).suffix or ".jpg"
            rel = f"images/{n:02d}{ext}"
            out_path = post_dir / rel

            if download(img_url, out_path):
                saved_imgs.append(str(out_path.relative_to(DOCS_DIR)))
                mapping_for_html[img_url] = rel

            time.sleep(SLEEP_SEC)

        # 余計な領域を削ってから画像をローカルに差し替え
        article_html = extract_article_only(raw_html)
        cooked = rewrite_html_images_to_local(article_html, mapping_for_html)
        (post_dir / "page.html").write_text(cooked, encoding="utf-8")

        # md 生成（本文: page.html で viewer 側が拾う）
        (post_dir / "index.md").write_text(
            f"""---
id: "{pid}"
title: "{title.replace('"', "'")}"
datetime: "{dt}"
source_url: "{final_detail_url}"
---

# {title}
- 更新日時: {dt}
- 元URL: {final_detail_url}

本文: page.html
""",
            encoding="utf-8",
        )

        index.append(
            PostIndex(
                id=pid,
                title=title,
                datetime=dt,
                url=final_detail_url,
                local_dir=str(post_dir.relative_to(DOCS_DIR)),
                images=saved_imgs,
                links_in_post=links,
            )
        )
        existing_ids.add(pid)

        time.sleep(SLEEP_SEC)

    # posts.json 書き出し（最新順に軽くソート：dtが unknown は後ろ）
    def sort_key(x: PostIndex):
        return (x.datetime == "unknown", x.datetime)

    index_sorted = sorted(index, key=sort_key, reverse=True)

    (INDEX_DIR / "posts.json").write_text(
        json.dumps([asdict(x) for x in index_sorted], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("done.")


if __name__ == "__main__":
    main()
