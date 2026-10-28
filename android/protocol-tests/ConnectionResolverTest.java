import cn.courseinbox.companion.ConnectionResolver;
import java.io.IOException;
public class ConnectionResolverTest {
 static int verified; static boolean closed;
 static void check(boolean ok) { if(!ok) throw new AssertionError(); }
 static ConnectionResolver.Verified value(String endpoint,String id) { return new ConnectionResolver.Verified(endpoint,id,"CourseInbox-test"); }
 static ConnectionResolver.Source source(String... endpoints) {
  return () -> new ConnectionResolver.Candidates() {
   int i=0;
   public String next(long deadline) { return i<endpoints.length?endpoints[i++]:null; }
   public void close(){closed=true;}
  };
 }
 public static void main(String[] args) throws Exception {
  ConnectionResolver.Verified result=ConnectionResolver.resolve("cached","paired",()->{throw new AssertionError("cached should not discover");},(e,id,d)->value(e,"paired"),1000);
  check(result.endpoint.equals("cached"));
  closed=false;verified=0;
  result=ConnectionResolver.resolve("stale","paired",source("other","bad","new"),(e,id,d)->{
   verified++; if(e.equals("stale")||e.equals("bad"))throw new IOException("invalid proof");
   return value(e,e.equals("other")?"different":"paired");
  },1000);
  check(result.endpoint.equals("new"));check(verified==4);check(closed);
  closed=false;
  try {ConnectionResolver.resolve("","paired",source("wrong"),(e,id,d)->value(e,"different"),1000);throw new AssertionError();}catch(IOException expected){}
  check(closed);
  closed=false;
  try {ConnectionResolver.resolve("","paired",source("bad"),(e,id,d)->{throw new IOException("timeout");},1000);throw new AssertionError();}catch(IOException expected){}
  check(closed);
  try {ConnectionResolver.resolve("cached","paired",source("new"),(e,id,d)->{throw new AssertionError("expired budget should not verify");},0);throw new AssertionError();}catch(IOException expected){}
  System.out.println("Connection recovery: 7 assertions passed");
 }
}
