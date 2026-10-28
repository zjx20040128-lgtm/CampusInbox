package cn.courseinbox.companion;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;

/** Durable incoming spool. Evidence is removed only after the inbox has saved it. */
public final class PendingNotificationStore {
    private final File directory;
    public static final class Entry {
        public final String id,payload;
        private Entry(String id,String payload){this.id=id;this.payload=payload;}
    }
    public interface Saver {void save(Entry entry)throws Exception;}
    public static final class DrainResult {
        public final int saved,pending;public final String error;
        private DrainResult(int saved,int pending,String error){this.saved=saved;this.pending=pending;this.error=error;}
    }
    public PendingNotificationStore(File directory){this.directory=directory;}
    public synchronized void enqueue(String payload)throws IOException{
        byte[] bytes=payload.getBytes(StandardCharsets.UTF_8);
        if(bytes.length==0||bytes.length>200000)throw new IOException("通知内容超过本机队列限制。");
        if(!directory.isDirectory()&&!directory.mkdirs())throw new IOException("通知重试队列无法保存。");
        String id=hash(bytes);File target=new File(directory,id+".json");
        if(target.exists())return;
        if(files().length>=200)throw new IOException("手机待保存通知已达 200 条，请处理存储错误后重试。");
        File temp=new File(directory,id+".tmp");
        try(FileOutputStream output=new FileOutputStream(temp)){output.write(bytes);output.getFD().sync();}
        try{Files.move(temp.toPath(),target.toPath(),StandardCopyOption.ATOMIC_MOVE);}
        catch(AtomicMoveNotSupportedException unsupported){Files.move(temp.toPath(),target.toPath());}
    }
    public synchronized List<Entry> entries()throws IOException{
        List<Entry> result=new ArrayList<>();File[] files=files();
        Arrays.sort(files,Comparator.comparingLong(File::lastModified).thenComparing(File::getName));
        for(File file:files){if(file.length()>200000)throw new IOException("通知重试文件异常，请保留数据。");result.add(new Entry(file.getName().substring(0,64),new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8)));}
        return result;
    }
    public synchronized void acknowledge(String id)throws IOException{
        if(!id.matches("[0-9a-f]{64}"))throw new IllegalArgumentException("通知队列标识无效。");
        Files.deleteIfExists(new File(directory,id+".json").toPath());
    }
    public synchronized DrainResult drain(Saver saver)throws IOException{
        int saved=0;String error="";
        for(Entry entry:entries()){
            try{saver.save(entry);acknowledge(entry.id);saved++;}
            catch(IOException failure){error=failure.getMessage()==null?"存储暂不可用":failure.getMessage();break;}
            catch(Exception failure){if(error.isEmpty())error=failure.getMessage()==null?"通知内容需检查":failure.getMessage();}
        }
        return new DrainResult(saved,files().length,error);
    }
    private File[] files()throws IOException{
        if(!directory.exists())return new File[0];
        File[] files=directory.listFiles((dir,name)->name.matches("[0-9a-f]{64}\\.json"));
        if(files==null)throw new IOException("通知重试队列无法读取。");return files;
    }
    private static String hash(byte[] bytes){try{StringBuilder value=new StringBuilder();for(byte b:MessageDigest.getInstance("SHA-256").digest(bytes))value.append(String.format(Locale.US,"%02x",b&255));return value.toString();}catch(Exception error){throw new IllegalStateException(error);}}
}
