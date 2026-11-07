import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_crawler as fixtures
from crawler import BASE, Halt, LazyClient, LiveStats, RunLock, Store, crawl, main


class ResumeTests(unittest.TestCase):
    def test_run_reuses_saved_queue_without_home_seed(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'state.sqlite')
            store.add(fixtures.COMPANY,'company','Chem','A',3);store.db.commit()
            self.assertEqual(store.prepare()[1],fixtures.COMPANY)
            self.assertEqual(store.db.execute('SELECT count(*) FROM tasks').fetchone()[0],1)
            store.db.close()

    def test_explicit_seed_keeps_existing_sector_labels(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'state.sqlite')
            url=BASE+'categories/1/a.html'
            store.add(url,'page','Chem','Original label',2);store.db.commit()
            following=store.prepare(url)
            self.assertEqual(following[4],'Original label')
            self.assertEqual(store.db.execute('SELECT count(*) FROM tasks').fetchone()[0],1)
            store.db.close()

    def test_resume_empty_db_requires_initial_run(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'state.sqlite')
            with self.assertRaises(Halt): store.prepare(resume_only=True)
            self.assertEqual(store.db.execute('SELECT count(*) FROM tasks').fetchone()[0],0)
            store.db.close()

    def test_interrupted_company_resumes_after_reopening_db(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.sqlite'
            store=Store(path);store.add(fixtures.COMPANY,'company');store.db.commit()
            client=Mock();client.get.side_effect=Halt('Interrupted')
            with self.assertRaises(Halt):crawl(store,client,0,Path(d)/'html')
            store.db.close()
            store=Store(path)
            self.assertEqual(store.prepare(resume_only=True)[1],fixtures.COMPANY)
            client=Mock();client.get.return_value=fixtures.CONTACT
            crawl(store,client,0,Path(d)/'html')
            self.assertIsNone(store.next_pending())
            self.assertEqual(store.db.execute('SELECT count(*) FROM companies').fetchone()[0],1)
            store.db.close()

    def test_completed_cli_run_does_not_open_browser(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.sqlite'
            store=Store(path);store.add(fixtures.COMPANY,'company');store.db.commit()
            client=Mock();client.get.return_value=fixtures.CONTACT
            crawl(store,client,0,Path(d)/'html');store.db.close()
            args=['crawler.py','run','--browser','--stealth','--db',str(path),'--out',str(Path(d)/'export'),'--stats-every','0']
            with patch('sys.argv',args),patch('crawler.BrowserClient') as browser:
                self.assertEqual(main(),0)
                browser.assert_not_called()

    def test_cached_company_does_not_initialize_lazy_client(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'state.sqlite');store.add(fixtures.COMPANY,'company','S','A');store.db.commit()
            first=Mock();first.get.return_value=fixtures.CONTACT
            crawl(store,first,0,Path(d)/'html')
            store.add(fixtures.COMPANY,'company','S','B');store.db.commit()
            factory=Mock();client=LazyClient(factory)
            crawl(store,client,0,Path(d)/'html')
            factory.assert_not_called()
            self.assertEqual(store.db.execute('SELECT count(*) FROM memberships').fetchone()[0],2)
            store.db.close()

    def test_run_lock_blocks_second_process_and_releases(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.sqlite'
            lock=RunLock(path);lock.acquire()
            script='from crawler import RunLock,Halt; import sys\ntry:\n lock=RunLock(sys.argv[1]);lock.acquire();lock.close()\nexcept Halt:\n sys.exit(2)'
            try:
                result=subprocess.run([sys.executable,'-c',script,str(path)],cwd=Path(__file__).parent,timeout=10,capture_output=True)
                self.assertEqual(result.returncode,2,result.stderr.decode())
            finally:lock.close()
            result=subprocess.run([sys.executable,'-c',script,str(path)],cwd=Path(__file__).parent,timeout=10,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode())

    def test_periodic_stats_run_while_crawler_waits(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.sqlite'
            store=Store(path);store.add(fixtures.COMPANY,'company');store.db.commit()
            observer=LiveStats(path,0.02);reported=threading.Event()
            original=observer.report
            def report():
                original();reported.set()
            observer.report=report
            client=Mock()
            def get(_):
                if not reported.wait(2):raise AssertionError('Statistics stopped during page load')
                return fixtures.CONTACT
            client.get.side_effect=get
            try:
                with self.assertLogs(level='INFO') as logs:
                    observer.start();crawl(store,client,0,Path(d)/'html',observer=observer)
                self.assertTrue(any('THỐNG KÊ' in line and fixtures.COMPANY in line for line in logs.output))
            finally:observer.stop();store.db.close()
            self.assertFalse(observer.thread.is_alive())

if __name__=='__main__':unittest.main()
