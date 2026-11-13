"""Compatibility launcher for the installed jwwkit command."""
import sys

from jwwkit.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["recognize-tategu", *sys.argv[1:]]))
