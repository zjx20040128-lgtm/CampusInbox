import cn.courseinbox.companion.EndpointDraft;
import cn.courseinbox.companion.CandidateResolution;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
public class DiscoveryRegressionTest {
 static void check(boolean value){if(!value)throw new AssertionError();}
 public static void main(String[] args)throws Exception {
  EndpointDraft draft=new EndpointDraft("old");draft.edited("manual-new");
  check(draft.automatic("old").equals("manual-new"));
  check(draft.automatic("background-new").equals("manual-new"));
  draft.saved("manual-new");check(draft.automatic("background-new").equals("background-new"));
  AtomicBoolean canceled=new AtomicBoolean(false);
  CandidateResolution.Operation<String> hung=new CandidateResolution.Operation<String>() {
   public void start(java.util.function.Consumer<String> callback){}
   public void cancel(){canceled.set(true);}
  };
  long start=System.nanoTime();String value=CandidateResolution.await(hung,start+TimeUnit.SECONDS.toNanos(2),25);
  check(value==null);check(canceled.get());check(System.nanoTime()-start<TimeUnit.SECONDS.toNanos(1));
  canceled.set(false);
  value=CandidateResolution.await(new CandidateResolution.Operation<String>(){
   public void start(java.util.function.Consumer<String> callback){callback.accept("next-good-candidate");}
   public void cancel(){canceled.set(true);}
  },System.nanoTime()+TimeUnit.SECONDS.toNanos(1),25);
  check(value.equals("next-good-candidate"));check(canceled.get());
  System.out.println("Discovery regressions: 8 assertions passed");
 }
}
