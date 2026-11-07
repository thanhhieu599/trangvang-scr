import asyncio,json,os,tempfile
from pathlib import Path
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1]
BASE='https://trangvangvietnam.com/'
UI=BASE+'__extension_test__/'
SHIM='''(() => {
 const event=()=>({listeners:[],addListener(fn){this.listeners.push(fn)},emit(...args){for(const fn of this.listeners)fn(...args)}});
 const tab={id:1,url:'https://trangvangvietnam.com/',status:'complete'};
 const runtime={id:'fixture-extension',onMessage:event(),onStartup:event(),getURL:p=>'https://trangvangvietnam.com/__extension_test__/'+p};
 runtime.sendMessage=m=>new Promise(resolve=>runtime.onMessage.listeners[0](m,{id:runtime.id,url:location.href},resolve));
 const tabs={create:async props=>{window.__openedDashboard=props.url;return {id:2,url:props.url}},onUpdated:event(),onRemoved:event(),get:async()=>({...tab}),query:async()=>[{...tab}],
 update:async(id,props)=>{tab.url=props.url;tab.status='loading';await window.fixtureNavigate(props.url);tab.status='complete';setTimeout(()=>tabs.onUpdated.emit(id,{status:'complete'}),0);return {...tab}}};
 const alarms={onAlarm:event(),create:async()=>{},clear:async()=>true,fire:name=>alarms.onAlarm.emit({name})};
 window.chrome={runtime,tabs,alarms,scripting:{executeScript:async({func})=>[{result:await window.fixtureRead(func.toString())}]}};
})();'''

