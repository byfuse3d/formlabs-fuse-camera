const path=require('node:path');const htmlSource=require('node:fs').readFileSync(path.join(__dirname,'../examples/browser/fuse-camera-viewer.html'),'utf8');const workerSource=htmlSource.match(/<script id="cameraWorker" type="text\/plain">([\s\S]*?)<\/script>/)[1];const pageSource=[...htmlSource.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n');
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=htmlSource;let draws=0,raf=null;
class El{constructor(){this.value='';this.handlers={};this.attributes={};this.hidden=false;this.textContent='';}addEventListener(k,f){this.handlers[k]=f;}setAttribute(k,v){this.attributes[k]=v;}getContext(){return{drawImage(){draws++;}};}}
const els=Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new El()]));els.host.value='printer.local';els.rate.value='0';els.cameraWorker.textContent=workerSource;
class FakeWorker{static all=[];constructor(){this.messages=[];FakeWorker.all.push(this);}postMessage(m){this.messages.push(m);}terminate(){this.ended=true;}}
const Url=URL;Url.createObjectURL=()=> 'blob:test';Url.revokeObjectURL=()=>{};
const scope={document:{getElementById:id=>els[id]},window:{addEventListener(){}},Worker:FakeWorker,Blob,URL:Url,performance:{now:()=>1000},requestAnimationFrame:f=>(raf=f,1),cancelAnimationFrame(){raf=null;}};
vm.createContext(scope);vm.runInContext(pageSource,scope);
els.connectForm.handlers.submit({preventDefault(){}});const w=FakeWorker.all[0];assert.equal(w.messages[0].url,'ws://printer.local:8084/');assert.equal(w.messages[0].rate,0);
let closed=0;const packet=()=>({type:'frame',bitmap:{width:1280,height:1024,close(){closed++;}},jpeg:new Uint8Array([255,216,255]).buffer,received:2,receivedFps:3});
w.onmessage({data:packet()});w.onmessage({data:packet()});assert.equal(closed,1,'Drop old pending bitmap');raf();assert.equal(draws,1);assert.equal(closed,2);assert.equal(els.frame.hidden,false);assert.match(els.stats.textContent,/3.0 FPS received/);
els.save.handlers.click({preventDefault(){throw Error('Should allow image saving');}});assert.equal(els.save.download,'fuse-camera.jpg');els.disconnect.handlers.click();assert.equal(w.ended,true);
w.onmessage({data:packet()});assert.equal(closed,3,'Close bitmap arriving after disconnect');assert.equal(draws,1);assert.equal(els.connect.disabled,false);
console.log('PASS: worker startup, latest-frame canvas painting, image saving, disconnect cleanup, stale-message disposal');
