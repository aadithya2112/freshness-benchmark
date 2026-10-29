"""Known-delay control backend: independent visibility and acknowledgement clocks."""
import threading
import time
import numpy as np
from .streaming import StreamConfig, arrival_times, run_stream


class DelayedBackend:
    def __init__(self,delay_s=0,ack_s=0,delete_never_visible=False):
        self.delay=delay_s;self.ack=ack_s;self.stuck_delete=delete_never_visible
        self.pending={};self.lock=threading.Lock()

    def write(self,operation,doc,vector):
        with self.lock:self.pending[doc['id']]=(operation,time.monotonic()+self.delay,doc)
        if self.ack:time.sleep(self.ack)

    def get(self,key):
        with self.lock:pending=self.pending.get(key)
        if pending is None:return None if key.startswith('insert') else {'doc_id':key,'version':0}
        operation,due,doc=pending
        if time.monotonic()<due or (operation=='delete' and self.stuck_delete):
            return None if operation=='insert' else {'doc_id':key,'version':0}
        return None if operation=='delete' else {'doc_id':key,'version':1}

    def search(self,vector,k=10,static=False):
        key=self.keys[int(vector[0])];result=self.get(key)
        return [] if result is None else [result]


def calibrate(output,delay_ms=0,ack_ms=0,duration=1):
    cfg=StreamConfig(duration_s=duration,rate=20,query_rate=0,poll_ms=5,stable_ms=20,deadline_s=1)
    operations=[]
    for i,_ in enumerate(arrival_times(cfg)):
        kind=('insert','update','delete')[i%3]
        operations.append({'operation':kind,'doc':{'id':f'{kind}-{i}','version':1},'vector':np.array([i])})
    backend=DelayedBackend(delay_ms/1000,ack_ms/1000);backend.keys=[op['doc']['id'] for op in operations]
    result=run_stream(backend,operations,[],cfg,output)
    result['injected_visibility_ms']=delay_ms;result['injected_ack_ms']=ack_ms
    return result