async def main():
 async with async_playwright() as p:
  with tempfile.TemporaryDirectory() as profile:
   context=await p.chromium.launch_persistent_context(profile,headless=True, **({'executable_path':os.environ['CRAWLER_CHROMIUM_EXECUTABLE']} if os.environ.get('CRAWLER_CHROMIUM_EXECUTABLE') else {}),
    proxy={'server':os.environ['HTTPS_PROXY']} if os.environ.get('HTTPS_PROXY') else None)
   try:
    site=await context.new_page();ui=await context.new_page();navigation=[]
    fixtures={}
    def company(name):return f'<article><h1>{name}</h1><p itemprop="address">123 Main St</p><a href="tel:0123456789">0123456789</a><a href="mailto:a@example.test">Email</a><a href="https://example.test">www.example.test</a></article>'
    fixtures[BASE]='<h1>Root</h1><a href="/gindex/7/chem">Chem</a>'
    fixtures[BASE+'robots.txt']='User-agent: *\nAllow: /\nDisallow: /admin/\nCrawl-delay: 5'
    fixtures[BASE+'gindex/7/chem']='<h1>Chem</h1><a href="/categories/1/a.html">A</a><a href="/categories/2/b.html">B</a>'
    fixtures[BASE+'categories/1/a.html']='<h1>A</h1><h2 class="tvx-cn"><a href="/listings/1/a.html">First</a></h2><a href="?page=2">Tiếp</a>'
    fixtures[BASE+'categories/1/a.html?page=2']='<h1>A</h1><h2 class="tvx-cn"><a href="/listings/2/b.html">Second</a></h2>'
    fixtures[BASE+'categories/2/b.html']='<h1>B</h1><h2 class="tvx-cn"><a href="/listings/1/a.html">First again</a></h2>'
    fixtures[BASE+'listings/1/a.html']=company('First')
    fixtures[BASE+'listings/2/b.html']=company('Second')
    async def route(request):
     url=request.request.url
     if url.startswith(UI):
      path=ROOT/url.removeprefix(UI)
      body=path.read_text() if path.is_file() else '<h1>UI</h1>'
      if path.name=='popup.html':body=body.replace('<script type="module" src="popup.js"></script>','')
      await request.fulfill(status=200,content_type='text/html' if path.suffix=='.html' else 'text/javascript',body=body)
     elif url in fixtures:await request.fulfill(status=200,content_type='text/plain; charset=utf-8' if url.endswith('robots.txt') else 'text/html; charset=utf-8',body=fixtures[url])
     else:await request.abort()
    await context.route('**/*',route)
    await ui.add_init_script(SHIM)
    async def navigate(source,url):
     navigation.append(url);await site.goto(url,wait_until='domcontentloaded')
    async def read(source,func):return await site.evaluate('('+func+')()')
    await ui.expose_binding('fixtureNavigate',navigate);await ui.expose_binding('fixtureRead',read)
    # Extract saved real production pages using real DOM/layout; no requests to source.
    src=(ROOT/'extract.js').read_text().replace('export function readPage()', 'function readPage()')
    for key,url in ([('company',BASE+'listings/1187779161/kemic.html'),('category',BASE+'categories/47910/a.html'),('sector',BASE+'gindex/7/test')] if os.environ.get('CRAWLER_HTML_FIXTURES') else []):
     fixtures[url]=(Path(os.environ['CRAWLER_HTML_FIXTURES'])/(key+'.html')).read_text()
     await site.goto(url,wait_until='domcontentloaded')
     result=await site.evaluate('() => {'+src+';return readPage();}')
     if key=='company':
      assert result['company']['emails']=='info@kemic.vn',result
      assert all(result['company'][k] for k in ['name','address','phones','emails','websites'])
     elif key=='category':
      assert len(result['children'])==38,len(result['children'])
      # Pagination hrefs are query-relative in the saved real page.
      assert result['next'].endswith('?page=2'),result['next']
     else:assert result['children']
    if os.environ.get('CRAWLER_HTML_FIXTURES'): print('PASS rendered production HTML: Kemic fields, 38 listings, next page and sectors')
    await site.goto(BASE)
    await ui.goto(UI+'popup.html');await ui.evaluate("async()=>{await import('./worker.js');await import('./popup.js')}")
    await ui.wait_for_function("document.querySelector('#status').textContent.includes('0 công ty')")
    response=await ui.evaluate("()=>chrome.runtime.sendMessage({type:'START',tabId:1,maxPages:0,delay:30})")
    assert response['ok'],response
    async def stats():return await ui.evaluate("async()=>{const db=await import('./db.js');return db.statistics()}")
    for _ in range(50):
     await ui.wait_for_timeout(100)
     snapshot=await stats();config=snapshot['config']
     if not config['running']:break
     if not config.get('current'):
      await ui.evaluate("async()=>{const db=await import('./db.js'),s=await db.state();s.nextAt=0;await db.saveState(s);chrome.alarms.fire('collector-next')}")
    snapshot=await stats()
    assert snapshot['companies']==2 and snapshot['pending']==0,snapshot
    assert snapshot['config']['savedThisRun']==2 and snapshot['config']['skippedThisRun']==1,snapshot
    assert any(e['type']=='skipped' for e in snapshot['config']['events']),snapshot
    assert navigation.count(BASE+'listings/1/a.html')==1,navigation
    assert navigation.index(BASE+'categories/1/a.html?page=2')<navigation.index(BASE+'categories/2/b.html'),navigation
    rows=await ui.evaluate("async()=>{const db=await import('./db.js');return db.rows()}")
    first=next(r for r in rows if r['name']=='First')
    assert first['categories']==['A','B'],first
    await ui.wait_for_function("document.querySelector('#total').textContent==='2' && document.querySelector('#skipped').textContent==='1'")
    assert 'a@example.test' in await ui.locator('#company').inner_text()
    assert await ui.locator('#events li').count()>0
    await ui.locator('#dashboard').click()
    assert (await ui.evaluate('window.__openedDashboard')).endswith('?tab=1')
    # CSV export initiated by actual popup button.
    async with ui.expect_download() as download:await ui.locator('#export').click()
    downloaded=await download.value
    assert downloaded.suggested_filename=='trangvang-companies.csv'
    # Reload simulates a fresh worker module/global state; IndexedDB remains.
    await ui.reload();await ui.evaluate("async()=>{await import('./worker.js');await import('./popup.js')}")
    assert (await stats())['companies']==2
    print('PASS mocked Chrome API controller: traversal, dedup/memberships, persistent counters, live progress UI, dashboard link, reload and CSV')
   finally:await context.close()
asyncio.run(main())
