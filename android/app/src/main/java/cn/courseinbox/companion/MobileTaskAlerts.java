package cn.courseinbox.companion;

import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** One notification plan for drafts actually added by a web-reading batch. */
public final class MobileTaskAlerts {
    public static final class Batch {
        public final int count;
        public final LocalInbox.Message message;
        private Batch(int count,LocalInbox.Message message){this.count=count;this.message=message;}
    }
    private MobileTaskAlerts(){}
    public static Batch combine(Batch first,Batch second){
        if(first==null)return second==null?new Batch(0,null):second;
        if(second==null)return first;
        LocalInbox.Message newest=first.message;
        if(newest==null||(second.message!=null&&(second.message.timeKnown?second.message.capturedAt:0)>(newest.timeKnown?newest.capturedAt:0)))newest=second.message;
        return new Batch(first.count+second.count,newest);
    }
    public static Batch plan(List<LocalInbox.Task> before,List<LocalInbox.Task> after,List<LocalInbox.Message> messages){
        Set<String> existing=new HashSet<>(),sources=new HashSet<>();
        for(LocalInbox.Task task:before)existing.add(task.id);
        int count=0;
        for(LocalInbox.Task task:after)if(task.status.equals("draft")&&!existing.contains(task.id)){count++;sources.add(task.messageId);}
        LocalInbox.Message newest=null;
        for(LocalInbox.Message message:messages)if(sources.contains(message.id)){
            if(newest==null||(message.timeKnown?message.capturedAt:0)>(newest.timeKnown?newest.capturedAt:0))newest=message;
        }
        return new Batch(newest==null?0:count,newest);
    }
}
