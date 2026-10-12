import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from atlas.usage import UsageLedger,TokenBudgetExceeded
from atlas.enrich import ModelClient,ModelUnavailable,request_not_sent
import requests


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.env=patch.dict(os.environ,{'ATLAS_LLM_USAGE_DIR':self.folder.name,'ATLAS_LLM_TOKEN_BUDGET':'60000'})
        self.env.start();self.addCleanup(self.env.stop)

    def test_inflight_reservations_and_confirmed_usage_limit_dispatch(self):
        ledger=UsageLedger();a=ledger.reserve('test','test',['a']*6);b=ledger.reserve('test','test',['b']*6)
        with self.assertRaises(TokenBudgetExceeded):ledger.reserve('test','test',['c']*6)
        ledger.complete(a,{'total_tokens':1200},'default')
        ledger.complete(b,error='Stream interrupted')
        self.assertEqual(ledger.state['charged_tokens'],31200)
        self.assertEqual(ledger.state['confirmed_tokens'],1200)
        self.assertEqual(ledger.state['unknown_usage_requests'],1)
        with self.assertRaises(TokenBudgetExceeded):ledger.reserve('test','test',['c']*6)

    def test_interrupted_request_is_conservatively_charged_on_resume(self):
        ledger=UsageLedger();ledger.reserve('test','test',['a'])
        resumed=UsageLedger()
        self.assertEqual(resumed.state['charged_tokens'],5000)
        self.assertFalse(resumed.state['inflight'])

    def test_usage_is_saved_even_when_model_json_is_invalid(self):
        with patch.dict(os.environ,{'ATLAS_LLM_PROVIDER':'openai','ATLAS_LLM_MODEL':'test','OPENAI_API_KEY':'test-fixture'}):
            client=ModelClient()
            events=[{'type':'response.output_text.done','text':'invalid JSON'},
                    {'type':'response.completed','response':{'usage':{'total_tokens':1234},'service_tier':'default'}}]
            response=Mock(ok=True);response.iter_lines.return_value=[('data: '+json.dumps(e)).encode() for e in events]
            response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
            with patch('atlas.enrich.requests.Session.post',return_value=response):
                with self.assertRaises(ValueError):client.run([{'id':'a','title':'Test','abstract_en':'Test abstract'}])
            self.assertEqual(client.usage_ledger.state['confirmed_tokens'],1234)
            self.assertFalse(client.usage_ledger.state['inflight'])
            records=[json.loads(p.read_text()) for p in Path(self.folder.name).glob('*.json') if p.name!='budget.json']
            self.assertEqual(records[0]['service_tier_returned'],'default')

    def test_connection_failures_stop_dispatch_instead_of_retrying_entire_catalog(self):
        with patch.dict(os.environ,{'ATLAS_LLM_PROVIDER':'openai','ATLAS_LLM_MODEL':'test','OPENAI_API_KEY':'test-fixture','ATLAS_LLM_TOKEN_BUDGET':'1000000'}):
            client=ModelClient()
            with patch.object(client,'_run',side_effect=requests.ConnectionError('Stream disconnected')) as call:
                for _ in range(8):
                    with self.assertRaises(requests.ConnectionError):client.run([{'id':'a'}])
                with self.assertRaises(ModelUnavailable):client.run([{'id':'a'}])
                self.assertEqual(call.call_count,8)
                self.assertEqual(client.usage_ledger.state['requests'],8)

    def test_completed_response_does_not_wait_for_connection_to_close(self):
        with patch.dict(os.environ,{'ATLAS_LLM_PROVIDER':'openai','ATLAS_LLM_MODEL':'test','OPENAI_API_KEY':'test-fixture'}):
            client=ModelClient()
            def lines():
                yield b'data: {"type":"response.output_text.done","text":"{}"}'
                yield b'data: {"type":"response.completed","response":{"usage":{"total_tokens":1234}}}'
                raise requests.exceptions.ChunkedEncodingError('Connection closed after complete result')
            response=Mock(ok=True);response.iter_lines.side_effect=lines
            response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
            with patch('atlas.enrich.requests.Session.post',return_value=response):
                output,usage=client.run([{'id':'a','title':'Test','abstract_en':'Full abstract'}])
            self.assertEqual(output,{})
            self.assertEqual(usage['total_tokens'],1234)

    def test_worker_reuses_its_http_session(self):
        with patch.dict(os.environ,{'ATLAS_LLM_PROVIDER':'openai','ATLAS_LLM_MODEL':'test','OPENAI_API_KEY':'test-fixture'}):
            client=ModelClient()
            self.assertIs(client.session(),client.session())
            self.assertEqual(len(client.sessions),1)
            client.close()

    def test_connect_timeout_before_request_does_not_charge_unknown_model_usage(self):
        with patch.dict(os.environ,{'ATLAS_LLM_PROVIDER':'openai','ATLAS_LLM_MODEL':'test','OPENAI_API_KEY':'test-fixture'}):
            client=ModelClient()
            with patch.object(client,'_run',side_effect=requests.ConnectTimeout('Connection not established')):
                with self.assertRaises(requests.ConnectTimeout):client.run([{'id':'a'}])
            self.assertEqual(client.usage_ledger.state['charged_tokens'],0)
            self.assertEqual(client.usage_ledger.state['unknown_usage_requests'],0)
            self.assertEqual(client.usage_ledger.state['not_sent_requests'],1)

    def test_ssl_error_requires_handshake_trace_to_be_classed_as_not_sent(self):
        def do_handshake():
            raise requests.exceptions.SSLError('TLS handshake failed')
        try:
            do_handshake()
        except requests.exceptions.SSLError as error:
            self.assertTrue(request_not_sent(error))
        self.assertFalse(request_not_sent(requests.exceptions.SSLError('Unknown SSL stream failure')))
        self.assertFalse(request_not_sent(requests.ReadTimeout('Request sent but no response received')))

    def test_wrapped_tls_handshake_timeout_is_not_a_sent_request(self):
        def do_handshake():raise TimeoutError('TLS handshake timed out')
        try:
            try:do_handshake()
            except TimeoutError as inner:raise requests.ReadTimeout('Wrapped handshake timeout') from inner
        except requests.ReadTimeout as error:
            self.assertTrue(request_not_sent(error))


if __name__=='__main__':unittest.main()
