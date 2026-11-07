"""Sequential, resumable crawler for authorized public Trang Vang pages."""
import argparse
import csv
import hashlib
import json
import logging
import os
import random
import re
import sqlite3
import time
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


def linked(soup, pattern, base):
    seen = set()
    for a in soup.select('a[href]'):
        url = canonical(a['href'], base)
        if url and re.search(pattern, urlsplit(url).path) and identity(url) not in seen:
            seen.add(identity(url))
            yield url, clean(a.get_text(' ', strip=True))


def parse_company(html, url):
    soup = BeautifulSoup(html, 'html.parser')
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
                 stealth=False, proxy=None, headless=False, jitter=0):
        super().__init__(delay)
        self.runtime = None
        self.context = None
        self.jitter = jitter
        self.headless = headless
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
        request = route.request
        if (request.is_navigation_request() and request.frame == self.page.main_frame
                and not canonical(request.url)):
            route.abort()
        else:
            route.continue_()

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
        return self.status == 403 or any(marker in content.lower() for marker in (
            'cf-chl-', 'challenge-platform', 'sorry, you have been blocked',
            'verify you are human', 'g-recaptcha', 'hcaptcha-container',
            '<title>just a moment', '<title>attention required'))

    def request(self, url):
        try:
            time.sleep(max(0, self.delay - (time.monotonic() - self.last))
                       + random.uniform(0, getattr(self, 'jitter', 0)))
            self.last = time.monotonic()
            self.status = None
            self.content_type = ''
            self.page.goto(url, wait_until='domcontentloaded', timeout=60000)
            content = self._document()
            if self.status in (401, 429):
                raise Halt(f'Website trả HTTP {self.status}; đã giữ tiến độ, không tiếp tục gửi yêu cầu.')
            if self._blocked(content):
                if getattr(self, 'headless', False):
                    raise Halt('Gặp trang chặn khi chạy headless. Chạy lại không có --headless '
                               'để kiểm tra/xác minh thủ công. Đã giữ tiến độ.')
                logging.warning('Cần thao tác thủ công trong cửa sổ trình duyệt tại %s', url)
                answer = input('Nếu website cho phép, hoàn tất xác minh trong trình duyệt. '
                               'Sau khi trang thật đã hiện, quay lại đây nhấn Enter; nhập q để dừng: ')
                if answer.strip().lower() == 'q': raise Halt('Người dùng dừng; tiến độ được giữ.')
                # Pump browser events after the user returns so the latest main-document
                # response replaces the challenge response before inspecting the page.
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
                self.page.wait_for_selector('h1, a[href*="/gindex/"]', timeout=15000)
                content = self._visible_document()
            return content
        except Halt:
            raise
        except EOFError as exc:
            raise Halt('Chế độ browser cần terminal tương tác để xác minh thủ công.') from exc
        except Exception as exc:
            raise Halt(f'Trình duyệt gián đoạn ({type(exc).__name__}); đã giữ tiến độ.') from exc

    def close(self):
        try:
            if self.context: self.context.close()
        finally:
            try:
                if self.runtime: self.runtime.stop()
            finally:
                super().close()


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS tasks (
          id INTEGER PRIMARY KEY, task_key TEXT UNIQUE, url TEXT, kind TEXT,
          sector TEXT, category TEXT, depth INTEGER, status TEXT DEFAULT 'pending', error TEXT);
        CREATE TABLE IF NOT EXISTS companies (company_id TEXT PRIMARY KEY, data TEXT);
        CREATE TABLE IF NOT EXISTS memberships (company_id TEXT, sector TEXT, category TEXT,
          UNIQUE(company_id, sector, category));
        ''')
        self.db.commit()

    def add(self, url, kind, sector='', category='', depth=0):
        # Listing pages retain their query (pagination); companies have a stable numeric ID.
        key = json.dumps([kind, url if kind == 'page' else identity(url), sector, category], ensure_ascii=False)
        self.db.execute('INSERT OR IGNORE INTO tasks(task_key,url,kind,sector,category,depth) VALUES(?,?,?,?,?,?)', (key, url, kind, sector, category, depth))

    def export(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        columns = FIELDS + ['sectors', 'categories', 'review_required']
        rows = []
        for company_id, raw in self.db.execute('SELECT company_id,data FROM companies ORDER BY company_id'):
            row = json.loads(raw)
            members = self.db.execute('SELECT sector,category FROM memberships WHERE company_id=?', (company_id,)).fetchall()
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
        logging.info('Đã xuất %s công ty', len(rows))


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


def crawl(store, client, limit, cache):
    done = 0
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    while not limit or done < limit:
        task = store.db.execute("SELECT id,url,kind,sector,category,depth FROM tasks WHERE status='pending' ORDER BY depth DESC,id ASC LIMIT 1").fetchone()
        if not task: break
        task_id, url, kind, sector, category, depth = task
        logging.info('%s %s', kind, url)
        try:
            company_id = identity(url)
            existing = store.db.execute('SELECT 1 FROM companies WHERE company_id=?', (company_id,)).fetchone() if kind == 'company' else None
            if not existing:
                html = client.get(url)
                (cache / (hashlib.sha256(url.encode()).hexdigest() + '.html')).write_text(html, encoding='utf-8')
                soup = BeautifulSoup(html, 'html.parser')
            if kind == 'company':
                if not existing:
                    data = parse_company(html, url)
                    store.db.execute('INSERT INTO companies VALUES(?,?)', (company_id, json.dumps(data, ensure_ascii=False)))
                store.db.execute('INSERT OR IGNORE INTO memberships VALUES(?,?,?)', (company_id, sector, category))
            elif kind == 'root':
                children = list(linked(soup, r'^/gindex/\d+', url))
                if not children: raise ValueError('Không tìm thấy lĩnh vực /gindex/; cần kiểm tra HTML')
                for dest, name in children: store.add(dest, 'sector', name, '', depth + 1)
            elif kind == 'sector':
                children = list(linked(soup, r'^/categories/\d+', url))
                if not children: raise ValueError('Không tìm thấy phân ngành /categories/; cần kiểm tra HTML')
                for dest, name in children: store.add(dest, 'page', sector, name, depth + 1)
            elif kind == 'page':
                listing_scope = BeautifulSoup(''.join(str(n) for n in soup.select('h2.tvx-cn')), 'html.parser') if soup.select_one('h2.tvx-cn') else soup
                children = list(linked(listing_scope, r'^/listings/\d+', url))
                if not children: raise ValueError('Không tìm thấy công ty /listings/; cần kiểm tra HTML')
                for dest, name in children: store.add(dest, 'company', sector, category, depth + 1)
                # Same depth: complete companies on this page before subsequent pages.
                for dest in next_pages(soup, url): store.add(dest, 'page', sector, category, depth)
            store.db.execute("UPDATE tasks SET status='done',error=NULL WHERE id=?", (task_id,))
            store.db.commit()
            done += 1
        except Halt:
            store.db.rollback()
            raise
        except Exception as exc:
            store.db.rollback()
            store.db.execute("UPDATE tasks SET status='error',error=? WHERE id=?", (str(exc), task_id))
            store.db.commit()
            logging.exception('Lỗi trang %s; đánh dấu error', url)
    return done


def main():
    parser = argparse.ArgumentParser(description='Thu thập Trang Vàng có lưu tiến độ')
    parser.add_argument('command', choices=['run', 'export', 'status', 'retry-errors'])
    parser.add_argument('--start', default=BASE)
    parser.add_argument('--db', default='data/crawler.sqlite')
    parser.add_argument('--out', default='data/export')
    parser.add_argument('--delay', type=float, default=5)
    parser.add_argument('--browser', action='store_true', help='Mở trình duyệt có giao diện, xác minh thủ công nếu cần')
    parser.add_argument('--browser-channel', choices=['chrome', 'msedge'], help='Dùng Chrome hoặc Edge đã cài; mặc định Chromium')
    parser.add_argument('--profile', help='Thư mục hồ sơ riêng; mặc định browser-profile cạnh DB')
    parser.add_argument('--stealth', action='store_true', help='Bật playwright-stealth 2.x (cần --browser)')
    parser.add_argument('--headless', action='store_true', help='Ẩn trình duyệt; dừng nếu cần xác minh')
    parser.add_argument('--proxy-env', metavar='VARIABLE', help='Tên biến môi trường chứa URL proxy (không nhập mật khẩu vào lệnh)')
    parser.add_argument('--jitter', type=float, default=0, help='Chờ thêm ngẫu nhiên 0..N giây trong chế độ browser')
    parser.add_argument('--max-pages', type=int, default=0, help='0 = không giới hạn; tính cả trang chi tiết')
    args = parser.parse_args()
    if args.max_pages < 0: parser.error('--max-pages phải >= 0')
    if not args.browser and (args.stealth or args.headless or args.proxy_env or args.jitter):
        parser.error('--stealth/--headless/--proxy-env/--jitter cần --browser')
    if args.jitter < 0 or args.jitter > 300: parser.error('--jitter phải nằm trong 0..300 giây')
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', handlers=[logging.StreamHandler(), logging.FileHandler(str(Path(args.db).with_suffix('.log')), encoding='utf-8')])
    store = Store(args.db)
    code = 0
    client = None
    try:
        if args.command == 'run':
            url = canonical(args.start)
            if not url: parser.error('URL phải thuộc trangvangvietnam.com')
            path = urlsplit(url).path
            kind = 'company' if path.startswith('/listings/') else 'page' if path.startswith('/categories/') else 'sector' if path.startswith('/gindex/') else 'root'
            store.add(url, kind, url if kind == 'sector' else '', url if kind == 'page' else '')
            store.db.commit()
            proxy = None
            if args.proxy_env:
                value = os.environ.get(args.proxy_env)
                if not value: raise Halt('Biến môi trường proxy chưa được cấu hình hoặc đang rỗng.')
                proxy = proxy_options(value)
            profile_tag = ('browser-profile-proxy-' + hashlib.sha256(json.dumps(proxy, sort_keys=True).encode()).hexdigest()[:12]) if proxy else 'browser-profile'
            profile = args.profile or Path(args.db).parent / profile_tag
            client = (BrowserClient(args.delay, profile, args.browser_channel,
                                    stealth=args.stealth, proxy=proxy, headless=args.headless, jitter=args.jitter)
                      if args.browser else Client(args.delay))
            crawl(store, client, args.max_pages, Path(args.db).parent / 'html')
        elif args.command == 'retry-errors':
            store.db.execute("UPDATE tasks SET status='pending',error=NULL WHERE status='error'")
            store.db.commit()
        elif args.command == 'status':
            print(dict(store.db.execute('SELECT status,count(*) FROM tasks GROUP BY status')))
            print('companies:', store.db.execute('SELECT count(*) FROM companies').fetchone()[0])
    except (Halt, KeyboardInterrupt) as exc:
        logging.warning('Đã tạm dừng: %s', exc)
        code = 2
    finally:
        try:
            if client: client.close()
        finally:
            try:
                store.export(args.out)
            finally:
                store.db.close()
    return code

if __name__ == '__main__':
    raise SystemExit(main())
