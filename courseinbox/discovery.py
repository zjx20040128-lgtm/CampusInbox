"""Stable pairing identity and optional LAN discovery; never publishes credentials."""
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import tempfile
from pathlib import Path

SERVICE_TYPE = '_courseinbox._tcp.local.'
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))


def load_identity(directory: Path) -> dict:
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/'mobile-device.json'
    if not path.exists():
        ident=secrets.token_hex(16)
        obj={'device_id':ident,'name':'CourseInbox-'+ident[:8]}
        fd,tmp=tempfile.mkstemp(prefix='mobile-device-',dir=directory)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                json.dump(obj,stream);stream.flush();os.fsync(stream.fileno())
            try: os.link(tmp,path)
            except FileExistsError: pass
        finally: os.unlink(tmp)
    try:
        result=json.loads(path.read_text(encoding='utf-8-sig'))
        ident=result['device_id']
        if not isinstance(ident,str) or not re.fullmatch('[0-9a-f]{32}',ident) or result.get('name')!='CourseInbox-'+ident[:8]:
            raise ValueError()
        return {'device_id':ident,'name':result['name']}
    except (KeyError,TypeError,ValueError) as error:
        raise ValueError('mobile-device.json invalid; restore the saved identity before restarting') from error


def private_ipv4(address: str) -> bool:
    try:
        ip=ipaddress.ip_address(address)
        return isinstance(ip,ipaddress.IPv4Address) and any(ip in n for n in PRIVATE_NETWORKS)
    except ValueError: return False


def make_proof(identity: dict, token: str, challenge: str, address: str, port: int) -> dict:
    if not re.fullmatch('[0-9a-f]{64}',challenge) or not re.fullmatch('[0-9a-f]{32}',identity['device_id']):
        raise ValueError('Invalid pairing challenge')
    if str(ipaddress.IPv4Address(address))!=address or not 1<=port<=65535:
        raise ValueError('Invalid pairing endpoint')
    message='\n'.join(('courseinbox-pair-v1',identity['device_id'],challenge,address,str(port)))
    proof=hmac.new(token.encode('utf-8'),message.encode('utf-8'),hashlib.sha256).hexdigest()
    return dict(version=1,**identity,challenge=challenge,address=address,port=port,proof=proof)


import socket
import threading


def local_ipv4() -> set:
    """Read assigned adapter addresses rather than cached DNS when on Windows."""
    if os.name=='nt':
        import ctypes
        size=ctypes.c_ulong(0)
        api=ctypes.WinDLL('iphlpapi').GetIpAddrTable
        code=api(None,ctypes.byref(size),False)
        if code not in (0,122): raise OSError(code,'Cannot enumerate local IPv4')
        buffer=ctypes.create_string_buffer(size.value)
        code=api(buffer,ctypes.byref(size),False)
        if code: raise OSError(code,'Cannot enumerate local IPv4')
        count=int.from_bytes(buffer.raw[:4],'little')
        return {socket.inet_ntoa(buffer.raw[4+24*i:8+24*i]) for i in range(count)}
    try:
        import ifaddr
        return {ip.ip for adapter in ifaddr.get_adapters() for ip in adapter.ips if isinstance(ip.ip,str)}
    except ImportError:
        return set(socket.gethostbyname_ex(socket.gethostname())[2])


def gateway_ipv4(address_rows,route_rows):
    """Exclude host-only adapters; a phone-facing address needs a default gateway."""
    interfaces={int.from_bytes(row[16:20],'little') for row in route_rows
                if row[:8]==bytes(8) and row[12:16]!=bytes(4)}
    return {socket.inet_ntoa(row[:4]) for row in address_rows
            if int.from_bytes(row[4:8],'little') in interfaces and private_ipv4(socket.inet_ntoa(row[:4]))}


