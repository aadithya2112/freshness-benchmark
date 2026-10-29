#!/usr/bin/env python3
"""Versioned mixed-mutation matrix. Run from the repository root."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import tarfile
import time

from freshness_benchmark.calibration import calibrate
from freshness_benchmark.quality import RetrievalData,file_sha
from freshness_benchmark.reporting import metric_stats
from freshness_benchmark.streaming import StreamConfig,arrival_times,run_stream
from freshness_benchmark.streaming_backends import StreamingBackend

SCENARIOS={
    'scifact-small': {'dataset':'scifact','base_count':4000,'rate':10,'query_rate':10,'arrival':'steady'},
    'nq-10k': {'dataset':'nq','base_count':10000,'rate':10,'query_rate':10,'arrival':'steady'},
    'nq-100k': {'dataset':'nq','base_count':100000,'rate':10,'query_rate':10,'arrival':'steady'},
    'nq-100k-burst': {'dataset':'nq','base_count':100000,'rate':10,'query_rate':10,'arrival':'burst'},
}


def resource_counters(backend):
    """Cumulative cgroup counters, outside the timed workload; never credentials."""
    result=subprocess.run(['docker','exec',f'freshness-v2-{backend}','sh','-c',
        'cat /sys/fs/cgroup/cpu.stat; echo memory_bytes $(cat /sys/fs/cgroup/memory.current); echo pids $(cat /sys/fs/cgroup/pids.current)'],
        text=True,capture_output=True,timeout=15)
    if result.returncode:return {'unavailable':result.stderr.strip()[:300]}
    return {key:int(value) for key,value in (line.split() for line in result.stdout.splitlines())}


def idle_queries(backend,queries,evaluate,seconds,rate):
    start=time.monotonic();rows=[];futures=[]
    def one(q):
        begin=time.monotonic();hits=backend.search(q['vector'],10,True);end=time.monotonic()
        return {'latency_ms':(end-begin)*1000,**evaluate(q,hits)}
    with ThreadPoolExecutor(4) as pool:
        for i in range(max(1,int(seconds*rate))):
            due=start+i/rate;time.sleep(max(0,due-time.monotonic()))
            futures.append(pool.submit(one,queries[i%len(queries)]))
        rows=[f.result() for f in futures]
    return {'count':len(rows),'ann_recall':sum(r['ann_recall'] for r in rows)/len(rows),
            'ndcg':sum(r['ndcg'] for r in rows)/len(rows),'latency_ms':metric_stats([r['latency_ms'] for r in rows])}


def prepare_operations(data,count,cfg):
    operations=[];initial=[];old_vectors=[];arrivals=arrival_times(cfg);old_index=count+len(arrivals)
    for i,_ in enumerate(arrivals):
        kind=('insert','update','delete')[i%3];key=f'mutation-{i:06d}'
        doc={'id':key,'text':data.docs[count+i]['text'],'cohort':'mutable','version':1}
        vector=data.vectors[count+i]
        if kind!='insert':
            if kind=='update':
                while old_index<len(data.docs) and float(data.vectors[old_index]@vector)>.3:old_index+=1
            if old_index>=len(data.docs):raise ValueError('Insufficient disjoint mutation documents for configuration')
            old={**doc,'version':0,'text':data.docs[old_index]['text']}
            initial.append(old);old_vectors.append(data.vectors[old_index])
            if kind=='delete':vector=data.vectors[old_index]
            old_index+=1
        operations.append({'operation':kind,'doc':doc,'vector':vector})
    return operations,initial,old_vectors


def run_cell(backend_name,collection,data,scenario,cfg,out):
    out.mkdir(parents=True,exist_ok=False)
    count=scenario['base_count'];queries,evaluate=data.prepare_reference(count)
    operations,initial,old_vectors=prepare_operations(data,count,cfg)
    backend=StreamingBackend(backend_name,collection)
    metadata={'backend':backend_name,'collection':collection,'dataset':data.manifest,'base_count':count,'profile':scenario,
              'config':asdict(cfg),'preloaded_mutable':len(initial),'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
    created=False
    try:
        setup_start=time.monotonic();backend.create(384);created=True
        static=[{**doc,'version':0,'cohort':'static'} for doc in data.docs[:count]]
        def load_batch(index):backend.bulk(static[index:index+256],data.vectors[index:index+256])
        with ThreadPoolExecutor(4) as pool:list(pool.map(load_batch,range(0,count,256)))
        for index in range(0,len(initial),128):backend.bulk(initial[index:index+128],old_vectors[index:index+128])
        backend.finish_load()
        deadline=time.monotonic()+300
        while True:
            info=backend.info(queries[0]['vector']);actual=backend.count()
            indexed=info.get('collection',{}).get('indexed_vectors_count',actual)
            if actual==count+len(initial) and indexed>=.95*actual:break
            if time.monotonic()>deadline:raise RuntimeError(f'Index readiness timeout: count={actual}, indexed={indexed}')
            time.sleep(1)
        metadata['setup_s']=time.monotonic()-setup_start;metadata['backend_before']=info;metadata['count_before']=actual
        # Check every initial mutation target through control and vector reads.
        vector_by_id={d['id']:v for d,v in zip(initial,old_vectors)}
        def preflight(op):
            if op['operation']=='insert':return backend.get(op['doc']['id']) is None
            key=op['doc']['id'];control=backend.get(key)
            hits=backend.search(vector_by_id[key],10,False)
            old_valid=control is not None and control.get('version')==0 and any(h['doc_id']==key and h['version']==0 for h in hits)
            new_absent=op['operation']!='update' or not any(h['doc_id']==key for h in backend.search(op['vector'],10,False))
            return old_valid and new_absent
        with ThreadPoolExecutor(8) as pool:
            for op,valid in zip(operations,pool.map(preflight,operations)):op['precondition']=bool(valid)
        idle_queries(backend,queries,evaluate,2,cfg.query_rate)  # excluded warmup
        metadata['idle_duration_s']=max(5,len(queries)/cfg.query_rate)
        metadata['idle_queries']=idle_queries(backend,queries,evaluate,metadata['idle_duration_s'],cfg.query_rate)
        metadata['exact_ndcg']=sum(q['exact_ndcg'] for q in queries)/len(queries)
        (out/'reference.json').write_text(json.dumps([{'id':q['id'],'cutoff':q['cutoff'],'exact_ids':q['exact_ids'],'exact_ndcg':q['exact_ndcg']} for q in queries],indent=2))
        metadata['resources_before']=resource_counters(backend_name)
        result=run_stream(backend,operations,queries,cfg,out,evaluate)
        metadata['resources_after']=resource_counters(backend_name)
        metadata['count_after']=backend.count();metadata['backend_after']=backend.info(queries[0]['vector'])
        max_rate=cfg.rate*(cfg.burst_multiplier if cfg.arrival=='burst' else 1)
        diagnostic=result['diagnostics'];q=result['query']
        gates={'arrival_dispatch':diagnostic['schedule_delay_ms']['p95']<=1000/max_rate,
               'probe_dispatch':diagnostic['probe_dispatch_ms']['p95'] is not None and diagnostic['probe_dispatch_ms']['p95']<=cfg.poll_ms,
               'query_dispatch':q['dispatch_delay_ms']['p95'] is not None and q['dispatch_delay_ms']['p95']<=1000/cfg.query_rate,
               'ann_recall':metadata['idle_queries']['ann_recall']>=.95 and q['ann_recall_at_10']>=.95,
               'preconditions':result['statuses']['invalid_precondition']==0,
               'client_capacity':result['statuses']['client_overload']==0,
               'cohort_integrity':not any(json.loads(line).get('unexpected_cohort',0) for line in (out/'queries.jsonl').read_text().splitlines())}
        if backend_name=='pgvector':gates['ann_index_used']='_hnsw' in json.dumps(metadata['backend_before']['query_plan'])
        elif backend_name=='qdrant':gates['ann_index_used']=metadata['backend_before']['collection']['indexed_vectors_count']>=.95*metadata['count_before']
        else:gates['ann_index_used']=metadata['backend_before']['schema']['vectorIndexType']=='hnsw' and metadata['backend_before']['schema']['vectorIndexConfig']['flatSearchCutoff']==0
        result.update({'metadata':metadata,'gates':gates,'eligible':all(gates.values()),'protocol':'mixed-mutations-v2'})
        (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
        return result
    except Exception as exc:
        (out/'failure.json').write_text(json.dumps({'error':str(exc),'metadata':metadata},indent=2))
        raise
    finally:
        if created:backend.drop()
        backend.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True,type=Path)
    p.add_argument('--scenarios',nargs='+',choices=list(SCENARIOS),default=list(SCENARIOS))
    p.add_argument('--backends',nargs='+',default=['qdrant','weaviate','pgvector']);p.add_argument('--trials',type=int,default=5)
    p.add_argument('--duration',type=float,default=30);p.add_argument('--seed',type=int,default=20261028)
    args=p.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    data={key:RetrievalData(Path('benchmarks/data/v2')/key) for key in {SCENARIOS[s]['dataset'] for s in args.scenarios}}
    cells=[(trial,backend,scenario) for trial in range(1,args.trials+1) for backend in args.backends for scenario in args.scenarios]
    random.Random(args.seed).shuffle(cells)
    metadata={'protocol':'mixed-mutations-v2','arguments':{**vars(args),'out':str(args.out)},'order':cells,
              'host':{'platform':platform.platform(),'cpu_count':os.cpu_count(),'cpu_model':subprocess.check_output(['sysctl','-n','machdep.cpu.brand_string'],text=True).strip() if platform.system()=='Darwin' else platform.processor(),'memory_bytes':os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')},
              'source':{},'datasets':{k:v.manifest for k,v in data.items()}}
    source_paths=sorted(Path('src').rglob('*.py'))+sorted(Path('scripts').glob('*.py'))+[
        Path('pyproject.toml'),Path('docker-compose.v2.yml'),Path('benchmarks/protocol-v2.json'),
        Path('benchmarks/nq-v2.lock.json'),Path('benchmarks/scifact-v2.lock.json')]
    for path in source_paths:metadata['source'][str(path)]=file_sha(path)
    metadata['dependencies']=subprocess.check_output(['uv','pip','freeze','--python','.venv/bin/python'],text=True)
    docker_info=json.loads(subprocess.check_output(['docker','info','--format','{{json .}}'],text=True))
    metadata['docker_host']={k:docker_info[k] for k in ('NCPU','MemTotal','KernelVersion','OperatingSystem','ServerVersion')}
    containers=json.loads(subprocess.check_output(['docker','inspect','freshness-v2-qdrant','freshness-v2-weaviate','freshness-v2-pgvector'],text=True))
    metadata['containers']=[{'name':c['Name'],'image_id':c['Image'],'image':c['Config']['Image'],'memory_bytes':c['HostConfig']['Memory'],'shm_bytes':c['HostConfig']['ShmSize'],'cpu_quota':c['HostConfig']['NanoCpus'],'async_indexing':next((s for s in c['Config']['Env'] if s.startswith('ASYNC_INDEXING=')),None)} for c in containers]
    (args.out/'experiment.json').write_text(json.dumps(metadata,indent=2)+'\n')
    with tarfile.open(args.out/'source.tar.gz','w:gz') as tar:
        for name in metadata['source']:tar.add(name)
    calibration=[]
    for delay,ack in ((0,0),(25,0),(100,0),(0,100)):
        calibration.append(calibrate(args.out/'calibration'/f'delay{delay}-ack{ack}',delay,ack))
    (args.out/'calibration.json').write_text(json.dumps(calibration,indent=2)+'\n')
    for index,(trial,backend,scenario_name) in enumerate(cells):
        scenario=SCENARIOS[scenario_name]
        cfg=StreamConfig(duration_s=args.duration,rate=scenario['rate'],query_rate=scenario['query_rate'],arrival=scenario['arrival'])
        tag=hashlib.sha256(str(args.out).encode()).hexdigest()[:6]
        name=f'fb2_{tag}_{index:03d}'
        print(f'CELL {index+1}/{len(cells)} trial={trial} {backend} {scenario_name}',flush=True)
        try:
            result=run_cell(backend,name,data[scenario['dataset']],scenario,cfg,args.out/'runs'/name)
            record={'run':name,'trial':trial,'backend':backend,'scenario':scenario_name,'status':'complete','eligible':result['eligible'],'gates':result['gates']}
            print(json.dumps(record),flush=True)
        except Exception as exc:
            record={'run':name,'trial':trial,'backend':backend,'scenario':scenario_name,'status':'failed','error':str(exc)}
            print(json.dumps(record),flush=True)
        with (args.out/'progress.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
        time.sleep(2)
    print('Matrix complete',flush=True)


if __name__=='__main__':main()
