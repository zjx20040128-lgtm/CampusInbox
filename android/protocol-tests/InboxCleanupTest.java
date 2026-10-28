import cn.courseinbox.companion.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.time.*;
import java.util.*;

public final class InboxCleanupTest {
    private static int assertions;
    private static void check(boolean ok,String why){assertions++;if(!ok)throw new AssertionError(why);}
    private static final class IntakeClock extends Clock {
        long at=Instant.parse("2026-10-16T10:00:00Z").toEpochMilli();
        public ZoneId getZone(){return ZoneOffset.UTC;}public Clock withZone(ZoneId zone){return this;}public Instant instant(){return Instant.ofEpochMilli(at++);}
    }
    private static LocalInbox.Message message(String key,String body,String published,boolean known){return new LocalInbox.Message(key,"学习通课程通知","课程","课程","老师",key,body,published.isEmpty()?0:Instant.parse(published).toEpochMilli(),known,"");}
    private static int clear(LocalInbox inbox,Collection<String> ids)throws Exception{return inbox.clearMessages(ids);}
    private static LocalInbox.Message source(LocalInbox inbox,String id)throws Exception{return inbox.sourceMessage(id);}
    private static void text(DataOutputStream out,String value)throws Exception{byte[] bytes=value.getBytes(StandardCharsets.UTF_8);out.writeInt(bytes.length);out.write(bytes);}
    private static void oldArchive(File file,LocalInbox.Message message)throws Exception{
        try(DataOutputStream out=new DataOutputStream(new FileOutputStream(file))){
            out.writeInt(0x43494D31);out.writeInt(1);for(String value:new String[]{message.id,message.source,message.conversation,message.course,message.sender,message.title,message.text,message.url})text(out,value);
            out.writeLong(message.capturedAt);out.writeLong(message.receivedAt);out.writeBoolean(message.timeKnown);out.writeInt(0);
        }
    }
    public static void main(String[] args)throws Exception{
        File directory=Files.createTempDirectory("courseinbox-cleanup").toFile();
        try{
            File file=new File(directory,"inbox.bin");IntakeClock clock=new IntakeClock();LocalInbox inbox=new LocalInbox(file,clock);
            LocalInbox.Message work=message("current-work","请完成实验任务，截止另行通知。","2026-10-16T09:00:00Z",true);
            LocalInbox.Message old=message("old","这是去年保留的普通通知。","2025-03-09T02:54:00Z",true);
            LocalInbox.Message unknown=message("unknown","普通消息，发布时间未知。","",false);
            inbox.ingest(work);inbox.ingest(old);inbox.ingest(unknown);
            check(inbox.messages().get(0).id.equals(unknown.id),"unknown publication time sorts by first receipt");
            check(inbox.messages().get(1).id.equals(work.id)&&inbox.messages().get(2).id.equals(old.id),"late backfill of an old notice cannot outrank a recently published message");
            check(inbox.tasks().size()==1&&inbox.tasks().get(0).deadline.isEmpty(),"undated work is retained as a task draft");
            LocalInbox.Task task=inbox.tasks().get(0);inbox.confirm(task.id,task.title,task.course,"");
            check(DeadlinePlan.next(task.id,"","pending",clock.millis(),Collections.emptySet())==null,"an undated task has no invented reminder time");
            check(clear(inbox,Arrays.asList(old.id,work.id,"missing"))==2,"cleanup removes exactly the chosen visible messages");
            check(inbox.messages().size()==1&&inbox.messages().get(0).id.equals(unknown.id),"unselected messages stay visible");
            check(inbox.tasks().size()==1&&inbox.tasks().get(0).status.equals("pending"),"cleanup cannot delete or change the existing task");
            check(source(inbox,work.id).text.equals(work.text),"task-linked source remains accessible after message cleanup");
            check(source(inbox,old.id)==null,"unreferenced deleted message body is removed");
            inbox=new LocalInbox(file,clock);
            check(inbox.messages().size()==1&&source(inbox,work.id).text.equals(work.text),"cleanup and source retention persist after restart");
            check(!inbox.ingest(work)&&!inbox.ingest(old),"replayed cleaned sources cannot immediately return or regenerate tasks");
            check(inbox.messages().size()==1&&inbox.tasks().size()==1,"replay leaves visible counts unchanged");
            LocalInbox.Message later=message("later","刚发布的普通通知。","2026-10-16T11:00:00Z",true);inbox.ingest(later);
            check(inbox.messages().get(0).id.equals(later.id),"newly published content remains first");
            Set<String> snapshot=new HashSet<>();for(LocalInbox.Message m:inbox.messages())snapshot.add(m.id);
            LocalInbox.Message arrived=message("arrived","清理确认期间新到的消息。","2026-10-16T11:01:00Z",true);inbox.ingest(arrived);
            check(clear(inbox,snapshot)==2&&inbox.messages().get(0).id.equals(arrived.id),"cleanup applies only to its reviewed snapshot and preserves later arrivals");
            check(clear(inbox,Collections.emptySet())==0,"an empty selection does not clear anything");
            byte[] bytes=Files.readAllBytes(file.toPath());File blocked=new File(file.getPath()+".tmp");blocked.mkdir();
            boolean failed=false;try{clear(inbox,Collections.singleton(arrived.id));}catch(IOException expected){failed=true;}
            check(failed&&inbox.messages().size()==1&&Arrays.equals(bytes,Files.readAllBytes(file.toPath())),"failed cleanup rolls back both the visible list and the stored archive");blocked.delete();
            check(clear(inbox,Collections.singleton(arrived.id))==1&&inbox.messages().isEmpty(),"cleanup succeeds after storage recovers");
            inbox=new LocalInbox(file,clock);check(inbox.messages().isEmpty()&&inbox.tasks().size()==1&&source(inbox,work.id)!=null,"an empty message list still preserves its task and original evidence");
            File legacy=new File(directory,"legacy.bin");oldArchive(legacy,old);LocalInbox prior=new LocalInbox(legacy,clock);
            check(prior.messages().size()==1&&clear(prior,Collections.singleton(old.id))==1,"old CIM1 archives can be cleaned without resetting data");
            prior=new LocalInbox(legacy,clock);check(prior.messages().isEmpty()&&!prior.ingest(old),"old archive cleanup upgrades durably and keeps its replay marker");
            String image=ImageEvidenceStore.save(directory,new byte[]{1,2,3,4});
            LocalInbox.Message photo=new LocalInbox.Message("photo","手机图片导入","","","","图片原文","这是一张课堂照片。",0,false,image);
            prior.ingest(photo);clear(prior,Collections.singleton(photo.id));
            check(ImageEvidenceStore.resolve(directory,image)==null,"cleanup removes the original image when no retained message references it");
            String shared=ImageEvidenceStore.save(directory,new byte[]{5,6,7,8});
            LocalInbox.Message first=new LocalInbox.Message("first-photo","手机图片导入","","","","图片原文","第一段图片文字。",0,false,shared),second=new LocalInbox.Message("second-photo","手机图片导入","","","","图片原文","第二段图片文字。",0,false,shared);
            prior.ingest(first);prior.ingest(second);clear(prior,Collections.singleton(first.id));
            check(ImageEvidenceStore.resolve(directory,shared)!=null,"a shared image survives until its last source is cleared");
            clear(prior,Collections.singleton(second.id));check(ImageEvidenceStore.resolve(directory,shared)==null,"the last removed image reference releases the file");
            String linked=ImageEvidenceStore.save(directory,new byte[]{9,10,11,12});
            LocalInbox.Message photoTask=new LocalInbox.Message("photo-work","手机图片导入","","","","图片原文","请提交实验报告。",0,false,linked);
            prior.ingest(photoTask);clear(prior,Collections.singleton(photoTask.id));
            check(ImageEvidenceStore.resolve(directory,linked)!=null&&source(prior,photoTask.id)!=null,"a hidden task source retains its original image");
            String failing=ImageEvidenceStore.save(directory,new byte[]{13,14,15,16});
            LocalInbox.Message blockedPhoto=new LocalInbox.Message("photo-write-failure","手机图片导入","","","","图片原文","普通图片说明。",0,false,failing);prior.ingest(blockedPhoto);
            File blockImageSave=new File(legacy.getPath()+".tmp");blockImageSave.mkdir();failed=false;try{clear(prior,Collections.singleton(blockedPhoto.id));}catch(IOException expected){failed=true;}
            check(failed&&ImageEvidenceStore.resolve(directory,failing)!=null,"a failed archive write never deletes an original image");blockImageSave.delete();clear(prior,Collections.singleton(blockedPhoto.id));
        }finally{File images=new File(directory,"image-evidence");if(images.isDirectory())for(File image:images.listFiles())image.delete();for(File file:directory.listFiles())file.delete();directory.delete();}
        System.out.println("Inbox ordering and cleanup: "+assertions+" assertions passed");
    }
}
