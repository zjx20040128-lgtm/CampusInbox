import json
import tempfile
import unittest
from pathlib import Path
from courseinbox.discovery import load_identity, make_proof

TOKEN='test-token-which-is-long-and-not-a-real-secret'
IDENTITY={'device_id':'0123456789abcdef0123456789abcdef','name':'CourseInbox-01234567'}
CHALLENGE='a'*64
PROOF='5f411416cb9ad795ba1992d132238b551d92787f056b7184e1d84c7c80c3f25e'

class IdentityTests(unittest.TestCase):
    def test_identity_survives_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=load_identity(Path(tmp))
            self.assertEqual(first,load_identity(Path(tmp)))
            self.assertRegex(first['device_id'],r'^[a-f0-9]{32}$')
            self.assertEqual(json.loads((Path(tmp)/'mobile-device.json').read_text()),first)
    def test_corrupt_identity_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'mobile-device.json';p.write_text('{"device_id":"bad"}')
            with self.assertRaises(ValueError):load_identity(Path(tmp))
            self.assertEqual(p.read_text(),'{"device_id":"bad"}')
    def test_proof_matches_independent_golden_vector(self):
        result=make_proof(IDENTITY,TOKEN,CHALLENGE,'10.1.2.3',8765)
        self.assertEqual(result,dict(version=1,**IDENTITY,challenge=CHALLENGE,address='10.1.2.3',port=8765,proof=PROOF))
        self.assertNotIn(TOKEN,json.dumps(result))
    def test_invalid_challenge_and_address_are_rejected(self):
        for challenge,address,port in [('A'*64,'10.1.2.3',8765),('a'*63,'10.1.2.3',8765),(CHALLENGE,'evil\naddress',8765),(CHALLENGE,'10.1.2.3',0)]:
            with self.assertRaises(ValueError):make_proof(IDENTITY,TOKEN,challenge,address,port)

from unittest.mock import patch
from courseinbox.discovery import DiscoveryService, private_ipv4

class DiscoveryTests(unittest.TestCase):
    def test_private_addresses_exclude_proxy_public_and_ipv6(self):
        for a in ['10.1.2.3','172.16.0.1','172.31.255.254','192.168.2.4']:
            self.assertTrue(private_ipv4(a))
        for a in ['198.18.0.1','8.8.8.8','172.32.0.1','127.0.0.1','::1','10.999.0.1']:
            self.assertFalse(private_ipv4(a))
    def test_changed_addresses_replace_host_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp, patch('courseinbox.discovery.local_ipv4',return_value={'10.1.2.3','198.18.0.1'}) as probe:
            service=DiscoveryService(Path(tmp),TOKEN,'0.0.0.0',8765)
            self.assertIn('10.1.2.3',service.allowed_hosts())
            self.assertNotIn('198.18.0.1',service.allowed_hosts())
            probe.return_value={'10.1.2.4'}
            service.refresh_addresses()
            self.assertNotIn('10.1.2.3',service.allowed_hosts())
            self.assertIn('10.1.2.4',service.allowed_hosts())
            service.close()
    def test_missing_discovery_dependency_keeps_pairing_available(self):
        with tempfile.TemporaryDirectory() as tmp, patch('courseinbox.discovery.local_ipv4',return_value={'10.1.2.3'}), patch('courseinbox.discovery.MdnsPublisher',side_effect=ImportError('unavailable')):
            service=DiscoveryService(Path(tmp),TOKEN,'0.0.0.0',8765)
            service.start()
            self.assertFalse(service.status()['available'])
            self.assertEqual(service.pairing(CHALLENGE,'10.1.2.3')['address'],'10.1.2.3')
            service.close()
            self.assertFalse(service.thread.is_alive())
    def test_changed_address_republishes_and_close_releases_resources(self):
        opened=[]
        class Publisher:
            def __init__(self,identity,addresses,port): self.closed=False;self.addresses=addresses;opened.append(self)
            def close(self): self.closed=True
        with tempfile.TemporaryDirectory() as tmp, patch('courseinbox.discovery.local_ipv4',return_value={'10.1.2.3'}) as probe, patch('courseinbox.discovery.MdnsPublisher',Publisher):
            service=DiscoveryService(Path(tmp),TOKEN,'0.0.0.0',8765)
            service.start()
            self.assertTrue(service.status()['available'])
            probe.return_value={'10.1.2.4'};service.refresh_addresses()
            self.assertTrue(opened[0].closed)
            self.assertEqual(opened[-1].addresses,['10.1.2.4'])
            service.close()
            self.assertTrue(opened[-1].closed)
            self.assertFalse(service.thread.is_alive())
    def test_loopback_does_not_broadcast(self):
        with tempfile.TemporaryDirectory() as tmp, patch('courseinbox.discovery.MdnsPublisher',side_effect=AssertionError('must not broadcast')):
            service=DiscoveryService(Path(tmp),TOKEN,'127.0.0.1',8765)
            service.start();self.assertFalse(service.status()['available']);service.close()
