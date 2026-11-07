import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from bs4 import BeautifulSoup
from crawler import BASE, Client, Halt, Store, canonical, crawl, next_pages, parse_company

COMPANY = BASE + 'listings/12/example.html'
ROOT = '<a href="/gindex/7/chem">Chem</a><a href="/gindex/8/pack">Pack</a>'
CONTACT = '''<article><h1>Example Ltd</h1><div itemprop="address">123 Main Street</div>
<a href="tel:0123456789">0123456789</a><a href="mailto:info@example.test">Email</a>
<a href="https://example.test">www.example.test</a></article>
<aside><a href="mailto:advert@example.test">Advertisement</a></aside>'''

class Tests(unittest.TestCase):
    def test_company_scoping(self):
        d = parse_company(CONTACT, COMPANY)
        self.assertEqual(d['emails'], 'info@example.test')
        self.assertEqual(d['phones'], '0123456789')
        self.assertEqual(d['address'], '123 Main Street')
        self.assertEqual(d['websites'], 'https://example.test')
        self.assertFalse(d['review_required'])

    def test_jsonld(self):
        doc = '<h1>Example</h1><script type="application/ld+json">' + json.dumps({'@type':'Organization','name':'Example','telephone':'123','address':{'streetAddress':'A'},'email':'a@example.test','url':'https://example.test'}) + '</script>'
        self.assertEqual(parse_company(doc, COMPANY)['address'], 'A')

    def test_pagination_and_domain(self):
        url = BASE + 'categories/1/a.html'
        soup = BeautifulSoup('<a href="?page=2">2</a><a href="?province=2">Hanoi</a><a href="https://evil.test/">3</a>', 'html.parser')
        self.assertEqual(list(next_pages(soup, url)), [url+'?page=2'])
        self.assertIsNone(canonical('https://evil.test'))

    def test_depth_resume_dedup(self):
        pages = {BASE:ROOT,
            BASE+'gindex/7/chem':'<a href="/categories/1/a.html">A</a><a href="/categories/2/b.html">B</a>',
            BASE+'gindex/8/pack':'<a href="/categories/3/c.html">C</a>',
            COMPANY:CONTACT}
        for n in range(1,4): pages[BASE+f'categories/{n}/{chr(96+n)}.html'] = '<a href="'+COMPANY+'">Example</a>'
        client = Mock()
        client.get.side_effect = lambda u: pages[u]
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d)/'state.db')
            store.add(BASE, 'root'); store.db.commit()
            crawl(store,client,4,Path(d)/'html')
            self.assertEqual(store.db.execute('SELECT count(*) FROM companies').fetchone()[0],1)
            crawl(store,client,0,Path(d)/'html')
            calls = [c.args[0] for c in client.get.call_args_list]
            self.assertEqual(calls.count(COMPANY),1)
            self.assertLess(calls.index(BASE+'categories/2/b.html'), calls.index(BASE+'gindex/8/pack'))
            self.assertEqual(store.db.execute('SELECT count(*) FROM memberships').fetchone()[0],3)
            before = len(calls)
            crawl(store,client,0,Path(d)/'html')
            self.assertEqual(client.get.call_count,before)
            store.export(Path(d)/'export')
            self.assertTrue((Path(d)/'export/companies.xlsx').exists())
            store.db.close()

    def test_finish_category_pagination_before_sibling(self):
        category = BASE+'categories/1/a.html'
        sibling = BASE+'categories/2/b.html'
        root = BASE+'gindex/7/chem'
        pages={root:'<a href="'+category+'">A</a><a href="'+sibling+'">B</a>',
            category:'<a href="'+COMPANY+'">First</a><a href="?page=2">Tiếp</a>',
            category+'?page=2':'<a href="'+COMPANY+'">First again</a>',
            sibling:'<a href="'+COMPANY+'">First again</a>',COMPANY:CONTACT}
        client=Mock();client.get.side_effect=lambda url:pages[url]
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'state.db');store.add(root,'sector','Chem');store.db.commit()
            crawl(store,client,0,Path(d)/'html')
            calls=[call.args[0] for call in client.get.call_args_list]
            self.assertLess(calls.index(category+'?page=2'),calls.index(sibling))
            store.db.close()

    def test_halt_keeps_pending(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d)/'state.db')
            store.add(BASE,'root'); store.db.commit()
            client = Mock(); client.get.side_effect = Halt('Blocked')
            with self.assertRaises(Halt): crawl(store,client,0,Path(d)/'html')
            self.assertEqual(store.db.execute('SELECT status FROM tasks').fetchone()[0],'pending')
            store.db.close()

    def test_cloudflare_stops_without_retry(self):
        client = Client()
        response = Mock(status_code=403, text='Sorry, you have been blocked')
        client.session.get = Mock(return_value=response)
        with self.assertRaises(Halt): client.request(COMPANY)
        self.assertEqual(client.session.get.call_count,1)

    def test_missing_name_rejected(self):
        with self.assertRaises(ValueError): parse_company('<p>unexpected page</p>',COMPANY)

if __name__ == '__main__': unittest.main()
