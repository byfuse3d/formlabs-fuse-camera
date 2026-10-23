const path=require('node:path');const htmlSource=require('node:fs').readFileSync(path.join(__dirname,'../examples/browser/fuse-camera-viewer.html'),'utf8');const workerSource=htmlSource.match(/<script id="cameraWorker" type="text\/plain">([\s\S]*?)<\/script>/)[1];const pageSource=[...htmlSource.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n');
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const messages=[],decodeJobs=[];let time=0;
class FakeSocket{static OPEN=1;static all=[];constructor(){this.readyState=0;this.bufferedAmount=0;this.sent=[];FakeSocket.all.push(this);}send(s){this.sent.push(s);}close(){this.readyState=3;}}
const scope={self:{postMessage:m=>messages.push(m)},WebSocket:FakeSocket,Blob,Uint8Array,performance:{now:()=>time},setTimeout:()=>1,clearTimeout(){},createImageBitmap:()=>new Promise(resolve=>decodeJobs.push(resolve))};vm.createContext(scope);vm.runInContext(workerSource,scope);
const jpeg=()=>new Uint8Array([255,216,255,217]).buffer;
(async()=>{
 scope.self.onmessage({data:{type:'connect',url:'ws://printer.local:8084/',rate:0}});const ws=FakeSocket.all[0];ws.readyState=1;ws.onopen();assert.equal(ws.sent.length,1);
 scope.self.onmessage({data:{type:'rate',rate:0}});assert.equal(ws.sent.length,1,'No second request while first is outstanding');
 ws.onmessage({data:'{"width":1280,"height":1024,"action":"init"}'});assert.equal(ws.sent.length,1,'Initialization metadata does not consume the pending image request');assert.equal(ws.readyState,1);
 time=200;ws.onmessage({data:jpeg()});assert.equal(ws.sent.length,2,'Request next image immediately after receipt');
 time=400;ws.onmessage({data:jpeg()});assert.equal(ws.sent.length,3);assert.equal(decodeJobs.length,1,'Decode only one frame at once');
 let closed=0;decodeJobs.shift()({close(){closed++;}});await new Promise(r=>setImmediate(r));assert.equal(closed,1,'Drop stale decoded frame');assert.equal(decodeJobs.length,1);
 decodeJobs.shift()({width:1280,height:1024,close(){closed++;}});await new Promise(r=>setImmediate(r));assert.equal(messages.filter(m=>m.type==='frame').length,1,'Deliver newest frame only');
 ws.onmessage({data:new Uint8Array([1,2,3]).buffer});assert.equal(ws.readyState,3);assert.equal(messages.at(-1).type,'error');
 console.log('PASS: one outstanding request, response-paced capture, bounded decoding, stale-frame dropping, invalid-image handling');
})().catch(e=>{console.error(e);process.exitCode=1;});
