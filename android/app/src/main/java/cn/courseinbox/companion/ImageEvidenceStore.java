package cn.courseinbox.companion;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.Locale;
import java.util.UUID;

/** Original imported images live in app-private storage, referenced by local inbox messages. */
public final class ImageEvidenceStore {
    private static final String PREFIX="local-image:";
    private ImageEvidenceStore(){}
    public static String save(File filesDir,byte[] image)throws IOException{
        if(image==null||!ImageImportPolicy.acceptsSize(image.length))throw new IllegalArgumentException("图片为空或超过 8 MB。");
        File directory=new File(filesDir,"image-evidence");
        if(!directory.exists()&&!directory.mkdirs())throw new IOException("无法创建图片存档目录。");
        String id=UUID.randomUUID().toString().toLowerCase(Locale.US);
        File temp=new File(directory,id+".tmp"),target=new File(directory,id+".img");
        try{
            try(FileOutputStream out=new FileOutputStream(temp)){out.write(image);out.flush();out.getFD().sync();}
            try{Files.move(temp.toPath(),target.toPath(),StandardCopyOption.ATOMIC_MOVE);}
            catch(AtomicMoveNotSupportedException unsupported){Files.move(temp.toPath(),target.toPath());}
        }finally{Files.deleteIfExists(temp.toPath());}
        return PREFIX+id;
    }
    public static File resolve(File filesDir,String reference){
        if(reference==null||!reference.matches("local-image:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"))return null;
        File file=new File(new File(filesDir,"image-evidence"),reference.substring(PREFIX.length())+".img");
        return file.isFile()?file:null;
    }
    public static void remove(File filesDir,String reference)throws IOException{
        File file=resolve(filesDir,reference);if(file!=null)Files.deleteIfExists(file.toPath());
    }
}
