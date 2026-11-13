"""Write a JWW JSON summary without modifying the input or overwriting output."""
from pathlib import Path

from jwwkit import CadDocument


def add_arguments(parser):
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)


def run(args):
    if args.output.exists():
        raise FileExistsError(args.output)
    result = CadDocument.open(args.source).write_summary(args.output)
    print(f"entities={result['entity_count']}, definitions={len(result['block_definitions'])}, output={args.output}")
