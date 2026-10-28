package cn.courseinbox.companion;

import java.net.URI;

/** Restricts the account WebView to official HTTPS pages. */
public final class LearningUrls {
    public static final String PORTAL="https://i.chaoxing.com/";
    public static final String CHAT="https://fe.chaoxing.com/front/webim/index.html";
    public static final String NOTICES="https://notice.chaoxing.com/pc/notice/myNotice";
    private LearningUrls(){}
    public static boolean allowed(String value){
        try {
            URI uri=new URI(value);String host=uri.getHost();
            return "https".equals(uri.getScheme())&&uri.getUserInfo()==null&&(uri.getPort()==-1||uri.getPort()==443)&&host!=null
                &&(host.equals("chaoxing.com")||host.endsWith(".chaoxing.com"));
        }catch(Exception ignored){return false;}
    }
    public static boolean collectible(String value){
        if(!allowed(value))return false;
        try{URI uri=new URI(value);return (uri.getHost().equals("fe.chaoxing.com")&&uri.getPath().equals("/front/webim/index.html"))
            ||(uri.getHost().equals("notice.chaoxing.com")&&uri.getPath().startsWith("/pc/notice/"));}
        catch(Exception ignored){return false;}
    }
    public static boolean login(String value){
        if(!allowed(value))return false;
        try{URI uri=new URI(value);return uri.getHost().equals("passport2.chaoxing.com")&&(uri.getPath().equals("/login")||uri.getPath().startsWith("/login/"));}
        catch(Exception ignored){return false;}
    }
}
