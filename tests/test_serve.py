import http.client, tempfile, threading, unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from video_temporal_audit.serve import RangeHandler

class QuietRangeHandler(RangeHandler):
    def log_message(self,*args):pass

class RangePlaybackServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();Path(cls.temp.name,'preview.mp4').write_bytes(bytes(range(100)))
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietRangeHandler,directory=cls.temp.name))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temp.cleanup()
    def request(self,method='GET',headers=None):
        client=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        client.request(method,'/preview.mp4',headers=headers or {});response=client.getresponse()
        answer=(response.status,dict(response.getheaders()),response.read());client.close();return answer
    def test_full_and_head_advertise_ranges(self):
        status,headers,body=self.request();self.assertEqual((status,len(body)),(200,100));self.assertEqual(headers['Accept-Ranges'],'bytes')
        status,headers,body=self.request('HEAD');self.assertEqual(status,200);self.assertEqual(body,b'');self.assertEqual(headers['Content-Length'],'100')
    def test_byte_range_is_exact(self):
        status,headers,body=self.request(headers={'Range':'bytes=10-19'})
        self.assertEqual((status,body),(206,bytes(range(10,20))));self.assertEqual(headers['Content-Range'],'bytes 10-19/100')
    def test_suffix_range_and_clamp(self):
        self.assertEqual(self.request(headers={'Range':'bytes=-5'})[2],bytes(range(95,100)))
        self.assertEqual(self.request(headers={'Range':'bytes=95-999'})[2],bytes(range(95,100)))
    def test_invalid_ranges_return_416(self):
        for value in ('bytes=100-','bytes=20-10','bytes=-0','bytes=0-1,4-5'):
            with self.subTest(value=value):self.assertEqual(self.request(headers={'Range':value})[0],416)
