package android.app;
import android.content.Context;
public class Notification {
 public static final String CATEGORY_REMINDER="reminder",CATEGORY_SERVICE="service";public static final int VISIBILITY_PRIVATE=0;
 public PendingIntent tap;public boolean onlyAlertOnce,ongoing;public String title,body,channel;public int visibility;
 public static class Builder {private final Notification n=new Notification();public Builder(Context c,String channel){n.channel=channel;}public Builder setSmallIcon(int icon){return this;}public Builder setContentTitle(String title){n.title=title;return this;}public Builder setContentText(String body){n.body=body;return this;}public Builder setStyle(BigTextStyle style){return this;}public Builder setContentIntent(PendingIntent tap){n.tap=tap;return this;}public Builder setOnlyAlertOnce(boolean once){n.onlyAlertOnce=once;return this;}public Builder setAutoCancel(boolean cancel){return this;}public Builder setCategory(String category){return this;}public Builder setVisibility(int visibility){n.visibility=visibility;return this;}public Builder setOngoing(boolean ongoing){n.ongoing=ongoing;return this;}public Builder addAction(Action action){return this;}public Notification build(){return n;}}
 public static class BigTextStyle {public BigTextStyle bigText(String body){return this;}}
 public static class Action {public static class Builder {public Builder(Object icon,String title,PendingIntent action){}public Action build(){return new Action();}}}
}
