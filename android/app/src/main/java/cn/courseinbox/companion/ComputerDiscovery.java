package cn.courseinbox.companion;

import android.content.Context;
import android.content.SharedPreferences;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.net.nsd.NsdManager;
import android.net.wifi.WifiManager;
import android.net.nsd.NsdServiceInfo;
import android.os.Build;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.URI;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.ArrayDeque;
import java.util.Collections;
import java.util.List;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/** Bounded NSD and proof verification. Call only on a worker thread. */
public final class ComputerDiscovery {
    public static final Object CONFIG_LOCK=new Object();
    private static final String SERVICE_TYPE="_courseinbox._tcp.";
    private static final SecureRandom RANDOM=new SecureRandom();
    private ComputerDiscovery() { }
    public static String resolve(Context context,boolean allowPairing) throws Exception {
        Context app=context.getApplicationContext();
        SharedPreferences prefs=NotificationQueue.preferences(app);
        final String token,id,cached,wantedName;final int generation;
        synchronized(CONFIG_LOCK) {
            token=prefs.getString("token","").trim();id=prefs.getString("paired_device_id","");
            cached=prefs.getString("server","").trim();wantedName=prefs.getString("target_name","").trim();
            generation=prefs.getInt("config_generation",0);
        }
        if(token.length()<24)throw new IOException("请先保存电脑访问令牌，再进行配对。");
        if(id.isEmpty()&&!allowPairing)throw new IOException("尚未配对电脑，请点击自动寻找并配对。");
        if(prefs.getBoolean("pairing_required",false)&&!allowPairing)throw new IOException("令牌已更改，请重新配对后补传。");
        prefs.edit().putString("last_status","正在寻找并验证"+(id.isEmpty()?"电脑":"已配对电脑")+"…").apply();
        ConnectionResolver.Verified result=ConnectionResolver.resolve(cached,id,
            ()->new Browser(app,wantedName.isEmpty()&&!id.isEmpty()?"CourseInbox-"+id.substring(0,8):wantedName),
            (endpoint,expected,deadline)->{
                ConnectionResolver.Verified candidate=verifyEndpoint(endpoint,token,expected,deadline);
                if(!wantedName.isEmpty()&&!wantedName.equals(candidate.name))throw new IOException("电脑名称不匹配。");
                return candidate;
            },15000);
        synchronized(CONFIG_LOCK) {
            if(generation!=prefs.getInt("config_generation",0)||!token.equals(prefs.getString("token","").trim())||!id.equals(prefs.getString("paired_device_id","")))
                throw new IOException("配置已改变，旧配对结果已取消；请重新操作。");
            if(!wantedName.isEmpty()&&!wantedName.equals(result.name))throw new IOException("电脑名称不匹配，请核对电脑页面的配对名称。");
            if(!prefs.edit().putString("server",result.endpoint).putString("paired_device_id",result.deviceId)
                .putString("paired_name",result.name).putBoolean("pairing_required",false)
                .putString("last_status","已配对 "+result.name+"；连接地址已自动更新。").commit())throw new IOException("配对配置保存失败，请重试。");
        }
        return result.endpoint;
    }
    public static boolean privateIpv4(String host) {
        if(host==null||!host.matches("[0-9]+(?:\\.[0-9]+){3}"))return false;
        String[] parts=host.split("\\.");int[] a=new int[4];
        try {for(int i=0;i<4;i++){a[i]=Integer.parseInt(parts[i]);if(a[i]>255||!Integer.toString(a[i]).equals(parts[i]))return false;}}
        catch(NumberFormatException error){return false;}
        return a[0]==10||(a[0]==192&&a[1]==168)||(a[0]==172&&a[1]>=16&&a[1]<=31);
    }
    private static int timeout(long deadline) throws IOException {
        long remaining=TimeUnit.NANOSECONDS.toMillis(deadline-System.nanoTime());
        if(remaining<=0)throw new IOException("寻找电脑超时，事件保留。");
        return (int)Math.min(3000,remaining);
    }
    private static ConnectionResolver.Verified verifyEndpoint(String endpoint,String token,String expectedId,long deadline) throws Exception {
        URI base=new URI(endpoint);
        if(!"http".equals(base.getScheme())||!privateIpv4(base.getHost())||!NotificationQueue.allowedEndpoint(base))
            throw new IOException("自动配对仅支持电脑私有 IPv4 地址。");
        int port=base.getPort()==-1?80:base.getPort();
        byte[] nonce=new byte[32];RANDOM.nextBytes(nonce);StringBuilder hex=new StringBuilder(64);
        for(byte b:nonce)hex.append(String.format(java.util.Locale.ROOT,"%02x",b&255));
        String challenge=hex.toString();
        HttpURLConnection connection=(HttpURLConnection)new URL(endpoint.replaceAll("/+$","")+"/api/mobile/pairing?challenge="+challenge).openConnection();
        try {
            connection.setInstanceFollowRedirects(false);connection.setConnectTimeout(timeout(deadline));connection.setReadTimeout(timeout(deadline));
            // No Authorization header until this response proves the pinned identity.
            connection.connect();connection.setReadTimeout(timeout(deadline));
            if(connection.getResponseCode()!=200)throw new IOException("电脑不支持配对验证，请升级或检查服务地址。");
            ByteArrayOutputStream bytes=new ByteArrayOutputStream();
            try(InputStream input=connection.getInputStream()) {
                byte[] block=new byte[1024];int count;
                while(true){connection.setReadTimeout(timeout(deadline));count=input.read(block);if(count==-1)break;if(bytes.size()+count>8192)throw new IOException("配对响应过大。");bytes.write(block,0,count);}
            }
            JSONObject proof=new JSONObject(new String(bytes.toByteArray(),StandardCharsets.UTF_8));
            String actualId=proof.getString("device_id"),name=proof.getString("name");
            if(proof.getInt("version")!=1 || !challenge.equals(proof.getString("challenge")) || !base.getHost().equals(proof.getString("address")) || port!=proof.getInt("port") ||
                !name.equals("CourseInbox-"+actualId.substring(0,Math.min(8,actualId.length()))) ||
                !PairingProof.verify(token,expectedId,challenge,base.getHost(),port,actualId,proof.getString("proof")))
                throw new IOException("电脑身份或令牌验证失败，未发送访问令牌。");
            return new ConnectionResolver.Verified("http://"+base.getHost()+":"+port,actualId,name);
        } finally {connection.disconnect();}
    }
    private static final class Browser implements ConnectionResolver.Candidates {
        private final NsdManager manager;
        private final String wantedName;
        private WifiManager.MulticastLock multicastLock;
        private final BlockingQueue<NsdServiceInfo> found=new ArrayBlockingQueue<>(32);
        private final ArrayDeque<String> ready=new ArrayDeque<>();
        private final Set<String> seen=Collections.synchronizedSet(new HashSet<>());
        private final AtomicBoolean closed=new AtomicBoolean(false);
        private volatile String failure="";
        private final NsdManager.DiscoveryListener listener=new NsdManager.DiscoveryListener() {
            public void onDiscoveryStarted(String type){if(closed.get())stopDiscovery();}
            public void onServiceFound(NsdServiceInfo service){
                if(!closed.get()&&service.getServiceType().startsWith(SERVICE_TYPE)&&
                   (wantedName.isEmpty()||wantedName.equals(service.getServiceName()))&&seen.add(service.getServiceName()))found.offer(service);
            }
            public void onServiceLost(NsdServiceInfo service) { }
            public void onDiscoveryStopped(String type) { }
            public void onStartDiscoveryFailed(String type,int code){failure="网络发现启动失败（"+code+"）；可使用当前地址手动连接。";stopDiscovery();}
            public void onStopDiscoveryFailed(String type,int code) { }
        };
        Browser(Context app,String wantedName) throws IOException {
            this.wantedName=wantedName;
            ConnectivityManager connectivity=(ConnectivityManager)app.getSystemService(Context.CONNECTIVITY_SERVICE);
            boolean wifi=false;
            for(android.net.Network network:connectivity.getAllNetworks()) {
                NetworkCapabilities caps=connectivity.getNetworkCapabilities(network);
                if(caps!=null&&caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)){wifi=true;break;}
            }
            if(!wifi)throw new IOException("请连接与电脑相同的 Wi-Fi，再寻找电脑。");
            manager=(NsdManager)app.getSystemService(Context.NSD_SERVICE);
            if(manager==null)throw new IOException("此手机的网络发现服务不可用，请手动连接。");
            try {
                WifiManager wifiManager=(WifiManager)app.getSystemService(Context.WIFI_SERVICE);
                if(wifiManager==null)throw new IllegalStateException("Wi-Fi service unavailable");
                multicastLock=wifiManager.createMulticastLock("CourseInbox-discovery");
                multicastLock.setReferenceCounted(false);multicastLock.acquire();
                manager.discoverServices(SERVICE_TYPE,NsdManager.PROTOCOL_DNS_SD,listener);
            }
            catch(RuntimeException error){close();throw new IOException("无法启动网络发现，请手动连接。",error);}
        }
        public String next(long deadline) throws Exception {
            while(!closed.get()&&System.nanoTime()<deadline) {
                if(!ready.isEmpty())return ready.removeFirst();
                if(!failure.isEmpty())throw new IOException(failure);
                NsdServiceInfo candidate=found.poll(Math.min(200,timeout(deadline)),TimeUnit.MILLISECONDS);
                if(candidate==null)continue;
                AtomicInteger errorCode=new AtomicInteger(-1);
                NsdServiceInfo info;
                try {
                    info=CandidateResolution.await(new CandidateResolution.Operation<NsdServiceInfo>() {
                        private final AtomicBoolean active=new AtomicBoolean(true);
                        private NsdManager.ResolveListener resolver;
                        public void start(java.util.function.Consumer<NsdServiceInfo> callback) {
                            resolver=new NsdManager.ResolveListener() {
                                public void onResolveFailed(NsdServiceInfo service,int code){errorCode.set(code);if(active.get())callback.accept(null);}
                                public void onServiceResolved(NsdServiceInfo service){if(active.get()&&!closed.get())callback.accept(service);}
                            };
                            manager.resolveService(candidate,resolver);
                        }
                        public void cancel() {
                            active.set(false);
                            if(resolver!=null&&canStopResolution())try{manager.stopServiceResolution(resolver);}catch(RuntimeException ignored){}
                        }
                    },deadline,3000);
                } catch(RuntimeException ignored){continue;}
                if(info==null) {
                    // Legacy Android cannot cancel resolution. Retry busy candidates while
                    // its system operation finishes, without blocking this browser on one host.
                    if(errorCode.get()==NsdManager.FAILURE_ALREADY_ACTIVE&&System.nanoTime()<deadline){found.offer(candidate);Thread.sleep(Math.min(100,timeout(deadline)));}
                    continue;
                }
                List<InetAddress> hosts=Build.VERSION.SDK_INT>=34?info.getHostAddresses():Collections.singletonList(info.getHost());
                for(InetAddress address:hosts)if(address instanceof Inet4Address && privateIpv4(address.getHostAddress())&&info.getPort()>0&&info.getPort()<=65535)
                    ready.add("http://"+address.getHostAddress()+":"+info.getPort());
            }
            return null;
        }
        private boolean canStopResolution(){
            return Build.VERSION.SDK_INT>=34||(Build.VERSION.SDK_INT>=33&&android.os.ext.SdkExtensions.getExtensionVersion(33)>=7);
        }
        private void stopDiscovery(){try{manager.stopServiceDiscovery(listener);}catch(RuntimeException ignored){}}
        public void close(){
            closed.set(true);
            try {stopDiscovery();found.clear();ready.clear();}
            finally {if(multicastLock!=null&&multicastLock.isHeld())multicastLock.release();}
        }
    }
}
