"""Isolated stdlib-only worker. This module never opens a drawing or a network."""
import json
import re
import sys


def main():
    tasks=json.loads(sys.stdin.buffer.read())
    matches=[]
    for task in tasks:
        pattern=re.compile(task['pattern'],re.IGNORECASE if task['ignore_case'] else 0)
        matches.append([pattern.search(text) is not None for text in task['texts']])
    sys.stdout.buffer.write(json.dumps({'matches':matches},separators=(',',':')).encode('ascii'))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        sys.stderr.buffer.write((type(exc).__name__+': '+str(exc)).encode('utf-8',errors='replace'))
        raise SystemExit(1)
