package cn.courseinbox.companion;

import android.app.Notification;
import android.app.NotificationManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.Bundle;
import android.os.IBinder;
import android.os.Parcelable;
import android.os.SystemClock;
import android.provider.Settings;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Set;
import java.util.TimeZone;
import org.json.JSONObject;

/** Receives user-authorized system notifications from configured packages. */
public final class CourseNotificationService extends NotificationListenerService {
    private static volatile CourseNotificationService connected;
    private static CourseNotificationService created,bound;
    private static long lastRebindAt;

    public static boolean isConnected() { return connected != null; }

    public static String connectionStage(){
        if(isConnected())return "已收到系统连接回调";
        if(bound!=null)return "系统已绑定，尚无连接回调";
        if(created!=null)return "系统已创建，尚未绑定";
        return "当前没有接收服务实例";
    }

    @Override public void onCreate(){super.onCreate();created=this;ListenerDiagnostics.event(this,"service_create");}
    @Override public IBinder onBind(Intent intent){
        IBinder binder=super.onBind(intent);bound=this;ListenerDiagnostics.event(this,"service_bind");return binder;
    }
    @Override public boolean onUnbind(Intent intent){
        if(bound==this)bound=null;
        ListenerDiagnostics.event(this,"service_unbind");return super.onUnbind(intent);
    }

    public static boolean hasAccess(Context context) {
        ComponentName component = new ComponentName(context, CourseNotificationService.class);
        if (Build.VERSION.SDK_INT >= 27) {
            NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
            return manager != null && manager.isNotificationListenerAccessGranted(component);
        }
        String enabled = Settings.Secure.getString(context.getContentResolver(), "enabled_notification_listeners");
        if (enabled != null) for (String value : enabled.split(":")) {
            if (component.equals(ComponentName.unflattenFromString(value))) return true;
        }
        return false;
    }

    /** A rebind request is asynchronous; only onListenerConnected marks us connected. */
    public static boolean ensureConnected(Context context) {
        if (isConnected() || !hasAccess(context)) return false;
        long now = SystemClock.elapsedRealtime();
        if (lastRebindAt != 0 && now - lastRebindAt < 10000) return false;
        lastRebindAt = now;
        ListenerDiagnostics.begin(context);
        try {
            requestRebind(new ComponentName(context, CourseNotificationService.class));
            ListenerDiagnostics.event(context,"rebind_requested");
            SharedPreferences prefs=NotificationQueue.preferences(context);
            prefs.edit().putInt("listener_rebind_count",prefs.getInt("listener_rebind_count",0)+1)
                .putString("listener_status", "已授权，正在请求重连通知接收服务").apply();
            return true;
        } catch (RuntimeException error) {
            ListenerDiagnostics.error(context,"rebind_failed",error);
            NotificationQueue.preferences(context).edit().putString("listener_status", "通知接收重连请求失败，请返回应用后重试；若持续失败再检查系统授权").apply();
            return false;
        }
    }

    /** On Android 14+, reset a stale system binding once after an upgrade or boot. */
    public static boolean resetStaleBinding(Context context) {
        if (Build.VERSION.SDK_INT < 34 || isConnected() || !hasAccess(context)) return false;
        SharedPreferences prefs=NotificationQueue.preferences(context);
        if (prefs.getInt("listener_soft_reset_count",0)>0) return false;
        ComponentName component=new ComponentName(context,CourseNotificationService.class);
        try {
            if (!prefs.edit().putInt("listener_soft_reset_count",1).commit()) {
                prefs.edit().putInt("listener_soft_reset_count",0).apply();
                return false;
            }
            requestUnbind(component);
            ListenerDiagnostics.event(context,"binding_reset_requested");
            lastRebindAt=0;
            boolean requested=ensureConnected(context);
            prefs.edit().putString("listener_status",requested
                ?"已授权；已重建通知接收绑定，等待系统连接回调。"
                :"已授权；已解绑旧通知接收，但重新绑定请求失败。").apply();
            return true;
        } catch (RuntimeException error) {
            ListenerDiagnostics.error(context,"binding_reset_failed",error);
            prefs.edit().putString("listener_status","已授权；系统拒绝重建通知接收绑定，将继续普通重连。").apply();
            return false;
        }
    }

