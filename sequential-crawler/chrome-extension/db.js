let opened;
export function database() {
  return opened ||= new Promise((resolve, reject) => {
    const request = indexedDB.open('trangvang-collector', 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      db.createObjectStore('meta');
      const tasks = db.createObjectStore('tasks', {keyPath: 'id'});
      tasks.createIndex('pending', ['status','priority','order']);
      db.createObjectStore('companies', {keyPath: 'id'});
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
export const req = request => new Promise((resolve, reject) => {
  request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
});
export async function transaction(stores, mode, fn) {
  const db = await database(), tx = db.transaction(stores, mode);
  const complete = new Promise((resolve,reject) => {
    tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error || Error('Transaction aborted'));
  });
  try { const result = await fn(tx); await complete; return result; }
  catch (e) { try { tx.abort(); } catch {} await complete.catch(() => {}); throw e; }
}
export const state = () => transaction(['meta'], 'readonly', tx => req(tx.objectStore('meta').get('state')));
export const saveState = value => transaction(['meta'], 'readwrite', tx => req(tx.objectStore('meta').put(value, 'state')));
export async function enqueue(store, entry, config) {
  if (!await req(store.get(entry.id))) {
    entry.order = ++config.sequence; await req(store.add(entry));
  }
}
export const nextTask = store => req(store.index('pending').get(IDBKeyRange.bound(['pending',-100000,0],['pending',100000,Number.MAX_SAFE_INTEGER])));
export async function rows() {
  return transaction(['companies'], 'readonly', tx => req(tx.objectStore('companies').getAll()));
}
export async function statistics() {
  return transaction(['tasks','companies','meta'], 'readonly', async tx => {
    const config = await req(tx.objectStore('meta').get('state'));
    const pending = await req(tx.objectStore('tasks').index('pending').count(IDBKeyRange.bound(['pending',-100000,0],['pending',100000,Number.MAX_SAFE_INTEGER])));
    const companies = await req(tx.objectStore('companies').count());
    return {config, pending, companies};
  });
}
