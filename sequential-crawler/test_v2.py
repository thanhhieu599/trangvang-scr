import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from bs4 import BeautifulSoup

import crawler as base
import crawler_v2 as v2
import test_crawler as fixtures

class V2Tests(unittest.TestCase):
    def test_balanced_preserves_content_resources(self):
        for kind in ('image','font','script','stylesheet','document','fetch','xhr'):
            self.assertFalse(v2.block_resource('https://trangvangvietnam.com/asset',kind,'balanced',True))
        self.assertTrue(v2.block_resource('https://trangvangvietnam.com/movie.mp4','media'))
        self.assertTrue(v2.block_resource('https://www.googletagmanager.com/gtag/js','script'))

    def test_lean_is_limited_to_details(self):
        self.assertTrue(v2.block_resource('https://trangvangvietnam.com/photo.jpg','image','lean',True))
        self.assertFalse(v2.block_resource('https://trangvangvietnam.com/photo.jpg','image','lean',False))
        self.assertFalse(v2.block_resource('https://trangvangvietnam.com/main.js','script','lean',True))

    def test_challenge_assets_are_not_filtered(self):
        for url in ('https://challenges.cloudflare.com/a','https://www.gstatic.com/recaptcha/image',
                    'https://new.hcaptcha.com/a','https://trangvangvietnam.com/cdn-cgi/script',
                    'https://www.google.com/recaptcha/api.js'):
            self.assertFalse(v2.block_resource(url,'image','lean',True),url)

    def test_full_profile_and_active_challenge_preserve_all_requests(self):
        url='https://doubleclick.net/ad.js'
        self.assertFalse(v2.block_resource(url,'script','full',True))
        self.assertFalse(v2.block_resource(url,'script','lean',True,True))
        self.assertFalse(v2.block_resource(url,'document','balanced',True))

    def test_wal_retains_full_durability_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as d:
            store=v2.FastStore(Path(d)/'state.sqlite')
            self.assertEqual(store.db.execute('PRAGMA journal_mode').fetchone()[0],'wal')
            self.assertEqual(store.db.execute('PRAGMA synchronous').fetchone()[0],2)
            store.db.execute('INSERT INTO companies VALUES(?,?)',('listings:1','{}'))
            store.db.rollback()
            self.assertEqual(store.db.execute('SELECT count(*) FROM companies').fetchone()[0],0)
            store.db.close()

    def test_v2_reuses_v1_scope_and_saved_records(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.sqlite';store=base.Store(path)
            store.select_scope(base.BASE+'categories/1/a.html')
            store.add(fixtures.COMPANY,'company','Chem','A');store.db.commit()
            first=Mock();first.get.return_value=fixtures.CONTACT
            base.crawl(store,first,0,Path(d)/'html');store.db.close()
            store=v2.FastStore(path);store.restore_scope()
            store.add(fixtures.COMPANY,'company','Chem','B');store.db.commit()
            second=Mock();second.get.side_effect=AssertionError('Cached company was downloaded')
            base.crawl(store,second,0,Path(d)/'html',save_html=False,progress_every=10)
            second.get.assert_not_called()
            self.assertEqual(store.active_scope,'categories:1')
            self.assertEqual(store.db.execute('SELECT count(*) FROM companies').fetchone()[0],1)
            self.assertEqual(store.db.execute('SELECT count(*) FROM memberships').fetchone()[0],2)
            store.db.close()

    def test_single_parse_has_identical_fields(self):
        first=base.parse_company(fixtures.CONTACT,fixtures.COMPANY)
        second=base.parse_company(BeautifulSoup(fixtures.CONTACT,'html.parser'),fixtures.COMPANY)
        first.pop('collected_at');second.pop('collected_at')
        self.assertEqual(first,second)

    def test_disabling_html_archive_keeps_data(self):
        with tempfile.TemporaryDirectory() as d:
            store=v2.FastStore(Path(d)/'state.sqlite');store.add(fixtures.COMPANY,'company');store.db.commit()
            client=Mock();client.get.return_value=fixtures.CONTACT
            base.crawl(store,client,0,Path(d)/'html',save_html=False)
            self.assertEqual(list((Path(d)/'html').glob('*.html')),[])
            raw=store.db.execute('SELECT data FROM companies').fetchone()[0]
            self.assertEqual(json.loads(raw)['emails'],'info@example.test')
            self.assertIsNone(store.next_pending());store.db.close()

    def test_v2_defaults_keep_explicit_rate_options(self):
        captured={}
        def main(**kwargs):captured.update(kwargs);captured['argv']=sys.argv[:];return 0
        with patch('crawler_v2.base.main',side_effect=main):
            self.assertEqual(v2.run(['select','--delay','8','--stats-every','5']),0)
        self.assertIn('--no-html-cache',captured['argv'])
        self.assertEqual(captured['argv'][captured['argv'].index('--delay')+1],'8')
        self.assertEqual(captured['argv'][captured['argv'].index('--stats-every')+1],'5')
        self.assertEqual(captured['store_factory'],v2.FastStore)

    def test_v2_can_keep_html_and_disable_asset_filter(self):
        captured={}
        def main(**kwargs):captured.update(kwargs);captured['argv']=sys.argv[:];return 0
        with patch('crawler_v2.base.main',side_effect=main):v2.run(['select','--save-html','--v2-assets','full'])
        self.assertNotIn('--no-html-cache',captured['argv'])
        self.assertEqual(captured['browser_factory'].keywords['assets'],'full')

    def test_progress_query_throttle_keeps_per_task_commits(self):
        with tempfile.TemporaryDirectory() as d:
            store=v2.FastStore(Path(d)/'state.sqlite');store.add(fixtures.COMPANY,'company');store.db.commit()
            client=Mock();client.get.return_value=fixtures.CONTACT
            with patch.object(store,'counts',wraps=store.counts) as counts:
                base.crawl(store,client,0,Path(d)/'html',progress_every=10)
                counts.assert_not_called()
            self.assertIsNone(store.next_pending())
            self.assertEqual(store.db.execute('SELECT count(*) FROM companies').fetchone()[0],1)
            store.db.close()

    def test_v2_cli_selects_scope_and_resumes_v1_database(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.sqlite';category=base.BASE+'categories/1/a.html'
            store=base.Store(path);store.add(fixtures.COMPANY,'company','Old','Old');store.db.commit()
            first=Mock();first.get.return_value=fixtures.CONTACT
            base.crawl(store,first,0,Path(d)/'old-html');store.db.close()
            browser=Mock();browser.get.side_effect=lambda url:'<h1>Chemicals</h1><a href="'+fixtures.COMPANY+'">Company</a>' if url==category else (_ for _ in ()).throw(AssertionError('Cached company downloaded'))
            common=['--db',str(path),'--out',str(Path(d)/'export'),'--stats-every','0']
            with patch('builtins.input',return_value=category),patch('crawler_v2.FastBrowser',return_value=browser),self.assertLogs(level='INFO'):
                self.assertEqual(v2.run(['select',*common]),0)
            self.assertEqual([call.args[0] for call in browser.get.call_args_list],[category])
            with patch('crawler_v2.FastBrowser') as factory,self.assertLogs(level='INFO'):
                self.assertEqual(v2.run(['resume',*common]),0)
                factory.assert_not_called()
            store=v2.FastStore(path);store.restore_scope()
            self.assertEqual(store.active_scope,'categories:1')
            self.assertEqual(store.db.execute('SELECT count(*) FROM companies').fetchone()[0],1)
            self.assertEqual(store.db.execute('SELECT count(*) FROM memberships').fetchone()[0],2)
            self.assertEqual(list((Path(d)/'html').glob('*.html')),[])
            store.db.close()

    def test_source_crawl_delay_is_still_respected(self):
        client=v2.FastBrowser.__new__(v2.FastBrowser)
        base.Client.__init__(client,delay=5)
        client.request=Mock(return_value='User-agent: *\nAllow: /\nCrawl-delay: 9')
        client.init_robots()
        self.assertEqual(client.delay,9)
        self.assertTrue(client.robots.can_fetch(base.AGENT,fixtures.COMPANY))
        client.session.close()

if __name__=='__main__':unittest.main()
