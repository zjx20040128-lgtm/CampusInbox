"""Opt-in real mDNS integration check using only temporary data and a fake token."""
import hashlib
import hmac
import json
import secrets
import tempfile
import threading
import urllib.request
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from courseinbox.core import Inbox
from courseinbox.http import create_server
from zeroconf import Zeroconf,ServiceBrowser,IPVersion
from courseinbox.discovery import SERVICE_TYPE


def main():
    with tempfile.TemporaryDirectory() as tmp:
        token='verification-token-not-a-real-device-secret'
        server=create_server('0.0.0.0',0,Inbox(Path(tmp)/'inbox.sqlite3'),token)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        state=server.discovery.status()
        if not state['available']:
            server.shutdown();server.server_close();thread.join()
            raise RuntimeError(state['reason'])
        added,removed=threading.Event(),threading.Event()
        name=state['name']+'.'+SERVICE_TYPE
        observer=Zeroconf(interfaces=state['addresses'],ip_version=IPVersion.V4Only)
        class Listener:
            def add_service(self,zc,type_,candidate):
                if candidate==name:added.set()
            def update_service(self,zc,type_,candidate): pass
            def remove_service(self,zc,type_,candidate):
                if candidate==name:removed.set()
        browser=ServiceBrowser(observer,SERVICE_TYPE,listener=Listener())
        result={}
        try:
            if not added.wait(8):raise RuntimeError('Same-computer mDNS service not found')
            info=observer.get_service_info(SERVICE_TYPE,name,timeout=3000)
            if not info:raise RuntimeError('mDNS service did not resolve')
            addresses=info.parsed_addresses(IPVersion.V4Only)
            assert info.properties[b'device_id'].decode()==state['device_id']
            assert set(info.properties)=={b'version',b'device_id',b'name'}
            address=addresses[0];challenge=secrets.token_hex(32)
            url=f'http://{address}:{info.port}/api/mobile/pairing?challenge={challenge}'
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url,timeout=4) as response:proof=json.load(response)
            message='\n'.join(('courseinbox-pair-v1',state['device_id'],challenge,address,str(info.port)))
            expected=hmac.new(token.encode(),message.encode(),hashlib.sha256).hexdigest()
            assert proof['proof']==expected and proof['challenge']==challenge and proof['address']==address
            result={'same_computer_discovery':True,'proof_verified':True,'addresses':addresses,'port':info.port,'properties_without_token':True}
        finally:
            server.shutdown();server.server_close();thread.join()
            result['unregistered']=removed.wait(5)
            browser.cancel();observer.close()
        assert result['unregistered'],'Service goodbye was not observed'
        print(json.dumps(result))
        return result

if __name__=='__main__':main()
