#!/usr/bin/env python3
"""Package audited reference evidence and exact licensed caches for publication."""
import argparse
import json
from pathlib import Path
import shutil
import tarfile
from freshness_benchmark.quality import file_sha
from verify_v2 import verify


def package(root,out,site):
    data=json.loads((root/'results.json').read_text())
    if data['status']!='complete' or data.get('track')!='reference':
        raise ValueError('Only a complete reference matrix can use this release packager')
    verification=verify(root,check_data=False)
    out.mkdir(parents=True,exist_ok=True)
    for source,name in ((site/'benchmark-source.zip','benchmark-source-v0.5.0.zip'),
                        (site/'benchmark-evidence.tar.gz','benchmark-evidence-v2.tar.gz')):
        shutil.copy2(source,out/name)
    for name in ('REPORT.md','results.json','results.csv','verification.json',
                 'latency-distributions.svg','latency-distributions.pdf','latency-distributions.png'):
        shutil.copy2(root/name,out/name)
    with tarfile.open(out/'reference-data-v2.tar.gz','w:gz') as archive:
        archive.add('docs/DATA-NOTICE.md',arcname='DATA-NOTICE.md')
        for name,manifest in data['experiment']['datasets'].items():
            base=Path('benchmarks/data/v2')/name
            if json.loads((base/'manifest.json').read_text())!=manifest:raise ValueError('Cache manifest changed')
            for filename,digest in manifest['files'].items():
                if file_sha(base/filename)!=digest:raise ValueError(f'Cache changed: {name}/{filename}')
                archive.add(base/filename,arcname=str(base/filename))
            archive.add(base/'manifest.json',arcname=str(base/'manifest.json'))
    with tarfile.open(out/'diagnostic-pilots-v2.tar.gz','w:gz') as archive:
        for directory in sorted(Path('artifacts').glob('v2-*')):
            if directory.is_dir():archive.add(directory,arcname=directory.name)
    prior=Path('artifacts/publication-v1-release.tar.gz')
    if prior.exists():shutil.copy2(prior,out/prior.name)
    (out/'README.md').write_text('''# Freshness Benchmark 0.5.0 / protocol 2

Start with REPORT.md and the methodology in benchmark-source-v0.5.0.zip.
The complete evidence archive contains raw observations, calibration,
continuation history, exact launch source, and integrity hashes.

Extract reference-data-v2.tar.gz at the repository root to use the exact measured
cache. Data licenses and attribution are in DATA-NOTICE.md and per-dataset
UPSTREAM-LICENSE.md files. Code is MIT; data retains its original terms.

Diagnostic pilots and the historical insert-only v1 pilot are separate. Do not
combine their observations with the final mixed-mutation reference matrix.

This is a single-host reference, not an independently replicated universal
ranking. All failed validity checks and interrupted attempts remain disclosed.
''')
    checksums={p.name:file_sha(p) for p in sorted(out.iterdir()) if p.is_file() and p.name!='SHA256SUMS'}
    (out/'SHA256SUMS').write_text(''.join(f'{digest}  {name}\n' for name,digest in checksums.items()))
    print(json.dumps({'directory':str(out),'files':len(checksums),'evidence_verified':verification['verified']},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path)
    p.add_argument('--out',type=Path,default=Path('artifacts/release-v2'))
    p.add_argument('--site-data',type=Path,default=Path('website/dist/data'));a=p.parse_args()
    package(a.directory,a.out,a.site_data)
