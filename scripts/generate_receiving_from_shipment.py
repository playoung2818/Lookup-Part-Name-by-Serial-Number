"""CLI wrapper for the same shipment generator used by the website."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from functions.receiving_shipment import generate

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('receipt', 'packing', 'serials', 'output'):
        parser.add_argument(f'--{name}', type=Path, required=True)
    parser.add_argument('--references', type=Path)
    args = parser.parse_args()
    generate(args.receipt, args.packing, args.serials, args.output, args.references)
