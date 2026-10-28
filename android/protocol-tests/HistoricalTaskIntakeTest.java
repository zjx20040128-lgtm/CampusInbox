import cn.courseinbox.companion.LocalInbox;
import cn.courseinbox.companion.MobileTaskAlerts;
import cn.courseinbox.companion.MobileTaskRules;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.time.*;
import java.util.*;

/** Historical reading keeps evidence without turning ended work into new drafts. */
public final class HistoricalTaskIntakeTest {
    private static int assertions;
    private static final long NOW=Instant.parse("2026-10-16T09:05:00Z").toEpochMilli();
    private static void check(boolean ok,String reason){assertions++;if(!ok)throw new AssertionError(reason);}
    private static LocalInbox open(File file)throws Exception {return new LocalInbox(file,Clock.fixed(Instant.ofEpochMilli(NOW),ZoneOffset.UTC));}
    private static LocalInbox.Message message(String key,String source,String title,String body){
        return new LocalInbox.Message(key,source,"","","老师",title,title+"\n"+body,Instant.parse("2026-09-15T08:00:00Z").toEpochMilli(),true,"");
    }
    private static void text(DataOutputStream out,String value)throws Exception{byte[] bytes=value.getBytes(StandardCharsets.UTF_8);out.writeInt(bytes.length);out.write(bytes);}
    private static void legacy(File file,LocalInbox.Message message,String deadline,String status,long received)throws Exception {
        try(DataOutputStream out=new DataOutputStream(new FileOutputStream(file))){
            out.writeInt(0x43494D31);out.writeInt(1);
            for(String value:new String[]{message.id,message.source,message.conversation,message.course,message.sender,message.title,message.text,message.url})text(out,value);
            out.writeLong(message.capturedAt);out.writeLong(received);out.writeBoolean(message.timeKnown);out.writeInt(1);
            for(String value:new String[]{"legacy-task",message.id,message.title,"课程",deadline,message.text,"",status})text(out,value);
        }
    }
    public static void main(String[] args)throws Exception {
        File directory=Files.createTempDirectory("courseinbox-history-intake").toFile();
        try {
            File file=new File(directory,"new.bin");LocalInbox inbox=open(file);
            LocalInbox.Message september=message("old-work","学习通课程通知","作业20260915","课程名称：自然辩证法概论\n作业名称：作业20260915\n结束时间：2026-09-15 17:45");
            check(inbox.ingest(september),"historical source is saved");
            check(inbox.tasks().isEmpty(),"a work already expired when first read must not become a new draft");
            check(inbox.messages().get(0).text.equals(september.text),"historical original text remains exact");
            check(!inbox.ingest(september),"historical replay stays deduplicated");
            inbox.ingest(message("old-reading","学习通聊天","第二次课课前阅读","《软件工程高级管理技术》请完成课前阅读，截止2026-10-09"));
            inbox.ingest(message("old-notification","学习通系统通知","实验报告","请提交实验报告，截止2026-10-16 17:04"));
            check(inbox.tasks().isEmpty(),"expired date-only and timed tasks are filtered across automatic learning sources");
            LocalInbox.Message ended=message("ended","学习通课程通知","任务结束提醒","课程名称：大数据分析与内存计算\n任务名称：实验0-环境准备-Spark安装及配置");
            inbox.ingest(ended);
            check(inbox.tasks().isEmpty(),"an explicit task-ended notice never creates a new action even without a deadline");
            check(MobileTaskRules.extract(ended.text,NOW,true)==null,"ended notice is excluded by recognition itself");
            String extended="《软件工程》 第三次作业原截止2026年10月09日23:59，现延期到2026年10月30日18:00，请完成并提交。";
            MobileTaskRules.Candidate extension=MobileTaskRules.extract(extended,NOW,true);
            check(extension!=null&&extension.deadline.equals("2026-10-30T18:00:00+08:00"),"an extension must use its new effective deadline before historical filtering");
            check(MobileTaskRules.extract("第三次作业原截止2026年10月09日23:59，申请延期到2026年10月30日18:00，请完成并提交。",NOW,true).deadline.equals("2026-10-09T23:59:00+08:00"),"an extension application is not an approved new deadline");
            check(MobileTaskRules.extract("第三次作业截止2026年10月09日23:59，不能延期到2026年10月30日18:00。",NOW,true).deadline.equals("2026-10-09T23:59:00+08:00"),"a denied extension cannot replace the real deadline");
            check(MobileTaskRules.extract("第三次作业原截止2026年10月09日23:59，现延期到另行通知，请完成并提交。",NOW,true).deadline.isEmpty(),"an unresolved extension stays reviewable instead of using an obsolete deadline");
            LocalInbox changes=open(new File(directory,"changes.bin"));
            LocalInbox.Message revised=message("extended","学习通课程通知","第三次作业",extended);
            changes.ingest(revised);check(changes.tasks().size()==1,"an extension into the future remains reviewable");
            LocalInbox.Message semicolon=message("ended-semicolon","学习通课程通知","作业已结束；请查看结果","实验任务：实验报告");
            changes.ingest(semicolon);check(changes.tasks().size()==1,"a semicolon-ended status is not an actionable task");
            File revisedOld=new File(directory,"revised-legacy.bin");legacy(revisedOld,revised,"2026-10-09T23:59:00+08:00","draft",NOW);
            check(open(revisedOld).tasks().get(0).status.equals("draft"),"upgrade cannot hide an extension because old parsing stored the original deadline");
            File semicolonOld=new File(directory,"semicolon-legacy.bin");legacy(semicolonOld,semicolon,"","draft",NOW);
            check(open(semicolonOld).tasks().get(0).status.equals("ignored"),"upgrade also retires task-ended messages with semicolons");
            List<LocalInbox.Task> before=inbox.tasks();
            inbox.ingest(message("target","学习通课程通知","作业:《人工智能与深度学习》目标检测编程实践","作业名称：目标检测编程实践\n开始时间：2026-10-15 22:04\n结束时间：2026-10-30 23:59"));
            check(inbox.tasks().size()==1&&inbox.tasks().get(0).title.equals("目标检测编程实践"),"current actual assignment still creates a draft");
            check(inbox.tasks().get(0).deadline.equals("2026-10-30T23:59:00+08:00"),"current actual deadline remains exact");
            check(MobileTaskAlerts.plan(before,inbox.tasks(),inbox.messages()).count==1,"only eligible new work enters the task alert plan");
            inbox.ingest(message("today","学习通课程通知","今天的作业","请完成作业，截止2026-10-16"));
            inbox.ingest(message("exact","学习通课程通知","准时作业","请完成作业，截止2026-10-16 17:05"));
            check(inbox.tasks().size()==3,"a date-only deadline lasts all Beijing day and an exact deadline is not past prematurely");
            inbox.ingest(message("long-running","学习通课程通知","长期实验任务","请完成实验任务，截止2099-10-30"));
            check(inbox.tasks().size()==4,"old publication time alone cannot discard work that is still open");
            inbox.ingest(message("manual","手机文字导入","补录旧作业","请完成作业，截止2026-09-15"));
            check(inbox.tasks().size()==5,"explicit manual import remains reviewable");
            check(open(file).tasks().size()==5,"restart preserves valid and manual drafts");

            String[] statuses={"draft","pending","in_progress","done","submitted","cancelled","ignored"};
            for(String status:statuses){
                File old=new File(directory,status+".bin");legacy(old,september,"2026-09-15T17:45:00+08:00",status,NOW);
                LocalInbox restored=open(old);String wanted=status.equals("draft")?"ignored":status;
                check(restored.tasks().get(0).status.equals(wanted),"upgrade retires only unconfirmed erroneous draft: "+status);
                check(restored.messages().get(0).text.equals(september.text)&&restored.tasks().get(0).id.equals("legacy-task"),"upgrade preserves evidence and identity: "+status);
                check(open(old).tasks().get(0).status.equals(wanted),"upgrade state is persistent and idempotent: "+status);
            }
            File endedFile=new File(directory,"ended.bin");legacy(endedFile,ended,"","draft",NOW);
            check(open(endedFile).tasks().get(0).status.equals("ignored"),"upgrade also retires undated task-ended drafts");
            File onceCurrent=new File(directory,"once-current.bin");legacy(onceCurrent,september,"2026-09-15T17:45:00+08:00","draft",Instant.parse("2026-09-15T08:00:00Z").toEpochMilli());
            check(open(onceCurrent).tasks().get(0).status.equals("draft"),"upgrade must not retire a valid draft merely because time passed after intake");
            File manual=new File(directory,"manual-legacy.bin");legacy(manual,message("manual-old","手机文字导入","补录旧作业","请完成作业，截止2026-09-15"),"2026-09-15","draft",NOW);
            check(open(manual).tasks().get(0).status.equals("draft"),"upgrade preserves deliberately imported historical drafts");
            LocalInbox reopened=open(file);
            check(!reopened.ingest(september)&&reopened.tasks().size()==5,"history cannot regenerate tasks after restart and replay");
            File blocked=new File(directory,"blocked.bin");legacy(blocked,september,"2026-09-15T17:45:00+08:00","draft",NOW);
            byte[] original=Files.readAllBytes(blocked.toPath());File temp=new File(blocked.getPath()+".tmp");temp.mkdir();
            boolean failed=false;try{open(blocked);}catch(IOException expected){failed=true;}
            check(failed&&Arrays.equals(original,Files.readAllBytes(blocked.toPath())),"failed upgrade writes must leave the original archive intact and report failure");
            temp.delete();check(open(blocked).tasks().get(0).status.equals("ignored"),"a failed migration can recover without losing evidence");
        } finally {for(File file:directory.listFiles())file.delete();directory.delete();}
        System.out.println("Historical task intake: "+assertions+" assertions passed");
    }
}
