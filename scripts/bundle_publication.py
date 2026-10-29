#!/usr/bin/env python3
"""Build a portable release from validated evidence, exact inputs and current source."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

from verify_publication import verify


def main():
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path)
    args=p.parse_args();root=args.directory
    if not verify(root):
        raise SystemExit("Client validity gates failed; inspect report before release")
    experiment = json.loads((root/'experiment.json').read_text())
    for filename, field in (('corpus.jsonl','corpus_sha256'), ('embeddings.json','cache_sha256')):
        actual = hashlib.sha256((Path('benchmarks/data/python-docs')/filename).read_bytes()).hexdigest()
        if actual != experiment['dataset'][field]:
            raise SystemExit(f'Data changed since experiment: {filename}')
    output = root.parent/(root.name+'-release.tar.gz')
    if output.exists():
        raise SystemExit(f'Refusing overwrite: {output}')
    with tarfile.open(output,'w:gz') as tar:
        tar.add(root,arcname='freshness-release/evidence')
        data=Path('benchmarks/data/python-docs')
        for name in ('corpus.jsonl','embeddings.json','manifest.json','PYTHON-LICENSE.txt'):
            tar.add(data/name,arcname='freshness-release/benchmarks/data/python-docs/'+name)
        for directory in ('src','scripts','tests','docs','results','.github'):
            for path in sorted(Path(directory).rglob('*')):
                if path.is_file() and '__pycache__' not in path.parts:
                    tar.add(path,arcname='freshness-release/'+str(path))
        for name in ('README.md','CONTRIBUTING.md','methodology.md','LICENSE','CITATION.cff','CHANGELOG.md','pyproject.toml','docker-compose.yml','benchmarks/python-docs.lock.json','benchmarks/protocol-v1.json','benchmarks/publication-requirements.txt'):
            tar.add(name,arcname='freshness-release/'+name)
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix+'.sha256').write_text(digest+'  '+output.name+'\n')
    print(f'{output}: {digest}')


if __name__=='__main__':
    main()
