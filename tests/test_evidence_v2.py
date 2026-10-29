"""Fault-injection tests for the published observation and audit contract."""
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
import numpy as np

from freshness_benchmark.calibration import calibrate
from freshness_benchmark.streaming import StreamConfig,run_stream

spec=importlib.util.spec_from_file_location('verify_v2',Path(__file__).resolve().parents[1]/'scripts/verify_v2.py')
verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)


class ObservationFaultTests(unittest.TestCase):
    def test_query_schedule_has_no_extra_boundary_admission(self):
        from freshness_benchmark.calibration import DelayedBackend
        from freshness_benchmark.streaming import arrival_times
        with tempfile.TemporaryDirectory() as td:
            cfg=StreamConfig(duration_s=.3,rate=10,query_rate=100)
            ops=[{'operation':'insert','doc':{'id':f'insert-{i}','version':1},'vector':np.array([i])} for i in range(len(arrival_times(cfg)))]
            backend=DelayedBackend();backend.keys=[op['doc']['id'] for op in ops]
            result=run_stream(backend,ops,[{'id':'q','vector':np.array([0])}],cfg,td)
            self.assertEqual(result['query']['count'],30)

    def one(self,backend,deadline=.2,stable=20):
        with tempfile.TemporaryDirectory() as td:
            cfg=StreamConfig(duration_s=.01,rate=1,query_rate=0,deadline_s=deadline,poll_ms=2,stable_ms=stable)
            summary=run_stream(backend,[{'operation':'insert','doc':{'id':'target','version':1},'vector':np.array([1])}],[],cfg,td)
            event=json.loads((Path(td)/'events.jsonl').read_text())
            probes=[json.loads(s) for s in (Path(td)/'probes.jsonl').read_text().splitlines()]
            verifier.audit_run(td,summary)
            return event,probes

    def test_read_error_breaks_confirmation_sequence(self):
        class Faulty:
            written=False;calls=0
            def write(self,*args):self.written=True
            def get(self,*args):return {'doc_id':'target','version':1} if self.written else None
            def search(self,*args):
                if not self.written:return []
                self.calls+=1
                if self.calls==3:raise RuntimeError('injected read error')
                return [{'doc_id':'target','version':1}]
        event,probes=self.one(Faulty())
        fault=next(p for p in probes if 'error' in p)
        self.assertEqual(event['status'],'success')
        self.assertGreater(event['search']['stable_since_ms'],fault['end_ms'])
        self.assertEqual(event['search']['regressions'],1)

    def test_late_good_responses_cannot_establish_success(self):
        class Slow:
            def write(self,*args):pass
            def get(self,*args):time.sleep(.07);return {'doc_id':'target','version':1}
            def search(self,*args):time.sleep(.07);return [{'doc_id':'target','version':1}]
        event,probes=self.one(Slow(),deadline=.02,stable=0)
        self.assertEqual(event['status'],'timeout')
        self.assertIsNone(event['search']['first_ms'])
        self.assertTrue(all(p['end_ms']>20 for p in probes))

    def test_late_read_error_is_retained_and_auditable(self):
        class LateError:
            calls=0
            def write(self,*args):pass
            def get(self,*args):return {'doc_id':'target','version':1}
            def search(self,*args):
                self.calls+=1
                if self.calls==3:
                    time.sleep(.06)
                    raise RuntimeError('late read failure')
                return [{'doc_id':'target','version':1}]
        event,probes=self.one(LateError(),deadline=.04,stable=20)
        self.assertEqual(event['status'],'timeout')
        self.assertEqual(event['search']['regressions'],1)
        self.assertTrue(any('error' in p and p['end_ms']>40 for p in probes))

    def test_old_version_search_hit_is_not_a_fresh_update(self):
        class Stale:
            def write(self,*args):pass
            def get(self,*args):return {'doc_id':'target','version':1}
            def search(self,*args):return [{'doc_id':'target','version':0}]
        event,_=self.one(Stale(),deadline=.06,stable=10)
        self.assertEqual(event['status'],'timeout')
        self.assertIsNone(event['search']['first_ms'])


class EvidenceAuditTests(unittest.TestCase):
    def test_summary_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            summary=calibrate(td,duration=.2)
            verifier.audit_run(td,summary)
            summary['operations']['insert']['first_observed_ms']['p95']+=500
            with self.assertRaises(verifier.EvidenceError):verifier.audit_run(td,summary)

    def test_missing_probe_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            summary=calibrate(td,duration=.2)
            path=Path(td)/'probes.jsonl'
            path.write_text(''.join(line+'\n' for line in path.read_text().splitlines() if json.loads(line)['channel']!='search'))
            with self.assertRaises(verifier.EvidenceError):verifier.audit_run(td,summary)
