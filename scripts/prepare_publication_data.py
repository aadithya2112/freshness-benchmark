#!/usr/bin/env python3
"""Download pinned Python docs, chunk deterministically, and cache semantic vectors."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import random
import tarfile
import urllib.request

MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
SOURCE = 'https://www.python.org/ftp/python/3.13.0/Python-3.13.0.tgz'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='benchmarks/data/python-docs')
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    archive = out / 'source.tgz'
    if not archive.exists():
        with urllib.request.urlopen(SOURCE, timeout=120) as response:
            archive.write_bytes(response.read())
    raw = archive.read_bytes()
    lock = Path('benchmarks/python-docs.lock.json')
    if lock.exists() and json.loads(lock.read_text())['source_sha256'] != sha(raw):
        raise ValueError('Pinned source archive checksum mismatch')
    rows, seen = [], set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as tar:
        for member in sorted(tar.getmembers(), key=lambda m: m.name):
            if not member.isfile():
                continue
            if member.name == 'Python-3.13.0/LICENSE':
                (out / 'PYTHON-LICENSE.txt').write_bytes(tar.extractfile(member).read())
            if not any(f'/Doc/{group}/' in member.name for group in ('library', 'tutorial', 'howto')) or not member.name.endswith('.rst'):
                continue
            text = tar.extractfile(member).read().decode('utf-8')
            words = text.split()
            for offset in range(0, len(words), 100):
                chunk = ' '.join(words[offset:offset+100])
                if len(chunk.split()) < 40 or sha(chunk.encode()) in seen:
                    continue
                seen.add(sha(chunk.encode()))
                path = member.name.split('/Doc/')[1]
                rows.append({'doc_id': f'{path}:{offset}', 'body': chunk,
                             'source': f'https://github.com/python/cpython/blob/v3.13.0/Doc/{path}',
                             'group': path.split('/')[0]})
    random.Random(20261028).shuffle(rows)
    corpus = ''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows).encode()
    (out / 'corpus.jsonl').write_bytes(corpus)
    import torch
    import sentence_transformers
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(4)
    model = SentenceTransformer(MODEL, revision=REVISION, device='cpu')
    vectors = model.encode([r['body'] for r in rows], normalize_embeddings=True,
                           batch_size=64, show_progress_bar=True)
    metadata = {'model': MODEL, 'revision': REVISION, 'dimensions': 384,
                'normalized': True, 'max_seq_length': model.max_seq_length,
                'sentence_transformers_version': sentence_transformers.__version__,
                'torch_version': torch.__version__, 'corpus_sha256': sha(corpus)}
    cache = {'metadata': metadata, 'vectors': {r['doc_id']: v.tolist() for r,v in zip(rows,vectors)},
             'text_sha256': {r['doc_id']: sha(r['body'].encode()) for r in rows}}
    (out / 'embeddings.json').write_text(json.dumps(cache))
    manifest = {'source_url': SOURCE, 'source_sha256': sha(raw),
                'corpus_sha256': sha(corpus), 'records': len(rows), 'seed': 20261028,
                'transformation': 'library/tutorial/howto RST; whitespace split into 100-word nonoverlapping chunks; discard <40 words and exact duplicates; seeded shuffle',
                'license': 'PSF-2.0; see PYTHON-LICENSE.txt',
                'embedding': metadata,
                'cache_sha256': sha((out/'embeddings.json').read_bytes())}
    lock = Path('benchmarks/python-docs.lock.json')
    if lock.exists():
        previous = json.loads(lock.read_text())
        for key in ('source_sha256', 'corpus_sha256'):
            if previous[key] != manifest[key]:
                raise ValueError(f'Pinned data mismatch: {key}')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
