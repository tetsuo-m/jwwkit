"""Read-only independent JWW comparison; incomplete results exit with code 2."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from drawing_comparison import compare_drawings,write_comparison

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--left',required=True,type=Path);p.add_argument('--right',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--left-groups',nargs='+',type=int);p.add_argument('--right-groups',nargs='+',type=int)
    p.add_argument('--units',choices=('real','paper'),default='real')
    p.add_argument('--position-tolerance',type=float,default=0)
    p.add_argument('--angle-tolerance-degrees',type=float,default=0)
    p.add_argument('--text-size-tolerance',type=float,default=0)
    p.add_argument('--right-rotation-degrees',type=float,default=0)
    p.add_argument('--right-translation',nargs=2,type=float,default=(0,0))
    p.add_argument('--no-line-coverage',action='store_true')
    a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    if a.output.suffix.lower()!='.json':raise ValueError('Output must be a new .json')
    r=compare_drawings(a.left,a.right,left_scope={'groups':a.left_groups} if a.left_groups is not None else None,
        right_scope={'groups':a.right_groups} if a.right_groups is not None else None,units=a.units,
        position_tolerance=a.position_tolerance,angle_tolerance_degrees=a.angle_tolerance_degrees,
        text_size_tolerance=a.text_size_tolerance,right_transform=dict(rotation_degrees=a.right_rotation_degrees,translation=a.right_translation),
        line_coverage=not a.no_line_coverage)
    write_comparison(r,a.output)
    print(json.dumps(dict(complete=r['complete'],summary=r['summary']),ensure_ascii=False))
    return 0 if r['complete'] else 2

if __name__=='__main__':raise SystemExit(main())
