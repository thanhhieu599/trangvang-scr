// This function is serialized by chrome.scripting; keep all helpers inside it.
export function readPage() {
  const clean = v => String(v ?? '').replace(/\s+/g, ' ').trim();
  const text = document.body?.innerText || '';
  const title = document.title.toLowerCase();
  if (/sorry,? you have been blocked|verify you are human|checking your browser|too many requests/i.test(text)
      || /just a moment|attention required/.test(title)
      || document.querySelector('iframe[src*="challenges.cloudflare.com"], .g-recaptcha, .h-captcha')) {
    return {url: location.href, blocked: true, reason: 'Trang chặn/xác minh/giới hạn tốc độ; cần kiểm tra thủ công.'};
  }
  if (location.pathname === '/robots.txt') return {url: location.href, robots: text};
  const visible = el => !!el.getClientRects().length && !el.closest('[hidden],[aria-hidden="true"]')
    && !['hidden','collapse'].includes(getComputedStyle(el).visibility);
  const local = href => {
    try { const u = new URL(href, location.href);
      if (u.protocol !== 'https:' || !['trangvangvietnam.com','www.trangvangvietnam.com'].includes(u.hostname)) return null;
      u.hostname = 'trangvangvietnam.com'; u.hash = ''; return u.href;
    } catch { return null; }
  };
  const kind = /^\/listings\//.test(location.pathname) ? 'company' : /^\/categories\//.test(location.pathname) ? 'category'
    : /^\/gindex\//.test(location.pathname) ? 'sector' : 'root';
  const target = kind === 'root' ? /^\/gindex\/\d+/ : kind === 'sector' ? /^\/categories\/\d+/ : /^\/listings\/\d+/;
  const headingLinks = kind === 'category' ? [...document.querySelectorAll('h2.tvx-cn a[href]')] : [];
  const links = headingLinks.length ? headingLinks : [...document.querySelectorAll('a[href]')];
  const children = [], seen = new Set();
  for (const a of links) {
    const url = local(a.href); if (!url || !visible(a)) continue;
    const path = new URL(url).pathname; if (!target.test(path)) continue;
    const id = path.match(/^\/(?:gindex|categories|listings)\/\d+/)?.[0] || url;
    if (!seen.has(id)) { seen.add(id); children.push({url, name: clean(a.innerText)}); }
  }
  let next = null;
  if (kind === 'category') {
    const here = new URL(location.href), n = Number(here.searchParams.get('page') || 1), numbered = [];
    for (const a of document.querySelectorAll('a[href]')) {
      const href = local(a.href); if (!href || !visible(a)) continue;
      const u = new URL(href), page = Number(u.searchParams.get('page'));
      if (u.pathname !== here.pathname || [...u.searchParams.keys()].some(k => k !== 'page') || !(page > n)) continue;
      if (a.relList.contains('next') || /^(tiếp|tiếp theo|next|›|»|>)$/i.test(clean(a.innerText))) next ||= href;
      if (/^\d+$/.test(clean(a.innerText))) numbered.push({page, href});
    }
    next ||= numbered.sort((a,b) => a.page-b.page)[0]?.href || null;
  }
  const result = {url: location.href, kind, children, next};
  if (kind !== 'company') return result;
  const h1 = document.querySelector('h1'), name = clean(h1?.innerText), entities = [];
  function walk(obj) {
    if (Array.isArray(obj)) return obj.forEach(walk);
    if (!obj || typeof obj !== 'object') return;
    const types = [].concat(obj['@type'] || []);
    if (types.some(t => ['Organization','LocalBusiness','Corporation','Store','ProfessionalService'].includes(t))) entities.push(obj);
    if (obj['@graph']) walk(obj['@graph']); if (obj.mainEntity) walk(obj.mainEntity);
  }
  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    try { walk(JSON.parse(script.textContent)); } catch { /* malformed optional data */ }
  }
  const entity = entities.find(e => clean(e.name) === name) || (entities.length === 1 ? entities[0] : {}) || {};
  let scope = h1?.parentElement;
  while (scope && scope.tagName !== 'BODY' && !scope.querySelector('a[href^="mailto:"],a[href^="tel:"],[itemprop="address"]')) scope = scope.parentElement;
  if (scope?.tagName === 'BODY') scope = document.querySelector('[itemtype*="LocalBusiness"],[itemtype*="Organization"]');
  const array = key => [].concat(entity[key] || []).filter(v => typeof v === 'string').map(clean);
  const phones = array('telephone'), emails = array('email'), websites = [];
  function website(v) {
    try { const u = new URL(v.startsWith('www.') ? 'https://' + v : v);
      if (['http:','https:'].includes(u.protocol) && !/^(www\.)?trangvangvietnam\.com$/.test(u.hostname)) websites.push(u.href);
    } catch { /* invalid contact URL */ }
  }
  array('url').forEach(website);
  let address = typeof entity.address === 'string' ? clean(entity.address) : ['streetAddress','addressLocality','addressRegion','addressCountry']
    .map(k => typeof entity.address?.[k] === 'string' ? clean(entity.address[k]) : '').filter(Boolean).join(', ');
  if (scope) {
    address ||= clean(scope.querySelector('[itemprop="address"],.company-address,.address')?.textContent);
    for (const p of scope.querySelectorAll('[itemprop="telephone"]')) phones.push(clean(p.getAttribute('content') || p.textContent));
    for (const a of scope.querySelectorAll('a[href]')) {
      if (!visible(a)) continue;
      if (a.href.startsWith('mailto:')) emails.push(decodeURIComponent(a.href.slice(7).split('?')[0]));
      else if (a.href.startsWith('tel:')) phones.push(a.href.slice(4));
      else if (/^(https?:\/\/|www\.)/i.test(clean(a.innerText))) website(a.href);
    }
  }
  const joined = values => [...new Set(values.filter(Boolean))].join(' | ');
  result.company = {name: clean(entity.name) || name, address, phones: joined(phones), emails: joined(emails),
    websites: joined(websites), source_url: location.href, collected_at: new Date().toISOString()};
  if (!result.company.name) throw Error('Không nhận diện được tên công ty.');
  result.company.review_required = ['address','phones','emails','websites'].some(k => !result.company[k]);
  return result;
}
