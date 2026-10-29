"""Prevent custom experiments from receiving the reference workload label."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('export_v2',ROOT/'scripts/export_v2.py')
exporter=importlib.util.module_from_spec(spec);spec.loader.exec_module(exporter)


class ReferenceTrackTests(unittest.TestCase):
    def setUp(self):
        self.protocol=json.loads((ROOT/'benchmarks/protocol-v2.json').read_text())
        self.experiment={'arguments':{'trials':5,'duration':30,'seed':20261028},
            'order':[[trial,backend,scenario] for trial in range(1,6)
                     for backend in self.protocol['backends'] for scenario in self.protocol['profiles']]}
        self.run={'scenario':'nq-100k','summary':{'config':{'duration_s':30,'rate':10,'query_rate':10,
            'arrival':'steady','deadline_s':5,'poll_ms':10,'stable_ms':50,'min_confirmations':3,
            'write_workers':4,'probe_workers':32,'query_workers':4,'max_active':1024},
            'metadata':{'profile':{'dataset':'nq','base_count':100000}}}}

    def test_reference_shape_is_accepted(self):
        self.assertTrue(exporter.reference_configuration(self.experiment,[self.run],self.protocol))

    def test_duplicate_cell_cannot_replace_a_planned_trial(self):
        self.experiment['order'][-1]=self.experiment['order'][0]
        self.assertFalse(exporter.reference_configuration(self.experiment,[self.run],self.protocol))

    def test_custom_workload_is_not_reference(self):
        for key,value in [('rate',20),('query_rate',1),('stable_ms',0),('probe_workers',64)]:
            with self.subTest(key=key):
                run=copy.deepcopy(self.run);run['summary']['config'][key]=value
                self.assertFalse(exporter.reference_configuration(self.experiment,[run],self.protocol))
