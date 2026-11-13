"""Offline command line entry point."""
import argparse
import json

from jwwkit import guide_paths
from jwwkit._commands import (
    check_installation, compare_drawings, inspect_jwf, recognize_planar_tategu, summarize_drawing,
)


def _check(_args):
    result = check_installation.check(
        compare_command="compare",
        inspect_jwf_command="inspect-jwf",
        summarize_command="summarize",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _guide(_args):
    for path in guide_paths().values():
        print(path)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="jwwkit", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="Check the installed package with synthetic drawings").set_defaults(run=_check)
    commands.add_parser("guide", help="Print the installed AGENTS.md and usage guide paths").set_defaults(run=_guide)
    for name, module in (
        ("summarize", summarize_drawing),
        ("compare", compare_drawings),
        ("inspect-jwf", inspect_jwf),
        ("recognize-tategu", recognize_planar_tategu),
    ):
        command = commands.add_parser(name, help=module.__doc__, description=module.__doc__)
        module.add_arguments(command)
        command.set_defaults(run=module.run)
    args = parser.parse_args(argv)
    return args.run(args)
