package android.service.notification;
import android.content.Context;
import android.content.ComponentName;
import android.content.Intent;
import android.os.IBinder;
import java.util.ArrayList;
import java.util.List;
public class NotificationListenerService extends Context {
    public static int binds,unbinds,reads;
    public static ComponentName requested;
    public static boolean rejectBind,rejectUnbind,failRead;
    public static final List<String> events=new ArrayList<>();
    public void onCreate(){}
    public IBinder onBind(Intent intent){return null;}
    public boolean onUnbind(Intent intent){return false;}
    public void onListenerConnected(){}
    public void onListenerDisconnected(){}
    public void onDestroy(){}
    public void onNotificationPosted(StatusBarNotification posted){}
    public static void requestRebind(ComponentName name){if(rejectBind)throw new SecurityException("denied");binds++;requested=name;events.add("rebind");}
    public static void requestUnbind(ComponentName name){if(rejectUnbind)throw new SecurityException("denied");unbinds++;requested=name;events.add("unbind");}
    public StatusBarNotification[] getActiveNotifications(){reads++;if(failRead)throw new SecurityException("disconnected");return null;}
}
