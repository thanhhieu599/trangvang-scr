"""Sequential, resumable crawler for authorized public Trang Vang pages."""
import argparse
import asyncio
import csv
import hashlib
import json
import logging
import os
import random
import re
import sqlite3
import time
from queue import Empty, Queue
from threading import Event, Lock, Thread
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qs, unquote
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = 'https://trangvangvietnam.com/'
AGENT = 'AuthorizedDirectoryCollector/1.0'
FIELDS = ['name', 'address', 'phones', 'emails', 'websites', 'source_url', 'collected_at']

class Halt(RuntimeError):
    pass


class PageLoadError(RuntimeError):
    pass


def proxy_options(value):
    """Parse a locally configured proxy without including its secrets in errors."""
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https', 'socks5') or not parsed.hostname
                or parsed.port is None or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment):
            raise ValueError()
        host = f'[{parsed.hostname}]' if ':' in parsed.hostname else parsed.hostname
        options = {'server': f'{parsed.scheme}://{host}:{parsed.port}'}
        if parsed.username is not None:
            if parsed.scheme == 'socks5': raise ValueError()
            options['username'] = unquote(parsed.username)
            options['password'] = unquote(parsed.password or '')
        return options
    except (ValueError, TypeError):
        raise Halt('Proxy không hợp lệ. Dùng http[s]://[user:password@]host:port '
                   'hoặc socks5://host:port không xác thực.') from None


def clean(value):
    return ' '.join(str(value or '').split())


def canonical(href, base=BASE):
    u = urlsplit(urljoin(base, href))
    if u.scheme not in ('https', 'http') or u.hostname not in ('trangvangvietnam.com', 'www.trangvangvietnam.com'):
        return None
    return urlunsplit(('https', 'trangvangvietnam.com', u.path or '/', u.query, ''))


def identity(url):
    m = re.search(r'/(gindex|categories|listings)/(\d+)', url)
    return ':'.join(m.groups()) if m else url


def category_url(value):
    try: url = canonical(value.strip().strip('<>'))
    except ValueError: url = None
    if not url or not re.match(r'^/(categories|gindex)/\d+(?:/|$)', urlsplit(url).path):
        raise Halt('Cần link danh mục /categories/... hoặc lĩnh vực /gindex/... của Trang Vàng.')
    return url


def prompt_category(previous=None):
    print('\n=== QUÉT DANH MỤC DO BẠN CHỌN ===')
    if previous: print('Danh mục gần nhất:', previous)
    while True:
        try: value = input('Dán link danh mục [Enter = tiếp tục danh mục gần nhất; q = thoát]: ').strip()
        except EOFError: raise Halt('Terminal không nhận nhập liệu; dùng --category URL thay thế.') from None
        if value.lower() == 'q': raise Halt('Người dùng thoát trước khi chạy.')
        try: return category_url(value or previous or '')
        except Halt as exc: print(exc)


def linked(soup, pattern, base):
    seen = set()
    for a in soup.select('a[href]'):
        url = canonical(a['href'], base)
        if url and re.search(pattern, urlsplit(url).path) and identity(url) not in seen:
            seen.add(identity(url))
            yield url, clean(a.get_text(' ', strip=True))


def parse_company(html, url):
    soup = html if isinstance(html, BeautifulSoup) else BeautifulSoup(html, 'html.parser')
    data = {k: '' for k in FIELDS}
    data['source_url'] = url
    data['collected_at'] = datetime.now(timezone.utc).isoformat()
    # Prefer structured data and microdata. Never scan the whole page for contacts:
    # advertisements and recommended suppliers may contain other companies' data.
    entities = []
    def walk(obj):
        if isinstance(obj, list):
            for item in obj: walk(item)
        elif isinstance(obj, dict):
            types = obj.get('@type', [])
            types = [types] if isinstance(types, str) else types
            if set(types) & {'Organization', 'LocalBusiness', 'Corporation', 'Store', 'ProfessionalService'}:
                entities.append(obj)
            if '@graph' in obj: walk(obj['@graph'])
            if isinstance(obj.get('mainEntity'), (dict, list)): walk(obj['mainEntity'])
    for script in soup.select('script[type="application/ld+json"]'):
        try: walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError): pass
    h1 = soup.find('h1')
    title = clean(h1.get_text(' ', strip=True)) if h1 else ''
    entity = next((e for e in entities if clean(e.get('name')) == title), None)
    if entity is None and len(entities) == 1: entity = entities[0]
    entity = entity or {}
    data['name'] = clean(entity.get('name')) or title
    addr = entity.get('address', '')
    if isinstance(addr, dict):
        addr = ', '.join(clean(addr.get(k)) for k in ('streetAddress', 'addressLocality', 'addressRegion', 'addressCountry') if isinstance(addr.get(k), str) and clean(addr.get(k)))
    if isinstance(addr, str): data['address'] = clean(addr)
    # Find the smallest ancestor containing the company heading and contact links.
    scope = None
    if h1:
        for node in h1.parents:
            if node.name in ('body', 'html'): break
            if node.select_one('a[href^="mailto:"], a[href^="tel:"], [itemprop="address"]'):
                scope = node
                break
    if scope is None:
        scope = soup.select_one('[itemtype*="LocalBusiness"], [itemtype*="Organization"]')
    def values(key):
        value = entity.get(key, [])
        return [clean(v) for v in (value if isinstance(value, list) else [value]) if isinstance(v, str) and clean(v)]
    phones, emails = values('telephone'), values('email')
    websites = []
    def website(value):
        if value.startswith('www.'): value = 'https://' + value
        p = urlsplit(value)
        if p.scheme in ('http', 'https') and p.hostname and p.hostname not in ('trangvangvietnam.com', 'www.trangvangvietnam.com'):
            websites.append(value)
    for item in values('url'): website(item)
    if scope:
        address = scope.select_one('[itemprop="address"], .company-address, .address')
        if not data['address'] and address: data['address'] = clean(address.get_text(' ', strip=True))
        for element in scope.select('[itemprop="telephone"]'):
            phones.append(clean(element.get('content') or element.get_text(' ', strip=True)))
        for a in scope.select('a[href]'):
            href = a['href'].strip()
            if href.lower().startswith('mailto:'): emails.append(href[7:].split('?')[0])
            elif href.lower().startswith('tel:'): phones.append(href[4:])
            elif re.match(r'^(?:https?://|www\.)', clean(a.get_text())):
                website(href)
    data['phones'] = ' | '.join(dict.fromkeys(filter(None, phones)))
    data['emails'] = ' | '.join(dict.fromkeys(filter(None, emails)))
    data['websites'] = ' | '.join(dict.fromkeys(websites))
    if not data['name']: raise ValueError('Không tìm thấy tên công ty; cần kiểm tra HTML/selector')
    data['review_required'] = not all(data[k] for k in ('address', 'phones', 'emails', 'websites'))
    return data


