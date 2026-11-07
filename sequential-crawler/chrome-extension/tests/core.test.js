import test from 'node:test';
import assert from 'node:assert/strict';
import {canonical, kindOf, task, parseRobots, allowed, toCSV} from '../core.js';

test('same-site HTTPS URL normalization',()=>{
  assert.equal(canonical('/gindex/7/test#part'),'https://trangvangvietnam.com/gindex/7/test');
  assert.equal(canonical('https://evil.test/listings/1/a'),null);
  assert.equal(canonical('javascript:alert(1)'),null);
});
test('all traversal levels and unsupported starts',()=>{
  for (const [path,kind] of [['/','root'],['/gindex/7/a','sector'],['/categories/1/a','category'],['/listings/1/a','company']]) assert.equal(kindOf('https://trangvangvietnam.com'+path),kind);
  assert.throws(()=>kindOf('https://trangvangvietnam.com/login.asp'));
});
test('dedup company by ID while preserving pagination and membership',()=>{
  const base='https://trangvangvietnam.com';
  assert.equal(task(base+'/listings/1/a','company','S','C').id,task(base+'/listings/1/b','company','S','C').id);
  assert.notEqual(task(base+'/categories/1/a?page=2','category').id,task(base+'/categories/1/a?page=3','category').id);
  assert.notEqual(task(base+'/listings/1/a','company','S','A').id,task(base+'/listings/1/a','company','S','B').id);
});
test('robots longest-match overrides Allow root',()=>{
  const r=parseRobots('User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /*.sql$\nCrawl-delay: 60');
  assert.equal(r.delay,60);
  assert.equal(allowed(r,'https://trangvangvietnam.com/admin/a'),false);
  assert.equal(allowed(r,'https://trangvangvietnam.com/data.sql'),false);
  assert.equal(allowed(r,'https://trangvangvietnam.com/listings/1/a'),true);
});
test('robots specific agent and equal specificity Allow',()=>{
  const r=parseRobots('User-agent: *\nDisallow: /\nUser-agent: AuthorizedDirectoryCollector\nDisallow: /a\nAllow: /a');
  assert.equal(allowed(r,'https://trangvangvietnam.com/a'),true);
});
test('HTML or invalid robots is rejected',()=>{
  assert.throws(()=>parseRobots('<html>Blocked</html>'));
  assert.throws(()=>parseRobots('Not a robots file'));
});
test('CSV Unicode, quoting, formula safety',()=>{
  const csv=toCSV([{name:'=1+1',address:'Hà Nội, "A"',phones:'+84123'}]);
  assert.ok(csv.startsWith('\uFEFF')); assert.ok(csv.includes("'=1+1"));
  assert.ok(csv.includes('"Hà Nội, ""A"""')); assert.ok(csv.includes("'+84123"));
});
