import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_browser
import test_crawler as fixtures
from crawler import BASE, Halt, PageLoadError, Store, category_url, crawl, main, prompt_category

CATEGORY=BASE+'categories/47910/chem.html'

class SelectionTests(unittest.TestCase):
    def test_prompt_rejects_bad_link_then_accepts_category(self):
        with patch('builtins.input',side_effect=['https://example.test/','',CATEGORY]):
            self.assertEqual(prompt_category(),CATEGORY)
        with patch('builtins.input',return_value=''):
            self.assertEqual(prompt_category(CATEGORY),CATEGORY)
        with self.assertRaises(Halt):category_url(fixtures.COMPANY)

    def test_selected_scope_ignores_older_high_priority_tasks(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'state.sqlite')
            old=BASE+'listings/99/old.html';store.add(old,'company','Old','Old',100);store.db.commit()
            store.select_scope(CATEGORY);store.prepare(CATEGORY)
            client=Mock();client.get.side_effect=lambda u:'<h1>Chemicals</h1><a href="'+fixtures.COMPANY+'">Company</a>' if u==CATEGORY else fixtures.CONTACT
            crawl(store,client,0,Path(d)/'html')
            self.assertNotIn(old,[call.args[0] for call in client.get.call_args_list])
            self.assertEqual(store.counts().get('pending',0),0)
            self.assertEqual(store.db.execute("SELECT status FROM tasks WHERE url=?",(old,)).fetchone()[0],'pending')
            store.db.close()

    def test_scope_persists_after_db_reopens(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.sqlite';store=Store(path)
            store.select_scope(CATEGORY);store.prepare(CATEGORY);store.db.close()
            store=Store(path);store.restore_scope()
            self.assertEqual(store.active_scope,'categories:47910')
            self.assertEqual(store.prepare(resume_only=True)[1],CATEGORY)
            store.db.close()

    def test_global_company_cache_is_reused_across_scopes(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'state.sqlite')
            store.add(fixtures.COMPANY,'company','Old','Old');store.db.commit()
            client=Mock();client.get.return_value=fixtures.CONTACT
            crawl(store,client,0,Path(d)/'html')
            store.select_scope(CATEGORY);store.add(fixtures.COMPANY,'company','Chem','Chemicals');store.db.commit()
            second=Mock();second.get.side_effect=AssertionError('Cached company reloaded')
            crawl(store,second,0,Path(d)/'html');second.get.assert_not_called()
            self.assertEqual(store.db.execute('SELECT count(*) FROM companies').fetchone()[0],1)
            store.db.close()

    def test_scope_export_excludes_other_companies(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'state.sqlite')
            other=BASE+'listings/99/old.html'
            store.add(other,'company','Old','Old');store.db.commit()
            client=Mock();client.get.return_value=fixtures.CONTACT.replace('Example Ltd','Other Ltd')
            crawl(store,client,0,Path(d)/'html')
            store.select_scope(CATEGORY);store.add(fixtures.COMPANY,'company','Chem','Chemicals');store.db.commit()
            client.get.return_value=fixtures.CONTACT
            crawl(store,client,0,Path(d)/'html');store.export(Path(d)/'export')
            with (Path(d)/'export/companies.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
            self.assertEqual([r['name'] for r in rows],['Example Ltd'])
            self.assertEqual(rows[0]['categories'],'Chemicals')
            self.assertEqual(store.db.execute('SELECT count(*) FROM companies').fetchone()[0],2)
            store.db.close()

    def test_page_timeout_does_not_stop_other_companies(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'state.sqlite')
            store.add(BASE+'listings/99/slow.html','company');store.add(fixtures.COMPANY,'company');store.db.commit()
            client=Mock();client.get.side_effect=[PageLoadError('Timed out'),fixtures.CONTACT]
            with self.assertLogs(level='INFO'):crawl(store,client,0,Path(d)/'html')
            self.assertEqual(store.counts(),{'done':1,'error':1})
            self.assertEqual(store.db.execute('SELECT count(*) FROM companies').fetchone()[0],1)
            store.db.close()

    def test_embedded_captcha_is_not_a_blocked_company_page(self):
        client=test_browser.BrowserTests().client(200)
        content=fixtures.CONTACT+'<div class="g-recaptcha"></div><script src="/cdn-cgi/challenge-platform/jsd"></script>'
        self.assertFalse(client._blocked(content))
        client.status=403
        self.assertTrue(client._blocked(content))

    def test_manual_wait_has_deadline(self):
        client=test_browser.BrowserTests().client(403);client.verify_timeout=120
        with patch('crawler.time.monotonic',side_effect=[0,121]),patch('builtins.input',return_value=''):
            with self.assertRaisesRegex(Halt,'Hết 120 giây'):client._wait_for_user()

    def test_browser_navigation_timeout_is_recoverable(self):
        client=test_browser.BrowserTests().client()
        client.page.goto.side_effect=type('TimeoutError',(Exception,),{})('Slow')
        with self.assertRaises(PageLoadError):client.request(fixtures.COMPANY)

    def test_select_cli_uses_input_and_only_the_selected_queue(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.sqlite';store=Store(path)
            old=BASE+'listings/99/old.html';store.add(old,'company','Old','Old',100);store.db.commit();store.db.close()
            client=Mock();client.get.side_effect=lambda u:'<h1>Chemicals</h1><a href="'+fixtures.COMPANY+'">Company</a>' if u==CATEGORY else fixtures.CONTACT
            args=['crawler.py','select','--db',str(path),'--out',str(Path(d)/'export'),'--stats-every','0']
            with patch('sys.argv',args),patch('builtins.input',return_value=CATEGORY),patch('crawler.BrowserClient',return_value=client),self.assertLogs(level='INFO'):
                self.assertEqual(main(),0)
            self.assertEqual([call.args[0] for call in client.get.call_args_list],[CATEGORY,fixtures.COMPANY])

    def test_retry_errors_only_requeues_selected_scope(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.sqlite';store=Store(path)
            old=BASE+'listings/99/old.html';store.add(old,'company');store.db.commit()
            store.select_scope(CATEGORY);store.add(fixtures.COMPANY,'company');store.db.commit()
            store.db.execute("UPDATE tasks SET status='error'");store.db.commit();store.db.close()
            args=['crawler.py','retry-errors','--db',str(path),'--out',str(Path(d)/'export')]
            with patch('sys.argv',args),self.assertLogs(level='INFO'):
                self.assertEqual(main(),0)
            store=Store(path)
            self.assertEqual(store.db.execute('SELECT status FROM tasks WHERE url=?',(old,)).fetchone()[0],'error')
            self.assertEqual(store.db.execute('SELECT status FROM tasks WHERE url=?',(fixtures.COMPANY,)).fetchone()[0],'pending')
            store.db.close()

    def test_migration_keeps_old_tasks_and_companies(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.sqlite';db=sqlite3.connect(path)
            db.executescript('CREATE TABLE tasks(id INTEGER PRIMARY KEY,task_key TEXT UNIQUE,url TEXT,kind TEXT,sector TEXT,category TEXT,depth INTEGER,status TEXT DEFAULT "pending",error TEXT); CREATE TABLE companies(company_id TEXT PRIMARY KEY,data TEXT);')
            db.execute('INSERT INTO tasks(task_key,url,kind) VALUES(?,?,?)',('old',fixtures.COMPANY,'company'))
            db.execute('INSERT INTO companies VALUES(?,?)',('listings:12',json.dumps({'name':'Saved'})));db.commit();db.close()
            store=Store(path)
            self.assertEqual(store.db.execute('SELECT scope FROM tasks').fetchone()[0],'')
            self.assertEqual(store.db.execute('SELECT data FROM companies').fetchone()[0],json.dumps({'name':'Saved'}))
            store.select_scope(CATEGORY);self.assertIsNone(store.next_pending());store.db.close()

if __name__=='__main__':unittest.main()
