import socket
import struct
import unittest
from courseinbox.discovery import gateway_ipv4


class LanAddressTests(unittest.TestCase):
    def address(self,ip,index):
        return socket.inet_aton(ip)+struct.pack('<I',index)+bytes(16)

    def route(self,index,gateway='10.18.25.254',destination='0.0.0.0',mask='0.0.0.0'):
        return socket.inet_aton(destination)+socket.inet_aton(mask)+bytes(4)+socket.inet_aton(gateway)+struct.pack('<I',index)+bytes(36)

    def test_only_private_addresses_on_default_gateway_adapters_are_advertised(self):
        addresses=[self.address('10.18.25.193',16),self.address('172.27.176.1',24),self.address('198.18.0.1',47),self.address('169.254.1.2',18)]
        routes=[self.route(16),self.route(47,'198.18.0.2'),self.route(24,'0.0.0.0','172.27.176.0','255.255.240.0')]
        self.assertEqual(gateway_ipv4(addresses,routes),{'10.18.25.193'})

    def test_hotspot_address_follows_new_gateway_and_never_uses_virtual_only_fallback(self):
        addresses=[self.address('192.168.43.20',16),self.address('172.27.176.1',24)]
        self.assertEqual(gateway_ipv4(addresses,[self.route(16,'192.168.43.1')]),{'192.168.43.20'})
        self.assertEqual(gateway_ipv4(addresses,[]),set())
