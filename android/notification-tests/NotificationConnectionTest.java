import android.content.Context;
import android.os.Build;
import android.os.SystemClock;
import android.provider.Settings;
import android.service.notification.NotificationListenerService;
import cn.courseinbox.companion.CourseNotificationService;
import cn.courseinbox.companion.NotificationQueue;

/** Executes the real listener against a small Android boundary shim; no device claim. */
public final class NotificationConnectionTest {
    private static int assertions;
    private static void check(boolean ok,String reason){assertions++;if(!ok)throw new AssertionError(reason);}
    private static boolean recover(Context context)throws Exception{return (boolean)CourseNotificationService.class.getMethod("ensureConnected",Context.class).invoke(null,context);}
    private static boolean access(Context context)throws Exception{return (boolean)CourseNotificationService.class.getMethod("hasAccess",Context.class).invoke(null,context);}
    public static void main(String[] args)throws Exception{
        Context context=new Context();
        CourseNotificationService service=new CourseNotificationService();
        CourseNotificationService.inspectVisibleNotifications(context);
        check(NotificationListenerService.reads==0,"disconnected listener must not read the shade");
        service.onListenerConnected();
        check(NotificationListenerService.reads==1,"connection must scan notifications posted before it was bound");
        check(CourseNotificationService.isConnected(),"only connection callback marks listener connected");
        check(!recover(context)&&NotificationListenerService.binds==0,"connected listener does not rebind");
        CourseNotificationService replacement=new CourseNotificationService();
        replacement.onListenerConnected();
        service.onListenerDisconnected();
        check(CourseNotificationService.isConnected(),"late disconnect from old instance must not hide the new live listener");
        check(NotificationListenerService.binds==0,"old instance must not request a redundant rebind");
        replacement.onListenerDisconnected();
        check(!CourseNotificationService.isConnected(),"disconnect clears the current listener");
        check(NotificationListenerService.binds==1,"authorized disconnected listener requests recovery");
        check(((Integer)NotificationQueue.values.get("listener_rebind_count"))==1,"rebind attempts are visible for phone diagnostics");
        check(NotificationListenerService.requested.flattenToString().equals("cn.courseinbox.companion/cn.courseinbox.companion.CourseNotificationService"),"recovery targets our exact listener component");
        check(!recover(context)&&NotificationListenerService.binds==1,"foreground refresh does not flood rebind requests");
        check(NotificationListenerService.reads==2,"rebind request is not treated as a connection");
        SystemClock.now+=15000;
        check(recover(context)&&NotificationListenerService.binds==2,"an unresolved disconnection can retry later");
        check(CourseNotificationService.resetStaleBinding(context),"authorized Android 14+ listener can reset a stale system binding once");
        check(NotificationListenerService.unbinds==1&&NotificationListenerService.binds==3,"stale recovery unbinds then immediately requests a new binding");
        check(!CourseNotificationService.isConnected(),"reset request is not a connection callback");
        check(!CourseNotificationService.resetStaleBinding(context)&&NotificationListenerService.unbinds==1,"automatic reset is bounded per upgrade");
        NotificationQueue.values.put("listener_soft_reset_count",0);Build.VERSION.SDK_INT=33;
        check(!CourseNotificationService.resetStaleBinding(context)&&NotificationListenerService.unbinds==1,"older Android versions never call API 34 unbind");
        Build.VERSION.SDK_INT=35;
        Context.manager.access=false;SystemClock.now+=15000;
        check(!CourseNotificationService.resetStaleBinding(context)&&NotificationListenerService.unbinds==1,"revoked access never triggers a binding reset");
        check(!recover(context)&&NotificationListenerService.binds==3,"revoked access must not request a rebind");
        Context.manager.access=true;NotificationListenerService.rejectBind=true;
        check(!recover(context)&&!CourseNotificationService.isConnected(),"system rejection remains disconnected without crashing");
        NotificationListenerService.rejectBind=false;NotificationListenerService.rejectUnbind=true;
        check(!CourseNotificationService.resetStaleBinding(context)&&NotificationListenerService.unbinds==1,"system rejection of reset preserves ordinary retry path");
        check(NotificationQueue.values.get("listener_soft_reset_count").equals(1),"rejected system reset is still bounded to one attempt per upgrade");
        NotificationListenerService.rejectUnbind=false;NotificationListenerService.failRead=true;
        service.onListenerConnected();
        check(NotificationQueue.values.get("scan_status").toString().contains("失败"),"scan errors remain visible");
        service.onDestroy();check(!CourseNotificationService.isConnected(),"destroyed listener cannot appear connected");
        Build.VERSION.SDK_INT=26;Settings.Secure.listeners="cn.courseinbox.companion/.CourseNotificationService";
        check(access(context),"Android 8 supports the enabled-listener setting");
        Settings.Secure.listeners="cn.courseinbox.companion/.OtherService:other.example/.Listener";
        check(!access(context),"grant to another component is not access to this listener");
        Settings.Secure.listeners=null;check(!access(context),"missing access settings mean not granted");
        System.out.println("PASS: notification connection/recovery: "+assertions+" assertions (Android boundary shim)");
    }
}
