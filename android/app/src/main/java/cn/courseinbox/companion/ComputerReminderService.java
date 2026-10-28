package cn.courseinbox.companion;

import android.app.Service;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.os.*;
import java.util.*;
import java.util.concurrent.*;

/** User-started connection to a paired computer; no boot receiver or notification-listener dependency. */
public final class ComputerReminderService extends Service {
    static final String ACTION_STOP="cn.courseinbox.companion.STOP_COMPUTER_REMINDERS";
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    private final Runnable poll=this::poll;private ComputerReminderStore store;private ComputerReminderNotifications notices;
    private boolean running;private volatile boolean destroyed;private int failures;
    static void start(Context context){
        ComputerReminderStore store=ComputerReminderStore.get(context);store.enable();
        try{context.startForegroundService(new Intent(context,ComputerReminderService.class));}
        catch(RuntimeException error){store.stop(false);store.status(store.session().generation,"系统未允许后台连接，请保持应用前台后重试");throw error;}
    }
    static void stop(Context context,boolean disconnect){ComputerReminderStore.get(context).stop(disconnect);context.stopService(new Intent(context,ComputerReminderService.class));}
    @Override public void onCreate(){super.onCreate();store=ComputerReminderStore.get(this);notices=new ComputerReminderNotifications(this);ComputerReminderNotifications.channels(this);}
    @Override public int onStartCommand(Intent intent,int flags,int startId){
        if(intent!=null&&ACTION_STOP.equals(intent.getAction())){store.stop(false);stopSelf();return START_NOT_STICKY;}
        ComputerReminderStore.Session session=store.session();
        if(!session.enabled||!session.paired()){stopSelf();return START_NOT_STICKY;}
        if(!notices.allowed()){store.stop(false);store.status(store.session().generation,"需要允许发送电脑提醒通知，然后点击开始接收");stopSelf();return START_NOT_STICKY;}
        try{if(Build.VERSION.SDK_INT>=29)startForeground(7100,ComputerReminderNotifications.connection(this),ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE);else startForeground(7100,ComputerReminderNotifications.connection(this));}
        catch(RuntimeException error){store.stop(false);store.status(store.session().generation,"系统未允许前台连接，请检查通知权限并重试");stopSelf();return START_NOT_STICKY;}
        if(!running){running=true;handler.post(poll);}return START_STICKY;
    }
    private void poll(){
        ComputerReminderStore.Session session=store.session();if(destroyed||!session.enabled||!session.paired()){stopSelf();return;}
        worker.execute(()->{
            boolean terminal=false;
            try{
                ComputerReminderApi api=new ComputerReminderApi();ComputerReminderApi.Batch batch=api.alerts(session);
                ComputerReminderDelivery delivery=new ComputerReminderDelivery(store,store,notices);
                List<String> ids;
                synchronized(ComputerReminderStore.LOCK){if(destroyed)return;ids=delivery.receive(session.generation,session.serverId,batch.enabled,batch.events);}
                if(!ids.isEmpty()&&store.current(session.generation,session.serverId)&&!destroyed&&notices.allowed()){api.ack(session,ids);delivery.acknowledged(session.generation,session.serverId,ids);}
                failures=0;store.status(session.generation,!notices.allowed()?"通知未允许；电脑提醒未消费，请开启通知":batch.enabled?"已连接电脑 · 每 15 秒检查新提醒":"电脑已暂停提醒");
            }catch(Exception error){
                failures++;
                if(error instanceof ComputerReminderApi.IdentityFailure||(error instanceof ComputerReminderHttp.Failure&&((ComputerReminderHttp.Failure)error).status==401)){
                    synchronized(ComputerReminderStore.LOCK){if(store.current(session.generation,session.serverId)){store.stop(true);store.status(store.session().generation,"配对已失效或电脑身份变化，请重新配对");terminal=true;}}
                }else store.status(session.generation,"暂未连接电脑；提醒保留，稍后重试。请检查同一 Wi-Fi 与电脑服务。");
            }finally{
                boolean stop=terminal;handler.post(()->{if(destroyed)return;if(stop||!store.session().enabled)stopSelf();else handler.postDelayed(poll,ComputerReminderProtocol.delayMillis(failures));});
            }
        });
    }
    @Override public void onDestroy(){destroyed=true;handler.removeCallbacksAndMessages(null);worker.shutdownNow();stopForeground(STOP_FOREGROUND_REMOVE);super.onDestroy();}
    @Override public IBinder onBind(Intent intent){return null;}
}
