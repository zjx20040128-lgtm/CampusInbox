package android.app;
import android.content.ComponentName;
public final class NotificationManager {
    public boolean access=true;
    public boolean isNotificationListenerAccessGranted(ComponentName name){return access;}
}
