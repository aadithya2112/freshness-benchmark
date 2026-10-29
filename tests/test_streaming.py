import json
from pathlib import Path
import tempfile
import unittest
import numpy as np

from freshness_benchmark.calibration import DelayedBackend,calibrate
from freshness_benchmark.streaming import StreamConfig,arrival_times,run_stream,update_channel,fresh_channel
from freshness_benchmark.quality import ndcg


class StreamingTests(unittest.TestCase):
    def test_independent_reader_observes_before_slow_ack(self):
        with tempfile.TemporaryDirectory() as td:
            result=calibrate(td,delay_ms=0,ack_ms=80,duration=.2)
            events=[json.loads(line) for line in (Path(td)/'events.jsonl').read_text().splitlines()]
            self.assertTrue(all(r['status']=='success' for r in events))
            self.assertTrue(any(r['search']['first_ms']<r['ack_ms']-30 for r in events))

    def test_known_delay_is_not_observed_early(self):
        with tempfile.TemporaryDirectory() as td:
            result=calibrate(td,delay_ms=35,duration=.2)
            events=[json.loads(line) for line in (Path(td)/'events.jsonl').read_text().splitlines()]
            self.assertTrue(all(r['status']=='success' for r in events))
            for r in events:self.assertGreaterEqual(r['first_observed_ms'],35)

    def test_negative_ann_result_alone_cannot_confirm_delete(self):
        with tempfile.TemporaryDirectory() as td:
            cfg=StreamConfig(duration_s=.02,rate=1,query_rate=0,deadline_s=.08,stable_ms=10,poll_ms=2)
            backend=DelayedBackend(delete_never_visible=True);backend.keys=['delete-0']
            backend.search=lambda *args,**kwargs:[]
            result=run_stream(backend,[{'operation':'delete','doc':{'id':'delete-0','version':1},'vector':np.array([0])}],[],cfg,td)
            self.assertEqual(result['statuses']['timeout'],1)
            self.assertEqual(result['statuses']['success'],0)

    def test_regression_resets_confirmation_window(self):
        cfg=StreamConfig(stable_ms=20,min_confirmations=3);state=fresh_channel()
        update_channel(state,True,0,cfg);update_channel(state,True,10,cfg)
        update_channel(state,False,15,cfg)
        update_channel(state,True,20,cfg);update_channel(state,True,30,cfg)
        self.assertIsNone(state['confirmed_ms'])
        update_channel(state,True,40,cfg)
        self.assertEqual(state['confirmed_ms'],40);self.assertEqual(state['regressions'],1)

    def test_bursts_change_arrivals_and_ndcg_respects_rank(self):
        self.assertGreater(len(arrival_times(StreamConfig(duration_s=1,rate=10,arrival='burst'))),30)
        self.assertEqual(len(arrival_times(StreamConfig(duration_s=30,rate=10))),300)
        self.assertEqual(len(arrival_times(StreamConfig(duration_s=30,rate=10,arrival='burst'))),390)
        self.assertEqual(ndcg(['a'],{'a':1}),1)
        self.assertLess(ndcg(['b','a'],{'a':1}),1)
