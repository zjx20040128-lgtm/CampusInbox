package cn.courseinbox.companion;

/** Bounds local OCR input and keeps the recognized text reviewable. */
public final class ImageImportPolicy {
    public static final int MAX_IMAGE_BYTES=8*1024*1024;
    private static final int MAX_TEXT_LENGTH=30000;
    private ImageImportPolicy(){}
    public static boolean acceptsMime(String mime){
        return "image/png".equals(mime)||"image/jpeg".equals(mime)||"image/bmp".equals(mime)||"image/webp".equals(mime);
    }
    public static boolean acceptsSize(long bytes){return bytes>0&&bytes<=MAX_IMAGE_BYTES;}
    public static int sampleSize(int width,int height){
        if(width<=0||height<=0)throw new IllegalArgumentException("图片尺寸无效。");
        int sample=1;
        while(width/sample>4096||height/sample>4096||(long)(width/sample)*(height/sample)>8000000L)sample*=2;
        return sample;
    }
    public static String reviewText(String raw){
        String value=raw==null?"":raw.replace("\r\n","\n").replace('\r','\n').trim();
        return validateEditedText(value);
    }
    /** OCR spacing may obstruct rules, but the saved message must keep the reviewed text. */
    public static String textForRules(String reviewed){
        return reviewed.replaceAll("(?<=[\\u4e00-\\u9fff《》【】：、，。])[ \\t\\u00a0]+(?=[\\u4e00-\\u9fff0-9《》【】：、，。])","")
            .replaceAll("(?<=[0-9])[ \\t\\u00a0]+(?=[\\u4e00-\\u9fff《》【】：、，。])","");
    }
    public static String validateEditedText(String raw){
        String value=raw==null?"":raw.trim();
        if(value.isEmpty())throw new IllegalArgumentException("图片中未识别到文字，请换一张清晰截图或导入文字。");
        if(value.length()>MAX_TEXT_LENGTH)throw new IllegalArgumentException("识别文字超过 30000 字，请分张导入。");
        return value;
    }
}
