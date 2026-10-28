import cn.courseinbox.companion.ComputerDiscovery;
public class PrivateAddressTest {
 public static void main(String[] args){
  String[] allowed={"10.1.2.3","172.16.0.1","172.31.255.254","192.168.1.5"};
  String[] rejected={"198.18.0.1","8.8.8.8","172.32.0.1","10.256.1.1","10.01.1.1","::1","evil.example"};
  for(String address:allowed)if(!ComputerDiscovery.privateIpv4(address))throw new AssertionError(address);
  for(String address:rejected)if(ComputerDiscovery.privateIpv4(address))throw new AssertionError(address);
  System.out.println("Private address validation: 11 assertions passed");
 }
}
