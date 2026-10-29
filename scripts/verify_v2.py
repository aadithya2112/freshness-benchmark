#!/usr/bin/env python3
"""Audit released evidence against protocol 2, independently of runner summaries.

An invalid experiment can still be a valid report: failed gates are recomputed
and retained. Missing, inconsistent, or tampered evidence fails this verifier.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import tarfile


class EvidenceError(ValueError):
    pass


def require(condition,message):
    if not condition:raise EvidenceError(message)


def read(path):
    return json.loads(Path(path).read_text())


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line]


def close(actual,expected,label):
    if actual is None or expected is None:
        require(actual is expected,f'{label}: {actual} != {expected}')
    else:
        require(math.isfinite(actual) and math.isclose(actual,expected,rel_tol=1e-8,abs_tol=1e-6),f'{label}: {actual} != {expected}')


def quantile(values,p):
    if not values:return None
    ordered=sorted(values);index=(len(values)-1)*p/100;lo=math.floor(index);hi=math.ceil(index)
    return ordered[lo]+(ordered[hi]-ordered[lo])*(index-lo)


def stats(actual,values,label):
    for key,p in [('min',0),('p50',50),('p95',95),('p99',99),('max',100)]:
        close(actual[key],quantile(values,p),f'{label}.{key}')


def replay(samples,cfg):
    """Rebuild the first and confirmed response times from the declared rule."""
    first=None;since=None;confirmed=None;consecutive=0;regressions=0;previous=-1
    for p in samples:
        require(p['end_ms']>=previous,'Channel responses out of order')
        previous=p['end_ms']
        if 'error' not in p:
            require(0<=p['start_ms']<=p['end_ms'],'Noncausal probe timestamp')
            require(p['dispatch_delay_ms']>=0,'Negative probe dispatch lag')
        if p['end_ms']>cfg['deadline_s']*1000 and 'error' not in p:continue
        if p.get('good',False):
            if first is None:first=p['end_ms']
            if since is None:since=p['end_ms']
            consecutive+=1
            if consecutive>=cfg['min_confirmations'] and p['end_ms']-since>=cfg['stable_ms']:
                confirmed=p['end_ms']
        else:
            regressions+=int(consecutive>0);consecutive=0;since=None;confirmed=None
    return {'first_ms':first,'confirmed_ms':confirmed,'regressions':regressions}


def audit_run(directory,summary=None,evaluate=None):
    directory=Path(directory);s=summary or read(directory/'summary.json');cfg=s['config']
    events=rows(directory/'events.jsonl');queries=rows(directory/'queries.jsonl')
    probes=rows(directory/'probes.jsonl');by_channel=defaultdict(list)
    expected_queries=math.ceil(cfg['duration_s']*cfg['query_rate']-1e-10)
    require(len(queries)==expected_queries,'Background query schedule count differs')
    for index,q in enumerate(sorted(queries,key=lambda q:q['scheduled_s'])):
        close(q['scheduled_s'],index/cfg['query_rate'],'Background query schedule')
    require(len(events)==s['total_operations'],'Event count mismatch')
    require([e['event'] for e in events]==list(range(len(events))),'Event IDs are not contiguous')
    require(len({e['doc_id'] for e in events})==len(events),'Reused mutation ID')
    for p in probes:
        require(isinstance(p['event'],int) and 0<=p['event']<len(events),'Unknown probe event')
        require(p['channel'] in ('control','search'),'Unknown read channel')
        by_channel[p['event'],p['channel']].append(p)
        if 'error' not in p and p['good']:
            require(p['version'] is None if events[p['event']]['operation']=='delete' else p['version']==1,'Unexpected fresh version')
    statuses=Counter(e['status'] for e in events)
    require(set(statuses)<=set(s['statuses']),'Unrecognized terminal status')
    for status,count in s['statuses'].items():require(statuses[status]==count,'Status totals differ')
    for e in events:
        require(e['operation'] in ('insert','update','delete'),'Unknown mutation')
        require(0<=e['scheduled_s']<cfg['duration_s'],'Arrival outside admission window')
        close((e['submitted_s']-e['scheduled_s'])*1000,e['schedule_delay_ms'],'Admission lag')
        if e['ack_ms'] is not None:require(0<=e['write_started_ms']<=e['ack_ms'],'Noncausal write acknowledgement')
        for channel in ('control','search'):
            reconstructed=replay(by_channel[e['event'],channel],cfg)
            for key,value in reconstructed.items():close(e[channel][key],value,f'Event {e["event"]} {channel} {key}')
        if e['status']=='success':
            require(e['precondition'] and e['write_finished'] and not e['write_error'],'Invalid successful event')
            require(all(e[c]['confirmed_ms'] is not None for c in ('control','search')),'Success without both confirmations')
            close(e['first_observed_ms'],max(e[c]['first_ms'] for c in ('control','search')),'First observation')
            close(e['confirmed_ms'],max(e[c]['confirmed_ms'] for c in ('control','search')),'Confirmation')
            close(e['search_minus_ack_ms'],e['search']['first_ms']-e['ack_ms'],'Search versus ACK')
            require(e['confirmed_ms']<=cfg['deadline_s']*1000,'Confirmation beyond deadline')
    for operation,m in s['operations'].items():
        subset=[e for e in events if e['operation']==operation];good=[e for e in subset if e['status']=='success']
        require(len(subset)==m['count'] and len(good)==m['success'],'Operation totals differ')
        close(m['success_rate'],len(good)/len(subset),'Success fraction')
        for key in ('first_observed_ms','confirmed_ms','search_minus_ack_ms'):
            stats(m[key],[e[key] for e in good],f'{operation}.{key}')
        stats(m['ack_ms'],[e['ack_ms'] for e in subset if e['ack_ms'] is not None],f'{operation}.ack_ms')
        for threshold in (100,1000):close(m[f'confirmed_within_{threshold}ms'],sum(e['confirmed_ms']<=threshold for e in good)/len(subset),'SLO fraction')
        require(m['regressions']==sum(e[c]['regressions'] for e in subset for c in ('control','search')),'Regression count differs')
        for key,status in [('errors','error'),('timeouts','timeout'),('invalid_preconditions','invalid_precondition')]:
            require(m[key]==sum(e['status']==status for e in subset),f'{key} count differs')
    good_queries=[q for q in queries if q['status']=='success']
    require(s['query']['count']==len(queries) and s['query']['success']==len(good_queries),'Query totals differ')
    for field,key in [('latency_ms','latency_ms'),('dispatch_delay_ms','dispatch_delay_ms')]:
        stats(s['query'][field],[q[key] for q in good_queries],f'query.{field}')
    for field,key in [('ann_recall_at_10','ann_recall'),('ndcg_at_10','ndcg')]:
        expected=sum(q.get(key,0) for q in good_queries)/len(queries) if queries else None
        close(s['query'][field],expected,f'query.{field}')
    if evaluate:
        for q in good_queries:
            expected=evaluate(q)
            for key in ('ann_recall','ndcg','unexpected_cohort'):close(q[key],expected[key],f'query oracle {key}')
    stats(s['diagnostics']['schedule_delay_ms'],[e['schedule_delay_ms'] for e in events],'schedule')
    stats(s['diagnostics']['probe_dispatch_ms'],[p['dispatch_delay_ms'] for p in probes if 'error' not in p],'probe dispatch')
    stats(s['diagnostics']['probe_service_ms'],[p['end_ms']-p['start_ms'] for p in probes if 'error' not in p],'probe service')
    stats(s['diagnostics']['write_service_ms'],[e['ack_ms']-e['write_started_ms'] for e in events if e['ack_ms'] is not None],'write service')
    if 'gates' in s:
        max_rate=cfg['rate']*(cfg['burst_multiplier'] if cfg['arrival']=='burst' else 1)
        m=s['metadata'];before=m['backend_before'];g=s['gates']
        within=lambda value,limit:value is not None and value<=limit
        expected={'arrival_dispatch':within(quantile([e['schedule_delay_ms'] for e in events],95),1000/max_rate),
          'probe_dispatch':within(quantile([p['dispatch_delay_ms'] for p in probes if 'error' not in p],95),cfg['poll_ms']),
          'query_dispatch':within(quantile([q['dispatch_delay_ms'] for q in good_queries],95),1000/cfg['query_rate']),
          'ann_recall':m['idle_queries']['ann_recall']>=.95 and s['query']['ann_recall_at_10']>=.95,
          'preconditions':statuses['invalid_precondition']==0,'client_capacity':statuses['client_overload']==0,
          'cohort_integrity':not any(q.get('unexpected_cohort',0) for q in queries)}
        if m['backend']=='qdrant':expected['ann_index_used']=before['collection']['indexed_vectors_count']>=.95*m['count_before']
        elif m['backend']=='pgvector':expected['ann_index_used']='_hnsw' in json.dumps(before['query_plan'])
        else:expected['ann_index_used']=before['schema']['vectorIndexType']=='hnsw' and before['schema']['vectorIndexConfig']['flatSearchCutoff']==0
        require(expected==g,'Declared validity gates do not match evidence')
        require(s['eligible']==all(expected.values()),'Eligibility does not match gates')
        if all(e['write_finished'] and not e['write_error'] for e in events):
            expected_count=m['count_before']+sum(e['operation']=='insert' for e in events)-sum(e['operation']=='delete' for e in events)
            require(m['count_after']==expected_count,'Final collection cardinality differs from acknowledged mutations')
    return {'events':len(events),'queries':len(queries),'probes':len(probes)}


def verify(root,check_data=False,allow_partial=False):
    root=Path(root);experiment=read(root/'experiment.json');progress=rows(root/'progress.jsonl')
    order=[tuple(cell) for cell in experiment['order']]
    observed=[(r['trial'],r['backend'],r['scenario']) for r in progress]
    require(len(set(order))==len(order),'Duplicate planned trial')
    require(observed==order[:len(observed)],'Trial order or identity changed')
    require(allow_partial or len(observed)==len(order),'Incomplete matrix')
    require(len({r['run'] for r in progress})==len(progress),'Duplicate run directory')
    with tarfile.open(root/'source.tar.gz') as archive:
        for name,digest in experiment['source'].items():
            member=archive.extractfile(name)
            require(member is not None and hashlib.sha256(member.read()).hexdigest()==digest,f'Launch source mismatch: {name}')
    if (root/'checksums.json').exists():
        for name,digest in read(root/'checksums.json').items():
            path=(root/name).resolve()
            require(path.is_relative_to(root.resolve()),'Checksum path leaves artifact')
            require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==digest,f'Artifact checksum mismatch: {name}')
    totals=Counter();limits=[];data={}
    for entry in progress:
        directory=root/'runs'/entry['run']
        if entry['status']=='failed':
            require((directory/'failure.json').is_file(),'Missing setup failure evidence');totals['failed_runs']+=1;continue
        require(entry['status']=='complete','Unknown run status')
        s=read(directory/'summary.json');m=s['metadata'];evaluator=None
        require(m['backend']==entry['backend'] and m['collection']==entry['run'],'Run identity mismatch')
        require(entry['eligible']==s['eligible'] and entry['gates']==s['gates'],'Progress summary mismatch')
        require(m['dataset']==experiment['datasets'][m['profile']['dataset']],'Dataset changed between runs')
        if check_data:
            from freshness_benchmark.quality import RetrievalData
            key=m['profile']['dataset']
            if key not in data:data[key]=RetrievalData(Path('benchmarks/data/v2')/key)
            require(data[key].manifest==m['dataset'],'Local cache is not the measured cache')
            references,evaluate=data[key].prepare_reference(m['base_count']);by_id={q['id']:q for q in references}
            evaluator=lambda q:evaluate(by_id[q['query_id']],[{'doc_id':key} for key in q['ids']])
            for reference in read(directory/'reference.json'):
                expected=by_id[reference['id']]
                for field in ('cutoff','exact_ndcg'):close(reference[field],expected[field],'Exact reference')
                require(reference['exact_ids']==expected['exact_ids'],'Exact neighbor IDs differ')
        totals.update(audit_run(directory,s,evaluator));totals['completed_runs']+=1
        if not s['eligible']:limits.append({'run':entry['run'],'gates':[k for k,v in s['gates'].items() if not v]})
    calibration_roots=[root]+sorted((root/'continuations').glob('*'))
    interrupted=[]
    for base in calibration_roots:
        if base!=root:
            continuation=read(base/'continuation.json')
            require(file_sha_local(base/'resume-source.py')==continuation['resume_source_sha256'],'Continuation source mismatch')
            if (base/'interrupted-trial.json').exists():interrupted.append(read(base/'interrupted-trial.json'))
        for c in read(base/'calibration.json'):
            path=base/'calibration'/f'delay{c["injected_visibility_ms"]}-ack{c["injected_ack_ms"]}'
            audit_run(path,c)
            events=rows(path/'events.jsonl')
            require(all(e['status']=='success' for e in events),'Calibration did not confirm every event')
            for e in events:
                require(e['first_observed_ms']>=e['write_started_ms']+c['injected_visibility_ms'],'Observed before injected visibility')
            if c['injected_ack_ms']>c['injected_visibility_ms']+30:
                require(any(e['search']['first_ms']<e['ack_ms']-30 for e in events),'Readers appear gated on ACK')
    return {'verified':True,'complete':len(observed)==len(order),'check_data':check_data,
            'planned_runs':len(order),**totals,'limited_runs':limits,'interrupted_attempts':interrupted}


def file_sha_local(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    parser.add_argument('--check-data',action='store_true');parser.add_argument('--allow-partial',action='store_true')
    parser.add_argument('--report',type=Path,help='Write JSON after verification, without truncating an artifact before it is checked')
    args=parser.parse_args()
    try:
        result=json.dumps(verify(args.directory,args.check_data,args.allow_partial),indent=2)
        if args.report:args.report.write_text(result+'\n')
        print(result)
    except (EvidenceError,OSError,KeyError,ValueError,TypeError) as error:
        parser.exit(1,f'VERIFICATION FAILED: {error}\n')
