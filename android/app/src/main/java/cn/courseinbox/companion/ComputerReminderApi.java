package cn.courseinbox.companion;

import org.json.*;
import java.io.IOException;
import java.util.*;

final class ComputerReminderApi {
    private final ComputerReminderHttp http=new ComputerReminderHttp();
    static final class Pair {final String token,deviceId,serverId;Pair(JSONObject obj)throws Exception {token=obj.getString("token");deviceId=identity(obj.getString("device_id"));serverId=identity(obj.getString("server_id"));if(!token.matches("[A-Za-z0-9_-]{24,256}"))throw new IOException("电脑配对信息不完整");}}
    static final class Batch {final boolean enabled;final List<ComputerReminderDelivery.Event> events;Batch(boolean enabled,List<ComputerReminderDelivery.Event> events){this.enabled=enabled;this.events=events;}}
    private static String identity(String id)throws IOException {if(!id.matches("[0-9a-f]{32}"))throw new IOException("电脑身份信息无效");return id;}
    private String health(String endpoint)throws Exception {JSONObject obj=new JSONObject(http.request(endpoint,"/v1/health","",null));if(!obj.getString("app").equals("CourseInbox Reminders")||obj.getInt("version")!=1)throw new IOException("电脑提醒服务版本不兼容");return identity(obj.getString("server_id"));}
    Pair pair(String endpoint,String code,String name)throws Exception {
        String id=health(endpoint);Pair result=new Pair(new JSONObject(http.request(endpoint,"/v1/pair","",new JSONObject().put("code",code).put("name",name).toString())));
        if(!id.equals(result.serverId))throw new IOException("配对期间电脑身份发生变化，请重新配对");return result;
    }
    Batch alerts(ComputerReminderStore.Session session)throws Exception {
        // Verify the remembered identity without a token before sending credentials to the LAN address.
        if(!health(session.endpoint).equals(session.serverId))throw new IdentityFailure();
        JSONObject obj=new JSONObject(http.request(session.endpoint,"/v1/alerts",session.token,null));
        if(!obj.getString("server_id").equals(session.serverId))throw new IdentityFailure();
        boolean enabled=obj.getBoolean("enabled");JSONArray events=obj.getJSONArray("events");
        if(events.length()>200)throw new IOException("电脑提醒批次过大");
        List<ComputerReminderDelivery.Event> rows=new ArrayList<>();
        for(int i=0;i<events.length();i++){JSONObject e=events.getJSONObject(i);rows.add(new ComputerReminderDelivery.Event(e.getString("id"),e.getString("kind"),e.getString("title"),e.getString("body")));}
        // Remote url is deliberately never retained or opened. Taps always show this phone's history.
        return new Batch(enabled,rows);
    }
    void ack(ComputerReminderStore.Session session,List<String> ids)throws Exception {
        JSONObject obj=new JSONObject(http.request(session.endpoint,"/v1/ack",session.token,new JSONObject().put("ids",new JSONArray(ids)).toString()));
        if(!obj.getBoolean("ok"))throw new IOException("电脑尚未确认提醒回执");
    }
    static final class IdentityFailure extends IOException {IdentityFailure(){super("电脑身份与配对记录不同，请检查地址并重新配对");}}
}
