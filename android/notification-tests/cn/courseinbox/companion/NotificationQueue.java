package cn.courseinbox.companion;
import android.content.Context;
import android.content.SharedPreferences;
import android.service.notification.NotificationListenerService;
import java.lang.reflect.Proxy;
import java.util.HashMap;
import java.util.Map;
import org.json.JSONObject;
public final class NotificationQueue {
    public static final Map<String,Object> values=new HashMap<>();
    private static final SharedPreferences.Editor editor=(SharedPreferences.Editor)Proxy.newProxyInstance(SharedPreferences.Editor.class.getClassLoader(),new Class<?>[]{SharedPreferences.Editor.class},(proxy,method,args)->{
        if(method.getName().startsWith("put")){values.put((String)args[0],args[1]);return proxy;}
        if(method.getName().equals("commit")){NotificationListenerService.events.add("commit");return true;}
        return null;
    });
    private static final SharedPreferences prefs=(SharedPreferences)Proxy.newProxyInstance(SharedPreferences.class.getClassLoader(),new Class<?>[]{SharedPreferences.class},(proxy,method,args)->{
        if(method.getName().equals("edit"))return editor;
        if(method.getName().startsWith("get"))return values.getOrDefault((String)args[0],args[1]);
        return null;
    });
    public static SharedPreferences preferences(Context context){return prefs;}
    public static void flush(Context context){}
    public static boolean enqueue(Context context,JSONObject event){return true;}
}