    public static String timestamp(long milliseconds) {
        SimpleDateFormat format = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US);
        format.setTimeZone(TimeZone.getTimeZone("UTC"));
        return format.format(new Date(milliseconds));
    }

    @Override public void onListenerConnected() {
        super.onListenerConnected();
        connected = this;
        lastRebindAt = 0;
        ListenerDiagnostics.connected(this);
        NotificationQueue.preferences(this).edit().putString("listener_status", "通知监听已连接").apply();
        MobileStore.retryNotifications(this);
        inspectVisibleNotifications(this, true);
        NotificationQueue.flush(this);
    }

    @Override public void onListenerDisconnected() {
        super.onListenerDisconnected();
        if (connected != this) return;
        connected = null;
        ListenerDiagnostics.event(this,"listener_disconnected");
        NotificationQueue.preferences(this).edit().putString("listener_status", "通知监听已断开，正在请求重连").apply();
        ensureConnected(this);
    }

    @Override public void onDestroy() {
        if (connected == this) connected = null;
        if(created==this)created=null;
        if(bound==this)bound=null;
        ListenerDiagnostics.event(this,"service_destroy");
        super.onDestroy();
    }

    @Override public void onNotificationPosted(StatusBarNotification posted) {
        if (posted == null || getPackageName().equals(posted.getPackageName())) return;
        SharedPreferences prefs = NotificationQueue.preferences(this);
        prefs.edit().putInt("callback_count", prefs.getInt("callback_count", 0) + 1)
            .putString("last_callback_at", timestamp(System.currentTimeMillis())).apply();
        capture(posted, true, true);
    }

    /** Inspect notifications still visible in the shade, including those posted before listener connection. */
    public static String inspectVisibleNotifications(Context context) {
        return inspectVisibleNotifications(context, false);
    }

    private static String inspectVisibleNotifications(Context context, boolean alertNew) {
        CourseNotificationService service = connected;
        if (service == null) {
            String result = "通知监听当前未连接，无法读取通知栏。请在系统设置检查 CampusInbox 的通知访问权限，返回后再试。";
            NotificationQueue.preferences(context).edit().putString("scan_status", result).apply();
            return result;
        }
        try {
            StatusBarNotification[] active = service.getActiveNotifications();
            if (active == null) active = new StatusBarNotification[0];
            int matched = 0, handled = 0;
            Set<String> otherPackages = new LinkedHashSet<>();
            for (StatusBarNotification posted : active) {
                if (posted == null || service.getPackageName().equals(posted.getPackageName())) continue;
                if (service.isAllowed(posted.getPackageName())) {
                    matched++;
                    if (service.capture(posted, false, alertNew)) handled++;
                } else if (otherPackages.size() < 5) {
                    otherPackages.add(posted.getPackageName());
                }
            }
            String result = "当前通知栏：" + active.length + " 条；白名单匹配：" + matched
                + " 条；已处理：" + handled + " 条。";
            if (matched == 0 && !otherPackages.isEmpty()) result += " 其他包名：" + String.join("、", otherPackages) + "。";
            if (matched == 0) result += " 请确认通知确实来自学习通，并检查手机和电脑两端的包名白名单。";
            NotificationQueue.preferences(service).edit().putString("scan_status", result).apply();
            if (handled > 0) NotificationQueue.flush(service);
            return result;
        } catch (Exception error) {
            String result = "读取当前通知栏失败，请检查通知访问授权。";
            NotificationQueue.preferences(service).edit().putString("scan_status", result).apply();
            return result;
        }
    }

    private boolean isAllowed(String packageName) {
        String allowed = NotificationQueue.preferences(this).getString("packages", "com.chaoxing.mobile");
        for (String candidate : allowed.split("[\\s,;]+")) if (candidate.equals(packageName)) return true;
        return false;
    }

    private boolean capture(StatusBarNotification posted, boolean sendNow, boolean alertNew) {
        SharedPreferences prefs = NotificationQueue.preferences(this);
        String packageName = posted.getPackageName();
        if (!isAllowed(packageName)) {
            prefs.edit().putString("last_other_package", packageName).apply();
            return false;
        }
        prefs.edit().putInt("matched_count", prefs.getInt("matched_count", 0) + 1).apply();
        Notification notification = posted.getNotification();
        if (notification == null) {
            prefs.edit().putString("capture_status", "已匹配 " + packageName + "，但系统未提供通知对象。").apply();
            return false;
        }
        if ((notification.flags & Notification.FLAG_GROUP_SUMMARY) != 0) {
            prefs.edit().putString("capture_status", "已匹配 " + packageName + "，但这条是分组摘要，等待单条通知。").apply();
            return false;
        }
        Bundle extras = notification.extras;
        if (extras == null) {
            prefs.edit().putString("capture_status", "已匹配 " + packageName + "，但系统未提供通知文字。").apply();
            return false;
        }
        String title = String.valueOf(extras.getCharSequence(Notification.EXTRA_TITLE, ""));
        CharSequence plain = extras.getCharSequence(Notification.EXTRA_TEXT, "");
        CharSequence big = extras.getCharSequence(Notification.EXTRA_BIG_TEXT, "");
        StringBuilder linesText = new StringBuilder();
        CharSequence[] lines = extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES);
        if (lines != null) for (CharSequence line : lines) {
            if (line != null && line.length() > 0) {
                if (linesText.length() > 0) linesText.append('\n');
                linesText.append(line);
            }
        }
        StringBuilder messagesText = new StringBuilder();
        if (Build.VERSION.SDK_INT >= 30) {
            try {
                Parcelable[] bundles = extras.getParcelableArray(Notification.EXTRA_MESSAGES);
                for (Notification.MessagingStyle.Message message : Notification.MessagingStyle.Message.getMessagesFromBundleArray(bundles)) {
                    CharSequence value = message.getText();
                    if (value != null && value.length() > 0) {
                        if (messagesText.length() > 0) messagesText.append('\n');
                        messagesText.append(value);
                    }
                }
            } catch (RuntimeException ignored) { /* A malformed optional extra must not discard the ordinary notification text. */ }
        }
        String body = NotificationText.select(String.valueOf(plain), String.valueOf(big), linesText.toString(), messagesText.toString());
        prefs.edit().putString("text_field_status", "普通文字 " + plain.length() + " 字；展开文字 " + big.length()
            + " 字；多行文字 " + linesText.length() + " 字；消息列表 " + messagesText.length()
            + " 字；实际发送 " + body.length() + " 字").apply();
        if (title.trim().isEmpty() && body.trim().isEmpty()) {
            prefs.edit().putString("capture_status", "已匹配 " + packageName + "，但通知标题和正文均为空。").apply();
            return false;
        }
        try {
            JSONObject event = new JSONObject();
            event.put("package_name", packageName);
            event.put("notification_key", posted.getKey());
            event.put("title", title);
            event.put("text", body);
            event.put("captured_at", timestamp(posted.getPostTime()));
            event.put("scope", prefs.getString("scope", ""));
            event.put("course", "");
            JSONObject localEvent = new JSONObject(event.toString());
            localEvent.put("_alert_live", alertNew);
            MobileStore.incoming(this,localEvent);
            if (prefs.getString("paired_device_id", "").isEmpty()) {
                prefs.edit().putString("capture_status", "已采集通知，正在保存到手机。").apply();
                return true;
            }
            if (!NotificationQueue.enqueue(this, event)) {
                prefs.edit().putString("capture_status", "已匹配 " + packageName + "，但本地队列未保存；请查看队列状态。").apply();
                return false;
            }
            prefs.edit().putString("capture_status", "已采集 " + packageName + " 的通知，正在发送。").apply();
            if (sendNow) NotificationQueue.flush(this);
            return true;
        } catch (Exception error) {
            prefs.edit().putString("capture_status", "已匹配 " + packageName + "，但通知转换失败。").apply();
            return false;
        }
    }
}
