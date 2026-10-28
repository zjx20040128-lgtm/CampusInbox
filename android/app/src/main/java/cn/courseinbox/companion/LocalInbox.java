package cn.courseinbox.companion;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.time.Clock;
import java.util.*;

/** App-private persistent evidence and human-confirmed tasks; no server required. */
public final class LocalInbox {
    private static final int MAGIC=0x43494D31,MAGIC_CLEANUP=0x43494D32,MAX_RECORDS=10000,MAX_BYTES=160000;
    private final File file;
    private final Clock clock;
    private final List<Message> messages=new ArrayList<>();
    private final List<Task> tasks=new ArrayList<>();
    private final Set<String> hiddenMessages=new HashSet<>();
    private final LinkedHashSet<String> clearedMessages=new LinkedHashSet<>();
    public static final class Message {
        public final String id,source,conversation,course,sender,title,text,url;
        public final long capturedAt,receivedAt;public final boolean timeKnown;
        public Message(String key,String source,String conversation,String course,String sender,String title,String text,long capturedAt,boolean timeKnown,String url){
            this(hash(source+"|"+key+"|"+text),source,conversation,course,sender,title,text,capturedAt,timeKnown,url,System.currentTimeMillis());
        }
        private Message(String id,String source,String conversation,String course,String sender,String title,String text,long capturedAt,boolean timeKnown,String url,long receivedAt){
            this.id=id;this.source=source;this.conversation=conversation;this.course=course;this.sender=sender;this.title=title;this.text=text;this.capturedAt=capturedAt;this.timeKnown=timeKnown;this.url=url;this.receivedAt=receivedAt;
        }
        private Message received(long at){return new Message(id,source,conversation,course,sender,title,text,capturedAt,timeKnown,url,at);}
    }
    public static final class Task {
        public final String id,messageId,title,course,deadline,requirements,warning,status;
        private Task(String id,String messageId,String title,String course,String deadline,String requirements,String warning,String status){this.id=id;this.messageId=messageId;this.title=title;this.course=course;this.deadline=deadline;this.requirements=requirements;this.warning=warning;this.status=status;}
        private Task change(String title,String course,String deadline,String status){return new Task(id,messageId,title,course,deadline,requirements,warning,status);}
    }
    public LocalInbox(File file)throws IOException{this(file,Clock.systemUTC());}
    public LocalInbox(File file,Clock clock)throws IOException{this.file=file;this.clock=Objects.requireNonNull(clock);if(file.exists()){load();retireHistoricalDrafts();}}
    public synchronized List<Message> messages(){
        List<Message> result=new ArrayList<>();for(Message message:messages)if(!hiddenMessages.contains(message.id))result.add(message);Collections.reverse(result);
        result.sort(Comparator.comparingLong((Message m)->m.timeKnown&&m.capturedAt>0?m.capturedAt:m.receivedAt).reversed().thenComparing(Comparator.comparingLong((Message m)->m.receivedAt).reversed()));return result;
    }
    public synchronized Message sourceMessage(String id){for(Message message:messages)if(message.id.equals(id))return message;return null;}
    public synchronized List<Task> tasks(){return new ArrayList<>(tasks);}
    public synchronized int clearMessages(Collection<String> ids)throws IOException{
        Set<String> selected=new HashSet<>(ids),referenced=new HashSet<>(),removedImages=new HashSet<>();for(Task task:tasks)referenced.add(task.messageId);
        List<Message> before=new ArrayList<>(messages);Set<String> oldHidden=new HashSet<>(hiddenMessages);LinkedHashSet<String> oldCleared=new LinkedHashSet<>(clearedMessages);int removed=0;
        for(Iterator<Message> iterator=messages.iterator();iterator.hasNext();){Message message=iterator.next();if(!selected.contains(message.id)||hiddenMessages.contains(message.id))continue;
            if(referenced.contains(message.id))hiddenMessages.add(message.id);else{iterator.remove();clearedMessages.add(message.id);if(message.url.startsWith("local-image:"))removedImages.add(message.url);}removed++;
        }
        while(clearedMessages.size()>MAX_RECORDS)clearedMessages.remove(clearedMessages.iterator().next());
        if(removed>0)try{save();}catch(IOException error){messages.clear();messages.addAll(before);hiddenMessages.clear();hiddenMessages.addAll(oldHidden);clearedMessages.clear();clearedMessages.addAll(oldCleared);throw error;}
        for(Message message:messages)removedImages.remove(message.url);
        IOException imageFailure=null;for(String reference:removedImages)try{ImageEvidenceStore.remove(file.getAbsoluteFile().getParentFile(),reference);}catch(IOException error){imageFailure=error;}
        if(imageFailure!=null)throw new IOException("消息已清理，但部分原图删除失败。",imageFailure);return removed;
    }
    public synchronized boolean ingest(Message message)throws IOException{
        if(message.text==null||message.text.trim().isEmpty()||message.text.length()>30000)throw new IllegalArgumentException("消息正文无效。");
        if(clearedMessages.contains(message.id)||sourceMessage(message.id)!=null)return false;
        if(messages.size()>=MAX_RECORDS)throw new IOException("手机消息存储已满，请先备份原文。");
        message=message.received(clock.millis());
        messages.add(message);
        String taskText="手机图片导入".equals(message.source)?ImageImportPolicy.textForRules(message.text):message.text;
        MobileTaskRules.Candidate candidate=MobileTaskRules.extract(taskText,message.capturedAt,message.timeKnown);
        if(candidate!=null&&"手机图片导入".equals(message.source))candidate=new MobileTaskRules.Candidate(candidate.title,candidate.course,candidate.deadline,message.text,candidate.warning);
        if(candidate!=null&&historical(message,candidate.deadline))candidate=null;
        if(candidate!=null)tasks.add(new Task(UUID.randomUUID().toString(),message.id,candidate.title,message.course.isEmpty()?candidate.course:message.course,candidate.deadline,candidate.requirements,candidate.warning,"draft"));
        try{save();}catch(IOException error){messages.remove(messages.size()-1);if(candidate!=null)tasks.remove(tasks.size()-1);throw error;}return true;
    }
    private static boolean historical(Message message,String deadline){
        if(!Arrays.asList("学习通课程通知","学习通聊天","学习通系统通知").contains(message.source))return false;
        return MobileTaskRules.endedNotice(message.text)||(message.receivedAt>0&&MobileTaskRules.overdue(deadline,"pending",message.receivedAt));
    }
    private void retireHistoricalDrafts()throws IOException{
        Map<String,Message> sources=new HashMap<>();for(Message message:messages)sources.put(message.id,message);
        List<Task> before=new ArrayList<>(tasks);boolean changed=false;
        for(int i=0;i<tasks.size();i++){
            Task task=tasks.get(i);Message source=sources.get(task.messageId);
            if(task.status.equals("draft")&&source!=null&&historical(source,task.deadline)){
                MobileTaskRules.Candidate parsed=MobileTaskRules.extract(source.text,source.capturedAt,source.timeKnown);
                if(!MobileTaskRules.endedNotice(source.text)&&parsed!=null&&!parsed.deadline.equals(task.deadline))continue;
                tasks.set(i,task.change(task.title,task.course,task.deadline,"ignored"));changed=true;
            }
        }
        if(changed)try{save();}catch(IOException error){tasks.clear();tasks.addAll(before);throw error;}
    }
    public synchronized void confirm(String id,String title,String course,String deadline)throws IOException{
        if(title==null||title.trim().isEmpty()||title.length()>100)throw new IllegalArgumentException("任务名称应为 1–100 字。");
        if(course==null||course.length()>100||!MobileTaskRules.validDeadline(deadline))throw new IllegalArgumentException("课程或截止时间无效，请填写 YYYY-MM-DD 或带时区的完整时间。");
        replace(id,title.trim(),course.trim(),deadline,"pending",true);
    }
    public synchronized void setStatus(String id,String status)throws IOException{
        if(!Arrays.asList("pending","in_progress","done","submitted","cancelled","ignored").contains(status))throw new IllegalArgumentException("任务状态无效。");
        replace(id,null,null,null,status,false);
    }
    public synchronized void updateDeadline(String id,String deadline)throws IOException{
        if(!MobileTaskRules.validDeadline(deadline))throw new IllegalArgumentException("截止日期或时间无效。");
        for(Task task:tasks)if(task.id.equals(id)){
            if(task.status.equals("draft")||task.status.equals("ignored"))throw new IllegalArgumentException("请先确认任务。");
            replace(id,null,null,deadline,task.status,false);return;
        }
        throw new IllegalArgumentException("任务不存在。");
    }
    private void replace(String id,String title,String course,String deadline,String status,boolean confirming)throws IOException{
        for(int i=0;i<tasks.size();i++){
            Task before=tasks.get(i);if(!before.id.equals(id))continue;
            if(confirming&&!before.status.equals("draft"))throw new IllegalArgumentException("这个草稿已处理。");
            if(!confirming&&before.status.equals("draft")&&!status.equals("ignored"))throw new IllegalArgumentException("请先确认草稿。");
            tasks.set(i,before.change(title==null?before.title:title,course==null?before.course:course,deadline==null?before.deadline:deadline,status));
            try{save();}catch(IOException error){tasks.set(i,before);throw error;}return;
        }throw new IllegalArgumentException("任务不存在。");
    }
    private void save()throws IOException{
        File parent=file.getParentFile();if(parent!=null&&!parent.exists()&&!parent.mkdirs())throw new IOException("无法创建手机存储目录。");
        File temp=new File(file.getPath()+".tmp");
        try(FileOutputStream raw=new FileOutputStream(temp);DataOutputStream out=new DataOutputStream(raw)){
            out.writeInt(MAGIC_CLEANUP);out.writeInt(messages.size());
            for(Message m:messages){for(String s:new String[]{m.id,m.source,m.conversation,m.course,m.sender,m.title,m.text,m.url})writeString(out,s);out.writeLong(m.capturedAt);out.writeLong(m.receivedAt);out.writeBoolean(m.timeKnown);}
            out.writeInt(tasks.size());
            for(Task t:tasks)for(String s:new String[]{t.id,t.messageId,t.title,t.course,t.deadline,t.requirements,t.warning,t.status})writeString(out,s);
            out.writeInt(hiddenMessages.size());for(String id:hiddenMessages)writeString(out,id);
            out.writeInt(clearedMessages.size());for(String id:clearedMessages)writeString(out,id);
            out.flush();raw.getFD().sync();
        }
        try{Files.move(temp.toPath(),file.toPath(),StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);}
        catch(AtomicMoveNotSupportedException unsupported){Files.move(temp.toPath(),file.toPath(),StandardCopyOption.REPLACE_EXISTING);}
    }
    private void load()throws IOException{
        try(DataInputStream in=new DataInputStream(new FileInputStream(file))){
            int format=in.readInt();if(format!=MAGIC&&format!=MAGIC_CLEANUP)throw new IOException("手机存档格式异常，请保留应用数据。");
            int count=readCount(in);
            for(int i=0;i<count;i++){String[] s=new String[8];for(int j=0;j<s.length;j++)s[j]=readString(in);long at=in.readLong(),received=in.readLong();boolean known=in.readBoolean();messages.add(new Message(s[0],s[1],s[2],s[3],s[4],s[5],s[6],at,known,s[7],received));}
            count=readCount(in);
            for(int i=0;i<count;i++){String[] s=new String[8];for(int j=0;j<s.length;j++)s[j]=readString(in);tasks.add(new Task(s[0],s[1],s[2],s[3],s[4],s[5],s[6],s[7]));}
            if(format==MAGIC_CLEANUP){
                count=readCount(in);for(int i=0;i<count;i++){String id=readString(in);if(sourceMessage(id)==null||!hiddenMessages.add(id))throw new IOException("消息清理记录异常，请保留应用数据。");}
                count=readCount(in);for(int i=0;i<count;i++){String id=readString(in);if(!id.matches("[0-9a-f]{64}")||!clearedMessages.add(id))throw new IOException("消息去重记录异常，请保留应用数据。");}
            }
            if(in.read()!=-1)throw new IOException("手机存档尾部异常，请保留应用数据。");
        }
    }
    private static int readCount(DataInputStream in)throws IOException{int count=in.readInt();if(count<0||count>MAX_RECORDS)throw new IOException("存档记录数量异常。");return count;}
    private static void writeString(DataOutputStream out,String value)throws IOException{byte[] bytes=(value==null?"":value).getBytes(StandardCharsets.UTF_8);if(bytes.length>MAX_BYTES)throw new IOException("消息字段过长。");out.writeInt(bytes.length);out.write(bytes);}
    private static String readString(DataInputStream in)throws IOException{int length=in.readInt();if(length<0||length>MAX_BYTES)throw new IOException("存档字段异常。");byte[] bytes=new byte[length];in.readFully(bytes);return new String(bytes,StandardCharsets.UTF_8);}
    private static String hash(String value){try{byte[] bytes=MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));StringBuilder result=new StringBuilder();for(byte b:bytes)result.append(String.format(Locale.US,"%02x",b&255));return result.toString();}catch(Exception error){throw new IllegalStateException(error);}}
}
