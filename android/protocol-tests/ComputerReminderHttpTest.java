import cn.courseinbox.companion.ComputerReminderHttp;
import java.net.*;import java.io.*;import java.nio.charset.StandardCharsets;
public final class ComputerReminderHttpTest {
 static int checks;static void check(boolean ok,String why){checks++;if(!ok)throw new AssertionError(why);}
 static final class Wire extends HttpURLConnection {
  int status=200;boolean disconnected;String response="{\"ok\":true}";ByteArrayOutputStream sent=new ByteArrayOutputStream();
  Wire(URL url){super(url);}public void connect(){}public boolean usingProxy(){return false;}public void disconnect(){disconnected=true;}
  public int getResponseCode(){return status;}public InputStream getInputStream(){return new ByteArrayInputStream(response.getBytes(StandardCharsets.UTF_8));}public OutputStream getOutputStream(){return sent;}
 }
 public static void main(String[] args)throws Exception {
  final Wire[] opened={null};final int[] status={200};ComputerReminderHttp http=new ComputerReminderHttp(url->{opened[0]=new Wire(url);opened[0].status=status[0];return opened[0];});
  String token="abcdefghijklmnopqrstuvwxyz_0123456789-ABCDE";
  check(http.request("http://192.168.1.8:8766","/v1/alerts",token,null).equals("{\"ok\":true}"),"successful response returned");
  check(!opened[0].getInstanceFollowRedirects(),"redirects disabled on actual connection");check(opened[0].getRequestProperty("Authorization").equals("Bearer "+token),"only independent device credential attached");
  check(opened[0].disconnected&&opened[0].getConnectTimeout()>0&&opened[0].getReadTimeout()>0,"bounded connection always closed");
  for(int code:new int[]{301,302,307,308,401,400}){status[0]=code;boolean rejected=false;try{http.request("http://192.168.1.8:8766","/v1/alerts",token,null);}catch(ComputerReminderHttp.Failure failure){rejected=failure.status==code&&!failure.getMessage().contains(token);}check(rejected&&opened[0].disconnected,"status "+code+" fails closed with no token in errors");}
  status[0]=200;http.request("http://192.168.1.8:8766","/v1/ack",token,"{\"ids\":[\"event-1\"]}");check(opened[0].getRequestMethod().equals("POST")&&opened[0].sent.toString("UTF-8").equals("{\"ids\":[\"event-1\"]}"),"ACK JSON is posted exactly once");
  Wire previous=opened[0];boolean rejected=false;try{http.request("http://8.8.8.8","/v1/alerts",token,null);}catch(IllegalArgumentException expected){rejected=true;}check(rejected&&opened[0]==previous,"public endpoint rejected before connection opens");
  rejected=false;try{http.request("http://192.168.1.8:8766","/api/tasks",token,null);}catch(IllegalArgumentException expected){rejected=true;}check(rejected&&opened[0]==previous,"main privileged routes cannot be called");
  rejected=false;try{http.request("http://192.168.1.8:8766","/v1/alerts",token+"\r\nBad: x",null);}catch(IllegalArgumentException expected){rejected=true;}check(rejected&&opened[0]==previous,"malformed token rejected before networking");
  System.out.println("Computer reminder HTTP: "+checks+" assertions passed");
 }
}
