package cn.courseinbox.companion;

import android.content.Context;
import android.content.SharedPreferences;
import org.json.JSONArray;
import org.json.JSONObject;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Persistent FIFO; only acknowledged events are removed. Does not promise background scheduling. */
public final class NotificationQueue {
    private static final Object LOCK = new Object();
    private static final ExecutorService WORKER = Executors.newSingleThreadExecutor();
    private static boolean flushing = false;
    private NotificationQueue() { }
    public static SharedPreferences preferences(Context context) {
        return context.getApplicationContext().getSharedPreferences("courseinbox", Context.MODE_PRIVATE);
    }
    private static JSONArray read(SharedPreferences prefs) {
        try { return new JSONArray(prefs.getString("queue", "[]")); }
        catch (Exception error) { prefs.edit().putString("last_status", "队列文件异常，请保留数据后检查。").commit(); return new JSONArray(); }
    }
    public static int count(Context context) { synchronized(LOCK) { return read(preferences(context)).length(); } }
    public static boolean enqueue(Context context, JSONObject event) {
        synchronized(LOCK) {
            SharedPreferences prefs = preferences(context);
            JSONArray queue = read(prefs);
            String signature = event.optString("notification_key") + "|" + event.optString("captured_at") + "|" + event.optString("title") + "|" + event.optString("text");
            for (int i=0;i<queue.length();i++) if (signature.equals(queue.optJSONObject(i).optString("_signature"))) return true;
            if (queue.length()>=200) {
                prefs.edit().putString("last_status","队列已满（200条）；新通知未保存，请先连接并补传。").putInt("dropped",prefs.getInt("dropped",0)+1).commit();
                return false;
            }
            try { event.put("_signature",signature); } catch (Exception ignored) { return false; }
            queue.put(event);
            return prefs.edit().putString("queue",queue.toString()).putString("last_status","新通知已排队，等待发送。").commit();
        }
    }
    public static void clear(Context context) { synchronized(LOCK) { preferences(context).edit().putString("queue","[]").putString("last_status","已手动清空待传队列。").commit(); } }
    public static void pair(Context context) {
        final Context app=context.getApplicationContext();
        WORKER.execute(() -> {
            try {ComputerDiscovery.resolve(app,true);flush(app);}
            catch(Exception error){preferences(app).edit().putString("last_status",error.getMessage()==null?"配对失败，事件保留。":error.getMessage()).apply();}
        });
    }
    public static void flush(Context context) {
        final Context app = context.getApplicationContext();
        synchronized(LOCK) { if (flushing) return; flushing = true; }
        WORKER.execute(() -> {
            try {
                SharedPreferences config=preferences(app);
                final int generation;
                synchronized(ComputerDiscovery.CONFIG_LOCK){generation=config.getInt("config_generation",0);}
                if(config.getBoolean("pairing_required",false)){config.edit().putString("last_status","令牌已改变，请重新配对后补传。").apply();return;}
                if(!config.getString("paired_device_id","").isEmpty()) {
                    try{ComputerDiscovery.resolve(app,false);}
                    catch(Exception error){config.edit().putString("last_status",error.getMessage()==null?"寻找电脑失败，事件保留。":error.getMessage()).apply();return;}
                }
                for (int turn=0;turn<200;turn++) {
                    SharedPreferences prefs = preferences(app);
                    final String server,token;
                    synchronized(ComputerDiscovery.CONFIG_LOCK) {
                        if(generation!=prefs.getInt("config_generation",0))break;
                        server=prefs.getString("server","").trim();token=prefs.getString("token","").trim();
                    }
                    if (server.isEmpty() || token.isEmpty()) { prefs.edit().putString("last_status","请先保存服务地址和令牌。").apply(); break; }
                    JSONObject event;
                    synchronized(LOCK) {
                        JSONArray queue = read(prefs);
                        if (queue.length()==0) { prefs.edit().putString("last_status","队列已发送完毕。").apply(); break; }
                        event = queue.optJSONObject(0);
                    }
                    HttpURLConnection connection = null;
                    try {
                        URI base = new URI(server);
                        if (!allowedEndpoint(base)) throw new IllegalArgumentException("服务地址无效或非可信局域网 HTTP");
                        URL endpoint = new URL(server.replaceAll("/+$","")+"/api/mobile/notifications");
                        connection = (HttpURLConnection) endpoint.openConnection();
                        connection.setInstanceFollowRedirects(false);
                        connection.setConnectTimeout(7000); connection.setReadTimeout(10000);
                        connection.setRequestMethod("POST"); connection.setDoOutput(true);
                        connection.setRequestProperty("Content-Type","application/json");
                        connection.setRequestProperty("Authorization","Bearer "+token);
                        JSONObject payload = new JSONObject(event.toString()); payload.remove("_signature");
                        byte[] data = payload.toString().getBytes(StandardCharsets.UTF_8);
                        connection.setFixedLengthStreamingMode(data.length);
                        synchronized(ComputerDiscovery.CONFIG_LOCK){if(generation!=prefs.getInt("config_generation",0))break;}
                        try (OutputStream output = connection.getOutputStream()) { output.write(data); }
                        int status = connection.getResponseCode();
                        if (status!=200 && status!=201) { prefs.edit().putString("last_status","服务器拒绝 HTTP "+status+"；事件仍在队列，请检查令牌、白名单和时间。").apply(); break; }
                        synchronized(LOCK) {
                            JSONArray queue = read(prefs), remaining = new JSONArray();
                            boolean removed = false;
                            for (int i=0;i<queue.length();i++) {
                                JSONObject current = queue.optJSONObject(i);
                                if (!removed && current.optString("_signature").equals(event.optString("_signature"))) { removed=true; continue; }
                                remaining.put(current);
                            }
                            // Preserve items appended while the request was in flight.
                            prefs.edit().putString("queue",remaining.toString()).putString("last_status","发送成功，剩余 "+remaining.length()+" 条。").commit();
                        }
                    } catch (Exception error) {
                        prefs.edit().putString("last_status","暂未连接服务，事件保留；打开客户端或点击重试后补传。").apply();
                        break;
                    } finally { if (connection!=null) connection.disconnect(); }
                }
            } finally { synchronized(LOCK) { flushing=false; } }
        });
    }
    public static boolean allowedEndpoint(URI uri) {
        String scheme=uri.getScheme(),host=uri.getHost();
        if (host==null || uri.getUserInfo()!=null || uri.getQuery()!=null || uri.getFragment()!=null || (uri.getPath()!=null && !uri.getPath().isEmpty() && !uri.getPath().equals("/"))) return false;
        if ("https".equals(scheme)) return true;
        if (!"http".equals(scheme)) return false;
        return "localhost".equals(host)||"127.0.0.1".equals(host)||ComputerDiscovery.privateIpv4(host);
    }
}
