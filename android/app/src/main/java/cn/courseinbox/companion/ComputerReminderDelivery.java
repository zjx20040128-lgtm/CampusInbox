package cn.courseinbox.companion;

import java.util.*;

/** Delivery policy independent of Android. Local side effects share the configuration fence. */
public final class ComputerReminderDelivery {
    public static final class Event {
        public final String id,kind,title,body;
        public Event(String id,String kind,String title,String body) {
            if(id==null||id.isEmpty()||id.length()>200||kind==null||kind.length()>80||title==null||title.length()>300||body==null||body.length()>20000)
                throw new IllegalArgumentException("电脑提醒格式不正确");
            this.id=id;this.kind=kind;this.title=title;this.body=body;
        }
    }
    public interface Fence { Object lock(); boolean current(long generation,String serverId); }
    public interface Journal {
        boolean delivered(String serverId,String id) throws Exception;
        void save(String serverId,Event event) throws Exception;
        List<String> pending(String serverId) throws Exception;
        void acknowledged(String serverId,List<String> ids) throws Exception;
    }
    public interface Notices { boolean allowed(); boolean show(String tag,Event event); }
    private final Fence fence;private final Journal journal;private final Notices notices;
    public ComputerReminderDelivery(Fence fence,Journal journal,Notices notices) {this.fence=fence;this.journal=journal;this.notices=notices;}
    public List<String> receive(long generation,String serverId,boolean serverEnabled,List<Event> events) throws Exception {
        synchronized(fence.lock()) {
            if(!serverEnabled||!fence.current(generation,serverId)||!notices.allowed())return Collections.emptyList();
            for(Event event:events) {
                if(!fence.current(generation,serverId)||!notices.allowed())return Collections.emptyList();
                if(journal.delivered(serverId,event.id))continue;
                if(!notices.show(tag(serverId,event.id),event))continue;
                journal.save(serverId,event); // Failed durable write must prevent ACK.
            }
            if(!fence.current(generation,serverId)||!notices.allowed())return Collections.emptyList();
            List<String> pending=journal.pending(serverId);
            // Backlogged receipts may span many polls; never exceed the server's per-request limit.
            return new ArrayList<>(pending.subList(0,Math.min(100,pending.size())));
        }
    }
    public void acknowledged(long generation,String serverId,List<String> ids) throws Exception {
        synchronized(fence.lock()) {if(fence.current(generation,serverId))journal.acknowledged(serverId,ids);}
    }
    public static String tag(String serverId,String eventId) {return "computer:"+serverId+":"+eventId;}
}
