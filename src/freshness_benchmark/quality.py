"""Fixed immutable-cohort references keep quality evaluation well-defined during writes."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits


def file_sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def ndcg(ids,qrels,k=10):
    gain=sum((2**qrels.get(str(key),0)-1)/math.log2(rank+2) for rank,key in enumerate(ids[:k]))
    ideal=sum((2**rel-1)/math.log2(rank+2) for rank,rel in enumerate(sorted(qrels.values(),reverse=True)[:k]))
    return gain/ideal if ideal else 0.0


class RetrievalData:
    def __init__(self,path):
        self.path=Path(path);self.manifest=json.loads((self.path/'manifest.json').read_text())
        for name,expected in self.manifest['files'].items():
            if file_sha(self.path/name)!=expected:raise ValueError(f'Dataset integrity failure: {name}')
        self.docs=[json.loads(line) for line in (self.path/'corpus.jsonl').read_text().splitlines()]
        self.vectors=np.load(self.path/'vectors.npy',mmap_mode='r',allow_pickle=False)
        self.query_vectors=np.load(self.path/'query_vectors.npy',mmap_mode='r',allow_pickle=False)
        self.queries=json.loads((self.path/'queries.json').read_text())
        if self.vectors.shape!=(len(self.docs),384) or self.query_vectors.shape!=(len(self.queries),384):raise ValueError('Vector shape mismatch')
        if len({d['id'] for d in self.docs})!=len(self.docs):raise ValueError('Duplicate source IDs')
        for matrix in (self.vectors,self.query_vectors):
            if not np.isfinite(matrix).all() or not np.allclose(np.linalg.norm(matrix,axis=1),1,atol=1e-4):raise ValueError('Invalid normalized vectors')
        self.references={}

    def prepare_reference(self,count):
        if count in self.references:return self.references[count]
        if not 10<=count<=len(self.docs):raise ValueError('Invalid base count')
        static_ids={d['id']:i for i,d in enumerate(self.docs[:count])};queries=[]
        with threadpool_limits(limits=4):
            for i,source in enumerate(self.queries):
                if not set(source['qrels'])<=set(static_ids):raise ValueError('Relevant docs outside static cohort')
                vector=self.query_vectors[i]
                scores=self.vectors[:count]@vector
                top=np.argpartition(-scores,9)[:10]
                top=sorted(top,key=lambda j:(-float(scores[j]),self.docs[j]['id']))
                queries.append({**source,'vector':vector,'cutoff':float(scores[top[-1]]),
                                'exact_ids':[self.docs[j]['id'] for j in top],
                                'exact_ndcg':ndcg([self.docs[j]['id'] for j in top],source['qrels'])})
        def evaluate(query,hits):
            ids=[str(h['doc_id']) for h in hits]
            valid=set(ids)&static_ids.keys()
            # Credit equal-score neighbors at the tenth boundary, avoiding arbitrary tie penalties.
            recall=sum(float(self.vectors[static_ids[key]]@query['vector'])>=query['cutoff']-1e-6 for key in valid)/10
            return {'ann_recall':min(recall,1.0),'ndcg':ndcg(ids,query['qrels']),
                    'unexpected_cohort':sum(key not in static_ids for key in ids)}
        self.references[count]=(queries,evaluate)
        return queries,evaluate
