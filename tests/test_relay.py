import base64,hashlib,importlib.util,io,json,socket,socketserver,struct,sys,threading,time,urllib.request
from pathlib import Path
spec=importlib.util.spec_from_file_location('fuse_relay',Path(__file__).resolve().parents[1] / 'formlabs_fuse_camera/relay.py');m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
from PIL import Image
out=io.BytesIO();Image.new('RGB',(24,16),'purple').save(out,format='JPEG');JPEG=out.getvalue()
class Fake(socketserver.BaseRequestHandler):
 def handle(self):
  s=self.request;s.settimeout(3);data=b''
  try:
   while b'\r\n\r\n' not in data:data+=s.recv(4096)
   headers={line.split(b':',1)[0].lower():line.split(b':',1)[1].strip() for line in data.split(b'\r\n')[1:] if b':' in line};key=headers[b'sec-websocket-key'];accept=base64.b64encode(hashlib.sha1(key+b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
   with self.server.lock:self.server.connections+=1
   s.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+b'\r\n\r\n'+b'\x81\x11{"action":"init"}'+b'\x89\x02hi')
   def read(n):
    result=b''
    while len(result)<n:
     chunk=s.recv(n-len(result))
     if not chunk:raise EOFError
     result+=chunk
    return result
   first=True;requests=0
   while True:
    h=read(2);assert h[1]&128;mask=read(4);raw=read(h[1]&127);payload=bytes(v^mask[i%4] for i,v in enumerate(raw));op=h[0]&15
    if op==10:assert payload==b'hi';continue
    assert op==1 and payload==b' '
    requests+=1
    if requests<=2:continue
    time.sleep(.03)
    if first:
     cut=100;s.sendall(b'\x02'+bytes([cut])+JPEG[:cut]+b'\x80\x7e'+struct.pack('>H',len(JPEG)-cut)+JPEG[cut:]);first=False
    else:s.sendall(b'\x82\x7e'+struct.pack('>H',len(JPEG))+JPEG)
  except (OSError,EOFError):pass
class TCP(socketserver.ThreadingTCPServer):allow_reuse_address=True;daemon_threads=True
fake=TCP(('127.0.0.1',0),Fake);fake.connections=0;fake.lock=threading.Lock();threading.Thread(target=fake.serve_forever,daemon=True).start()
source=m.CameraSource(m.Settings(printer_host='127.0.0.1',printer_port=fake.server_address[1],idle_seconds=1))
server=m.make_server(source,('127.0.0.1',0));threading.Thread(target=server.serve_forever,daemon=True).start();base='http://127.0.0.1:'+str(server.server_address[1]);streams=[]
def frame(response):
 assert response.readline().strip()==b'--fuseframe';headers={}
 while (line:=response.readline().strip()):
  k,v=line.split(b':',1);headers[k.lower()]=v.strip()
 data=response.read(int(headers[b'content-length']));assert data==JPEG;assert response.read(2)==b'\r\n';return data
try:
 for _ in range(2):
  response=urllib.request.urlopen(base+'/stream',timeout=5);streams.append(response);frame(response)
 snap=urllib.request.urlopen(base+'/snapshot.jpg',timeout=5);assert snap.headers['Content-Type']=='image/jpeg';Image.open(io.BytesIO(snap.read())).load();snap.close()
 assert fake.connections==1,'All HTTP consumers must share one printer connection'
 stats=json.load(urllib.request.urlopen(base+'/health'));assert stats['viewers']==2;assert stats['frames']>=1
 for response in streams:response.close()
 deadline=time.monotonic()+4
 while time.monotonic()<deadline and source.connection is not None:time.sleep(.1)
 assert source.connection is None,'Idle camera connection must close'
 assert source.clients==0
 print('PASS: WebSocket handshake/init, masked requests, ping/pong, fragmented JPEGs, MJPEG, valid snapshot, shared camera connection, idle shutdown')
finally:
 for response in streams:response.close()
 source.stop();server.shutdown();server.server_close();fake.shutdown();fake.server_close()
