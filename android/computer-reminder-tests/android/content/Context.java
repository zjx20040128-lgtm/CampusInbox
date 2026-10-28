package android.content;
import java.util.*;import android.app.NotificationManager;
public class Context {
 public static final int MODE_PRIVATE=0;public static final String NOTIFICATION_SERVICE="notification";
 public int permission=0;public final NotificationManager manager=new NotificationManager();public boolean failCommit;
 private final Map<String,Preferences> preferences=new HashMap<>();
 public Context getApplicationContext(){return this;}public Object getSystemService(String service){return manager;}public int checkSelfPermission(String permission){return this.permission;}
 public SharedPreferences getSharedPreferences(String name,int mode){return preferences.computeIfAbsent(name,key->new Preferences());}
 private class Preferences implements SharedPreferences {
  final Map<String,Object> data=new HashMap<>();public long getLong(String key,long fallback){return (Long)data.getOrDefault(key,fallback);}public boolean getBoolean(String key,boolean fallback){return (Boolean)data.getOrDefault(key,fallback);}public String getString(String key,String fallback){return (String)data.getOrDefault(key,fallback);}
  public Editor edit(){return new Editor(){final Map<String,Object> staged=new HashMap<>();final Set<String> removed=new HashSet<>();public Editor putLong(String k,long v){staged.put(k,v);return this;}public Editor putBoolean(String k,boolean v){staged.put(k,v);return this;}public Editor putString(String k,String v){staged.put(k,v);return this;}public Editor remove(String k){removed.add(k);return this;}public boolean commit(){if(failCommit)return false;for(String key:removed)data.remove(key);data.putAll(staged);return true;}};}
 }
}
