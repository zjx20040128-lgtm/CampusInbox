package cn.courseinbox.companion;

import android.content.Context;
import java.io.File;
import java.io.IOException;
import java.time.OffsetDateTime;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONObject;

/** All local disk operations run off the Android main thread. */
public final class MobileStore {
    public static final ExecutorService WORKER=Executors.newSingleThreadExecutor();
    private static LocalInbox instance;
    private MobileStore(){}
    public static synchronized LocalInbox get(Context context)throws IOException{
        if(instance==null)instance=new LocalInbox(new File(context.getApplicationContext().getFilesDir(),"mobile-inbox.bin"));
        return instance;
    }
    public static boolean notification(Context context,JSONObject event)throws Exception{
        long posted=parseTime(event.optString("captured_at",""));
        String source=event.optString("package_name").equals("com.chaoxing.mobile")?"学习通系统通知":event.optString("package_name")+" 系统通知";
        LocalInbox.Message message=new LocalInbox.Message(event.optString("notification_key")+"|"+event.optString("captured_at"),source,event.optString("title"),event.optString("course"),"",event.optString("title"),
            (event.optString("title").isEmpty()?"":event.optString("title")+"\n")+event.optString("text"),posted,posted>0,"");
        boolean saved=get(context).ingest(message);
        if(saved&&event.optBoolean("_alert_live",false)&&event.optString("package_name").equals("com.chaoxing.mobile"))MobileAlert.show(context,message);
        return saved;
    }
    public static void incoming(Context context,JSONObject event){
        final Context app=context.getApplicationContext();final String payload=event.toString();
        WORKER.execute(()->{
            try{pending(app).enqueue(payload);drainNotifications(app);}
            catch(Exception error){NotificationQueue.preferences(app).edit().putString("local_capture_status","通知保存失败："+error.getMessage()+" 请保留通知栏消息并重试。").apply();}
        });
    }
    public static void retryNotifications(Context context){final Context app=context.getApplicationContext();WORKER.execute(()->drainNotifications(app));}
    private static PendingNotificationStore pending(Context context){return new PendingNotificationStore(new File(context.getFilesDir(),"incoming-notifications"));}
    private static void drainNotifications(Context context){
        PendingNotificationStore pending=pending(context);
        try{
            PendingNotificationStore.DrainResult result=pending.drain(entry->notification(context,new JSONObject(entry.payload)));
            android.content.SharedPreferences.Editor update=NotificationQueue.preferences(context).edit().putInt("local_pending_count",result.pending);
            if(!result.error.isEmpty())update.putString("local_capture_status","部分通知保存失败，原文仍在手机重试队列："+result.error);
            else if(result.saved>0)update.putString("local_capture_status","通知原文已保存到手机。");
            update.apply();
        }catch(Exception error){NotificationQueue.preferences(context).edit().putString("local_capture_status","手机存档保存失败，通知原文仍在本机重试队列："+error.getMessage()).apply();}
    }
    public static boolean web(Context context,JSONObject job)throws Exception{
        String url=job.optString("url");if(!LearningUrls.collectible(url))throw new IllegalArgumentException("消息来源网址未授权。");
        String kind=job.optString("kind");if(!kind.equals("chat")&&!kind.equals("course_notice"))throw new IllegalArgumentException("消息类型无效。");
        String key=job.optString("message_id"),text=job.optString("text"),title=job.optString("title");
        boolean confirmedEmpty=kind.equals("course_notice")&&!title.isEmpty()&&job.optBoolean("empty_body_ready",false);
        if(key.isEmpty()||key.length()>200||(text.isEmpty()&&!confirmedEmpty)||text.length()>28000||title.length()>160)throw new IllegalArgumentException("消息内容无效。");
        if(kind.equals("chat")&&job.optString("direction").equals("sent"))return false;
        long posted=parseTime(job.optString("captured_at",""));
        String content=(title.isEmpty()?"":title+"\n")+text;
        String account=NotificationQueue.preferences(context).getString("learning_session_scope","default");
        return get(context).ingest(new LocalInbox.Message(account+"|"+key,kind.equals("chat")?"学习通聊天":"学习通课程通知",job.optString("conversation"),job.optString("course"),job.optString("sender"),title,content,posted,posted>0,url));
    }
    private static long parseTime(String value){try{return OffsetDateTime.parse(value).toInstant().toEpochMilli();}catch(RuntimeException ignored){return 0;}}
}
