package cn.courseinbox.companion;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Matrix;
import android.media.ExifInterface;
import android.net.Uri;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Reads a user-selected image with strict byte and decoded-pixel bounds. */
public final class MobileImageOcr {
    public static final ExecutorService WORKER=Executors.newSingleThreadExecutor();
    public static final class Selection {
        public final byte[] bytes;public final Bitmap bitmap;
        Selection(byte[] bytes,Bitmap bitmap){this.bytes=bytes;this.bitmap=bitmap;}
    }
    private MobileImageOcr(){}
    public static Selection open(Context context,Uri uri)throws IOException{
        if(uri==null)throw new IOException("未选中图片。");
        try(InputStream input=context.getContentResolver().openInputStream(uri)){
            if(input==null)throw new IOException("无法读取所选图片。");
            ByteArrayOutputStream output=new ByteArrayOutputStream();byte[] chunk=new byte[8192];int count;
            while((count=input.read(chunk))!=-1){
                if(output.size()+count>ImageImportPolicy.MAX_IMAGE_BYTES)throw new IOException("图片超过 8 MB，请缩小后重试。");
                output.write(chunk,0,count);
            }
            byte[] bytes=output.toByteArray();
            if(!ImageImportPolicy.acceptsSize(bytes.length))throw new IOException("图片为空或超过 8 MB。");
            return new Selection(bytes,decode(bytes));
        }
    }
    public static Bitmap preview(File file)throws IOException{return decode(Files.readAllBytes(file.toPath()));}
    private static Bitmap decode(byte[] bytes)throws IOException{
        if(!ImageImportPolicy.acceptsSize(bytes.length))throw new IOException("图片为空或超过 8 MB。");
        BitmapFactory.Options bounds=new BitmapFactory.Options();bounds.inJustDecodeBounds=true;
        BitmapFactory.decodeByteArray(bytes,0,bytes.length,bounds);
        if(!ImageImportPolicy.acceptsMime(bounds.outMimeType))throw new IOException("请选择 PNG、JPG、BMP 或 WebP 图片。");
        BitmapFactory.Options options=new BitmapFactory.Options();
        options.inSampleSize=ImageImportPolicy.sampleSize(bounds.outWidth,bounds.outHeight);
        Bitmap bitmap=BitmapFactory.decodeByteArray(bytes,0,bytes.length,options);
        if(bitmap==null)throw new IOException("图片无法解码，请换一张清晰截图。");
        try{
            int orientation=new ExifInterface(new ByteArrayInputStream(bytes)).getAttributeInt(ExifInterface.TAG_ORIENTATION,ExifInterface.ORIENTATION_NORMAL);
            Matrix matrix=new Matrix();int rotation=0;
            switch(orientation){
                case ExifInterface.ORIENTATION_ROTATE_90:case ExifInterface.ORIENTATION_TRANSPOSE:rotation=90;break;
                case ExifInterface.ORIENTATION_ROTATE_180:case ExifInterface.ORIENTATION_FLIP_VERTICAL:rotation=180;break;
                case ExifInterface.ORIENTATION_ROTATE_270:case ExifInterface.ORIENTATION_TRANSVERSE:rotation=270;break;
                default:break;
            }
            if(orientation==ExifInterface.ORIENTATION_FLIP_HORIZONTAL||orientation==ExifInterface.ORIENTATION_TRANSPOSE||orientation==ExifInterface.ORIENTATION_TRANSVERSE||orientation==ExifInterface.ORIENTATION_FLIP_VERTICAL)matrix.postScale(-1,1);
            if(rotation!=0)matrix.postRotate(rotation);
            if(!matrix.isIdentity()){
                Bitmap adjusted=Bitmap.createBitmap(bitmap,0,0,bitmap.getWidth(),bitmap.getHeight(),matrix,true);
                if(adjusted!=bitmap){bitmap.recycle();bitmap=adjusted;}
            }
        }catch(IOException|RuntimeException ignored){/* Images without EXIF keep their decoded orientation. */}
        return bitmap;
    }
}
