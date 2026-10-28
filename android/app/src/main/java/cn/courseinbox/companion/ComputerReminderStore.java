package cn.courseinbox.companion;

import android.content.*;
import android.database.Cursor;
import android.database.sqlite.*;
import java.util.*;

/** Independent credentials and durable delivery journal; never uses the notification-upload preferences. */
final class ComputerReminderStore extends SQLiteOpenHelper implements ComputerReminderDelivery.Fence,ComputerReminderDelivery.Journal {
    static final Object LOCK=new Object();private static ComputerReminderStore instance;
    private final SharedPreferences prefs;
    static ComputerReminderStore get(Context context) {synchronized(LOCK){if(instance==null)instance=new ComputerReminderStore(context.getApplicationContext());return instance;}}
    private ComputerReminderStore(Context context){super(context,"computer-reminders.db",null,1);prefs=context.getSharedPreferences("computer-reminder-receiver",Context.MODE_PRIVATE);}
    @Override public void onCreate(SQLiteDatabase db){db.execSQL("CREATE TABLE delivered(server_id TEXT NOT NULL, device_id TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, received_at INTEGER NOT NULL, acked INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(server_id,device_id,id))");}
    @Override public void onUpgrade(SQLiteDatabase db,int oldVersion,int newVersion){throw new IllegalStateException("Unsupported reminder journal upgrade");}
    static final class Session {
        final long generation;final boolean enabled;final String endpoint,token,deviceId,serverId,status;
        Session(SharedPreferences prefs){generation=prefs.getLong("generation",0);enabled=prefs.getBoolean("enabled",false);endpoint=prefs.getString("endpoint","");token=prefs.getString("token","");deviceId=prefs.getString("device_id","");serverId=prefs.getString("server_id","");status=prefs.getString("status","尚未配对电脑");}
        boolean paired(){return !token.isEmpty()&&!deviceId.isEmpty()&&!serverId.isEmpty();}
    }
    Session session(){synchronized(LOCK){return new Session(prefs);}}
    public Object lock(){return LOCK;}
    public boolean current(long generation,String serverId){synchronized(LOCK){Session s=session();return s.enabled&&s.generation==generation&&s.serverId.equals(serverId);}}
    private void commit(SharedPreferences.Editor editor){if(!editor.commit())throw new IllegalStateException("无法保存电脑提醒配置，请重试");}
    long beginPair(){synchronized(LOCK){long g=session().generation+1;commit(prefs.edit().putLong("generation",g).putBoolean("enabled",false).putString("status","正在配对电脑…"));return g;}}
    boolean paired(long generation,String endpoint,String token,String deviceId,String serverId,String name){synchronized(LOCK){if(session().generation!=generation)return false;commit(prefs.edit().putString("endpoint",endpoint).putString("token",token).putString("device_id",deviceId).putString("server_id",serverId).putString("name",name).putBoolean("enabled",false).putString("status","已配对，点击开始接收"));return true;}}
    void enable(){synchronized(LOCK){Session s=session();if(!s.paired())throw new IllegalStateException("请先配对电脑");commit(prefs.edit().putLong("generation",s.generation+1).putBoolean("enabled",true).putString("status","正在连接电脑…"));}}
    void stop(boolean disconnect){synchronized(LOCK){SharedPreferences.Editor e=prefs.edit().putLong("generation",session().generation+1).putBoolean("enabled",false).putString("status",disconnect?"已断开配对；历史提醒保留":"已停止接收电脑提醒");if(disconnect)e.remove("token").remove("device_id").remove("server_id");commit(e);}}
    void status(long generation,String value){synchronized(LOCK){if(session().generation==generation)commit(prefs.edit().putString("status",value));}}
    String name(){return prefs.getString("name",android.os.Build.MODEL);}
    private String[] key(String serverId,String id){return new String[]{serverId,session().deviceId,id};}
    public boolean delivered(String serverId,String id){try(Cursor c=getReadableDatabase().rawQuery("SELECT 1 FROM delivered WHERE server_id=? AND device_id=? AND id=?",key(serverId,id))){return c.moveToFirst();}}
    public void save(String serverId,ComputerReminderDelivery.Event event){ContentValues values=new ContentValues();values.put("server_id",serverId);values.put("device_id",session().deviceId);values.put("id",event.id);values.put("kind",event.kind);values.put("title",event.title);values.put("body",event.body);values.put("received_at",System.currentTimeMillis());getWritableDatabase().insertOrThrow("delivered",null,values);}
    public List<String> pending(String serverId){List<String> ids=new ArrayList<>();try(Cursor c=getReadableDatabase().rawQuery("SELECT id FROM delivered WHERE server_id=? AND device_id=? AND acked=0 ORDER BY received_at LIMIT 200",new String[]{serverId,session().deviceId})){while(c.moveToNext())ids.add(c.getString(0));}return ids;}
    public void acknowledged(String serverId,List<String> ids){SQLiteDatabase db=getWritableDatabase();db.beginTransaction();try{ContentValues values=new ContentValues();values.put("acked",1);for(String id:ids)db.update("delivered",values,"server_id=? AND device_id=? AND id=?",key(serverId,id));db.setTransactionSuccessful();}finally{db.endTransaction();}}
    static final class History {final String title,body;final long receivedAt;History(Cursor c){title=c.getString(0);body=c.getString(1);receivedAt=c.getLong(2);}}
    List<History> history(){synchronized(LOCK){List<History> rows=new ArrayList<>();try(Cursor c=getReadableDatabase().rawQuery("SELECT title,body,received_at FROM delivered ORDER BY received_at DESC LIMIT 100",null)){while(c.moveToNext())rows.add(new History(c));}return rows;}}
}
