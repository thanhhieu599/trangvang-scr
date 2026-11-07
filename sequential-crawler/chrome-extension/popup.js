import {rows} from './db.js';
import {toCSV} from './core.js';
const el=id=>document.getElementById(id);
const pinnedTab=Number(new URL(location.href).searchParams.get('tab')) || null;
if (pinnedTab) { document.body.classList.add('panel'); el('dashboard').hidden=true; }
let busy=false;
async function targetTab() {
  if (pinnedTab) return pinnedTab;
  const [tab]=await chrome.tabs.query({active:true,currentWindow:true}); return tab?.id;
}
function render({config,pending,companies}) {
  const current=config?.current || config?.lastTask;
  const labels={root:'Lĩnh vực',sector:'Phân ngành',category:'Danh sách công ty',company:'Chi tiết công ty',robots:'robots.txt'};
  const wait=config?.running && !config.current ? Math.max(0,Math.ceil(((config.nextAt||0)-Date.now())/1000)) : null;
  el('status').textContent=[config?.running?'Đang chạy':'Đã dừng', `${companies} công ty · ${pending} trang chờ · ${config?.totalPages||0} trang đã xử lý`,
    `Bước: ${labels[current?.kind]||'Chưa bắt đầu'}`,`Ngành: ${current?.sector||'—'}`,`Phân ngành: ${current?.category||'—'}`,
    current?.url||'',wait!==null?`Lượt tiếp theo: ${wait} giây (Chrome có thể chạy trễ hơn)`:'',config?.message||'Chưa bắt đầu'].filter(Boolean).join('\n');
  el('total').textContent=companies;el('saved').textContent=config?.savedThisRun||0;el('skipped').textContent=config?.skippedThisRun||0;
  const company=config?.lastCompany;
  el('company').textContent=company?[
    `Tên: ${company.name}`,`Địa chỉ: ${company.address||'Chưa có'}`,`SĐT: ${company.phones||'Chưa có'}`,
    `Email: ${company.emails||'Chưa có'}`,`Website: ${company.websites||'Chưa có'}`,
    `Nguồn: ${company.source_url}`,`Cần kiểm tra dữ liệu: ${company.review_required?'Có':'Không'}`].join('\n'):'Chưa có công ty.';
  el('events').replaceChildren();
  for(const event of [...(config?.events||[])].reverse()) {
    const li=document.createElement('li');li.textContent=`${new Date(event.at).toLocaleTimeString()} — ${event.message}${event.url?' · '+event.url:''}`;el('events').append(li);
  }
}
async function command(type) {
  if(busy)return;busy=true;
  try {
    const response=await chrome.runtime.sendMessage({type,tabId:await targetTab(),delay:Number(el('delay').value),maxPages:Number(el('limit').value)});
    if(!response?.ok)throw Error(response?.error||'Không nhận được phản hồi.');
    render(response.data);
  } catch(error) {el('status').textContent=error.message;}
  finally {busy=false;}
}
for(const [id,type] of [['start','START'],['resume','RESUME'],['pause','PAUSE']])el(id).onclick=()=>command(type);
el('dashboard').onclick=async()=>{
  const tabId=await targetTab();
  await chrome.tabs.create({url:chrome.runtime.getURL('popup.html')+'?tab='+tabId});
};
el('export').onclick=async()=>{
  try {
    const data=await rows(),url=URL.createObjectURL(new Blob([toCSV(data)],{type:'text/csv;charset=utf-8'}));
    const a=document.createElement('a');a.href=url;a.download='trangvang-companies.csv';a.click();
    setTimeout(()=>URL.revokeObjectURL(url),10000);
    el('status').textContent=`Đã xuất ${data.length} công ty.`;
  } catch(error){el('status').textContent=error.message;}
};
command('STATUS');
setInterval(()=>command('STATUS'),2000);
