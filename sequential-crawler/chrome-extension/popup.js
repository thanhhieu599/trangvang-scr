import {rows} from './db.js';
import {toCSV} from './core.js';
const el=id=>document.getElementById(id);
async function command(type) {
  try {
    const [tab] = await chrome.tabs.query({active:true,currentWindow:true});
    const response = await chrome.runtime.sendMessage({type,tabId:tab?.id,delay:Number(el('delay').value),maxPages:Number(el('limit').value)});
    if (!response?.ok) throw Error(response?.error || 'Không nhận được phản hồi.');
    const {config,pending,companies} = response.data;
    el('status').textContent = `${config?.running ? 'Đang chạy' : 'Đã dừng'}\n${companies} công ty · ${pending} trang chờ\n${config?.message || 'Chưa bắt đầu'}`;
  } catch(error) { el('status').textContent = error.message; }
}
for (const [id,type] of [['start','START'],['resume','RESUME'],['pause','PAUSE']]) el(id).onclick=()=>command(type);
el('export').onclick=async()=>{
  try {
    const data=await rows(), url=URL.createObjectURL(new Blob([toCSV(data)],{type:'text/csv;charset=utf-8'}));
    const a=document.createElement('a');a.href=url;a.download='trangvang-companies.csv';a.click();
    setTimeout(()=>URL.revokeObjectURL(url),10000);
    el('status').textContent=`Đã xuất ${data.length} công ty.`;
  } catch(error) { el('status').textContent=error.message; }
};
command('STATUS');
