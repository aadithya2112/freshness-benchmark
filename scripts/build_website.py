#!/usr/bin/env python3
"""Build the static public website exclusively from the declared experiment."""
import argparse
from pathlib import Path
import shutil
from export_v2 import export

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('experiment',type=Path)
    p.add_argument('--out',type=Path,default=Path('website/dist'));args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    for asset in Path('web').iterdir():
        if asset.is_file():shutil.copy2(asset,args.out/asset.name)
    export(args.experiment,args.out/'data')
