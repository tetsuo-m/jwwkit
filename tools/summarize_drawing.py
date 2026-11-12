"""Write a JWW JSON summary without modifying the input or overwriting output."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from cad_model import CadDocument

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    result=CadDocument.open(args.source).write_summary(args.output)
    print(f"entities={result['entity_count']}, definitions={len(result['block_definitions'])}, output={args.output}")
