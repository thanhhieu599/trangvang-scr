import types
import unittest
from unittest.mock import Mock, patch

from crawler import BrowserClient, Halt, proxy_options
import test_browser


class OptionTests(unittest.TestCase):
    def test_proxy_credentials_are_separate(self):
        proxy = proxy_options('http://alice:p%40ss@proxy.example:8000')
        self.assertEqual(proxy, {'server': 'http://proxy.example:8000', 'username': 'alice', 'password': 'p@ss'})

    def test_invalid_proxy_never_echoes_secret(self):
        for value in ('https://alice:secret@proxy.example:bad', 'ftp://alice:secret@proxy.example:80',
                      'socks5://alice:secret@proxy.example:1080', 'http://proxy.example:80/?secret=1'):
            with self.assertRaises(Halt) as caught: proxy_options(value)
            self.assertNotIn('secret', str(caught.exception))
            self.assertNotIn('alice', str(caught.exception))

    def test_ipv6_proxy(self):
        self.assertEqual(proxy_options('socks5://[::1]:1080'), {'server': 'socks5://[::1]:1080'})

    def test_headless_stops_without_input(self):
        client = test_browser.BrowserTests().client(403, 'challenge-platform')
        client.headless = True
        with patch('builtins.input') as prompt:
            with self.assertRaisesRegex(Halt, 'headless'): client.request('https://trangvangvietnam.com/')
        prompt.assert_not_called()

    def test_jitter_adds_to_minimum_delay(self):
        client = test_browser.BrowserTests().client()
        client.jitter = 2
        client.delay = 5
        client.last = 98
        with patch('crawler.time.monotonic', return_value=100), patch('crawler.time.sleep') as sleep, patch('crawler.random.uniform', return_value=2):
            client.request('https://trangvangvietnam.com/')
        sleep.assert_called_once_with(5)

    def test_stealth_and_proxy_launch_options(self):
        runtime = Mock()
        context = runtime.chromium.launch_persistent_context.return_value
        context.pages = []
        plugin = Mock()
        factory = Mock(return_value=plugin)
        api = types.ModuleType('playwright.sync_api')
        api.sync_playwright = Mock()
        api.sync_playwright.return_value.start.return_value = runtime
        stealth = types.ModuleType('playwright_stealth')
        stealth.Stealth = factory
        with patch.dict('sys.modules', {'playwright.sync_api': api, 'playwright_stealth': stealth}):
            client = BrowserClient(stealth=True, proxy={'server': 'http://proxy.example:8000'}, headless=True)
        options = runtime.chromium.launch_persistent_context.call_args.kwargs
        self.assertEqual(options['proxy']['server'], 'http://proxy.example:8000')
        self.assertTrue(options['headless'])
        self.assertNotIn('user_agent', options)
        plugin.apply_stealth_sync.assert_called_once_with(context)
        client.close()


if __name__ == '__main__': unittest.main()
