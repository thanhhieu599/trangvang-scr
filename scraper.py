"""
Cào danh bạ doanh nghiệp theo luồng: Lĩnh vực -> Phân ngành -> Danh sách công ty -> Chi tiết công ty.

Thu thập: tên, địa chỉ, điện thoại, email, website (+ lĩnh vực, phân ngành, link nguồn).
Có lưu tiến độ vào SQLite: dừng giữa chừng chạy lại sẽ làm tiếp, không cào lại công ty đã có.

Ví dụ:
    python scraper.py crawl --start-url "https://trangvangvietnam.com/<trang-linh-vuc>"
    python scraper.py export --out data/cong_ty.xlsx
"""
from __future__ import annotations

import argparse
import csv
import logging
import random
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse, unquote

import requests
from bs4 import BeautifulSoup, Tag

log = logging.getLogger("trangvang")

# ---------------------------------------------------------------------------
# Cấu hình nhận diện URL (chỉnh ở đây nếu website đổi cấu trúc)
# ---------------------------------------------------------------------------
CATEGORY_RE = re.compile(r"/categories/\d+", re.I)          # trang phân ngành
LISTING_RE = re.compile(r"/listings/\d+", re.I)             # trang chi tiết công ty
# Trang lĩnh vực (cấp trung gian giữa trang tổng và phân ngành). Không chắc mẫu URL
# nên mặc định: mọi link nội bộ không phải categories/listings nằm trong khối chứa
# chữ "phân ngành". Có thể ghi đè bằng --sector-pattern.
DEFAULT_SECTOR_PATTERN = None

# Domain không được coi là website của công ty
NON_COMPANY_DOMAINS = (
    "trangvangvietnam.com", "facebook.com", "fb.com", "zalo.me", "google.", "goo.gl",
    "youtube.com", "youtu.be", "twitter.com", "x.com", "instagram.com", "linkedin.com",
    "tiktok.com", "pinterest.com", "messenger.com", "apple.com", "play.google.com",
    "cloudflare.com", "maps.app.goo.gl", "bit.ly",
)

PHONE_RE = re.compile(r"(?:\+?84|0)[\d\s.\-()]{8,14}\d")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
SECTOR_CARD_RE = re.compile(r"\d[\d.,]*\s*phân ngành")
ADDRESS_ICON_RE = re.compile(r"(location|map-marker|map-pin|fa-map|place|address|dia-chi)", re.I)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}


# ---------------------------------------------------------------------------
# Tải trang
# ---------------------------------------------------------------------------
class Blocked(Exception):
    """Website từ chối truy cập tự động."""


