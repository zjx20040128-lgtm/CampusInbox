package cn.courseinbox.companion;

import java.io.IOException;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.TimeUnit;

/** Recovery policy separated from Android and network IO. */
public final class ConnectionResolver {
    public static final class Verified {
        public final String endpoint,deviceId,name;
        public Verified(String endpoint,String deviceId,String name) {this.endpoint=endpoint;this.deviceId=deviceId;this.name=name;}
    }
    public interface Candidates extends AutoCloseable { String next(long deadline) throws Exception; void close(); }
    public interface Source { Candidates open() throws Exception; }
    public interface Verifier { Verified verify(String endpoint,String expectedId,long deadline) throws Exception; }
    private ConnectionResolver() { }
    public static Verified resolve(String cached,String expectedId,Source source,Verifier verifier,long budgetMillis) throws Exception {
        long deadline=System.nanoTime()+TimeUnit.MILLISECONDS.toNanos(budgetMillis);
        Exception last=null;
        if(!cached.isEmpty() && System.nanoTime()<deadline) {
            try { Verified v=verifier.verify(cached,expectedId,deadline); if(matches(v,expectedId)) return v; }
            catch(Exception error) {last=error;}
        }
        if(System.nanoTime()>=deadline)throw new IOException("寻找电脑超时；事件保留。",last);
        Set<String> tried=new HashSet<>();tried.add(cached);
        try(Candidates candidates=source.open()) {
            while(System.nanoTime()<deadline) {
                String endpoint=candidates.next(deadline);
                if(endpoint==null) break;
                if(!tried.add(endpoint))continue;
                try {Verified v=verifier.verify(endpoint,expectedId,deadline);if(matches(v,expectedId))return v;}
                catch(Exception error) {last=error;}
            }
        }
        throw new IOException(last==null?"未找到已配对电脑；请确认电脑已启动，或使用当前地址手动连接。":"未能验证电脑；请检查令牌、电脑身份和网络，事件保留。",last);
    }
    private static boolean matches(Verified value,String expectedId) {
        return value!=null && (expectedId.isEmpty()||expectedId.equals(value.deviceId));
    }
}
