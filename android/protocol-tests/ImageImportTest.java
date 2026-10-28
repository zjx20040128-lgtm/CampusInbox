import cn.courseinbox.companion.ImageImportPolicy;
import cn.courseinbox.companion.ImageEvidenceStore;
import cn.courseinbox.companion.LocalInbox;
import java.io.File;
import java.nio.file.Files;
import java.util.Arrays;

public final class ImageImportTest {
    private static int assertions;
    private static void check(boolean condition,String reason){assertions++;if(!condition)throw new AssertionError(reason);}
    public static void main(String[] args)throws Exception{
        check(ImageImportPolicy.acceptsMime("image/png"),"PNG screenshots accepted");
        check(ImageImportPolicy.acceptsMime("image/jpeg"),"JPEG photos accepted");
        check(!ImageImportPolicy.acceptsMime("text/plain"),"non-image file rejected");
        check(ImageImportPolicy.acceptsSize(8*1024*1024),"8 MB limit inclusive");
        check(!ImageImportPolicy.acceptsSize(8*1024*1024+1),"oversized image rejected");
        check(ImageImportPolicy.sampleSize(1440,3168)==1,"normal phone screenshot keeps resolution");
        check(ImageImportPolicy.sampleSize(12000,9000)>=4,"large dimensions are bounded before decoding");
        String recognized=ImageImportPolicy.reviewText("《软件工程》 请 提 交 SQL scripts。截止：2026 年 10 月 20 日 23：59。\n");
        check(recognized.contains("请 提 交 SQL scripts"),"OCR spacing remains visible for review");
        check(recognized.contains("2026 年 10 月 20 日 23：59"),"OCR date spacing is preserved for review");
        check(ImageImportPolicy.reviewText("请完成第 1 2 题\r\n明天截止").equals("请完成第 1 2 题\n明天截止"),"number spacing survives OCR review and newlines normalize");
        check(ImageImportPolicy.textForRules(recognized).contains("请提交 SQL scripts"),"rules can parse OCR-spaced Chinese without changing displayed text");
        check(ImageImportPolicy.textForRules("请完成第 1 2 题").contains("第1 2题"),"rule normalization cannot merge two separate digits");
        check(ImageImportPolicy.validateEditedText("请完成第 1 2 题").equals("请完成第 1 2 题"),"user-corrected spacing is preserved exactly");
        boolean rejected=false;try{ImageImportPolicy.reviewText("  \n  ");}catch(IllegalArgumentException expected){rejected=true;}
        check(rejected,"empty OCR result cannot create an inbox message");

        File root=Files.createTempDirectory("courseinbox-image-import").toFile();
        try{
            byte[] image=new byte[]{1,2,3,4,5};
            String reference=ImageEvidenceStore.save(root,image);
            File saved=ImageEvidenceStore.resolve(root,reference);
            check(saved!=null&&Arrays.equals(Files.readAllBytes(saved.toPath()),image),"original image bytes stored privately");
            check(ImageEvidenceStore.resolve(root,"local-image:../other")==null,"crafted reference cannot escape private storage");
            LocalInbox inbox=new LocalInbox(new File(root,"inbox.bin"));
            LocalInbox.Message message=new LocalInbox.Message("image-test","手机图片导入","","软件工程","","图片原文",recognized,0,false,reference);
            check(inbox.ingest(message),"recognized text ingested once");
            check(!inbox.ingest(new LocalInbox.Message("image-test","手机图片导入","","软件工程","","图片原文",recognized,0,false,reference)),"same image import key and text cannot create duplicate messages or drafts");
            check(inbox.messages().get(0).text.equals(recognized),"saved source evidence keeps OCR spacing");
            check(inbox.tasks().size()==1&&inbox.tasks().get(0).status.equals("draft"),"image text creates only a reviewable draft");
            check(inbox.tasks().get(0).requirements.equals(recognized),"draft requirements preserve reviewed OCR text");
            LocalInbox reopened=new LocalInbox(new File(root,"inbox.bin"));
            check(reopened.messages().get(0).url.equals(reference),"image reference survives inbox reload");
            reopened.ingest(new LocalInbox.Message("image-course","手机图片导入","","软件工程","","图片原文","请阅读《数据库系统》并提交报告",0,false,""));
            check(reopened.tasks().get(1).course.equals("软件工程"),"explicitly corrected course outranks a book title in OCR text");
            ImageEvidenceStore.remove(root,reference);
            check(ImageEvidenceStore.resolve(root,reference)==null,"cancelled image can be removed");
        }finally{
            File dir=new File(root,"image-evidence");if(dir.exists())for(File file:dir.listFiles())file.delete();
            if(dir.exists())dir.delete();for(File file:root.listFiles())file.delete();root.delete();
        }
        System.out.println("Mobile image import: "+assertions+" assertions passed");
    }
}
