import cn.courseinbox.companion.DeadlinePlan;
import cn.courseinbox.companion.LocalInbox;
import java.time.Instant;
import java.util.*;
import java.nio.file.Files;
import java.io.File;

public final class DeadlinePlanTest {
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    static long at(String value){return Instant.parse(value).toEpochMilli();}
    public static void main(String[] args)throws Exception{
        Set<String> sent=new HashSet<>();String due="2026-10-20T18:00:00+08:00";
        DeadlinePlan.Event next=DeadlinePlan.next("a",due,"pending",at("2026-10-18T00:00:00Z"),sent);
        check(next.at==at("2026-10-19T10:00:00Z"),"first alert 24 hours before exact deadline");
        check(DeadlinePlan.next("a",due,"draft",0,sent)==null,"draft cannot alert");
        check(DeadlinePlan.next("a",due,"submitted",0,sent)==null,"submitted cannot alert");
        check(DeadlinePlan.next("a",due,"cancelled",0,sent)==null,"cancelled cannot alert");
        check(DeadlinePlan.next("a","bad","pending",0,sent)==null,"invalid deadline cannot alert");
        next=DeadlinePlan.next("a",due,"done",at("2026-10-20T09:00:00Z"),sent);
        check(next.level.equals("soon"),"done still needs submission; catch up only most urgent threshold");
        sent.add(next.key);
        next=DeadlinePlan.next("a",due,"done",at("2026-10-20T09:00:00Z"),sent);
        check(next.level.equals("overdue")&&next.at==at("2026-10-20T10:00:00Z"),"sent two-hour alert does not cause old day alert");
        sent.add(next.key);
        check(DeadlinePlan.next("a",due,"pending",at("2026-10-21T00:00:00Z"),sent)==null,"delivered deadline stays deduplicated after restart");
        check(DeadlinePlan.next("a","2026-10-22T18:00:00+08:00","pending",at("2026-10-20T09:00:00Z"),sent).level.equals("day"),"extension has a new schedule identity");
        next=DeadlinePlan.next("b","2026-10-20","pending",at("2026-10-20T00:00:00Z"),sent);
        check(next.at==at("2026-10-20T01:00:00Z")&&next.level.equals("date"),"date-only reminder uses Beijing 09:00, not invented deadline");
        next=DeadlinePlan.next("b","2026-10-20","pending",at("2026-10-20T23:00:00Z"),sent);
        check(next.level.equals("overdue"),"morning after deadline must never announce today deadline");
        File dir=Files.createTempDirectory("deadline-test").toFile();File file=new File(dir,"inbox.bin");
        try{
            LocalInbox inbox=new LocalInbox(file);
            inbox.ingest(new LocalInbox.Message("x","手动导入","","数据库","","","实验三作业：提交报告",0,false,""));
            String id=inbox.tasks().get(0).id;inbox.confirm(id,"实验三","数据库",due);
            inbox.setStatus(id,"done");inbox.updateDeadline(id,"2026-10-22");
            LocalInbox reopened=new LocalInbox(file);
            check(reopened.tasks().get(0).deadline.equals("2026-10-22"),"edited deadline persists");
            check(reopened.tasks().get(0).status.equals("done"),"deadline edit preserves local progress");
        }finally{for(File f:dir.listFiles())f.delete();dir.delete();}
        System.out.println("PASS: deadline timing, date precision, deduplication, lifecycle and persisted rescheduling");
    }
}