class Fetcher:
    """Tải trang bằng HTTP thường, nghỉ giữa các lần gọi, thử lại khi lỗi tạm thời.
    Nếu website chặn (403 / ngắt kết nối) thì dừng ngay, không cố truy cập tiếp."""

    def __init__(self, delay: float = 2.0, retries: int = 3):
        self.delay = delay
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._last = 0.0

    def _wait(self):
        gap = self.delay * random.uniform(0.7, 1.4) - (time.time() - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.time()

    def get(self, url: str) -> str | None:
        blocked = 0
        for attempt in range(1, self.retries + 1):
            self._wait()
            try:
                r = self.session.get(url, timeout=30)
                if r.status_code == 200:
                    return r.text
                if r.status_code == 404:
                    log.warning("404: %s", url)
                    return None
                if r.status_code in (401, 403):
                    blocked += 1
                log.warning("HTTP %s (lần %d): %s", r.status_code, attempt, url)
            except requests.exceptions.ConnectionError as e:
                msg = str(e)
                if "10054" in msg or "reset" in msg.lower() or "aborted" in msg.lower():
                    blocked += 1
                log.warning("Lỗi kết nối (lần %d) %s: %s", attempt, url, e)
            except requests.RequestException as e:
                log.warning("Lỗi tải (lần %d) %s: %s", attempt, url, e)
            if blocked >= 2:
                raise Blocked(url)
            time.sleep(min(60, 2 ** attempt * 2))
        log.error("Bỏ qua sau %d lần thử: %s", self.retries, url)
        return None

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Tiện ích
# ---------------------------------------------------------------------------
def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip(" \t\r\n|·-–")


def norm_url(base: str, href: str) -> str:
    u = urlparse(urljoin(base, href.strip()))
    return urlunparse((u.scheme, u.netloc, u.path, "", u.query, ""))


def strip_page_param(url: str) -> str:
    u = urlparse(url)
    q = {k: v for k, v in parse_qs(u.query).items() if k.lower() != "page"}
    return urlunparse((u.scheme, u.netloc, u.path, "", urlencode(q, doseq=True), ""))


def with_page(url: str, page: int) -> str:
    u = urlparse(url)
    q = {k: v for k, v in parse_qs(u.query).items() if k.lower() != "page"}
    if page > 1:
        q["page"] = [str(page)]
    return urlunparse((u.scheme, u.netloc, u.path, "", urlencode(q, doseq=True), ""))


def listing_id(url: str) -> str:
    m = re.search(r"/listings/(\d+)", url)
    return m.group(1) if m else url


def decode_cfemail(hexstr: str) -> str:
    """Giải mã email bị Cloudflare ẩn (data-cfemail / /cdn-cgi/l/email-protection#...)."""
    try:
        key = int(hexstr[:2], 16)
        return "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))
    except ValueError:
        return ""


def page_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1 and clean(h1.get_text()):
        return clean(h1.get_text())
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return clean(og["content"])
    return clean(soup.title.get_text()) if soup.title else ""


# ---------------------------------------------------------------------------
# Bóc tách trang tổng / lĩnh vực / phân ngành
# ---------------------------------------------------------------------------
@dataclass
class Link:
    url: str
    text: str


def extract_category_links(html: str, base: str) -> list[Link]:
    """Mọi link phân ngành (/categories/...) theo đúng thứ tự xuất hiện, không trùng."""
    soup = BeautifulSoup(html, "html.parser")
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        if not CATEGORY_RE.search(a["href"]):
            continue
        url = strip_page_param(norm_url(base, a["href"]))
        if url in seen:
            continue
        seen.add(url)
        text = re.sub(r"\(\s*[\d.,]+\s*\)\s*$", "", clean(a.get_text()))  # bỏ "(1640)"
        out.append(Link(url, clean(text)))
    return out


def extract_sector_links(html: str, base: str, pattern: str | None = None) -> list[Link]:
    """Link sang trang lĩnh vực từ trang tổng (mũi tên ↗ ở góc thẻ)."""
    soup = BeautifulSoup(html, "html.parser")
    host = urlparse(base).netloc
    seen, out = set(), []
    rx = re.compile(pattern, re.I) if pattern else None
    for a in soup.find_all("a", href=True):
        url = norm_url(base, a["href"])
        if urlparse(url).netloc != host or url.rstrip("/") == base.rstrip("/"):
            continue
        if CATEGORY_RE.search(url) or LISTING_RE.search(url):
            continue
        if rx:
            ok = bool(rx.search(url))
        else:
            # Thẻ lĩnh vực: tổ tiên gần nhất chứa chữ "phân ngành" và có <h2>/<h3> tiêu đề
            ok = False
            node = a
            for _ in range(5):
                node = node.parent
                if not isinstance(node, Tag):
                    break
                txt = node.get_text(" ", strip=True).lower()
                # Thẻ ở trang tổng có dòng kiểu "nhà cung cấp · 46 phân ngành"
                if SECTOR_CARD_RE.search(txt) and node.find(["h2", "h3", "h4"]):
                    ok = True
                    break
        if not ok or url in seen:
            continue
        seen.add(url)
        # Tên lĩnh vực = tiêu đề của thẻ chứa link
        name = clean(a.get_text())
        card = a
        for _ in range(5):
            card = card.parent
            if isinstance(card, Tag) and card.find(["h2", "h3", "h4"]):
                name = clean(card.find(["h2", "h3", "h4"]).get_text())
                break
        out.append(Link(url, name))
    # Một thẻ có thể có nhiều link (mũi tên + "Xem tất cả") -> gộp theo tên
    uniq, names = [], set()
    for l in out:
        if l.text and l.text in names:
            continue
        names.add(l.text)
        uniq.append(l)
    return uniq


def extract_listing_links(html: str, base: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        if LISTING_RE.search(a["href"]):
            url = norm_url(base, a["href"]).split("#")[0]
            lid = listing_id(url)
            if lid not in seen:
                seen.add(lid)
                out.append(url)
    return out


# ---------------------------------------------------------------------------
# Bóc tách trang chi tiết công ty
# ---------------------------------------------------------------------------
@dataclass
class Company:
    url: str
    name: str = ""
    address: str = ""
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    website: str = ""


def _main_block(soup: BeautifulSoup) -> Tag:
    """Khối thông tin chính: tổ tiên gần nhất của <h1> có chứa link tel:/mailto:."""
    h1 = soup.find("h1")
    node = h1
    for _ in range(8):
        if node is None or node.parent is None:
            break
        node = node.parent
        if node.find("a", href=re.compile(r"^(tel:|mailto:)", re.I)) or \
           node.find(attrs={"data-cfemail": True}):
            return node
    return soup.body or soup


def _norm_phone(p: str) -> str:
    p = re.sub(r"[^\d+()]", " ", p)
    return clean(p)


def parse_company(html: str, url: str) -> Company:
    soup = BeautifulSoup(html, "html.parser")
    return parse_block(_main_block(soup), url, page_title(soup))


def parse_block(block: Tag, url: str, name: str) -> Company:
    c = Company(url=url, name=name)

    # --- Điện thoại: ưu tiên link tel:, bỏ số fax ---
    for a in block.find_all("a", href=re.compile(r"^tel:", re.I)):
        num = _norm_phone(unquote(a["href"][4:]) or a.get_text())
        ctx = clean(a.parent.get_text()).lower() if a.parent else ""
        if num and "fax" not in ctx and num not in c.phones:
            c.phones.append(num)
    if not c.phones:
        for line in block.get_text("\n").split("\n"):
            if "fax" in line.lower():
                continue
            for m in PHONE_RE.findall(line):
                num = _norm_phone(m)
                if len(re.sub(r"\D", "", num)) >= 9 and num not in c.phones:
                    c.phones.append(num)

    # --- Email: mailto, Cloudflare, rồi regex ---
    def add_email(e: str):
        e = e.strip().strip(".").lower()
        if EMAIL_RE.fullmatch(e) and e not in c.emails:
            c.emails.append(e)

    for a in block.find_all("a", href=True):
        h = a["href"]
        if h.lower().startswith("mailto:"):
            add_email(unquote(h[7:].split("?")[0]))
        elif "email-protection#" in h:
            add_email(decode_cfemail(h.split("#", 1)[1]))
    for el in block.find_all(attrs={"data-cfemail": True}):
        add_email(decode_cfemail(el["data-cfemail"]))
    if not c.emails:
        for m in EMAIL_RE.findall(block.get_text(" ")):
            add_email(m)

    # --- Website: link ra ngoài, không phải mạng xã hội / chính trang danh bạ ---
    candidates = []
    for a in block.find_all("a", href=True):
        href = a["href"].strip()
        if not href.lower().startswith(("http", "//")):
            continue
        # Link chuyển hướng dạng ...?url=https://abc.vn
        q = parse_qs(urlparse(href).query)
        for key in ("url", "u", "link", "redirect", "target"):
            if key in q and q[key][0].startswith("http"):
                href = q[key][0]
        dom = urlparse(href if "//" in href else "http://" + href).netloc.lower()
        if not dom or any(bad in dom for bad in NON_COMPANY_DOMAINS):
            continue
        text = clean(a.get_text()).lower()
        score = 2 if (text.startswith("www.") or dom.replace("www.", "") in text) else 1
        candidates.append((score, href))
    if candidates:
        candidates.sort(key=lambda x: -x[0])
        c.website = candidates[0][1]
    else:  # website chỉ ghi dạng chữ
        m = re.search(r"\b(www\.[a-z0-9\-.]+\.[a-z]{2,})", block.get_text(" "), re.I)
        if m:
            c.website = m.group(1)

    # --- Địa chỉ: phần tử cạnh icon vị trí, hoặc dòng đầu có "Việt Nam" ---
    for icon in block.find_all(["i", "span", "img", "svg"]):
        attrs = " ".join(icon.get("class", [])) + " " + (icon.get("alt") or "") + " " + (icon.get("src") or "")
        if ADDRESS_ICON_RE.search(attrs):
            parent = icon.parent
            txt = clean(parent.get_text(" ")) if parent else ""
            if len(txt) > 10 and not txt.lower().startswith(("vp ", "văn phòng", "địa chỉ đăng ký")):
                c.address = txt
                break
    if not c.address:
        for line in block.get_text("\n").split("\n"):
            line = clean(line)
            low = line.lower()
            if ("việt nam" in low or "tp." in low or "quận" in low or "phường" in low) \
                    and 15 < len(line) < 250 and not low.startswith(("vp ", "văn phòng", "địa chỉ đăng ký", "ngành")):
                c.address = line
                break
    return c


def parse_listing_cards(html: str, base: str) -> list[Company]:
    """Bóc từng thẻ công ty trên trang danh sách phân ngành (hình 4).
    Thẻ = khối lớn nhất bao quanh link /listings/<id> mà không chứa công ty khác."""
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=LISTING_RE):
        url = norm_url(base, a["href"]).split("#")[0]
        lid = listing_id(url)
        if lid in seen:
            continue
        card = a
        while isinstance(card.parent, Tag) and card.parent.name not in ("body", "html"):
            ids = {listing_id(x["href"]) for x in card.parent.find_all("a", href=LISTING_RE)}
            if len(ids) > 1:
                break
            card = card.parent
        if card is a:
            continue
        # Tên: link /listings/ nằm trong thẻ tiêu đề, nếu không thì link có chữ dài nhất
        title = card.find(["h1", "h2", "h3", "h4"])
        name = clean(title.get_text()) if title else ""
        if not name:
            name = max((clean(x.get_text()) for x in card.find_all("a", href=LISTING_RE)), key=len, default="")
        name = re.sub(r"^\d+\s+", "", name)  # bỏ số thứ tự "1 Hóa Chất Kemic..."
        seen.add(lid)
        out.append(parse_block(card, url, name))
    return out


def saved_page_url(html: str) -> str:
    """Link gốc của trang lưu bằng Ctrl+S (Chrome/Edge ghi trong comment 'saved from url')."""
    m = re.search(r"saved from url=\(\d+\)(\S+?)\s*-->", html[:3000])
    if m:
        return m.group(1)
    soup = BeautifulSoup(html[:200000], "html.parser")
    for sel in (("link", {"rel": "canonical"}, "href"), ("meta", {"property": "og:url"}, "content")):
        tag = soup.find(sel[0], attrs=sel[1])
        if tag and tag.get(sel[2]):
            return tag[sel[2]]
    return "https://trangvangvietnam.com/"


def category_name_of(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    inp = soup.find("input", attrs={"value": True, "type": re.compile("text|search", re.I)})
    if inp and len(clean(inp["value"])) > 3:
        return clean(inp["value"])
    return page_title(soup)


def list_html_files(folder: str) -> list[str]:
    import glob
    import os
    return sorted(glob.glob(os.path.join(folder, "**", "*.htm*"), recursive=True))


def import_file(store: "Store", path: str, sector: str = "") -> int | None:
    """Đọc 1 file đã lưu. Trả về số công ty, hoặc None nếu không phải trang Trang Vàng."""
    import os
    with open(path, encoding="utf-8", errors="ignore") as fh:
        html = fh.read()
    if "trangvang" not in html.lower():
        return None
    base = saved_page_url(html)
    if LISTING_RE.search(base):  # trang chi tiết 1 công ty
        companies = [parse_company(html, base)]
        cat = ""
    else:                         # trang danh sách phân ngành
        companies = parse_listing_cards(html, base)
        cat = category_name_of(html)
    for c in companies:
        store.upsert_company(c, sector, cat)
    log.info("%s: %d công ty", os.path.basename(path), len(companies))
    return len(companies)


def import_html(store: "Store", folder: str, sector: str = "") -> int:
    """Đọc mọi file .html/.htm trong thư mục (trang danh sách hoặc trang chi tiết đã lưu)."""
    files = list_html_files(folder)
    if not files:
        log.error("Không thấy file .html nào trong %s", folder)
        return 0
    return sum(import_file(store, f, sector) or 0 for f in files)


def watch(store: "Store", folder: str, out: str, sector: str = "", interval: float = 3.0,
          once: bool = False):
    """Chạy nền: thấy file .html mới/được lưu lại trong thư mục thì đọc ngay và cập nhật file Excel."""
    import os
    os.makedirs(folder, exist_ok=True)
    store.db.execute("CREATE TABLE IF NOT EXISTS imported_files (path TEXT PRIMARY KEY, mtime REAL)")
    done = dict(store.db.execute("SELECT path, mtime FROM imported_files").fetchall())
    log.info("Đang theo dõi thư mục: %s", os.path.abspath(folder))
    log.info("Lưu trang Trang Vàng (Ctrl+S) vào thư mục này, file Excel tự cập nhật: %s", os.path.abspath(out))
    log.info("Nhấn Ctrl+C để dừng.")
    while True:
        changed = 0
        for f in list_html_files(folder):
            try:
                mtime = os.path.getmtime(f)
            except OSError:
                continue
            if done.get(f) == mtime or time.time() - mtime < 1.5:  # chưa đổi / đang ghi dở
                continue
            try:
                n = import_file(store, f, sector)
            except Exception as e:
                log.warning("Không đọc được %s: %s", f, e)
                n = None
            done[f] = mtime
            store.db.execute("INSERT OR REPLACE INTO imported_files VALUES (?,?)", (f, mtime))
            store.db.commit()
            if n:
                changed += n
        if changed:
            export(store, out)
            total = store.db.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
            log.info(">>> Tổng: %d công ty trong %s", total, out)
        if once:
            return
        time.sleep(interval)


# ---------------------------------------------------------------------------
# Lưu trữ / tiến độ
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    url TEXT PRIMARY KEY, sector TEXT, name TEXT, ord INTEGER,
    done INTEGER DEFAULT 0, last_page INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS companies (
    listing_id TEXT PRIMARY KEY, url TEXT, name TEXT, address TEXT, phone TEXT,
    email TEXT, website TEXT, sector TEXT, category TEXT, all_categories TEXT, scraped_at TEXT
);
"""


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def add_category(self, url, sector, name, ord_):
        self.db.execute(
            "INSERT OR IGNORE INTO categories(url, sector, name, ord) VALUES (?,?,?,?)",
            (url, sector, name, ord_))
        self.db.commit()

    def pending_categories(self):
        return self.db.execute(
            "SELECT url, sector, name, last_page FROM categories WHERE done=0 ORDER BY ord").fetchall()

    def set_page(self, url, page, done=False):
        self.db.execute("UPDATE categories SET last_page=?, done=? WHERE url=?", (page, int(done), url))
        self.db.commit()

    def has_company(self, lid) -> bool:
        return self.db.execute("SELECT 1 FROM companies WHERE listing_id=?", (lid,)).fetchone() is not None

    def tag_category(self, lid, category):
        row = self.db.execute("SELECT all_categories FROM companies WHERE listing_id=?", (lid,)).fetchone()
        cats = [x for x in (row[0] or "").split(" | ") if x]
        if category not in cats:
            cats.append(category)
            self.db.execute("UPDATE companies SET all_categories=? WHERE listing_id=?",
                            (" | ".join(cats), lid))
            self.db.commit()

    def upsert_company(self, c: Company, sector, category):
        lid = listing_id(c.url)
        row = self.db.execute(
            "SELECT name, address, phone, email, website, sector, category FROM companies WHERE listing_id=?",
            (lid,)).fetchone()
        if not row:
            return self.save_company(c, sector, category)
        new = (c.name, c.address, " / ".join(c.phones), "; ".join(c.emails), c.website, sector, category)
        merged = [o or n for o, n in zip(row, new)]
        self.db.execute(
            "UPDATE companies SET name=?, address=?, phone=?, email=?, website=?, sector=?, category=? "
            "WHERE listing_id=?", (*merged, lid))
        self.db.commit()
        if category:
            self.tag_category(lid, category)

    def save_company(self, c: Company, sector, category):
        self.db.execute(
            "INSERT OR REPLACE INTO companies VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (listing_id(c.url), c.url, c.name, c.address, " / ".join(c.phones),
             "; ".join(c.emails), c.website, sector, category, category,
             datetime.now().isoformat(timespec="seconds")))
        self.db.commit()


# ---------------------------------------------------------------------------
# Luồng chạy
# ---------------------------------------------------------------------------
def discover(fetcher: Fetcher, store: Store, start_urls: list[str], sector_pattern: str | None,
             only_sectors: list[str]):
    """Bước 1-2: từ trang tổng/lĩnh vực -> danh sách phân ngành (lưu theo thứ tự)."""
    ord_ = store.db.execute("SELECT COALESCE(MAX(ord),0) FROM categories").fetchone()[0]
    for start in start_urls:
        if CATEGORY_RE.search(start):  # đưa thẳng link phân ngành
            ord_ += 1
            store.add_category(strip_page_param(start), "", "", ord_)
            continue
        html = fetcher.get(start)
        if not html:
            continue
        sectors = extract_sector_links(html, start, sector_pattern)
        if sectors:  # đây là trang tổng các lĩnh vực
            log.info("Tìm thấy %d lĩnh vực trên %s", len(sectors), start)
        else:        # đây là một trang lĩnh vực
            sectors = [Link(start, page_title(BeautifulSoup(html, "html.parser")))]
        for s in sectors:
            if only_sectors and not any(k.lower() in s.text.lower() for k in only_sectors):
                continue
            s_html = html if s.url == start else fetcher.get(s.url)
            if not s_html:
                continue
            cats = extract_category_links(s_html, s.url)
            log.info("Lĩnh vực [%s]: %d phân ngành", s.text, len(cats))
            for cat in cats:
                ord_ += 1
                store.add_category(cat.url, s.text, cat.text, ord_)


def crawl_categories(fetcher: Fetcher, store: Store, max_pages: int, max_companies: int | None):
    """Bước 3-4: lần lượt từng phân ngành -> từng trang danh sách -> từng công ty."""
    count = 0
    for cat_url, sector, cat_name, last_page in store.pending_categories():
        page = last_page + 1
        seen_in_cat: set[str] = set()
        log.info("=== Phân ngành: %s | %s (từ trang %d)", sector, cat_name or cat_url, page)
        while page <= max_pages:
            html = fetcher.get(with_page(cat_url, page))
            if not html:
                break
            if not cat_name:
                cat_name = page_title(BeautifulSoup(html, "html.parser"))
                store.db.execute("UPDATE categories SET name=? WHERE url=?", (cat_name, cat_url))
            links = [u for u in extract_listing_links(html, cat_url) if listing_id(u) not in seen_in_cat]
            if not links:  # hết trang
                break
            for u in links:
                lid = listing_id(u)
                seen_in_cat.add(lid)
                if store.has_company(lid):
                    store.tag_category(lid, cat_name)
                    continue
                d_html = fetcher.get(u)
                if not d_html:
                    continue
                c = parse_company(d_html, u)
                store.save_company(c, sector, cat_name)
                count += 1
                log.info("  [%d] %s | %s | %s | %s", count, c.name, ", ".join(c.phones),
                         ", ".join(c.emails), c.website)
                if max_companies and count >= max_companies:
                    log.info("Đạt giới hạn %d công ty, dừng.", max_companies)
                    return
            store.set_page(cat_url, page)
            page += 1
        store.set_page(cat_url, page - 1, done=True)


EXPORT_COLS = [
    ("sector", "Lĩnh vực"), ("category", "Phân ngành"), ("name", "Tên công ty"),
    ("address", "Địa chỉ"), ("phone", "Điện thoại"), ("email", "Email"),
    ("website", "Website"), ("all_categories", "Tất cả phân ngành"), ("url", "Link nguồn"),
    ("scraped_at", "Ngày cào"),
]


def export(store: Store, out: str):
    cols = ", ".join(c for c, _ in EXPORT_COLS)
    rows = store.db.execute(
        f"SELECT {cols} FROM companies ORDER BY sector, category, name").fetchall()
    headers = [h for _, h in EXPORT_COLS]
    if out.lower().endswith(".xlsx"):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Cong ty"
        ws.append(headers)
        for r in rows:
            ws.append(list(r))
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for col, w in zip("ABCDEFGHIJ", (18, 30, 40, 50, 22, 30, 30, 40, 40, 20)):
            ws.column_dimensions[col].width = w
        try:
            wb.save(out)
        except PermissionError:
            alt = out[:-5] + datetime.now().strftime("_%H%M%S") + ".xlsx"
            log.warning("File %s đang mở trong Excel, lưu tạm sang %s", out, alt)
            wb.save(alt)
            out = alt
    else:
        with open(out, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig để Excel đọc đúng tiếng Việt
            w = csv.writer(f)
            w.writerow(headers)
            w.writerows(rows)
    log.info("Đã xuất %d công ty -> %s", len(rows), out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Cào danh bạ doanh nghiệp theo Lĩnh vực > Phân ngành > Công ty")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("crawl", help="Cào dữ liệu (tự tiếp tục nếu bị ngắt)")
    c.add_argument("--start-url", action="append", required=False, default=[],
                   help="Trang tổng lĩnh vực, trang 1 lĩnh vực, hoặc link phân ngành. Dùng nhiều lần được.")
    c.add_argument("--only-sector", action="append", default=[],
                   help='Chỉ cào lĩnh vực có tên chứa chuỗi này, vd: --only-sector "Bảo hộ"')
    c.add_argument("--sector-pattern", default=DEFAULT_SECTOR_PATTERN,
                   help="Regex URL trang lĩnh vực (khi tự nhận diện không đúng)")
    c.add_argument("--delay", type=float, default=2.0, help="Giây nghỉ giữa 2 request (mặc định 2)")
    c.add_argument("--max-pages", type=int, default=500, help="Số trang tối đa mỗi phân ngành")
    c.add_argument("--max-companies", type=int, default=None, help="Dừng sau N công ty (để chạy thử)")
    c.add_argument("--rediscover", action="store_true", help="Quét lại danh sách phân ngành")
    c.add_argument("--db", default="trangvang.db")
    c.add_argument("--out", default=None, help="Xuất file ngay khi cào xong (.xlsx hoặc .csv)")

    e = sub.add_parser("export", help="Xuất dữ liệu ra Excel/CSV")
    e.add_argument("--db", default="trangvang.db")
    e.add_argument("--out", default="cong_ty.xlsx")

    i = sub.add_parser("import-html", help="Đọc các trang đã lưu bằng Ctrl+S rồi xuất Excel")
    i.add_argument("--dir", default="trang_da_luu", help="Thư mục chứa file .html")
    i.add_argument("--sector", default="", help="Tên lĩnh vực ghi vào cột Lĩnh vực (tùy chọn)")
    i.add_argument("--db", default="trangvang.db")
    i.add_argument("--out", default="cong_ty.xlsx")

    w = sub.add_parser("watch", help="Chạy nền: tự đọc trang vừa lưu (Ctrl+S) và cập nhật Excel")
    w.add_argument("--dir", default="trang_da_luu", help="Thư mục theo dõi (mặc định: trang_da_luu)")
    w.add_argument("--sector", default="", help="Tên lĩnh vực ghi vào cột Lĩnh vực (tùy chọn)")
    w.add_argument("--interval", type=float, default=3.0, help="Giây giữa 2 lần quét thư mục")
    w.add_argument("--db", default="trangvang.db")
    w.add_argument("--out", default="cong_ty.xlsx")

    s = sub.add_parser("status", help="Xem tiến độ")
    s.add_argument("--db", default="trangvang.db")

    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler("trangvang.log", encoding="utf-8")])
    store = Store(a.db)

    if a.cmd == "export":
        export(store, a.out)
        return
    if a.cmd == "status":
        t, d = store.db.execute("SELECT COUNT(*), SUM(done) FROM categories").fetchone()
        n = store.db.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        print(f"Phân ngành: {d or 0}/{t} xong | Công ty đã cào: {n}")
        return

    if a.cmd == "watch":
        try:
            watch(store, a.dir, a.out, a.sector, a.interval)
        except KeyboardInterrupt:
            log.info("Đã dừng theo dõi.")
        return

    if a.cmd == "import-html":
        n = import_html(store, a.dir, a.sector)
        log.info("Đã đọc %d công ty từ %s", n, a.dir)
        export(store, a.out)
        return

    fetcher = Fetcher(delay=a.delay)
    try:
        has_cats = store.db.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        if a.start_url and (a.rediscover or not has_cats):
            discover(fetcher, store, a.start_url, a.sector_pattern, a.only_sector)
        elif not has_cats:
            ap.error("Lần chạy đầu cần --start-url")
        crawl_categories(fetcher, store, a.max_pages, a.max_companies)
    except KeyboardInterrupt:
        log.info("Đã dừng. Chạy lại cùng lệnh để làm tiếp.")
    except Blocked as b:
        log.error("Website từ chối truy cập tự động (%s). Đã dừng để tránh bị khóa IP.", b)
        log.error("Dùng cách khác: bookmarklet 'cai_dat_bookmarklet.html' hoặc lệnh 'import-html' (xem README).")
    finally:
        fetcher.close()
        if a.out:
            export(store, a.out)


if __name__ == "__main__":
    main()
