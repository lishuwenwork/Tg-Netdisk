import {_electron as electron} from 'playwright';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=path.resolve(import.meta.dirname,'..');
const environment={...process.env,TG_DATA_DIR:path.join(root,'.runtime','exit-save-data')};
delete environment.ELECTRON_RUN_AS_NODE;delete environment.TG_DEV;
const options={...(process.env.TG_SMOKE_EXE?{executablePath:process.env.TG_SMOKE_EXE,args:[]}:{args:[root]}),env:environment,timeout:60000};
let desktop,window;
try {
  desktop=await electron.launch(options);window=await desktop.firstWindow({timeout:60000});
  await window.getByText('本地服务已连接',{exact:true}).waitFor({timeout:30000});
  const expected=`退出保存 ${Date.now()}`;
  const connection=await window.evaluate(()=>globalThis.desktop.connection());
  await window.getByLabel('标题',{exact:true}).fill(expected);
  const exited=new Promise(resolve=>desktop.process().once('exit',resolve));
  await window.evaluate(()=>globalThis.desktop.quit()).catch(()=>{});
  await Promise.race([exited,new Promise((_,reject)=>setTimeout(()=>reject(new Error('Quit did not complete')),10000))]);
  await desktop.close().catch(()=>{});
  let alive=false;
  try {const response=await fetch(`${connection.baseUrl}/api/health`,{headers:{Authorization:`Bearer ${connection.token}`},signal:AbortSignal.timeout(1000)});alive=response.ok;}catch{}
  assert.equal(alive,false,'Python child survived desktop exit');
  desktop=await electron.launch(options);window=await desktop.firstWindow({timeout:60000});
  await window.getByText('本地服务已连接',{exact:true}).waitFor({timeout:30000});
  assert.equal(await window.getByLabel('标题',{exact:true}).inputValue(),expected);
  console.log('Exit/restart check passed: last input saved immediately, Python child stopped, draft restored.');
} finally {
  if(window) await window.evaluate(()=>globalThis.desktop.quit()).catch(()=>{});
  await desktop?.close().catch(()=>{});
}
