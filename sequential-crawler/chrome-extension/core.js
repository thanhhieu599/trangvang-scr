export const BASE = 'https://trangvangvietnam.com/';
export function canonical(value, base = BASE) {
  try {
    const u = new URL(value, base);
    if (u.protocol !== 'https:' || !['trangvangvietnam.com', 'www.trangvangvietnam.com'].includes(u.hostname)) return null;
    u.hostname = 'trangvangvietnam.com'; u.hash = ''; return u.href;
  } catch { return null; }
}
export const identity = url => new URL(url).pathname.match(/^\/(?:gindex|categories|listings)\/\d+/)?.[0] || url;
export function kindOf(url) {
  const p = new URL(url).pathname;
  if (/^\/listings\/\d+/.test(p)) return 'company';
  if (/^\/categories\/\d+/.test(p)) return 'category';
  if (/^\/gindex\/\d+/.test(p)) return 'sector';
  if (p === '/') return 'root';
  throw Error('Chỉ bắt đầu từ trang chủ, /gindex/, /categories/ hoặc /listings/.');
}
export function task(url, kind, sector = '', category = '', depth = 0) {
  return {id: JSON.stringify([kind, kind === 'category' ? url : identity(url), sector, category]),
    url, kind, sector, category, depth, priority: -depth, status: 'pending'};
}
export function parseRobots(text) {
  if (/<(?:!doctype|html)/i.test(text)) throw Error('robots.txt trả HTML; không xác định được quy tắc.');
  const groups = []; let group = null, sawRule = false;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.split('#')[0].trim(), at = line.indexOf(':');
    if (at < 0) continue;
    const key = line.slice(0, at).trim().toLowerCase(), value = line.slice(at + 1).trim();
    if (key === 'user-agent') {
      if (!group || sawRule) { group = {agents: [], rules: [], delay: 0}; groups.push(group); sawRule = false; }
      group.agents.push(value.toLowerCase());
    } else if (group && ['allow', 'disallow', 'crawl-delay'].includes(key)) {
      sawRule = true;
      if (key === 'crawl-delay') { const n = Number(value); if (Number.isFinite(n) && n >= 0) group.delay = Math.max(group.delay, n); }
      else if (value) group.rules.push({allow: key === 'allow', path: value});
    }
  }
  if (!groups.length) throw Error('robots.txt không có nhóm User-agent hợp lệ.');
  const agent = 'authorizeddirectorycollector';
  let best = -1, chosen = [];
  for (const g of groups) {
    const score = Math.max(-1, ...g.agents.map(a => a === '*' ? 0 : agent.includes(a) ? a.length : -1));
    if (score > best) { best = score; chosen = [g]; }
    else if (score === best && score >= 0) chosen.push(g);
  }
  return {rules: chosen.flatMap(g => g.rules), delay: Math.max(0, ...chosen.map(g => g.delay))};
}
export function allowed(robots, url) {
  const u = new URL(url), path = u.pathname + u.search; let best = -1, result = true;
  for (const rule of robots.rules) {
    const anchor = rule.path.endsWith('$'), raw = anchor ? rule.path.slice(0, -1) : rule.path;
    const pattern = '^' + raw.split('*').map(s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('.*') + (anchor ? '$' : '');
    const score = raw.replaceAll('*', '').length;
    if (new RegExp(pattern).test(path) && (score > best || (score === best && rule.allow))) {
      best = score; result = rule.allow;
    }
  }
  return result;
}
export function toCSV(rows) {
  const columns = ['name','address','phones','emails','websites','source_url','collected_at','sectors','categories','review_required'];
  const cell = v => { let s = String(Array.isArray(v) ? v.join(' | ') : v ?? '');
    if (/^[\s]*[=+@-]/.test(s)) s = "'" + s;
    return '"' + s.replaceAll('"', '""') + '"'; };
  return '\uFEFF' + [columns, ...rows.map(r => columns.map(c => r[c]))].map(row => row.map(cell).join(',')).join('\r\n');
}
