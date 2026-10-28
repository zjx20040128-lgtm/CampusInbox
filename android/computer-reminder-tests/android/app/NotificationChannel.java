package android.app;
public class NotificationChannel {public final String id;private final int importance;public NotificationChannel(String id,String name,int importance){this.id=id;this.importance=importance;}public int getImportance(){return importance;}}
