"""V2 performance profile. Same scoped queue, transactions and verification flow."""
import argparse
import functools
import sys
from urllib.parse import urlsplit

import crawler as base

VERSION = '2.0.0'
AD_HOSTS = ('doubleclick.net', 'googlesyndication.com', 'googleadservices.com',
            'googletagmanager.com', 'google-analytics.com')
CHALLENGE_HOSTS = ('challenges.cloudflare.com', 'recaptcha.net', 'hcaptcha.com')


def matches(host, domains):
    return any(host == domain or host.endswith('.' + domain) for domain in domains)


def block_resource(url, resource_type, mode='balanced', company_page=False, challenge_active=False):
    if mode == 'full' or challenge_active or resource_type == 'document':
        return False
    parsed = urlsplit(url)
    host, path = (parsed.hostname or '').lower(), parsed.path.lower()
    if matches(host, CHALLENGE_HOSTS) or '/cdn-cgi/' in path or '/recaptcha/' in path or '/turnstile/' in path:
        return False
    if matches(host, AD_HOSTS):
        return True
    if resource_type == 'media':
        return True
    # Balanced preserves images/fonts; lean is opt-in and limited to details.
    return mode == 'lean' and company_page and resource_type in ('image', 'font')


class FastBrowser(base.BrowserClient):
    def __init__(self, *args, assets='balanced', **kwargs):
        self.assets = assets
        self.company_page = False
        self.challenge_active = False
        self.resources_skipped = 0
        super().__init__(*args, **kwargs)

    def request(self, url):
        self.company_page = urlsplit(url).path.startswith('/listings/')
        self.challenge_active = False
        return super().request(url)

    def _phase(self, text):
        if text.startswith('CHỜ XÁC MINH'):
            self.challenge_active = True
        super()._phase(text)

    def _route(self, route):
        try:
            request = route.request
            if not self._closing and block_resource(request.url, request.resource_type, self.assets,
                    self.company_page, self.challenge_active or getattr(self, 'status', None) in (401,403,429)):
                self.resources_skipped += 1
                route.abort()
                return
        except base.asyncio.CancelledError:
            return
        except Exception:
            if self._closing or self.page.is_closed(): return
            raise
        super()._route(route)

    def close(self):
        if not getattr(self, '_closing', False):
            base.logging.info('V2 | Tài nguyên phụ đã bỏ qua: %s | Chế độ: %s', self.resources_skipped, self.assets)
        super().close()


class FastStore(base.Store):
    def __init__(self, path):
        super().__init__(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        # Retain durable per-task commits, rather than trading data safety for speed.
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.execute('PRAGMA cache_size=-16384')


def run(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--v2-assets', choices=['balanced','lean','full'], default='balanced')
    parser.add_argument('--save-html', action='store_true')
    parser.add_argument('--version', action='store_true')
    args, rest = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    if args.version:
        print('Trang Vang crawler v' + VERSION)
        return 0
    if '--help' in rest or '-h' in rest:
        print('V2 options: --v2-assets balanced|lean|full; --save-html; --version\n')
    def option_present(name):
        return any(value == name or value.startswith(name+'=') for value in rest)
    command = next((v for v in rest if v in ('select','run','resume','status','export','retry-errors')), 'select')
    if command in ('select','run','resume'):
        if not option_present('--browser'): rest.append('--browser')
        if not option_present('--browser-channel'): rest += ['--browser-channel','chrome']
        if not option_present('--stealth'): rest.append('--stealth')
    if not args.save_html and not option_present('--no-html-cache'):
        rest.append('--no-html-cache')
    if not option_present('--progress-every'):
        rest += ['--progress-every','10']
    if not option_present('--stats-every'):
        rest += ['--stats-every','10']
    label = {'balanced':'cân bằng','lean':'nhẹ','full':'tải đầy đủ'}[args.v2_assets]
    print(f'TRANG VÀNG v{VERSION} | chế độ {label} | quét tuần tự, giữ tiến độ')
    original_argv = sys.argv
    try:
        sys.argv = ['crawler_v2.py', *rest]
        return base.main(browser_factory=functools.partial(FastBrowser, assets=args.v2_assets), store_factory=FastStore)
    finally:
        sys.argv = original_argv


if __name__ == '__main__':
    raise SystemExit(run())
