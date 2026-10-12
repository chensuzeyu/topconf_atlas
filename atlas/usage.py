"""Record each model attempt, including retries, and stop dispatch at a token budget."""
import json
import os
import secrets
import threading
from pathlib import Path
from .storage import DATA, now, write_json


class TokenBudgetExceeded(RuntimeError):
    pass


class UsageLedger:
    def __init__(self):
        self.directory=Path(os.environ.get('ATLAS_LLM_USAGE_DIR',DATA/'reports'/('model-usage-'+secrets.token_hex(6))))
        self.limit=int(os.environ.get('ATLAS_LLM_TOKEN_BUDGET','0'))
        self.mutex=threading.Lock()
        self.state_path=self.directory/'budget.json'
        self.state=json.loads(self.state_path.read_text()) if self.state_path.exists() else {
            'started_at':now(),'charged_tokens':0,'confirmed_tokens':0,'requests':0,'unknown_usage_requests':0,'inflight':{}}
        # An interrupted request may have consumed tokens. Charge its reserved estimate conservatively.
        for ticket,reserved in self.state['inflight'].items():
            self.state['charged_tokens']+=reserved
            self.state['unknown_usage_requests']+=1
        self.state['inflight']={}
        self.state['token_budget']=self.limit
        write_json(self.state_path,self.state)

    def reserve(self,model,provider,papers):
        reservation=min(30000,max(5000,5000*len(papers)))
        with self.mutex:
            if self.limit and self.state['charged_tokens']+sum(self.state['inflight'].values())+reservation>self.limit:
                raise TokenBudgetExceeded('Model token budget reached; no additional request dispatched')
            ticket=secrets.token_hex(12)
            self.state['inflight'][ticket]=reservation
            self.state['requests']+=1
            record={'requested_at':now(),'model':model,'provider':provider,'papers':papers,
                    'service_tier_requested':None,'reasoning_effort_requested':None,'status':'started','reserved_tokens':reservation}
            write_json(self.directory/(ticket+'.json'),record)
            write_json(self.state_path,self.state)
        return ticket

    def complete(self,ticket,usage=None,service_tier=None,error=None,not_sent=False):
        with self.mutex:
            reserved=self.state['inflight'].pop(ticket)
            confirmed=0 if not_sent else (usage.get('total_tokens') if usage else None)
            self.state['charged_tokens']+=confirmed if confirmed is not None else reserved
            if confirmed is not None:self.state['confirmed_tokens']+=confirmed
            else:self.state['unknown_usage_requests']+=1
            if not_sent:self.state['not_sent_requests']=self.state.get('not_sent_requests',0)+1
            path=self.directory/(ticket+'.json');record=json.loads(path.read_text())
            record.update(finished_at=now(),status='not_sent' if not_sent else ('completed' if confirmed is not None else 'usage_unknown'),
                          usage=usage,service_tier_returned=service_tier,error=error)
            write_json(path,record);write_json(self.state_path,self.state)
