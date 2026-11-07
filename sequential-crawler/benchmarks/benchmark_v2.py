"""Synthetic browser benchmark: no live scraping, no performance claim for the source."""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import crawler as base
from crawler_v2 import FastBrowser
from playwright.sync_api import BrowserType


class Transport:
    # Compose production routing policies with a local test fixture transport.
    def __init__(self,route):self.route=route
    def __getattr__(self,key):return getattr(self.route,key)
    def continue_(self):return self.route.fallback()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pages',type=int,default=3)
    parser.add_argument('--ad-delay',type=float,default=6)
    parser.add_argument('--executable',default=os.environ.get('CRAWLER_CHROMIUM_EXECUTABLE'))
    parser.add_argument('--report',default='benchmark_v2.json')
    args=parser.parse_args()
    if args.pages<1 or not 0<=args.ad_delay<=20:parser.error('pages >=1; ad-delay in 0..20')
    launch=BrowserType.launch_persistent_context
    def headless(self,*a,**kw):
        kw['headless']=True
        if args.executable:kw['executable_path']=args.executable
        return launch(self,*a,**kw)
    proxy={'server':os.environ['HTTPS_PROXY']} if os.environ.get('HTTPS_PROXY') else None
    results={};parity=[]
    for label,cls in [('baseline_browser',base.BrowserClient),('v2_balanced',FastBrowser)]:
        with tempfile.TemporaryDirectory() as profile:
            with patch.object(BrowserType,'launch_persistent_context',headless):
                client=cls(delay=5,profile=profile,proxy=proxy)
            ads=[0];protected=[0]
            def fixture(route):
                url=route.request.url
                if 'googletagmanager.com' in url:
                    ads[0]+=1;time.sleep(args.ad_delay)
                    route.fulfill(status=200,content_type='text/javascript',body='/* synthetic delayed analytics */')
                elif 'challenges.cloudflare.com' in url:
                    protected[0]+=1
                    route.fulfill(status=200,content_type='text/javascript',body='/* fixture resource, not an actual CAPTCHA */')
                elif url.startswith(base.BASE+'listings/'):
                    number=urlsplit(url).path.split('/')[2]
                    route.fulfill(status=200,content_type='text/html; charset=utf-8',body=f'''<!doctype html><html><head><meta charset="utf-8">
                    <script src="https://www.googletagmanager.com/fixture-ads.js?id={number}"></script>
                    <script src="https://challenges.cloudflare.com/fixture-script.js?id={number}"></script></head>
                    <body><article><h1>Fixture company {number}</h1><div itemprop="address">123 Main St</div>
                    <a href="tel:0123456789">0123456789</a><a href="mailto:a@example.test">Email</a>
                    <a href="https://example.test">www.example.test</a></article></body></html>''')
                else:route.abort()
            try:
                client.page.unroute_all(behavior='ignoreErrors')
                client.page.route('**/*',fixture)
                client.page.route('**/*',lambda route:client._route(Transport(route)))
                rows=[];started=time.perf_counter()
                for index in range(args.pages):
                    url=base.BASE+f'listings/{910000001+index}/fixture.html'
                    # Fixtures only. request() retains normal pacing; robots is not
                    # fetched because every response is supplied by the test harness.
                    html=client.request(url)
                    row=base.parse_company(html,url);row.pop('collected_at');rows.append(row)
                    print(f'{label}: {index+1}/{args.pages}',flush=True)
                seconds=time.perf_counter()-started
                results[label]={'seconds':round(seconds,3),'pages':args.pages,'loaded_ad_scripts':ads[0],
                    'loaded_protected_fixture_scripts':protected[0],'assets_skipped':getattr(client,'resources_skipped',0)}
                parity.append(rows)
            finally:client.close()
    assert parity[0]==parity[1], 'Extracted company fields differ'
    assert all(not row['review_required'] for row in parity[1])
    assert results['v2_balanced']['loaded_protected_fixture_scripts']==args.pages
    report={'type':'synthetic_fixture_only','ad_delay_seconds':args.ad_delay,'request_start_interval_seconds':5,
      'company_fields_equal':True,'results':results,
      'wall_time_ratio':round(results['baseline_browser']['seconds']/results['v2_balanced']['seconds'],2),
      'limitations':'Not a live-source benchmark. No guarantee of this speedup on Trang Vang. Browser startup excluded.'}
    Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