class Client:
    def __init__(self, delay=5):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = AGENT
        self.delay = max(3, delay)
        self.last = 0
        self.robots = None

    def request(self, url):
        for attempt in range(4):
            time.sleep(max(0, self.delay - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            try:
                response = self.session.get(url, timeout=(15, 45), allow_redirects=False)
            except requests.RequestException as exc:
                if attempt == 3: raise RuntimeError(f'Lỗi mạng: {url}') from exc
                time.sleep(2 ** (attempt + 1))
                continue
            if response.status_code in (301, 302, 303, 307, 308):
                raise Halt(f'Tạm dừng: trang chuyển hướng, cần kiểm tra URL: {url}')
            if not response.encoding or response.encoding.lower() == 'iso-8859-1':
                response.encoding = 'utf-8'
            content = response.text.lower()
            if response.status_code in (401, 403, 429) or any(x in content for x in ('cf-chl-', 'challenge-platform', 'sorry, you have been blocked', 'verify you are human', 'g-recaptcha', 'hcaptcha-container')):
                raise Halt(f'Bị chặn/CAPTCHA/giới hạn tốc độ tại {url}. Đã giữ tiến độ; cần chủ website cho phép truy cập.')
            if response.status_code >= 500:
                if attempt < 3:
                    time.sleep(2 ** (attempt + 1))
                    continue
            response.raise_for_status()
            return response.text
        raise RuntimeError('Đã hết số lần thử')

    def init_robots(self):
        try:
            text = self.request(urljoin(BASE, 'robots.txt'))
        except (requests.RequestException, RuntimeError) as exc:
            raise Halt(f'Không đọc được robots.txt: {exc}') from exc
        if '<html' in text.lower() or '<!doctype' in text.lower():
            raise Halt('robots.txt trả HTML; không xác định được chính sách truy cập.')
        self.robots = RobotFileParser()
        self.robots.parse(text.splitlines())
        delay = self.robots.crawl_delay(AGENT) or self.robots.crawl_delay('*')
        if delay: self.delay = max(self.delay, delay)
        rate = self.robots.request_rate(AGENT) or self.robots.request_rate('*')
        if rate and rate.requests: self.delay = max(self.delay, rate.seconds / rate.requests)

    def get(self, url):
        if self.robots is None: self.init_robots()
        if not self.robots.can_fetch(AGENT, url): raise Halt(f'robots.txt không cho phép: {url}')
        return self.request(url)

    def close(self):
        self.session.close()


class BrowserClient(Client):
    """Visible browser with a dedicated local profile and manual verification."""
    def __init__(self, delay=5, profile='data/browser-profile', channel=None,
                 stealth=False, proxy=None, headless=False, jitter=0,
                 verify_timeout=120, page_timeout=45, on_phase=None):
        super().__init__(delay)
        self.runtime = None
        self.context = None
        self._closing = False
        self.jitter = jitter
        self.headless = headless
        self.verify_timeout = verify_timeout
        self.page_timeout = page_timeout
        self.on_phase = on_phase
        try:
            from playwright.sync_api import sync_playwright
            stealth_plugin = None
            if stealth:
                try:
                    from playwright_stealth import Stealth
                    stealth_plugin = Stealth(navigator_languages_override=('vi-VN', 'vi'), navigator_platform=False, navigator_platform_override=None)
                except ImportError:
                    raise Halt('Thiếu playwright-stealth. Chạy: pip install -r requirements-stealth.txt') from None
            self.runtime = sync_playwright().start()
            options = {'headless': headless, 'locale': 'vi-VN', 'viewport': {'width': 1366, 'height': 768}}
            if proxy: options['proxy'] = proxy
            if stealth:
                options['args'] = ['--disable-blink-features=AutomationControlled']
            if channel: options['channel'] = channel
            self.context = self.runtime.chromium.launch_persistent_context(
                user_data_dir=str(Path(profile).resolve()), **options)
            if stealth_plugin: stealth_plugin.apply_stealth_sync(self.context)
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            self.status = None
            self.content_type = ''
            self.page.on('response', self._response)
            self.page.route('**/*', self._route)
        except Halt:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise Halt('Không mở được trình duyệt. Cài: pip install -r requirements-browser.txt; '
                       'python -m playwright install chromium. Hoặc dùng --browser-channel chrome. '
                       'Không dùng chung thư mục hồ sơ với Chrome đang mở.') from exc

    def _route(self, route):
        try:
            if self._closing: return
            request = route.request
            if (request.is_navigation_request() and request.frame == self.page.main_frame
                    and not canonical(request.url)):
                route.abort()
            else:
                route.continue_()
        except asyncio.CancelledError:
            # Playwright may cancel in-flight route callbacks during shutdown.
            return
        except Exception:
            if self._closing or self.page.is_closed(): return
            raise

    def _response(self, response):
        request = response.request
        if request.is_navigation_request() and request.frame == self.page.main_frame:
            self.status = response.status
            self.content_type = response.headers.get('content-type', '')

    def _document(self):
        if 'text/plain' in self.content_type:
            return self.page.locator('body').inner_text()
        return self.page.content()

    def _visible_document(self):
        # Read the rendered DOM, stripping invisible links in a detached copy.
        # Offscreen links remain if they have layout; this is not viewport filtering.
        return self.page.evaluate('''() => {
            const copy = document.documentElement.cloneNode(true);
            const links = document.querySelectorAll('a[href]');
            const copies = copy.querySelectorAll('a[href]');
            links.forEach((link, i) => {
                const style = getComputedStyle(link);
                if (!link.getClientRects().length || style.display === 'none' ||
                    style.visibility === 'hidden' || style.visibility === 'collapse' ||
                    link.closest('[hidden], [aria-hidden="true"]')) copies[i].remove();
            });
            return '<!DOCTYPE html>' + copy.outerHTML;
        }''')

    def _blocked(self, content):
        if self.status == 403: return True
        lower = content.lower()
        soup = BeautifulSoup(content, 'html.parser')
        title = clean(soup.title.get_text()).lower() if soup.title else ''
        if 'sorry, you have been blocked' in lower or any(x in title for x in ('just a moment', 'attention required')):
            return True
        # A legitimate company page may embed a contact-form CAPTCHA or a
        # background Cloudflare JS detection script. Neither alone is a block.
        real_content = soup.find('h1') and soup.select_one('a[href^="tel:"],a[href^="mailto:"],[itemprop="address"],a[href*="/gindex/"],a[href*="/categories/"],a[href*="/listings/"]')
        if real_content: return False
        return any(marker in lower for marker in ('cf-chl-', 'challenge-platform', 'verify you are human', 'g-recaptcha', 'hcaptcha-container'))

    def _phase(self, text):
        callback = getattr(self, 'on_phase', None)
        if callback: callback(phase=text)

    def _wait_for_user(self):
        # Only terminal input runs on a worker. All Playwright calls remain on
        # the owning thread, which keeps dispatching route/response events.
        replies = Queue()
        started = time.monotonic()
        timeout = getattr(self, 'verify_timeout', 120)
        def read_terminal():
            try:
                answer = input('Hoàn tất xác minh trong cửa sổ Chrome do chương trình mở. '
                               'Giữ cửa sổ đó mở; khi trang thật hiện, nhấn Enter ở đây. '
                               'Nhập q để dừng: ')
                replies.put((True, answer))
            except BaseException as exc:
                replies.put((False, exc))
        Thread(target=read_terminal, name='crawler-terminal', daemon=True).start()
        while True:
            elapsed = time.monotonic() - started
            if timeout and elapsed >= timeout:
                raise Halt(f'Hết {timeout:g} giây chờ xác minh. Đã giữ tiến độ và dừng; không tiếp tục gửi yêu cầu khi bị chặn.')
            self._phase(f'CHỜ XÁC MINH — còn {max(0, int(timeout-elapsed))}s; xử lý trong Chrome rồi Enter' if timeout else 'CHỜ XÁC MINH — đang chờ bạn nhấn Enter')
            if self.page.is_closed():
                raise Halt('Cửa sổ/tab Chrome của chương trình đã đóng; tiến độ được giữ. '
                           'Chạy lại và giữ cửa sổ đó mở trong khi xác minh.')
            try:
                success, value = replies.get_nowait()
            except Empty:
                self.page.wait_for_timeout(100)
                continue
            if not success: raise value
            return value

    def request(self, url):
        try:
            waiting = max(0, self.delay - (time.monotonic() - self.last)) + random.uniform(0, getattr(self, 'jitter', 0))
            self._phase(f'NGHỈ GIỮA HAI LƯỢT — {waiting:.1f}s')
            time.sleep(waiting)
            self.last = time.monotonic()
            self.status = None
            self.content_type = ''
            timeout_ms = getattr(self, 'page_timeout', 45) * 1000
            self._phase(f'ĐANG TẢI — giới hạn {timeout_ms/1000:g}s')
            self.page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)
            content = self._document()
            if self.status in (401, 429):
                raise Halt(f'Website trả HTTP {self.status}; đã giữ tiến độ, không tiếp tục gửi yêu cầu.')
            if 'sorry, you have been blocked' in content.lower():
                raise Halt('Cloudflare từ chối truy cập (Sorry, you have been blocked). '
                           'Trang này không có bước xác minh để tiếp tục; đã giữ tiến độ.')
            if self._blocked(content):
                if getattr(self, 'headless', False):
                    raise Halt('Gặp trang chặn khi chạy headless. Chạy lại không có --headless '
                               'để kiểm tra/xác minh thủ công. Đã giữ tiến độ.')
                logging.warning('Cần thao tác thủ công trong cửa sổ trình duyệt tại %s', url)
                logging.warning('Trạng thái: CHỜ XÁC MINH; giới hạn %ss (0 = không giới hạn).', getattr(self, 'verify_timeout', 120))
                answer = self._wait_for_user()
                if answer.strip().lower() == 'q': raise Halt('Người dùng dừng; tiến độ được giữ.')
                # Flush any final navigation event after confirmation.
                self.page.wait_for_timeout(300)
                self.page.wait_for_load_state('domcontentloaded', timeout=15000)
                content = self._document()
            if not canonical(self.page.url) or identity(self.page.url) != identity(url):
                raise Halt('Trình duyệt không ở đúng trang yêu cầu; đã giữ tiến độ.')
            if self.status in (401, 429) or self._blocked(content):
                raise Halt('Trang vẫn bị chặn. Cần website cho phép truy cập; đã giữ tiến độ.')
            if self.status is None or not 200 <= self.status < 300:
                raise Halt(f'Trình duyệt trả HTTP {self.status}; đã giữ tiến độ.')
            if 'robots.txt' not in urlsplit(url).path:
                self._phase('ĐỢI NỘI DUNG TRANG — tối đa 15s')
                self.page.wait_for_selector('h1, a[href*="/gindex/"]', timeout=min(15000, timeout_ms))
                content = self._visible_document()
            self._phase('ĐỌC DỮ LIỆU TRANG')
            return content
        except Halt:
            raise
        except EOFError as exc:
            raise Halt('Chế độ browser cần terminal tương tác để xác minh thủ công.') from exc
        except Exception as exc:
            if self.page.is_closed():
                raise Halt('Cửa sổ/tab Chrome của chương trình đã đóng; đã giữ tiến độ. '
                           'Chạy lại và giữ cửa sổ đó mở.') from None
            if type(exc).__name__ == 'TimeoutError':
                raise PageLoadError('Trang tải quá thời hạn; đánh dấu lỗi để xử lý lại sau.') from exc
            raise Halt(f'Trình duyệt gián đoạn ({type(exc).__name__}); đã giữ tiến độ.') from exc

    def close(self):
        if getattr(self, '_closing', False): return
        self._closing = True
        try:
            page = getattr(self, 'page', None)
            actions = []
            if page is not None:
                actions += [lambda: page.unroute_all(behavior='ignoreErrors'),
                            lambda: page.remove_listener('response', self._response)]
            if self.context: actions.append(self.context.close)
            if self.runtime: actions.append(self.runtime.stop)
            for action in actions:
                try:
                    action()
                except (Exception, asyncio.CancelledError) as exc:
                    logging.debug('Phiên trình duyệt đã đóng trong lúc dọn dẹp (%s)', type(exc).__name__)
        finally:
            self.context = None
            self.runtime = None
            super().close()


class Store:
    def __init__(self, path):
        self.active_scope = None
        self.db = sqlite3.connect(path)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS tasks (
          id INTEGER PRIMARY KEY, task_key TEXT UNIQUE, url TEXT, kind TEXT,
          sector TEXT, category TEXT, depth INTEGER, status TEXT DEFAULT 'pending', error TEXT);
        CREATE TABLE IF NOT EXISTS companies (company_id TEXT PRIMARY KEY, data TEXT);
        CREATE TABLE IF NOT EXISTS memberships (company_id TEXT, sector TEXT, category TEXT,
          UNIQUE(company_id, sector, category));
        CREATE INDEX IF NOT EXISTS tasks_pending_order ON tasks(status,depth DESC,id);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        ''')
        if 'scope' not in {row[1] for row in self.db.execute('PRAGMA table_info(tasks)')}:
            self.db.execute("ALTER TABLE tasks ADD COLUMN scope TEXT NOT NULL DEFAULT ''")
        self.db.execute('CREATE INDEX IF NOT EXISTS tasks_scope_order ON tasks(scope,status,depth DESC,id)')
        self.db.commit()

    def restore_scope(self):
        row = self.db.execute("SELECT value FROM settings WHERE key='active_scope'").fetchone()
        self.active_scope = row[0] if row and row[0] else None

    def select_scope(self, url):
        url = category_url(url)
        self.active_scope = identity(url)
        self.db.executemany('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',
                            [('active_scope', self.active_scope), ('active_url', url)])
        self.db.commit()
        return url

    def counts(self):
        if self.active_scope is None:
            return dict(self.db.execute('SELECT status,count(*) FROM tasks GROUP BY status'))
        return dict(self.db.execute('SELECT status,count(*) FROM tasks WHERE scope=? GROUP BY status', (self.active_scope,)))

    def add(self, url, kind, sector='', category='', depth=0):
        # Listing pages retain their query (pagination); companies have a stable numeric ID.
        parts = [kind, url if kind == 'page' else identity(url), sector, category]
        if self.active_scope is not None: parts.append(self.active_scope)
        key = json.dumps(parts, ensure_ascii=False)
        self.db.execute('INSERT OR IGNORE INTO tasks(task_key,url,kind,sector,category,depth,scope) VALUES(?,?,?,?,?,?,?)', (key, url, kind, sector, category, depth, self.active_scope or ''))

    def next_pending(self):
        if self.active_scope is not None:
            return self.db.execute("SELECT id,url,kind,sector,category,depth FROM tasks WHERE scope=? AND status='pending' ORDER BY depth DESC,id ASC LIMIT 1", (self.active_scope,)).fetchone()
        return self.db.execute("SELECT id,url,kind,sector,category,depth FROM tasks WHERE status='pending' ORDER BY depth DESC,id ASC LIMIT 1").fetchone()

    def prepare(self, start=None, resume_only=False):
        count = sum(self.counts().values())
        if resume_only and not count:
            raise Halt('Chưa có tiến độ trong DB này. Dùng lệnh run --start URL để bắt đầu.')
        if start is None and count:
            logging.info('Dùng hàng đợi đã lưu, không thêm lại URL bắt đầu.')
            return self.next_pending()
        url = canonical(start or BASE)
        if not url: raise Halt('URL phải thuộc trangvangvietnam.com')
        path = urlsplit(url).path
        kind = 'company' if path.startswith('/listings/') else 'page' if path.startswith('/categories/') else 'sector' if path.startswith('/gindex/') else 'root'
        # An explicit start may refer to a previously discovered task with a
        # different sector label. Reuse that task instead of adding another seed.
        exists = self.db.execute('SELECT 1 FROM tasks WHERE kind=? AND url=? AND scope=? LIMIT 1', (kind, url, self.active_scope or '')).fetchone()
        if not exists:
            self.add(url, kind, url if kind == 'sector' else '', url if kind == 'page' else '')
            self.db.commit()
        return self.next_pending()

    def export(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        columns = FIELDS + ['sectors', 'categories', 'review_required']
        rows = []
        selected = None
        if self.active_scope is not None:
            selected = {}
            for url, sector, category in self.db.execute("SELECT url,sector,category FROM tasks WHERE scope=? AND kind='company' AND status='done'", (self.active_scope,)):
                selected.setdefault(identity(url), []).append((sector, category))
        records = self.db.execute('SELECT company_id,data FROM companies ORDER BY company_id') if selected is None else (
            row for key in sorted(selected) if (row := self.db.execute('SELECT company_id,data FROM companies WHERE company_id=?', (key,)).fetchone()))
        for company_id, raw in records:
            row = json.loads(raw)
            members = self.db.execute('SELECT sector,category FROM memberships WHERE company_id=?', (company_id,)).fetchall() if selected is None else selected[company_id]
            row['sectors'] = ' | '.join(dict.fromkeys(x[0] for x in members if x[0]))
            row['categories'] = ' | '.join(dict.fromkeys(x[1] for x in members if x[1]))
            rows.append(row)
        # Neutralize spreadsheet formulas in CSV and XLSX.
        def safe(value):
            value = str(value)
            return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
        with (directory / 'companies.csv').open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            writer.writerows([safe(row.get(k, '')) for k in columns] for row in rows)
        from openpyxl import Workbook
        book = Workbook()
        sheet = book.active
        sheet.title = 'Companies'
        sheet.append(columns)
        for row in rows: sheet.append([safe(row.get(k, '')) for k in columns])
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
        book.save(directory / 'companies.xlsx')
        logging.info('Đã xuất %s công ty | Phạm vi: %s | Thư mục: %s', len(rows), self.active_scope or 'tất cả', directory.resolve())


class RunLock:
    """One crawler process per SQLite file; OS releases the lock after a crash."""
    def __init__(self, db_path):
        self.path = str(Path(db_path).resolve()) + '.lock'
        self.handle = None

    def acquire(self):
        self.handle = open(self.path, 'a+b')
        try:
            self.handle.seek(0)
            if not self.handle.read(1):
                self.handle.write(b'0'); self.handle.flush()
            self.handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close(); self.handle = None
            raise Halt('Đã có tiến trình crawler đang dùng DB này. Dừng tiến trình đó trước khi chạy tiếp.') from None

    def close(self):
        if self.handle:
            try:
                self.handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            finally:
                self.handle.close(); self.handle = None


class LiveStats:
    """Read SQLite on a separate connection; never call Playwright from this thread."""
    def __init__(self, db_path, interval=15, scope=None):
        self.uri = Path(db_path).resolve().as_uri() + '?mode=ro'
        self.interval = interval
        self.scope = scope
        self.stopped = Event()
        self.guard = Lock()
        self.current = {'saved': 0, 'skipped': 0, 'url': '', 'sector': '', 'category': '', 'phase': 'CHUẨN BỊ'}
        self.started = time.monotonic()
        self.thread = None

    def update(self, **values):
        with self.guard: self.current.update(values)

    def report(self):
        with self.guard: current = dict(self.current)
        # This connection belongs only to the calling thread. Short read
        # transactions allow the main crawler to keep committing progress.
        db = sqlite3.connect(self.uri, uri=True, timeout=2)
        try:
            db.execute('BEGIN')
            counts = dict(db.execute('SELECT status,count(*) FROM tasks GROUP BY status')) if self.scope is None else dict(db.execute('SELECT status,count(*) FROM tasks WHERE scope=? GROUP BY status', (self.scope,)))
            total = db.execute('SELECT count(*) FROM companies').fetchone()[0]
            db.rollback()
        finally: db.close()
        elapsed = max(1, time.monotonic() - self.started)
        logging.info('THỐNG KÊ | Trạng thái: %s | Phạm vi: %s | Tổng kho: %s | Mới lượt này: %s | Bỏ qua: %s | Tác vụ xong: %s | Chờ: %s | Lỗi: %s | Đã chạy: %.0fs | Tốc độ: %.1f công ty mới/phút | Ngành: %s | Phân ngành: %s | URL: %s',
                     current['phase'], self.scope or 'toàn bộ hàng đợi',
                     total, current['saved'], current['skipped'], counts.get('done', 0), counts.get('pending', 0), counts.get('error', 0),
                     elapsed, current['saved'] * 60 / elapsed, current['sector'] or '-', current['category'] or '-', current['url'] or '-')

    def start(self):
        if not self.interval: return
        def watch():
            while not self.stopped.wait(self.interval):
                try: self.report()
                except sqlite3.Error: logging.warning('Chưa đọc được thống kê; sẽ thử ở lần cập nhật tiếp theo.')
        self.thread = Thread(target=watch, name='crawler-statistics', daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread: self.thread.join()


class LazyClient:
    """Open Chrome only when the next task actually needs a network request."""
    def __init__(self, factory):
        self.factory = factory
        self.client = None

    def get(self, url):
        if self.client is None: self.client = self.factory()
        return self.client.get(url)

    def close(self):
        if self.client is not None: self.client.close()


def next_pages(soup, url):
    current = urlsplit(url)
    params = parse_qs(current.query)
    current_number = int(next((params[k][0] for k in ('page', 'p', 'pageindex', 'pageIndex') if k in params and params[k][0].isdigit()), '1'))
    numbered = []
    explicit = []
    for a in soup.select('a[href]'):
        dest = canonical(a['href'], url)
        if not dest or dest == url or identity(dest) != identity(url): continue
        query = parse_qs(urlsplit(dest).query)
        if set(query) - {'page', 'p', 'pageindex', 'pageIndex'}: continue
        text = clean(a.get_text()).lower()
        number = next((int(query[k][0]) for k in ('page', 'p', 'pageindex', 'pageIndex') if k in query and query[k][0].isdigit()), None)
        if 'next' in a.get('rel', []) or text in ('sau', 'tiếp', 'tiếp theo', 'next', '›', '»', '>'):
            if number is None or number > current_number: explicit.append(dest)
        if text.isdigit() and number is not None and number > current_number:
            numbered.append((number, dest))
    if explicit: yield explicit[0]
    elif numbered: yield min(numbered)[1]


def crawl(store, client, limit, cache, observer=None, save_html=True, progress_every=1):
    done = 0
    saved = 0
    skipped = 0
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    while not limit or done < limit:
        task = store.next_pending()
        if not task: break
        task_id, url, kind, sector, category, depth = task
        logging.info('ĐANG XỬ LÝ | %s | Ngành: %s | Phân ngành: %s | %s', kind, sector or '-', category or '-', url)
        if observer: observer.update(url=url, sector=sector, category=category, phase='KIỂM TRA DỮ LIỆU ĐÃ CÓ')
        try:
            company_id = identity(url)
            existing = store.db.execute('SELECT data FROM companies WHERE company_id=?', (company_id,)).fetchone() if kind == 'company' else None
            if not existing:
                html = client.get(url)
                if save_html:
                    (cache / (hashlib.sha256(url.encode()).hexdigest() + '.html')).write_text(html, encoding='utf-8')
                soup = BeautifulSoup(html, 'html.parser')
            if kind == 'company':
                if not existing:
                    data = parse_company(soup, url)
                    store.db.execute('INSERT INTO companies VALUES(?,?)', (company_id, json.dumps(data, ensure_ascii=False)))
                store.db.execute('INSERT OR IGNORE INTO memberships VALUES(?,?,?)', (company_id, sector, category))
            elif kind == 'root':
                children = list(linked(soup, r'^/gindex/\d+', url))
                if not children: raise ValueError('Không tìm thấy lĩnh vực /gindex/; cần kiểm tra HTML')
                for dest, name in children: store.add(dest, 'sector', name, '', depth + 1)
            elif kind == 'sector':
                if soup.h1: sector = clean(soup.h1.get_text(' ', strip=True))
                children = list(linked(soup, r'^/categories/\d+', url))
                if not children: raise ValueError('Không tìm thấy phân ngành /categories/; cần kiểm tra HTML')
                for dest, name in children: store.add(dest, 'page', sector, name, depth + 1)
            elif kind == 'page':
                if soup.h1: category = clean(soup.h1.get_text(' ', strip=True))
                listing_scope = BeautifulSoup(''.join(str(n) for n in soup.select('h2.tvx-cn')), 'html.parser') if soup.select_one('h2.tvx-cn') else soup
                children = list(linked(listing_scope, r'^/listings/\d+', url))
                if not children: raise ValueError('Không tìm thấy công ty /listings/; cần kiểm tra HTML')
                for dest, name in children: store.add(dest, 'company', sector, category, depth + 1)
                # Pagination outranks sibling categories but follows this page's companies.
                for dest in next_pages(soup, url): store.add(dest, 'page', sector, category, depth + 0.5)
            store.db.execute("UPDATE tasks SET status='done',error=NULL WHERE id=?", (task_id,))
            store.db.commit()
            done += 1
            if kind == 'company':
                if existing:
                    skipped += 1
                    data = json.loads(existing[0])
                    logging.info('BỎ QUA ĐÃ CÓ | %s | %s | chỉ bổ sung quan hệ ngành', company_id, data['name'])
                else:
                    saved += 1
                    logging.info('ĐÃ LƯU | %s | %s | Địa chỉ: %s | SĐT: %s | Email: %s | Website: %s | Cần kiểm tra: %s',
                                 company_id, data['name'], data['address'] or '-', data['phones'] or '-',
                                 data['emails'] or '-', data['websites'] or '-', data['review_required'])
            if observer: observer.update(saved=saved, skipped=skipped, sector=sector, category=category, phase='ĐÃ XỬ LÝ — CHỌN TRANG TIẾP THEO')
            if done % progress_every == 0:
                counts = store.counts()
                total = store.db.execute('SELECT count(*) FROM companies').fetchone()[0]
                logging.info('TIẾN ĐỘ | Tổng: %s công ty | Mới lượt này: %s | Bỏ qua lượt này: %s | Trang chờ: %s | Trang lỗi: %s | Ngành: %s | Phân ngành: %s',
                             total, saved, skipped, counts.get('pending', 0), counts.get('error', 0), sector or '-', category or '-')
        except Halt:
            store.db.rollback()
            raise
        except Exception as exc:
            store.db.rollback()
            store.db.execute("UPDATE tasks SET status='error',error=? WHERE id=?", (str(exc), task_id))
            store.db.commit()
            if observer: observer.update(phase='TRANG LỖI — CHUYỂN TÁC VỤ TIẾP THEO')
            if isinstance(exc, PageLoadError): logging.warning('Lỗi trang %s: %s', url, exc)
            else: logging.exception('Lỗi trang %s; đánh dấu error', url)
    return done


def main(browser_factory=None, store_factory=None):
    parser = argparse.ArgumentParser(description='Thu thập Trang Vàng có lưu tiến độ')
    parser.add_argument('command', nargs='?', default='select', choices=['select', 'run', 'resume', 'export', 'status', 'retry-errors'])
    parser.add_argument('--start', help='URL bắt đầu; nếu bỏ qua thì tiếp tục hàng đợi cũ, DB mới bắt đầu ở trang chủ')
    parser.add_argument('--category', help='Chỉ quét danh mục /categories/ hoặc lĩnh vực /gindex/ này; select sẽ hỏi nếu bỏ qua')
    parser.add_argument('--db', default='data/crawler.sqlite')
    parser.add_argument('--out', help='Thư mục xuất; mặc định cạnh DB, tách theo danh mục đang chọn')
    parser.add_argument('--delay', type=float, default=5)
    parser.add_argument('--browser', action='store_true', help='Mở trình duyệt có giao diện, xác minh thủ công nếu cần')
    parser.add_argument('--browser-channel', choices=['chrome', 'msedge'], help='Dùng Chrome hoặc Edge đã cài; mặc định Chromium')
    parser.add_argument('--profile', help='Thư mục hồ sơ riêng; mặc định browser-profile cạnh DB')
    parser.add_argument('--stealth', action='store_true', help='Bật playwright-stealth 2.x (cần --browser)')
    parser.add_argument('--headless', action='store_true', help='Ẩn trình duyệt; dừng nếu cần xác minh')
    parser.add_argument('--proxy-env', metavar='VARIABLE', help='Tên biến môi trường chứa URL proxy (không nhập mật khẩu vào lệnh)')
    parser.add_argument('--jitter', type=float, default=0, help='Chờ thêm ngẫu nhiên 0..N giây trong chế độ browser')
    parser.add_argument('--max-pages', type=int, default=0, help='0 = không giới hạn; tính cả trang chi tiết')
    parser.add_argument('--stats-every', type=float, default=15, help='In thống kê mỗi N giây; 0 = chỉ in sau mỗi tác vụ')
    parser.add_argument('--verify-timeout', type=float, default=120, help='Chờ xác minh tối đa N giây; 0 = chờ không giới hạn')
    parser.add_argument('--page-timeout', type=float, default=45, help='Giới hạn tải một trang (giây); quá hạn ghi lỗi và chuyển trang khác')
    parser.add_argument('--no-html-cache', action='store_true', help='Không lưu bản HTML cho mỗi trang; dữ liệu và tiến độ vẫn commit vào SQLite')
    parser.add_argument('--progress-every', type=int, default=1, help='In tổng kết sau N tác vụ; log công ty và thống kê định kỳ vẫn hoạt động')
    args = parser.parse_args()
    if args.command == 'select':
        args.browser = True
        args.browser_channel = args.browser_channel or 'chrome'
        args.stealth = True
    if args.start and args.category: parser.error('Chỉ dùng một trong --start hoặc --category')
    if args.category and args.command not in ('select', 'run'): parser.error('--category dùng với select hoặc run')
    if args.verify_timeout != 0 and not 1 <= args.verify_timeout <= 3600: parser.error('--verify-timeout phải bằng 0 hoặc nằm trong 1..3600 giây')
    if not 1 <= args.page_timeout <= 300: parser.error('--page-timeout phải nằm trong 1..300 giây')
    if args.max_pages < 0: parser.error('--max-pages phải >= 0')
    if not 1 <= args.progress_every <= 1000: parser.error('--progress-every phải nằm trong 1..1000')
    if args.command == 'resume' and args.start: parser.error('resume tiếp tục hàng đợi cũ; không dùng --start')
    if args.stats_every != 0 and not 1 <= args.stats_every <= 3600: parser.error('--stats-every phải bằng 0 hoặc nằm trong 1..3600 giây')
    if not args.browser and (args.stealth or args.headless or args.proxy_env or args.jitter):
        parser.error('--stealth/--headless/--proxy-env/--jitter cần --browser')
    if args.jitter < 0 or args.jitter > 300: parser.error('--jitter phải nằm trong 0..300 giây')
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    log_handlers = [logging.StreamHandler(), logging.FileHandler(str(Path(args.db).with_suffix('.log')), encoding='utf-8')]
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', handlers=log_handlers)
    store = (store_factory or Store)(args.db)
    code = 0
    client = None
    run_lock = None
    observer = None
    export_on_exit = args.command not in ('select', 'run', 'resume', 'retry-errors')
    try:
        if args.command in ('select', 'run', 'resume', 'retry-errors'):
            run_lock = RunLock(args.db)
            run_lock.acquire()
            export_on_exit = True
        store.restore_scope()
        if args.command == 'select' or args.category:
            previous = store.db.execute("SELECT value FROM settings WHERE key='active_url'").fetchone()
            chosen = args.category or args.start or prompt_category(previous[0] if previous else None)
            args.start = store.select_scope(chosen)
            logging.info('CHỈ QUÉT DANH MỤC | %s | %s', store.active_scope, args.start)
        elif args.start:
            store.active_scope = None
            store.db.execute("DELETE FROM settings WHERE key IN ('active_scope','active_url')")
            store.db.commit()
        if args.command in ('select', 'run', 'resume'):
            following = store.prepare(args.start, resume_only=args.command == 'resume')
            if following:
                logging.info('TIẾP TỤC TỪ | %s | %s', following[2], following[1])
            else:
                logging.info('Không còn tác vụ pending. Không cần mở trình duyệt.')
            proxy = None
            if args.proxy_env:
                value = os.environ.get(args.proxy_env)
                if not value: raise Halt('Biến môi trường proxy chưa được cấu hình hoặc đang rỗng.')
                proxy = proxy_options(value)
            profile_tag = ('browser-profile-proxy-' + hashlib.sha256(json.dumps(proxy, sort_keys=True).encode()).hexdigest()[:12]) if proxy else 'browser-profile'
            profile = args.profile or Path(args.db).parent / profile_tag
            client = LazyClient(lambda: (browser_factory or BrowserClient)(args.delay, profile, args.browser_channel,
                                    stealth=args.stealth, proxy=proxy, headless=args.headless, jitter=args.jitter,
                                    verify_timeout=args.verify_timeout, page_timeout=args.page_timeout, on_phase=observer.update)
                                if args.browser else Client(args.delay))
            observer = LiveStats(args.db, args.stats_every, scope=store.active_scope)
            observer.report()
            observer.start()
            crawl(store, client, args.max_pages, Path(args.db).parent / 'html', observer=observer,
                  save_html=not args.no_html_cache, progress_every=args.progress_every)
            if store.next_pending():
                observer.update(phase='ĐÃ ĐẠT GIỚI HẠN LƯỢT CHẠY')
                logging.info('Đã đạt giới hạn lượt chạy. Chạy lại cùng lệnh hoặc dùng resume để tiếp tục.')
            elif store.counts().get('error', 0):
                observer.update(phase='KẾT THÚC LƯỢT — CÒN TRANG LỖI CẦN KIỂM TRA')
                logging.warning('Hết hàng đợi pending nhưng còn trang lỗi. Kiểm tra status, rồi dùng retry-errors để thử lại.')
            else:
                observer.update(phase='HOÀN TẤT HÀNG ĐỢI ĐANG CHỌN')
                logging.info('HOÀN TẤT | Đã xử lý hết hàng đợi.')
        elif args.command == 'retry-errors':
            if store.active_scope is None:
                store.db.execute("UPDATE tasks SET status='pending',error=NULL WHERE status='error'")
            else:
                store.db.execute("UPDATE tasks SET status='pending',error=NULL WHERE status='error' AND scope=?", (store.active_scope,))
            store.db.commit()
        elif args.command == 'status':
            print('scope:', store.active_scope or 'toàn bộ hàng đợi')
            print(store.counts())
            print('companies:', store.db.execute('SELECT count(*) FROM companies').fetchone()[0])
            following = store.next_pending()
            print('next_url:', following[1] if following else 'Không còn trang chờ')
    except (Halt, KeyboardInterrupt) as exc:
        if observer: observer.update(phase='ĐÃ TẠM DỪNG — ' + str(exc))
        logging.warning('Đã tạm dừng: %s', exc)
        code = 2
    finally:
        if observer:
            observer.stop()
            try: observer.report()
            except sqlite3.Error: logging.warning('Không đọc được thống kê cuối phiên.')
        try:
            if client: client.close()
        finally:
            try:
                output = Path(args.out) if args.out else Path(args.db).parent / 'export'
                if not args.out and store.active_scope: output /= store.active_scope.replace(':', '_')
                if export_on_exit: store.export(output)
            finally:
                try:
                    store.db.close()
                    if run_lock: run_lock.close()
                finally:
                    for handler in log_handlers:
                        logging.getLogger().removeHandler(handler)
                        handler.close()
    return code

if __name__ == '__main__':
    raise SystemExit(main())
