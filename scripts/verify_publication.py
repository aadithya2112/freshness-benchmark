#!/usr/bin/env python3
"""Fail closed on incomplete, altered, or internally inconsistent publication evidence."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


def verify(root):
    checksums = json.loads((root/'checksums.json').read_text())
    for name, expected in checksums.items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest() == expected, f'Checksum mismatch: {name}'
    experiment = json.loads((root/'experiment.json').read_text())
    progress = [json.loads(line) for line in (root/'progress.jsonl').read_text().splitlines()]
    expected = Counter((trial+1,backend,rate) for trial,backend,rate in experiment['order'])
    observed = Counter((r['trial'],r['backend'],r['rate']) for r in progress)
    assert observed == expected, 'Incomplete or duplicate trial matrix'
    for entry in progress:
        run = root/'runs'/Path(entry['run_dir']).name
        s = json.loads((run/'summary.json').read_text())
        records = [json.loads(line) for line in (run/'trace.jsonl').read_text().splitlines()]
        assert len(records) == experiment['arguments']['docs'] == s['docs_total']
        assert len({r['doc_id'] for r in records}) == len(records)
        assert s['config']['search_scope']=='collection' and not s['config']['inject_anchor']
        assert s['environment']['embedding_source']['type']=='cached_semantic'
        assert s['environment']['embedding_source']['cache_sha256']==experiment['dataset']['cache_sha256']
        assert s['environment']['dataset_sha256']==experiment['dataset']['corpus_sha256']
        assert s['preload_written']==experiment['arguments']['preload']
        assert not s['backend_info'].get('error'), 'Backend metadata unavailable'
        counts = Counter(r['status'] for r in records)
        assert counts['success']==s['docs_success'] and counts['timeout']==s['docs_timeout'] and counts['error']==s['docs_error']
        assert sum(counts[k] for k in ('success','timeout','error'))==len(records)
        for record in records:
            assert record['search_attempts']==len(record['probes'])
            if record['status']=='success':
                assert record['probes'][-1]['found']
                assert 0 <= record['freshness_ms'] <= s['config']['max_wait_s']*1000
                assert math.isclose(record['freshness_ms'],sum(record[k] for k in ('embedding_ms','write_ack_ms','visibility_ms')),abs_tol=1e-6)
                assert math.isclose(record['freshness_ms'],record['probes'][-1]['end_ms'],abs_tol=1e-6)
    results = json.loads((root/'results.json').read_text())
    assert len(results)==len({(b,r) for t,b,r in experiment['order']})
    gates = all(row['all_trials_observed'] and row['arrival_schedule_pass'] and row['probe_resolution_pass'] for row in results)
    print(f'Verified {len(progress)} runs and {sum(row["documents"] for row in results)} records. Client validity gates: {gates}')
    return gates


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path)
    if not verify(p.parse_args().directory):
        raise SystemExit('Client validity gate failed; report retained with limitations')
