"""Optional local visual QA using installed Edge and its DevTools protocol.

No browser/tooling installation. Temporary profiles/screenshots are written
only inside app/verification (ignored). This is not application frontend code.
"""
import base64
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen
from websockets.sync.client import connect

APP = Path(__file__).resolve().parents[1]
OUTPUT = APP / 'verification'
EDGE = Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
URL = os.getenv('RENTAL_DEMO_URL', 'http://127.0.0.1:8501')

def main():
    OUTPUT.mkdir(exist_ok=True)
    process = subprocess.Popen([str(EDGE),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=9224',f'--user-data-dir={OUTPUT / "browser-profile"}',URL],creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        targets=[]
        for _ in range(100):
            try:
                with urlopen('http://127.0.0.1:9224/json',timeout=1) as response:
                    targets=json.load(response)
                if any(target.get('type')=='page' for target in targets):break
            except OSError:pass
            time.sleep(.1)
        target=next(target for target in targets if target.get('type')=='page' and URL in target.get('url',''))
        with connect(target['webSocketDebuggerUrl'],max_size=20_000_000) as ws:
            sequence=0
            errors=[]
            contexts={}
            def call(method,params=None,session_id=None):
                nonlocal sequence
                sequence+=1
                command={'id':sequence,'method':method,'params':params or {}}
                if session_id:command['sessionId']=session_id
                ws.send(json.dumps(command))
                while True:
                    message=json.loads(ws.recv(timeout=30))
                    if message.get('method')=='Runtime.executionContextCreated':
                        context=message['params']['context']
                        contexts[context['id']]=context
                    if message.get('method')=='Runtime.executionContextDestroyed':
                        contexts.pop(message['params']['executionContextId'],None)
                    if message.get('method')=='Runtime.executionContextsCleared':
                        contexts.clear()
                    if message.get('method')=='Runtime.exceptionThrown':errors.append(message)
                    if message.get('method')=='Log.entryAdded' and message.get('params',{}).get('entry',{}).get('level')=='error':errors.append(message)
                    if message.get('id')==sequence:
                        if 'error' in message:raise RuntimeError(message['error'])
                        return message.get('result',{})
            def evaluate(expression,context_id=None):
                params={'expression':expression,'returnByValue':True}
                if context_id is not None:params['contextId']=context_id
                return call('Runtime.evaluate',params).get('result',{}).get('value')
            def wait(expression):
                for _ in range(160):
                    if evaluate(expression):return
                    time.sleep(.25)
                print('TIMEOUT_PAGE',evaluate('({url:location.href,text:document.body.innerText})'))
                print('ERRORS',json.dumps(errors,ensure_ascii=False)[:4000])
                capture('browser-timeout.png',1440,900)
                raise RuntimeError(f'Browser condition timed out: {expression}')
            def click(label):
                label=json.dumps(label)
                assert evaluate(f'(()=>{{const b=[...document.querySelectorAll("button")].find(b=>b.textContent.trim().endsWith({label}));if(!b)return false;b.click();return true;}})()')
            def capture(name,width,height):
                call('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width<600})
                time.sleep(3)
                if name == 'chat-desktop.png':
                    assert evaluate('(()=>{const b=document.querySelector("[class*=st-key-chat-user-] [data-testid=stChatMessage]");const p=b?.querySelector("p");if(!b||!p)return false;const r=b.getBoundingClientRect(),t=p.getBoundingClientRect();return getComputedStyle(b).borderRadius==="22px"&&t.bottom<=r.bottom&&t.right<=r.right;})()'), 'User bubble must contain the full message.'
                print("GEOMETRY",evaluate('["global-rail","chat-history","chat-thread","map-panel","listing-panel"].map(k=>{const e=document.querySelector(".st-key-"+k);return {key:k,rect:e?e.getBoundingClientRect().toJSON():null,tag:e?.getAttribute("data-testid"),parent:e?.parentElement.outerHTML.slice(0,300)}})'))
                result=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
                (OUTPUT/name).write_bytes(base64.b64decode(result['data']))
                return evaluate('({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,traceback:document.body.innerText.includes("Traceback")})')
            call('Runtime.enable')
            call('Log.enable')
            call('Page.enable')
            call('Page.navigate',{'url':URL})
            call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':900,'deviceScaleFactor':1,'mobile':False})
            wait('document.body.innerText.includes("Continue with demo account")')
            click('Continue with demo account')
            wait('document.body.innerText.includes("How can I help with your rental search?")')
            capture('home-desktop.png',1440,900)
            click('Find a room under SGD 2,500 near NUS with MRT access.')
            wait('document.body.innerText.includes("Recommended listings")')
            wait('document.querySelectorAll("iframe").length > 0')
            # Click a real Folium listing marker through the embedded iframe.
            marker_clicked=evaluate('(()=>{for(const frame of document.querySelectorAll("iframe")){try{const markers=frame.contentDocument.querySelectorAll(".leaflet-marker-icon");if(markers.length>2){markers[2].click();return true;}}catch(e){}}return false;})()')
            if not marker_clicked:
                for context_id in list(contexts):
                    try:
                        count=evaluate('document.querySelectorAll(".leaflet-marker-icon").length',context_id)
                    except RuntimeError:
                        continue
                    if count and count>2:
                        marker_clicked=evaluate('document.querySelectorAll(".leaflet-marker-icon")[2].click();true',context_id)
                        break
            if not marker_clicked:
                for info in call('Target.getTargets').get('targetInfos',[]):
                    if info['type']=='iframe':
                        attached=call('Target.attachToTarget',{'targetId':info['targetId'],'flatten':True})['sessionId']
                        result=call('Runtime.evaluate',{'expression':'(()=>{const markers=document.querySelectorAll(".leaflet-marker-icon");if(markers.length>2){markers[2].click();return true;}return false;})()','returnByValue':True},attached)
                        if result.get('result',{}).get('value'):
                            marker_clicked=True
                            break
            if marker_clicked:
                wait('document.body.innerText.includes("Recommended listings")')
            print('MAP_MARKER_CLICK',marker_clicked)
            assert evaluate('document.body.innerText.includes("V2 data locations") && document.body.innerText.includes("checked 2026-10-04")'), 'V2 source and snapshot date must be visible.'
            print('CHAT_DESKTOP',capture('chat-desktop.png',1440,900))
            print('CHAT_MOBILE',capture('chat-mobile.png',390,844))
            # Restore desktop for navigation, then inspect all remaining pages.
            call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':900,'deviceScaleFactor':1,'mobile':False})
            for page in ['Profile','Favorites']:
                click(page)
                wait(f'[...document.querySelectorAll("h1")].some(h=>h.textContent==={json.dumps(page)})')
                time.sleep(.5)
                print('PAGE',page,'TRACEBACK',evaluate('document.body.innerText.includes("Traceback")'))
                if page=='Evaluation':capture('evaluation-desktop.png',1440,900)
            # Return to main demo before closing the QA browser.
            click('Home')
            wait('document.body.innerText.includes("Recommended listings")')
            click('Hide conversation history')
            print('COLLAPSED',capture('home-collapsed.png',1440,900))
            click('Toggle conversation history')
            wait('[...document.querySelectorAll("button")].some(b=>b.textContent.trim().endsWith("New conversation"))')
            click('New conversation')
            wait('document.body.innerText.includes("How can I help with your rental search?")')
            capture('new-chat-reset.png',1440,900)
            print('BROWSER_ERRORS',json.dumps(errors,ensure_ascii=False)[:4000])
            print('SCREENSHOTS',str(OUTPUT))
    finally:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill()

if __name__=='__main__':main()
