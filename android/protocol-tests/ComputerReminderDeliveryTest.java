import cn.courseinbox.companion.ComputerReminderDelivery;
import cn.courseinbox.companion.ComputerReminderDelivery.*;
import java.util.*;
/** Removing the generation fence, durable delivery record, or permission gate breaks these cases. */
public final class ComputerReminderDeliveryTest {
    private static int assertions;
    private static void check(boolean ok,String why){assertions++;if(!ok)throw new AssertionError(why);}
    private static final class Session implements Fence {
        long generation=1;boolean enabled=true;String server="pc-a";
        public Object lock(){return this;}
        public boolean current(long g,String s){return enabled&&g==generation&&server.equals(s);}
    }
    private static final class Disk implements Journal {
        final Map<String,Event> history=new LinkedHashMap<>();final Set<String> pending=new LinkedHashSet<>();boolean fail;
        public boolean delivered(String server,String id){return history.containsKey(server+"/"+id);}
        public void save(String server,Event event)throws Exception{if(fail)throw new Exception("disk full");history.put(server+"/"+event.id,event);pending.add(server+"/"+event.id);}
        public List<String> pending(String server){List<String> ids=new ArrayList<>();for(String key:pending)if(key.startsWith(server+"/"))ids.add(key.substring(server.length()+1));return ids;}
        public void acknowledged(String server,List<String> ids){for(String id:ids)pending.remove(server+"/"+id);}
    }
    private static final class Shade implements Notices {
        boolean allowed=true,success=true;int posted;String lastTag;
        public boolean allowed(){return allowed;}
        public boolean show(String tag,Event event){posted++;lastTag=tag;return success;}
    }
    public static void main(String[] args)throws Exception {
        Session session=new Session();Disk disk=new Disk();Shade shade=new Shade();
        ComputerReminderDelivery engine=new ComputerReminderDelivery(session,disk,shade);
        List<Event> batch=Arrays.asList(new Event("event-1","message","老师通知","请阅读附件"));
        List<String> ack=engine.receive(1,"pc-a",true,batch);
        check(ack.equals(Arrays.asList("event-1"))&&disk.delivered("pc-a","event-1"),"ACK eligible only after successful notification and durable history");
        check(shade.posted==1&&shade.lastTag.equals("computer:pc-a:event-1"),"stable tag binds computer identity and event id");
        engine=new ComputerReminderDelivery(session,disk,shade);
        check(engine.receive(1,"pc-a",true,batch).equals(ack)&&shade.posted==1,"restart retries pending ACK without re-alerting");
        engine.acknowledged(1,"pc-a",ack);
        check(engine.receive(1,"pc-a",true,batch).isEmpty()&&shade.posted==1,"acknowledged replay remains deduplicated");
        List<Event> fresh=Arrays.asList(new Event("event-2","task","新任务","作业要求"));
        shade.allowed=false;check(engine.receive(1,"pc-a",true,fresh).isEmpty()&&!disk.delivered("pc-a","event-2")&&shade.posted==1,"disabled notifications cannot consume fresh alert");
        shade.allowed=true;shade.success=false;check(engine.receive(1,"pc-a",true,fresh).isEmpty()&&!disk.delivered("pc-a","event-2"),"failed notification remains unacknowledged");
        shade.success=true;disk.fail=true;boolean failed=false;try{engine.receive(1,"pc-a",true,fresh);}catch(Exception expected){failed=true;}
        check(failed&&!disk.delivered("pc-a","event-2"),"disk failure aborts ACK");disk.fail=false;
        int before=shade.posted;session.generation++;
        check(engine.receive(1,"pc-a",true,fresh).isEmpty()&&shade.posted==before,"old in-flight pairing cannot deliver");
        check(engine.receive(2,"pc-b",true,fresh).isEmpty()&&shade.posted==before,"wrong server identity cannot deliver");
        check(engine.receive(2,"pc-a",false,fresh).isEmpty()&&shade.posted==before,"paused computer cannot deliver");
        session.enabled=false;check(engine.receive(2,"pc-a",true,fresh).isEmpty()&&shade.posted==before,"phone stop fences delivery");session.enabled=true;
        ack=engine.receive(2,"pc-a",true,fresh);session.generation++;engine.acknowledged(2,"pc-a",ack);
        check(disk.pending("pc-a").equals(Arrays.asList("event-2")),"stale ACK response cannot mutate new session state");
        shade.allowed=false;check(engine.receive(3,"pc-a",true,Collections.emptyList()).isEmpty(),"pending ACK also waits while permission disabled");
        Session recoverySession=new Session();Disk recoveryDisk=new Disk();Shade recoveryShade=new Shade();
        ComputerReminderDelivery recovery=new ComputerReminderDelivery(recoverySession,recoveryDisk,recoveryShade);
        List<Event> backlog=new ArrayList<>();for(int i=0;i<201;i++)backlog.add(new Event("backlog-"+i,"message","恢复提醒","原文"));
        List<String> first=recovery.receive(1,"pc-a",true,backlog);
        check(first.size()==100&&recoveryDisk.pending("pc-a").size()==201,"large durable receipt backlog must honor server's 100-ID ACK limit");
        recovery.acknowledged(1,"pc-a",first);
        List<String> second=recovery.receive(1,"pc-a",true,Collections.emptyList());check(second.size()==100,"next empty poll recovers next ACK batch without new events");recovery.acknowledged(1,"pc-a",second);
        List<String> last=recovery.receive(1,"pc-a",true,Collections.emptyList());check(last.size()==1,"last ACK batch retains the remainder");recovery.acknowledged(1,"pc-a",last);
        check(recoveryDisk.pending("pc-a").isEmpty()&&recoveryShade.posted==201,"all receipts eventually ACK without re-alerting delivered history");
        System.out.println("Computer reminder delivery: "+assertions+" assertions passed");
    }
}
