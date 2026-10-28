package cn.courseinbox.companion;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;

/** Narrow HTTP transport: direct LAN, bounded requests, no redirects, no credentials in errors. */
public final class ComputerReminderHttp {
    public interface Connections {HttpURLConnection open(URL url)throws IOException;}
    public static final class Failure extends IOException {public final int status;Failure(int status){super("电脑提醒服务返回 "+status);this.status=status;}}
    private final Connections connections;
    public ComputerReminderHttp(){this(url->(HttpURLConnection)url.openConnection(Proxy.NO_PROXY));}
    public ComputerReminderHttp(Connections connections){this.connections=connections;}
    public String request(String endpoint,String path,String token,String body)throws IOException {
        String base=ComputerReminderProtocol.endpoint(endpoint);
        boolean post=path.equals("/v1/pair")||path.equals("/v1/ack");
        if(!(post||path.equals("/v1/alerts")||path.equals("/v1/health")))throw new IllegalArgumentException("不支持的提醒接口");
        if((post&&body==null)||(!post&&body!=null))throw new IllegalArgumentException("提醒请求格式不正确");
        if(token!=null&&!token.isEmpty()&&!token.matches("[A-Za-z0-9_-]{24,256}"))throw new IllegalArgumentException("设备配对信息无效，请重新配对");
        HttpURLConnection c=connections.open(new URL(base+path));
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(12);
        try {
            c.setInstanceFollowRedirects(false);c.setConnectTimeout(5000);c.setReadTimeout(5000);c.setUseCaches(false);
            c.setRequestMethod(post?"POST":"GET");c.setRequestProperty("Accept","application/json");
            if(token!=null&&!token.isEmpty())c.setRequestProperty("Authorization","Bearer "+token);
            if(body!=null){byte[] bytes=body.getBytes(StandardCharsets.UTF_8);if(bytes.length>65536)throw new IOException("提醒请求过大");c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json; charset=utf-8");c.setFixedLengthStreamingMode(bytes.length);try(OutputStream out=c.getOutputStream()){out.write(bytes);}}
            int status=c.getResponseCode();if(status!=200)throw new Failure(status);
            ByteArrayOutputStream bytes=new ByteArrayOutputStream();
            try(InputStream in=c.getInputStream()){byte[] block=new byte[4096];while(true){long remaining=TimeUnit.NANOSECONDS.toMillis(deadline-System.nanoTime());if(remaining<=0)throw new IOException("电脑提醒连接超时");c.setReadTimeout((int)Math.min(5000,remaining));int count=in.read(block);if(count<0)break;if(bytes.size()+count>2097152)throw new IOException("电脑提醒响应过大");bytes.write(block,0,count);}}
            return new String(bytes.toByteArray(),StandardCharsets.UTF_8);
        }finally{c.disconnect();}
    }
}
