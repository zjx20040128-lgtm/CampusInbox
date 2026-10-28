package cn.courseinbox.companion;

import java.time.*;
import java.util.*;

/** Pure reminder policy: notification times never change the stored deadline. */
public final class DeadlinePlan {
    private static final ZoneOffset CN=ZoneOffset.ofHours(8);
    public static final class Event {
        public final String key,level;public final long at;
        Event(String id,String deadline,String level,long at){this.key=id+"|"+deadline+"|"+level;this.level=level;this.at=at;}
    }
    public static Event next(String id,String deadline,String status,long now,Set<String> sent){
        if(!Arrays.asList("pending","in_progress","done").contains(status)||deadline==null||deadline.isEmpty())return null;
        List<Event> events=new ArrayList<>();
        try{
            if(deadline.matches("\\d{4}-\\d{2}-\\d{2}")){
                LocalDate day=LocalDate.parse(deadline);
                events.add(new Event(id,deadline,"day",day.minusDays(1).atTime(9,0).toInstant(CN).toEpochMilli()));
                events.add(new Event(id,deadline,"date",day.atTime(9,0).toInstant(CN).toEpochMilli()));
                events.add(new Event(id,deadline,"overdue",day.plusDays(1).atTime(9,0).toInstant(CN).toEpochMilli()));
            }else{
                long due=OffsetDateTime.parse(deadline).toInstant().toEpochMilli();
                events.add(new Event(id,deadline,"day",due-86400000L));
                events.add(new Event(id,deadline,"soon",due-7200000L));
                events.add(new Event(id,deadline,"overdue",due));
            }
        }catch(RuntimeException invalid){return null;}
        Event latest=null;
        for(Event event:events)if(event.at<=now)latest=event;
        int dayComparison=deadline.length()==10?Instant.ofEpochMilli(now).atOffset(CN).toLocalDate().toString().compareTo(deadline):0;
        boolean expiredDayNotice=deadline.length()==10&&latest!=null&&((latest.level.equals("day")&&dayComparison>=0)||(latest.level.equals("date")&&dayComparison>0));
        if(latest!=null&&!expiredDayNotice&&!sent.contains(latest.key))return latest;
        for(Event event:events)if(event.at>now&&!sent.contains(event.key))return event;
        return null;
    }
    private DeadlinePlan(){}
}
