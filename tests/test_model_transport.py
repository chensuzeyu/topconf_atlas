import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from atlas.enrich import ModelClient


class TransportTests(unittest.TestCase):
    def test_completed_chunked_responses_leave_connection_reusable(self):
        ports=[]
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                ports.append(self.client_address[1])
                events=[{'type':'response.output_text.done','text':'{}'},
                        {'type':'response.completed','response':{'usage':{'total_tokens':1200}}}]
                body=''.join('data: '+json.dumps(event)+'\n\n' for event in events).encode()
                self.send_response(200);self.send_header('Transfer-Encoding','chunked');self.end_headers()
                self.wfile.write(f'{len(body):x}\r\n'.encode()+body+b'\r\n0\r\n\r\n');self.wfile.flush()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{
                'ATLAS_LLM_USAGE_DIR':folder,'ATLAS_LLM_PROVIDER':'openai','ATLAS_LLM_MODEL':'test',
                'OPENAI_API_KEY':'test-fixture','NO_PROXY':'127.0.0.1','no_proxy':'127.0.0.1'}):
                client=ModelClient();client.url=f'http://127.0.0.1:{server.server_port}/responses'
                try:
                    for _ in range(2):client.run([{'id':'a','title':'Title','abstract_en':'Full abstract'}])
                    self.assertEqual(len(ports),2)
                    self.assertEqual(ports[0],ports[1],'Completed streams should reuse the TCP connection')
                finally:client.close()
        finally:server.shutdown();server.server_close();thread.join()
