"""Read-only planar candidates. No answer/reference input is accepted."""
import json
from pathlib import Path
from jwwkit.tategu_recognition import recognize_planar_tategu

def add_arguments(parser):
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--tolerances',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)


def run(args):
    if args.output.exists():raise FileExistsError(args.output)
    if args.output.resolve() in (args.source.resolve(),args.tolerances.resolve()):
        raise ValueError('Output conflicts with input')
    result=recognize_planar_tategu(args.source,tolerances=json.loads(args.tolerances.read_text(encoding='utf-8')))
    with args.output.open('x',encoding='utf-8')as stream:
        json.dump(result,stream,ensure_ascii=False,allow_nan=False,indent=2)
    print(json.dumps({'candidates':len(result['recognized_candidates']),'complete':result['complete']}))
    return 0 if result['complete']else 2
