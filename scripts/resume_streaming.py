#!/usr/bin/env python3
"""Resume an interrupted matrix without changing its measurement implementation.

Completed trials are never replaced. A partial trial without a terminal record
is archived and restarted in a fresh collection, with a public continuation log.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import time

from run_streaming import SCENARIOS,run_cell
from freshness_benchmark.calibration import calibrate
from freshness_benchmark.quality import RetrievalData,file_sha
from freshness_benchmark.streaming import StreamConfig
from freshness_benchmark.streaming_backends import StreamingBackend
from verify_v2 import verify


def resume(root):
    experiment=json.loads((root/'experiment.json').read_text())
    progress=[json.loads(line) for line in (root/'progress.jsonl').read_text().splitlines()]
    verify(root,allow_partial=True)
    for name,digest in experiment['source'].items():
        if name.startswith('src/') or name in ('scripts/run_streaming.py','pyproject.toml','docker-compose.v2.yml','benchmarks/protocol-v2.json'):
            if file_sha(name)!=digest:raise ValueError(f'Measurement source changed: {name}; start a new experiment')
    if platform.platform()!=experiment['host']['platform']:raise ValueError('Host platform changed')
    dependencies=subprocess.check_output(['uv','pip','freeze','--python','.venv/bin/python'],text=True)
    if dependencies!=experiment['dependencies']:raise ValueError('Python environment changed')
    info=json.loads(subprocess.check_output(['docker','info','--format','{{json .}}'],text=True))
    for key in ('NCPU','MemTotal','KernelVersion','OperatingSystem','ServerVersion'):
        if info[key]!=experiment['docker_host'][key]:raise ValueError(f'Docker host changed: {key}')
    containers=json.loads(subprocess.check_output(['docker','inspect','freshness-v2-qdrant','freshness-v2-weaviate','freshness-v2-pgvector'],text=True))
    for current,before in zip(containers,experiment['containers']):
        for actual,expected in ((current['Image'],before['image_id']),(current['HostConfig']['Memory'],before['memory_bytes']),
                                (current['HostConfig']['NanoCpus'],before['cpu_quota']),(current['HostConfig']['ShmSize'],before['shm_bytes'])):
            if actual!=expected:raise ValueError('Container image/resource configuration changed')
    stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    continuation=root/'continuations'/stamp;continuation.mkdir(parents=True,exist_ok=False)
    pause_path=root/'PAUSED.json'
    pause=json.loads(pause_path.read_text()) if pause_path.exists() else None
    record={'resumed_utc':stamp,'completed_prefix':len(progress),'reason':
            'Resuming a user-requested pause; completed trials retained.' if pause else
            'Host/session interruption; containers restarted. Completed trials retained; partial trial archived and restarted.',
            'measurement_source_unchanged':True,'environment_unchanged':True,
            'containers':[{'name':c['Name'],'started_at':c['State']['StartedAt'],'image_id':c['Image']} for c in containers],
            'resume_source_sha256':file_sha(__file__)}
    if pause:record['paused_checkpoint']=pause
    shutil.copy2(__file__,continuation/'resume-source.py')
    (continuation/'continuation.json').write_text(json.dumps(record,indent=2)+'\n')
    controls=[]
    for delay,ack in ((0,0),(25,0),(100,0),(0,100)):
        controls.append(calibrate(continuation/'calibration'/f'delay{delay}-ack{ack}',delay,ack))
    (continuation/'calibration.json').write_text(json.dumps(controls,indent=2)+'\n')
    data={name:RetrievalData(Path('benchmarks/data/v2')/name) for name in experiment['datasets']}
    for name,cache in data.items():
        if cache.manifest!=experiment['datasets'][name]:raise ValueError('Dataset/cache changed')
    pause_path.unlink(missing_ok=True)  # The receipt is preserved in continuation.json.
    cells=experiment['order'];tag=hashlib.sha256(experiment['arguments']['out'].encode()).hexdigest()[:6]
    for index in range(len(progress),len(cells)):
        trial,backend,scenario_name=cells[index];scenario=SCENARIOS[scenario_name]
        name=f'fb2_{tag}_{index:03d}';directory=root/'runs'/name
        if directory.exists():
            if (directory/'summary.json').exists() or (directory/'failure.json').exists():raise ValueError('Unlogged terminal trial requires explicit recovery, not replacement')
            interrupted=continuation/'interrupted';interrupted.mkdir(exist_ok=True)
            shutil.move(str(directory),str(interrupted/name))
            cleanup=StreamingBackend(backend,name)
            try:cleanup.drop()
            except Exception as error:
                # A restarted container may no longer contain the partial collection.
                (continuation/'cleanup-note.txt').write_text(str(error)+'\n')
            finally:cleanup.close()
            (continuation/'interrupted-trial.json').write_text(json.dumps({'run':name,'trial':trial,'backend':backend,'scenario':scenario_name,'status':'interrupted','restarted':True},indent=2)+'\n')
        cfg=StreamConfig(duration_s=experiment['arguments']['duration'],rate=scenario['rate'],query_rate=scenario['query_rate'],arrival=scenario['arrival'])
        print(f'CELL {index+1}/{len(cells)} trial={trial} {backend} {scenario_name}',flush=True)
        try:
            result=run_cell(backend,name,data[scenario['dataset']],scenario,cfg,directory)
            entry={'run':name,'trial':trial,'backend':backend,'scenario':scenario_name,'status':'complete','eligible':result['eligible'],'gates':result['gates']}
        except Exception as error:entry={'run':name,'trial':trial,'backend':backend,'scenario':scenario_name,'status':'failed','error':str(error)}
        print(json.dumps(entry),flush=True)
        with (root/'progress.jsonl').open('a') as output:output.write(json.dumps(entry)+'\n')
        time.sleep(2)
    print('Matrix complete',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    resume(parser.parse_args().directory)
