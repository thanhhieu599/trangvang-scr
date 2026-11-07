import {BASE, canonical, identity, kindOf, task, parseRobots, allowed, addEvent} from './core.js';
import {req, transaction, state, saveState, enqueue, nextTask, statistics} from './db.js';
import {readPage} from './extract.js';
let tail = Promise.resolve();
const serial = fn => { const work = tail.then(fn); tail = work.catch(() => {}); return work; };
const ALARM = 'collector-next';
async function pause(message) {
  const config = await state();
  if (config) { config.running = false; config.message = message; addEvent(config,'paused',message); await saveState(config); }
  await chrome.alarms.clear(ALARM);
  await chrome.alarms.clear('collector-watchdog');
}
async function report(error) { await pause(error.message || String(error)); }
async function schedule(config) {
  config.current = null;
  config.nextAt = Date.now() + Math.max(30, config.delay || 30) * 1000 + Math.random() * 5000;
  config.message = 'Đang chờ lượt tiếp theo…';
  await saveState(config);
  await chrome.alarms.create(ALARM, {when: config.nextAt});
}
function member(company, entry) {
  company.sectors = [...new Set([...(company.sectors || []), entry.sector].filter(Boolean))];
  company.categories = [...new Set([...(company.categories || []), entry.category].filter(Boolean))];
  return company;
}
async function kick() {
  let config = await state();
  if (!config?.running) return;
  if (config.current) {
    const tab = await chrome.tabs.get(config.tabId);
    if (tab.status === 'complete') return consume(config.tabId);
    if (Date.now() - config.navigationAt > 120000) throw Error('Trang tải quá lâu. Kiểm tra tab rồi bấm Tiếp tục.');
    return;
  }
  if (config.nextAt > Date.now() + 100) {
    await chrome.alarms.create(ALARM, {when: config.nextAt}); return;
  }
  if (config.maxPages && config.runPages >= config.maxPages) return pause('Đã đạt số trang chạy thử; bấm Tiếp tục để xử lý tiếp.');
  for (let i=0; i<100; i++) {
    const entry = await transaction(['tasks'], 'readonly', tx => nextTask(tx.objectStore('tasks')));
    if (!entry) return pause('Đã xử lý hết hàng đợi. Có thể xuất CSV.');
    if (!allowed(config.robots, entry.url)) throw Error('robots.txt không cho phép URL đang chờ: ' + entry.url);
    const cached = entry.kind === 'company' ? await transaction(['companies'], 'readonly', tx => req(tx.objectStore('companies').get(identity(entry.url)))) : null;
    if (cached) {
      await transaction(['tasks','companies','meta'], 'readwrite', async tx => {
        await req(tx.objectStore('companies').put(member(cached, entry)));
        entry.status = 'done'; await req(tx.objectStore('tasks').put(entry));
        config.skippedThisRun = (config.skippedThisRun || 0) + 1;
        config.skippedTotal = (config.skippedTotal || 0) + 1;
        config.lastTask = entry; config.lastCompany = cached;
        addEvent(config,'skipped','Bỏ qua công ty đã có: ' + cached.name,{url:entry.url});
        await req(tx.objectStore('meta').put(config,'state'));
      });
      continue;
    }
    config.current = entry;
    addEvent(config,'loading','Đang tải ' + entry.kind,{url:entry.url});
    config.navigationAt = Date.now(); config.message = entry.url;
    await saveState(config);
    await chrome.tabs.update(config.tabId, {url: entry.url});
    return;
  }
  await schedule(config);
}
async function consume(tabId) {
  const config = await state();
  if (!config?.running || config.tabId !== tabId || !config.current) return;
  const tab = await chrome.tabs.get(tabId);
  if (tab.status !== 'complete') return;
  const [{result}] = await chrome.scripting.executeScript({target: {tabId}, func: readPage});
  if (!result) throw Error('Không đọc được trang. Kiểm tra tab và quyền extension.');
  if (result.blocked) throw Error(result.reason + ' Giải quyết trong tab này rồi bấm Tiếp tục.');
  const expected = canonical(config.current.url), actual = canonical(result.url);
  if (expected !== actual) throw Error('Tab đã chuyển sang URL khác. Quay về ' + config.current.url + ' rồi bấm Tiếp tục.');
  if (config.current.kind === 'robots') {
    config.robots = parseRobots(result.robots || '');
    config.delay = Math.max(config.delay, config.robots.delay, 30);
    await schedule(config); return;
  }
  const entry = config.current;
  if (result.kind !== entry.kind) throw Error('Loại trang không khớp hàng đợi; kiểm tra tab.');
  if (entry.kind !== 'company' && !result.children.length) throw Error('Không tìm thấy liên kết con. Kiểm tra trang/selector; hàng đợi được giữ.');
  await transaction(['tasks','companies','meta'], 'readwrite', async tx => {
    const tasks = tx.objectStore('tasks');
    if (entry.kind === 'company') {
      const record = member({...result.company, id: identity(entry.url)}, entry);
      if (!record.name) throw Error('Thiếu tên công ty.');
      const existing = await req(tx.objectStore('companies').get(record.id));
      if (existing) {
        record.sectors = [...new Set([...existing.sectors, ...record.sectors])];
        record.categories = [...new Set([...existing.categories, ...record.categories])];
      }
      await req(tx.objectStore('companies').put(record));
      config.savedThisRun = (config.savedThisRun || 0) + (existing ? 0 : 1);
      config.lastCompany = record;
      addEvent(config,'saved','Đã lưu: ' + record.name,{url:entry.url,review_required:record.review_required});
    } else {
      for (const child of result.children) {
        const url = canonical(child.url); if (!url) continue;
        const kind = entry.kind === 'root' ? 'sector' : entry.kind === 'sector' ? 'category' : 'company';
        const sector = entry.kind === 'root' ? child.name : entry.sector;
        const category = entry.kind === 'sector' ? child.name : entry.category;
        await enqueue(tasks, task(url, kind, sector, category, entry.depth+1), config);
      }
      if (result.next && entry.kind === 'category') {
        const next = canonical(result.next);
        if (next && identity(next) === identity(entry.url)) {
          const page = task(next, 'category', entry.sector, entry.category, entry.depth);
          page.priority = -(entry.depth + 0.5); // Before sibling categories, after this page's companies.
          await enqueue(tasks, page, config);
        }
      }
    }
    entry.status = 'done'; await req(tasks.put(entry));
    config.runPages++; config.totalPages++; config.lastTask = entry;
    if (entry.kind !== 'company') addEvent(config,'processed','Đã xử lý trang ' + entry.kind,{url:entry.url});
    // Clearing current in the same commit makes duplicate tab events harmless.
    config.current = null;
    await req(tx.objectStore('meta').put(config,'state'));
  });
  await schedule(config);
}
async function start(message) {
  const tab = await chrome.tabs.get(message.tabId), url = canonical(tab.url);
  if (!url) throw Error('Mở trangvangvietnam.com trong Chrome rồi bấm biểu tượng extension.');
  const existing = await statistics();
  if (existing.pending) throw Error('Còn hàng đợi cũ; dùng Tiếp tục để giữ đúng tiến độ.');
  const kind = kindOf(url);
  const config = {running:true, tabId:tab.id, delay:Math.max(30, Number(message.delay)||30),
    maxPages:Math.max(0, Math.floor(Number(message.maxPages)||0)), runPages:0, totalPages:existing.config?.totalPages||0,
    sequence:existing.config?.sequence||0, savedThisRun:0, skippedThisRun:0,
    skippedTotal:existing.config?.skippedTotal||0, events:existing.config?.events||[],
    lastCompany:existing.config?.lastCompany||null, robots:null, current:{kind:'robots',url:BASE+'robots.txt'},
    navigationAt:Date.now(), nextAt:0, message:'Đọc robots.txt trong phiên Chrome hiện tại…'};
  addEvent(config,'started','Bắt đầu thu thập từ tab hiện tại',{url});
  await transaction(['tasks','meta'], 'readwrite', async tx => {
    await enqueue(tx.objectStore('tasks'), task(url,kind,kind==='sector'?url:'',kind==='category'?url:'',0),config);
    await req(tx.objectStore('meta').put(config,'state'));
  });
  await chrome.alarms.create('collector-watchdog',{periodInMinutes:1});
  await chrome.tabs.update(tab.id,{url:BASE+'robots.txt'});
}
async function resume(message) {
  const config = await state(); if (!config) throw Error('Chưa có phiên thu thập; chọn Bắt đầu.');
  const tab = await chrome.tabs.get(message.tabId);
  if (!canonical(tab.url)) throw Error('Chọn tab Trang Vàng cần dùng rồi bấm Tiếp tục.');
  config.tabId = tab.id; config.running = true; config.runPages=0;
  config.savedThisRun=0; config.skippedThisRun=0;
  addEvent(config,'resumed','Tiếp tục từ tiến độ đã lưu');
  config.maxPages = Math.max(0, Math.floor(Number(message.maxPages)||0));
  config.delay = Math.max(30, config.robots?.delay || 0, Number(message.delay)||30);
  config.nextAt = Math.max(config.nextAt || 0, Date.now());
  if (!config.robots && !config.current) config.current = {kind:'robots',url:BASE+'robots.txt'};
  await saveState(config);
  await chrome.alarms.create('collector-watchdog',{periodInMinutes:1});
  if (config.current && canonical(tab.url) !== canonical(config.current.url)) {
    config.navigationAt = Date.now(); await saveState(config);
    await chrome.tabs.update(tab.id, {url: config.current.url}); return;
  }
  await kick();
}
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  // Only extension UI pages can issue controller commands.
  if (sender.id !== chrome.runtime.id || sender.tab || (sender.url && !sender.url.startsWith(chrome.runtime.getURL('')))) return;
  serial(async () => {
    if (message.type === 'START') await start(message);
    else if (message.type === 'RESUME') await resume(message);
    else if (message.type === 'PAUSE') await pause('Người dùng tạm dừng; tiến độ đã lưu.');
    else if (message.type !== 'STATUS') throw Error('Lệnh không hợp lệ.');
    return statistics();
  }).then(data => reply({ok:true,data})).catch(error => reply({ok:false,error:error.message}));
  return true;
});
chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (change.status === 'complete') serial(() => consume(tabId)).catch(report);
});
chrome.tabs.onRemoved.addListener(tabId => serial(async () => {
  const config = await state(); if (config?.running && config.tabId === tabId) await pause('Tab thu thập đã đóng; mở lại Trang Vàng và bấm Tiếp tục.');
}).catch(report));
chrome.alarms.onAlarm.addListener(alarm => {
  if ([ALARM,'collector-watchdog'].includes(alarm.name)) serial(kick).catch(report);
});
chrome.runtime.onStartup.addListener(() => serial(() => pause('Chrome đã mở lại; chọn tab Trang Vàng và bấm Tiếp tục.')).catch(report));