def lan_ipv4():
    if os.name!='nt':return {address for address in local_ipv4() if private_ipv4(address)}
    import ctypes
    def table(name,row_size):
        size=ctypes.c_ulong(0);api=getattr(ctypes.WinDLL('iphlpapi'),name)
        code=api(None,ctypes.byref(size),False)
        if code not in (0,122):raise OSError(code,'Cannot enumerate LAN adapters')
        buffer=ctypes.create_string_buffer(size.value);code=api(buffer,ctypes.byref(size),False)
        if code:raise OSError(code,'Cannot enumerate LAN adapters')
        count=int.from_bytes(buffer.raw[:4],'little')
        return [buffer.raw[4+i*row_size:4+(i+1)*row_size] for i in range(count)]
    return gateway_ipv4(table('GetIpAddrTable',24),table('GetIpForwardTable',56))


class MdnsPublisher:
    def __init__(self,identity,addresses,port):
        from zeroconf import Zeroconf,ServiceInfo,IPVersion
        self.zc=Zeroconf(interfaces=addresses,ip_version=IPVersion.V4Only)
        self.info=ServiceInfo(SERVICE_TYPE,identity['name']+'.'+SERVICE_TYPE,
            addresses=[socket.inet_aton(a) for a in addresses],port=port,
            properties={'version':'1',**identity},server=identity['name']+'.local.')
        try: self.zc.register_service(self.info)
        except Exception:
            self.zc.close();raise
    def close(self):
        try: self.zc.unregister_service(self.info)
        finally: self.zc.close()


class DiscoveryService:
    def __init__(self,directory: Path,token: str,host: str,port: int):
        self.identity=load_identity(directory)
        self.token,self.host,self.port=token,host,port
        self.lan=host in ('0.0.0.0','::') or private_ipv4(host)
        self.lock=threading.RLock()
        self.stop=threading.Event()
        self.thread=None
        self.publisher=None
        self.addresses=[]
        self.reason='尚未启用局域网发现；请运行 start-lan.cmd。'
        self.refresh_addresses()
    def allowed_hosts(self) -> set:
        with self.lock:
            hosts={'localhost','127.0.0.1','::1',*self.addresses}
            if self.host not in ('0.0.0.0','::'): hosts.add(self.host)
            return hosts
    def status(self) -> dict:
        with self.lock:
            return dict(version=1,**self.identity,available=self.publisher is not None,
                        reason=self.reason,addresses=list(self.addresses))
    def pairing(self,challenge: str,address: str) -> dict:
        if address not in self.allowed_hosts(): raise ValueError('Pairing host is not local')
        return make_proof(self.identity,self.token,challenge,address,self.port)
    def refresh_addresses(self):
        try: addresses=sorted(a for a in local_ipv4() if private_ipv4(a))
        except OSError:
            with self.lock: self.reason='无法读取电脑网络地址；稍后自动重试。'
            return
        if self.host not in ('0.0.0.0','::','127.0.0.1','localhost','::1'):
            addresses=[a for a in addresses if a==self.host]
        with self.lock:
            changed=addresses!=self.addresses
            self.addresses=addresses
            if self.stop.is_set() or self.thread is None or not self.lan: return
            if not changed and self.publisher is not None: return
            if self.publisher is not None:
                try: self.publisher.close()
                except Exception: pass
                self.publisher=None
            if not addresses:
                self.reason='没有可用的私有 IPv4；请连接 Wi-Fi。';return
            try:
                self.publisher=MdnsPublisher(self.identity,addresses,self.port)
                self.reason='已广播电脑身份；手机能否发现取决于当前 Wi-Fi。'
            except ImportError:
                self.reason='自动发现依赖未安装；运行 scripts/setup-mobile.ps1，或继续手动连接。'
            except Exception:
                self.reason='局域网发现暂不可用；检查网络和防火墙，仍可手动连接。'
    def start(self):
        if not self.lan or self.thread is not None: return
        self.thread=threading.Thread(target=self._run,name='CourseInbox-discovery',daemon=True)
        self.refresh_addresses()
        self.thread.start()
    def _run(self):
        while not self.stop.wait(2): self.refresh_addresses()
    def close(self):
        self.stop.set()
        if self.thread and self.thread.is_alive(): self.thread.join()
        with self.lock:
            if self.publisher:
                try: self.publisher.close()
                finally: self.publisher=None
            self.reason='电脑服务已关闭。'
