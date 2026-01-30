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

# 松尾美佑 ct（公式側で変わる可能性はある）
CT = "55386"

# ✅ cd=MEMBER は付けない（dy取得で取りこぼしやすい）
LIST_URL = f"{BASE}/s/n46/diary/MEMBER/list?ct={CT}"

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
POSTS_DIR = DOCS_DIR / "posts"
INDEX_DIR = DOCS_DIR / "index"

HEADERS = {"User-Agent": "matsuo-miyu-blog/1.0 (personal archive)"}
SLEEP_SEC = 1.0
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


@dataclass
class PostIndex:
  id: str
  title: str
  datetime: str
  url: str
  local_dir: str         # docs/ からの相対 (POSIX)
  images: list[str]      # docs/ からの相対 (POSIX)
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
  r = requests.get(url, headers=HEADERS, timeout=45)
  r.raise_for_status()
  return r


def get_soup(url: str) -> BeautifulSoup:
  r = get(url)
  return BeautifulSoup(r.text, "html.parser")


def normalize_detail_url(u: str) -> str:
  return re.sub(r"\?.*$", "", u)


def ym_prev(ym: str) -> str:
  y = int(ym[:4]); m = int(ym[4:6])
  m -= 1
  if m == 0:
    y -= 1
    m = 12
  return f"{y:04d}{m:02d}"


def parse_ym_from_calendar(soup: BeautifulSoup) -> str | None:
  # 例: "2025年12月"
  text = soup.get_text("\n", strip=True)
  m = re.search(r"(20\d{2})年(0?\d|1[0-2])月", text)
  if not m:
    return None
  y = int(m.group(1))
  mm = int(m.group(2))
  return f"{y:04d}{mm:02d}"


def extract_detail_urls_from_list(soup: BeautifulSoup) -> list[str]:
  urls: list[str] = []
  for a in soup.select('a[href]'):
    href = a.get("href") or ""
    if "/s/n46/diary/detail/" not in href:
      continue
    full = urljoin(BASE, href)
    urls.append(normalize_detail_url(full))
  return _dedup_keep(urls)


def extract_post_urls_by_month(start_ym: str, stop_ym: str = "201801") -> list[str]:
  urls: list[str] = []
  ym = start_ym
  empty_months = 0

  while int(ym) >= int(stop_ym):
    page = 1
    month_added = 0

    while True:
      page_url = f"{LIST_URL}&dy={ym}&page={page}"
      print(f"[LIST] ym={ym} page={page} -> {page_url}")
      soup = get_soup(page_url)

      found = extract_detail_urls_from_list(soup)
      if not found:
        break

      before = len(urls)
      urls.extend(found)
      urls = _dedup_keep(urls)
      month_added += (len(urls) - before)

      page += 1
      time.sleep(SLEEP_SEC)

      # 念のためページ上限（無限ループ防止）
      if page > 50:
        break

    if month_added == 0:
      empty_months += 1
    else:
      empty_months = 0

    # 連続で空の月が続きすぎたら止める（松尾の初期より前に行く前に）
    if empty_months >= 24 and len(urls) > 0:
      print("[LIST] too many empty months. stop.")
      break

    ym = ym_prev(ym)
    time.sleep(SLEEP_SEC)

  print(f"[LIST] found {len(urls)} post urls")
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
    full_noq = re.sub(r"\?.*$", "", full)
    if full_noq.lower().endswith(IMG_EXTS):
      image_urls.append(full_noq)
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
    full_noq = re.sub(r"\?.*$", "", full)
    if full_noq in mapping:
      img["src"] = mapping[full_noq]
  return str(soup)


def parse_dt_sortkey(dt_str: str) -> tuple:
  # "2025.12.31 23:59" -> (2025,12,31,23,59)
  m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})", dt_str or "")
  if not m:
    return (0, 0, 0, 0, 0)
  return tuple(int(x) for x in m.groups())


def load_existing_index() -> dict[str, dict]:
  path = INDEX_DIR / "posts.json"
  if not path.exists():
    return {}
  data = json.loads(path.read_text(encoding="utf-8"))
  if not isinstance(data, list):
    return {}
  by_id = {}
  for item in data:
    pid = str(item.get("id", ""))
    if pid:
      by_id[pid] = item
  return by_id


def main():
  DOCS_DIR.mkdir(parents=True, exist_ok=True)
  POSTS_DIR.mkdir(parents=True, exist_ok=True)
  INDEX_DIR.mkdir(parents=True, exist_ok=True)

  existing = load_existing_index()
  existing_ids = set(existing.keys())
  print(f"[SKIP] existing posts.json detected. existing ids: {len(existing_ids)}")

  # start_ym をカレンダーから取得（取れなければ今月）
  soup0 = get_soup(LIST_URL)
  start_ym = parse_ym_from_calendar(soup0)
  if not start_ym:
    start_ym = datetime.now().strftime("%Y%m")
  print(f"[LIST] start_ym: {start_ym}")

  post_urls = extract_post_urls_by_month(start_ym)
  print(f"found {len(post_urls)} post urls")

  new_items: list[PostIndex] = []

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
        # docs/ からの相対に揃える
        saved_imgs.append(str(out_path.relative_to(DOCS_DIR)).replace("\\", "/"))
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

    local_dir = str(post_dir.relative_to(DOCS_DIR)).replace("\\", "/")

    new_items.append(
      PostIndex(
        id=pid,
        title=title,
        datetime=dt,
        url=url,
        local_dir=local_dir,
        images=saved_imgs,
        links_in_post=links,
      )
    )

    time.sleep(SLEEP_SEC)

  # 既存 + 新規 をマージして datetime 降順で保存
  merged: list[dict] = []
  merged.extend(existing.values())
  merged.extend(asdict(x) for x in new_items)

  merged.sort(key=lambda x: parse_dt_sortkey(str(x.get("datetime", ""))), reverse=True)

  (INDEX_DIR / "posts.json").write_text(
    json.dumps(merged, ensure_ascii=False, indent=2),
    encoding="utf-8",
  )

  print(f"[DONE] added={len(new_items)} total={len(merged)}")
  print(f"[DONE] wrote: {INDEX_DIR / 'posts.json'}")


if __name__ == "__main__":
  main()
