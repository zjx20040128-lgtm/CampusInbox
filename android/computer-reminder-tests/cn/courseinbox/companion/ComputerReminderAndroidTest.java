package cn.courseinbox.companion;
import android.app.*;import android.content.*;import android.os.Build;
/** Actual Android adapters with controlled permission, shade and preferences boundaries. No real-device claim. */
public final class ComputerReminderAndroidTest {
 private static int assertions;private static void check(boolean ok,String why){assertions++;if(!ok)throw new AssertionError(why);}
 public static void main(String[] args)throws Exception {
  Context context=new Context();ComputerReminderNotifications.channels(context);ComputerReminderNotifications alerts=new ComputerReminderNotifications(context);
  ComputerReminderDelivery.Event event=new ComputerReminderDelivery.Event("event","message","老师通知","阅读附件 https://untrusted.example/ 应当只是文本");
  context.permission=-1;check(!alerts.allowed()&&!alerts.show("computer:pc:event",event)&&context.manager.posted==0,"Android13+ denied runtime permission prevents notify");
  Build.VERSION.SDK_INT=26;check(alerts.allowed(),"Android8 requires no runtime notification permission");Build.VERSION.SDK_INT=35;context.permission=0;
  context.manager.enabled=false;check(!alerts.show("computer:pc:event",event)&&context.manager.posted==0,"disabled app notifications prevent notify");context.manager.enabled=true;
  context.manager.replaceChannel(new NotificationChannel(ComputerReminderNotifications.CHANNEL,"blocked",0));check(!alerts.allowed()&&!alerts.show("computer:pc:event",event),"blocked reminder channel prevents notify");
  ComputerReminderNotifications.channels(context);check(!alerts.allowed(),"recreating channels cannot override user's blocked channel");
  context.manager.replaceChannel(new NotificationChannel(ComputerReminderNotifications.CHANNEL,"allowed",4));check(alerts.show("computer:pc:event",event),"allowed notification is delivered");
  Notification sent=context.manager.last;check(context.manager.lastTag.equals("computer:pc:event")&&sent.onlyAlertOnce,"stable tag replaces a notification without re-alert on crash replay");
  check(sent.tap.intent.target==ComputerRemindersActivity.class&&sent.tap.intent.data.toString().startsWith("courseinbox://computer-history/"),"tap targets local history even when body contains a URL");
  check((sent.tap.flags&PendingIntent.FLAG_IMMUTABLE)!=0&&sent.visibility==Notification.VISIBILITY_PRIVATE,"notification intent immutable and content private");
  context.manager.failNotify=true;check(!alerts.show("computer:pc:event",event),"notification manager failure returns false so no ACK can follow");
  ComputerReminderStore store=ComputerReminderStore.get(context);check(!store.session().paired()&&!store.session().enabled,"receiver starts unpaired and disabled");
  long first=store.beginPair();check(!store.paired(first-1,"http://192.168.1.8:8766","old-token","old-device","pc-old","old"),"stale pairing response cannot save credentials");
  check(store.paired(first,"http://192.168.1.8:8766","device-token","phone-a","pc-a","phone")&&!store.session().enabled,"pairing saves independent credentials but service requires explicit enable");
  context.getSharedPreferences("courseinbox",0).edit().putString("token","upload-token").commit();store.enable();ComputerReminderStore.Session live=store.session();
  check(store.current(live.generation,"pc-a")&&!store.current(live.generation,"pc-b"),"current generation is pinned to paired server");
  store.stop(false);check(!store.current(live.generation,"pc-a")&&store.session().paired()&&!store.session().enabled,"stop fences old requests and retains resumable pairing");
  long next=store.beginPair();store.stop(true);check(!store.paired(next,"http://192.168.1.9:8766","new-token","phone-b","pc-b","phone")&&!store.session().paired(),"disconnect fences in-flight pairing and clears receiver credentials");
  check(context.getSharedPreferences("courseinbox",0).getString("token","").equals("upload-token"),"receiver disconnect leaves upload credential intact");
  context.failCommit=true;boolean failed=false;try{store.beginPair();}catch(IllegalStateException expected){failed=true;}check(failed&&!store.session().enabled,"configuration storage failure is surfaced instead of enabling receive");
  System.out.println("Computer reminder Android adapters: "+assertions+" assertions passed");
 }
}
