"""Independent-reader mutation measurements with bounded execution and explicit evidence."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
import json
import math
from pathlib import Path
import time

from .reporting import metric_stats


@dataclass
class StreamConfig:
    duration_s: float = 30
    rate: float = 10
    query_rate: float = 10
    arrival: str = 'steady'
    burst_multiplier: float = 4
    deadline_s: float = 5
    poll_ms: float = 10
    stable_ms: float = 50
    min_confirmations: int = 3
    write_workers: int = 4
    probe_workers: int = 32
    query_workers: int = 4
    max_active: int = 1024

    def validate(self):
        if self.duration_s<=0 or self.rate<=0 or self.query_rate<0:raise ValueError('Invalid arrival configuration')
        if self.arrival not in ('steady','burst') or self.burst_multiplier<1:raise ValueError('Unknown arrival process or multiplier')
        if self.deadline_s<=0 or self.poll_ms<=0 or self.stable_ms<0 or self.min_confirmations<1:raise ValueError('Invalid observation rule')
        if min(self.write_workers,self.probe_workers,self.query_workers,self.max_active)<1:raise ValueError('Invalid worker limits')


def arrival_times(cfg):
    """Burst: first 1 second of each 10-second period runs at the multiplier."""
    cfg.validate()
    result=[]
    segments=[(0,cfg.duration_s,cfg.rate)] if cfg.arrival=='steady' else [
        segment for period in range(math.ceil(cfg.duration_s/10))
        for segment in ((period*10,min(period*10+1,cfg.duration_s),cfg.rate*cfg.burst_multiplier),
                        (period*10+1,min(period*10+10,cfg.duration_s),cfg.rate))]
    for begin,end,rate in segments:
        if end<=begin:continue
        result.extend(begin+i/rate for i in range(math.ceil((end-begin)*rate-1e-10)))
    return result


def target_matches(operation, expected_id, result):
    if operation=='delete':return result is None
    return result is not None and str(result.get('doc_id'))==expected_id and result.get('version')==1


def fresh_channel():
    return {'first_ms':None,'stable_since_ms':None,'confirmed_ms':None,'consecutive':0,
            'regressions':0,'requests':0,'next_due':0.0,'inflight':False}


def update_channel(channel, good, elapsed_ms, cfg):
    channel['requests']+=1
    if good:
        if channel['first_ms'] is None:channel['first_ms']=elapsed_ms
        if channel['stable_since_ms'] is None:channel['stable_since_ms']=elapsed_ms
        channel['consecutive']+=1
        if channel['consecutive']>=cfg.min_confirmations and elapsed_ms-channel['stable_since_ms']>=cfg.stable_ms:
            channel['confirmed_ms']=elapsed_ms
    else:
        if channel['consecutive']>0:channel['regressions']+=1
        channel['consecutive']=0;channel['stable_since_ms']=None;channel['confirmed_ms']=None


def run_stream(backend, operations, queries, cfg, out_dir, query_evaluator=None):
    """Operations are disjoint IDs, already validated and prepared before admission."""
    cfg.validate()
    output=Path(out_dir);output.mkdir(parents=True,exist_ok=True)
    arrivals=arrival_times(cfg)
    if len(operations)!=len(arrivals):raise ValueError('Operation count differs from arrival schedule')
    records=[];query_records=[];active={};writes={};probes={};query_futures={}
    write_latency=[];probe_delay=[];probe_service=[];query_index=0;index=0
    query_interval=1/cfg.query_rate if cfg.query_rate else float('inf')
    start=time.monotonic();next_query=start
    def write(op):
        begin=time.monotonic()
        backend.write(op['operation'],op['doc'],op['vector'])
        return begin,time.monotonic()
    def probe(op,channel):
        begin=time.monotonic()
        if channel=='control':
            result=backend.get(op['doc']['id'])
        else:
            hits=backend.search(op['vector'],10,False)
            result=next((hit for hit in hits if str(hit.get('doc_id'))==op['doc']['id']),None)
        end=time.monotonic()
        return begin,end,target_matches(op['operation'],op['doc']['id'],result),None if result is None else result.get('version')
    def query(q):
        begin=time.monotonic();hits=backend.search(q['vector'],10,True)
        return begin,time.monotonic(),hits
    with (output/'probes.jsonl').open('w') as raw, ThreadPoolExecutor(cfg.write_workers) as wp, ThreadPoolExecutor(cfg.probe_workers) as pp, ThreadPoolExecutor(cfg.query_workers) as qp:
        while index<len(operations) or active or writes or probes or query_futures or time.monotonic()<start+cfg.duration_s:
            now=time.monotonic()
            for future,(i,submitted) in list(writes.items()):
                if not future.done():continue
                del writes[future];record=records[i]
                try:
                    begin,end=future.result();record['write_started_ms']=(begin-submitted)*1000;record['ack_ms']=(end-submitted)*1000
                    write_latency.append((end-begin)*1000)
                except Exception as exc:record['write_error']=str(exc)
                record['write_finished']=True
            for future,(i,channel,due,dispatch) in list(probes.items()):
                if not future.done():continue
                del probes[future];record=records[i];state=record[channel];state['inflight']=False
                try:
                    begin,end,good,version=future.result();elapsed=(end-record['_submitted'])*1000
                    delay=(begin-due)*1000;probe_delay.append(delay);probe_service.append((end-begin)*1000)
                    # An observation received after the deadline remains evidence, never success.
                    if end<=record['_submitted']+cfg.deadline_s:
                        update_channel(state,good,elapsed,cfg)
                    raw.write(json.dumps({'event':i,'channel':channel,'start_ms':(begin-record['_submitted'])*1000,
                                          'end_ms':elapsed,'dispatch_delay_ms':delay,'good':good,'version':version})+'\n')
                    gap_ms=max(cfg.poll_ms,cfg.stable_ms/max(1,cfg.min_confirmations-1)) if good else cfg.poll_ms
                    state['next_due']=end+gap_ms/1000
                except Exception as exc:
                    # A failed observation breaks the evidence sequence; it cannot
                    # bridge two successful samples into a confirmation window.
                    update_channel(state,False,(time.monotonic()-record['_submitted'])*1000,cfg)
                    record['probe_errors'].append(str(exc));state['next_due']=time.monotonic()+cfg.poll_ms/1000
                    raw.write(json.dumps({'event':i,'channel':channel,'error':str(exc),'end_ms':(time.monotonic()-record['_submitted'])*1000})+'\n')
            for future,(q,scheduled) in list(query_futures.items()):
                if not future.done():continue
                del query_futures[future]
                rec={'query_id':q['id'],'scheduled_s':scheduled-start}
                try:
                    begin,end,hits=future.result();rec.update({'latency_ms':(end-begin)*1000,'dispatch_delay_ms':(begin-scheduled)*1000,'ids':[str(h['doc_id']) for h in hits],'status':'success'})
                    if query_evaluator:rec.update(query_evaluator(q,hits))
                except Exception as exc:rec.update({'status':'error','error':str(exc)})
                query_records.append(rec)
            while index<len(operations) and start+arrivals[index]<=now:
                op=operations[index];submitted=time.monotonic()
                record={'event':index,'operation':op['operation'],'doc_id':op['doc']['id'],
                        'scheduled_s':arrivals[index],'submitted_s':submitted-start,'schedule_delay_ms':(submitted-start-arrivals[index])*1000,
                        'precondition':op.get('precondition',True),'status':'pending','ack_ms':None,'write_started_ms':None,'write_finished':False,
                        'write_error':None,'probe_errors':[],'control':fresh_channel(),'search':fresh_channel(),'_submitted':submitted}
                records.append(record)
                if not record['precondition']:record['status']='invalid_precondition'
                elif len(active)>=cfg.max_active:record['status']='client_overload'
                else:
                    active[index]=op
                    # Dispatch readers before the writer; observations are not gated on acknowledgement.
                    for channel in ('control','search'):
                        state=record[channel];state['inflight']=True
                        probes[pp.submit(probe,op,channel)]=(index,channel,submitted,submitted)
                    writes[wp.submit(write,op)]=(index,submitted)
                index+=1
            if queries and cfg.query_rate:
                while next_query<=now and next_query<start+cfg.duration_s:
                    q=queries[query_index%len(queries)];query_index+=1
                    if len(query_futures)<cfg.max_active:query_futures[qp.submit(query,q)]=(q,next_query)
                    else:query_records.append({'query_id':q['id'],'status':'client_overload','scheduled_s':next_query-start})
                    # Derive each deadline from its integer ordinal. Repeated
                    # floating-point addition can admit a spurious boundary query.
                    next_query=start+query_index*query_interval
            for i,op in list(active.items()):
                record=records[i];deadline=record['_submitted']+cfg.deadline_s
                if record['write_error'] and not any(record[c]['inflight'] for c in ('control','search')):
                    record['status']='error';del active[i];continue
                if now>=deadline and not any(record[c]['inflight'] for c in ('control','search')):
                    record['status']='timeout';del active[i];continue
                if record['write_finished'] and all(record[c]['confirmed_ms'] is not None for c in ('control','search')):
                    record['status']='success';record['first_observed_ms']=max(record[c]['first_ms'] for c in ('control','search'))
                    record['confirmed_ms']=max(record[c]['confirmed_ms'] for c in ('control','search'))
                    record['search_minus_ack_ms']=record['search']['first_ms']-record['ack_ms']
                    del active[i];continue
            # Oldest due request first, with at most one request per event/channel in flight.
            due=[]
            for i,op in active.items():
                record=records[i]
                if now>=record['_submitted']+cfg.deadline_s:continue
                for channel in ('control','search'):
                    state=record[channel]
                    if not state['inflight'] and state['confirmed_ms'] is None and state['next_due']<=now:
                        due.append((state['next_due'],i,channel))
            for scheduled,i,channel in sorted(due)[:max(0,cfg.probe_workers-len(probes))]:
                records[i][channel]['inflight']=True
                probes[pp.submit(probe,active[i],channel)]=(i,channel,scheduled,time.monotonic())
            time.sleep(0.0005)
    elapsed=time.monotonic()-start
    for record in records:
        record.pop('_submitted')
        for c in ('control','search'):
            record[c].pop('next_due');record[c].pop('inflight')
    with (output/'events.jsonl').open('w') as f:
        for r in records:f.write(json.dumps(r)+'\n')
    with (output/'queries.jsonl').open('w') as f:
        for r in query_records:f.write(json.dumps(r)+'\n')
    metrics={}
    for operation in ('insert','update','delete'):
        subset=[r for r in records if r['operation']==operation];success=[r for r in subset if r['status']=='success']
        if not subset:continue
        metrics[operation]={'count':len(subset),'success':len(success),'success_rate':len(success)/len(subset),
                            'first_observed_ms':metric_stats([r['first_observed_ms'] for r in success]),
                            'confirmed_ms':metric_stats([r['confirmed_ms'] for r in success]),
                            'ack_ms':metric_stats([r['ack_ms'] for r in subset if r['ack_ms'] is not None]),
                            'search_minus_ack_ms':metric_stats([r['search_minus_ack_ms'] for r in success]),
                            'regressions':sum(r[c]['regressions'] for r in subset for c in ('control','search')),
                            'confirmed_within_100ms':sum(r['confirmed_ms']<=100 for r in success)/len(subset),
                            'confirmed_within_1000ms':sum(r['confirmed_ms']<=1000 for r in success)/len(subset),
                            'errors':sum(r['status']=='error' for r in subset),'timeouts':sum(r['status']=='timeout' for r in subset),
                            'invalid_preconditions':sum(r['status']=='invalid_precondition' for r in subset)}
    good_queries=[q for q in query_records if q['status']=='success']
    mean=lambda name:sum(q.get(name,0) for q in good_queries)/len(query_records) if query_records else None
    summary={'config':asdict(cfg),'wall_s':elapsed,'operations':metrics,'total_operations':len(records),
             'statuses':{status:sum(r['status']==status for r in records) for status in ('success','timeout','error','invalid_precondition','client_overload')},
             'query':{'count':len(query_records),'success':len(good_queries),'ann_recall_at_10':mean('ann_recall'),
                      'ndcg_at_10':mean('ndcg'),'latency_ms':metric_stats([q['latency_ms'] for q in good_queries]),
                      'dispatch_delay_ms':metric_stats([q['dispatch_delay_ms'] for q in good_queries])},
             'diagnostics':{'schedule_delay_ms':metric_stats([r['schedule_delay_ms'] for r in records]),
                            'probe_dispatch_ms':metric_stats(probe_delay),'probe_service_ms':metric_stats(probe_service),
                            'write_service_ms':metric_stats(write_latency)},
             'actual_submission_rate':((len(records)-1)/(records[-1]['submitted_s']-records[0]['submitted_s']) if len(records)>1 else 0)}
    (output/'measurement.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary
