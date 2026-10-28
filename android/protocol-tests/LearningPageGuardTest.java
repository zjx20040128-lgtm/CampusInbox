import cn.courseinbox.companion.LearningPageGuard;
import cn.courseinbox.companion.LearningUrls;

public final class LearningPageGuardTest {
    private static int assertions;
    private static void check(boolean condition,String message){assertions++;if(!condition)throw new AssertionError(message);}
    public static void main(String[] args){
        LearningPageGuard request=new LearningPageGuard(7,LearningUrls.CHAT);
        check(request.permits(7,LearningUrls.CHAT,true),"refresh can reload the unchanged active official page");
        check(!request.permits(8,LearningUrls.CHAT,true),"refresh confirmation cannot reload a newer load of the same URL");
        check(!request.permits(7,LearningUrls.NOTICES,true),"refresh confirmation cannot reload a different page");
        check(!request.permits(7,LearningUrls.CHAT,false),"refresh confirmation cannot reload an inactive WebView");
        check(!request.permits(7,null,true),"refresh confirmation cannot reload a destroyed WebView");
        LearningPageGuard detail=new LearningPageGuard(3,LearningUrls.NOTICES+"?noticeId=14");
        check(detail.permits(3,LearningUrls.NOTICES+"?noticeId=14",true),"refresh preserves the current notice detail URL");
        check(!detail.permits(3,LearningUrls.NOTICES+"?noticeId=15",true),"changed detail parameters invalidate the old confirmation");
        check(!new LearningPageGuard(1,"https://example.com/").permits(1,"https://example.com/",true),"refresh cannot reload an untrusted page");
        check(!new LearningPageGuard(1,"https://chaoxing.com.evil.example/").permits(1,"https://chaoxing.com.evil.example/",true),"refresh rejects a lookalike official host");
        check(!new LearningPageGuard(1,"http://i.chaoxing.com/").permits(1,"http://i.chaoxing.com/",true),"refresh requires official HTTPS");
        check(!new LearningPageGuard(1,null).permits(1,null,true),"refresh cannot reload before a URL exists");
        System.out.println("Learning page refresh guard: "+assertions+" assertions passed");
    }
}
