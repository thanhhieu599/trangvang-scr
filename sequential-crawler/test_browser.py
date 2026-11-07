import asyncio
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.robotparser import RobotFileParser
from crawler import BASE, BrowserClient, Client, Halt


class BrowserTests(unittest.TestCase):
    def client(self, status=200, content='<h1>Company</h1>'):
        client = BrowserClient.__new__(BrowserClient)
        Client.__init__(client)
        client.page = Mock()
        client.page.url = BASE
        client.page.is_closed.return_value = False
        client._closing = False
        client.runtime = None
        client.context = None
        client.content_type = 'text/html'
        client.status = status
        def navigate(*args, **kwargs):
            client.status = status
            client.content_type = 'text/html'
        client.page.goto.side_effect = navigate
        client.page.content.return_value = content
        client.page.evaluate.return_value = content
        return client

    def test_manual_verification_then_continue(self):
        client = self.client(403)
        client.page.content.side_effect = ['challenge-platform', '<h1>Home</h1>', '<h1>Home</h1>']
        client.page.wait_for_timeout.side_effect = lambda _: setattr(client, 'status', 200)
        client.page.evaluate.return_value = '<h1>Home</h1>'
        with patch('builtins.input', return_value='') as prompt:
            self.assertEqual(client.request(BASE), '<h1>Home</h1>')
        prompt.assert_called_once()
        client.page.goto.assert_called_once()

    def test_still_blocked_stops_after_one_prompt(self):
        client = self.client(403, 'challenge-platform')
        with patch('builtins.input', return_value='') as prompt:
            with self.assertRaises(Halt): client.request(BASE)
        prompt.assert_called_once()
        client.page.goto.assert_called_once()

    def test_rate_limit_does_not_prompt(self):
        client = self.client(429)
        with patch('builtins.input') as prompt:
            with self.assertRaises(Halt): client.request(BASE)
        prompt.assert_not_called()
        client.page.goto.assert_called_once()

    def test_user_can_stop(self):
        client = self.client(403)
        with patch('builtins.input', return_value='q'):
            with self.assertRaisesRegex(Halt, 'Người dùng dừng'): client.request(BASE)

    def test_noninteractive_terminal_stops(self):
        client = self.client(403)
        with patch('builtins.input', side_effect=EOFError):
            with self.assertRaisesRegex(Halt, 'terminal tương tác'): client.request(BASE)

    def test_plain_text_robots_not_wrapped_in_html(self):
        client = self.client()
        client.content_type = 'text/plain; charset=utf-8'
        client.page.locator.return_value.inner_text.return_value = 'User-agent: *\nDisallow: /private/'
        self.assertTrue(client._document().startswith('User-agent:'))
        client.page.content.assert_not_called()

    def test_browser_respects_disallow(self):
        client = self.client()
        client.robots = RobotFileParser()
        client.robots.parse(['User-agent: *', 'Disallow: /'])
        with self.assertRaisesRegex(Halt, 'robots.txt'): client.get(BASE)
        client.page.goto.assert_not_called()

    def test_wrong_page_is_not_parsed(self):
        client = self.client()
        client.page.url = 'https://example.test/'
        with self.assertRaisesRegex(Halt, 'đúng trang'): client.request(BASE)

    def test_input_wait_keeps_browser_events_running(self):
        client = self.client(403)
        ready = threading.Event()
        def terminal(_):
            if not ready.wait(2): raise AssertionError('Browser events stopped during input')
            return ''
        client.page.wait_for_timeout.side_effect = lambda _: ready.set()
        with patch('builtins.input', side_effect=terminal):
            self.assertEqual(client._wait_for_user(), '')
        client.page.wait_for_timeout.assert_called()

    def test_hard_block_does_not_wait_for_enter(self):
        client = self.client(403, 'Sorry, you have been blocked')
        with patch('builtins.input') as prompt:
            with self.assertRaisesRegex(Halt, 'Cloudflare từ chối'): client.request(BASE)
        prompt.assert_not_called()

    def test_closed_page_has_clear_message(self):
        client = self.client(403)
        client.page.is_closed.return_value = True
        with patch('builtins.input', return_value=''):
            with self.assertRaisesRegex(Halt, 'Chrome.*đã đóng'): client._wait_for_user()

    def test_cleanup_continues_after_closed_context(self):
        client = self.client()
        context, runtime = Mock(), Mock()
        client.context, client.runtime = context, runtime
        client.page.unroute_all.side_effect = RuntimeError('already closed')
        context.close.side_effect = RuntimeError('already closed')
        client.close()
        runtime.stop.assert_called_once()
        client.close()
        runtime.stop.assert_called_once()

    def test_cancelled_route_is_expected_during_shutdown(self):
        client = self.client()
        route = Mock()
        route.request.is_navigation_request.return_value = False
        route.continue_.side_effect = asyncio.CancelledError()
        client._route(route)


if __name__ == '__main__': unittest.main()
