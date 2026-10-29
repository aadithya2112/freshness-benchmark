#!/usr/bin/env python3
"""Prepare BEIR subsets with real questions, relevance judgments and float32 caches."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import random
import urllib.request
import zipfile

MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
SOURCE_MD5 = {'nq': 'd4d3d2e48787a744b6f6e691ff534307', 'scifact': '5f7d1de60b170fc8027bb7898e2efca1'}
LICENSES = {
    'nq': ('CC-BY-SA-3.0', 'https://raw.githubusercontent.com/google-research-datasets/natural-questions/master/nq_open/README.md'),
    'scifact': ('Corpus: ODC-By-1.0; claims/evidence: CC-BY-4.0', 'https://raw.githubusercontent.com/allenai/scifact/master/LICENSE.md'),
}


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('dataset', choices=list(SOURCE_MD5)); p.add_argument('--archive', type=Path)
    p.add_argument('--limit', type=int, default=124000); p.add_argument('--queries', type=int, default=100)
    p.add_argument('--device', default='mps'); args=p.parse_args()
    out=Path('benchmarks/data/v2')/args.dataset; out.mkdir(parents=True,exist_ok=True)
    source=f'https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/{args.dataset}.zip'
    archive=args.archive or out/'source.zip'
    if not archive.exists():
        urllib.request.urlretrieve(source,archive)
    if hashlib.md5(archive.read_bytes()).hexdigest()!=SOURCE_MD5[args.dataset]:
        raise ValueError('Upstream BEIR archive MD5 mismatch')
    rng=random.Random(20261028)
    with zipfile.ZipFile(archive) as z:
        qrels=list(csv.DictReader(io.TextIOWrapper(z.open(f'{args.dataset}/qrels/test.tsv')),delimiter='\t'))
        query_map={str(q['_id']):q['text'] for q in map(json.loads,io.TextIOWrapper(z.open(f'{args.dataset}/queries.jsonl')))}
        qids=sorted({row['query-id'] for row in qrels});rng.shuffle(qids);qids=qids[:args.queries]
        qrels=[r for r in qrels if r['query-id'] in set(qids) and int(r['score'])>0]
        required={r['corpus-id'] for r in qrels}
        reserved=[];reservoir=[];seen=0;capacity=args.limit-len(required)
        for line in io.TextIOWrapper(z.open(f'{args.dataset}/corpus.jsonl')):
            row=json.loads(line);key=str(row['_id'])
            text=' '.join((row.get('title','')+'\n'+row['text']).split()[:200])
            doc={'id':key,'title':row.get('title',''),'text':text}
            if key in required:
                reserved.append(doc);continue
            seen+=1
            if len(reservoir)<capacity:reservoir.append(doc)
            else:
                index=rng.randrange(seen)
                if index<capacity:reservoir[index]=doc
        if len(reserved)!=len(required):raise ValueError('Missing relevant documents')
        # The prefix retains all judged relevant docs for the fixed real query set.
        rng.shuffle(reservoir);docs=sorted(reserved,key=lambda r:r['id'])+reservoir
    with (out/'corpus.jsonl').open('w') as f:
        for row in docs:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    queries=[{'id':key,'text':query_map[key], 'qrels':{r['corpus-id']:int(r['score']) for r in qrels if r['query-id']==key}} for key in qids]
    (out/'queries.json').write_text(json.dumps(queries,indent=2))
    license_name,license_url=LICENSES[args.dataset]
    with urllib.request.urlopen(license_url) as response:
        (out/'UPSTREAM-LICENSE.md').write_bytes(response.read())
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(4)
    model=SentenceTransformer(MODEL,revision=REVISION,device=args.device)
    for name,texts in [('vectors',[d['text'] for d in docs]),('query_vectors',[q['text'] for q in queries])]:
        array=model.encode(texts,batch_size=128,normalize_embeddings=True,show_progress_bar=True)
        np.save(out/f'{name}.npy',array.astype('float32'),allow_pickle=False)
    manifest={'dataset':args.dataset,'source':source,'source_sha256':sha(archive),'source_md5':SOURCE_MD5[args.dataset],
              'records':len(docs),'queries':len(queries),'relevant_documents_retained':len(reserved),
              'seed':20261028,'license':license_name,'license_source':license_url,
              'attribution':'BEIR and original dataset authors; Wikipedia contributors for NQ, SciFact authors and cited article authors for SciFact.',
              'transformation':'200-word title+text prefix; seeded reservoir of documents with relevant documents for selected test queries retained at front. Simulated mutations; no historical replay.',
              'model':MODEL,'model_revision':REVISION,'dimensions':384,'normalized':True,'max_tokens':model.max_seq_length,
              'device':args.device,'files':{name:sha(out/name) for name in ['corpus.jsonl','queries.json','vectors.npy','query_vectors.npy','UPSTREAM-LICENSE.md']}}
    lock=Path('benchmarks')/f'{args.dataset}-v2.lock.json'
    if lock.exists():
        old=json.loads(lock.read_text())
        for key in ('corpus.jsonl','queries.json'):
            if old['files'][key]!=manifest['files'][key]:raise ValueError(f'Data drift: {key}')
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2),flush=True)


if __name__=='__main__':main()
