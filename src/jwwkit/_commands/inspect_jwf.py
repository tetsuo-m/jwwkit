"""Local read-only JWF summary/differences; writes only a new diagnostic JSON."""
from pathlib import Path
import json
from jwwkit.jwf import JwfDocument


def add_arguments(p):
    p.add_argument('--source',required=True,type=Path);p.add_argument('--other',type=Path);p.add_argument('--drawing',type=Path)
    p.add_argument('--encoding',default='cp932');p.add_argument('--preserve-invalid',action='store_true')
    p.add_argument('--include-after-end',action='store_true',help='Compare declarations after END as documentation; never apply them')
    p.add_argument('--output',required=True,type=Path)


def run(a):
    if a.output.exists():raise FileExistsError(a.output)
    options=dict(encoding=a.encoding,errors='preserve' if a.preserve_invalid else 'strict')
    doc=JwfDocument.open(a.source,**options);report=dict(jwf=doc.summary())
    if a.other:report['jwf_difference']=doc.diff(JwfDocument.open(a.other,**options),include_inactive=a.include_after_end)
    if a.drawing:
        from jwwkit.cad_model import CadDocument
        report['drawing_comparison']=doc.compare_drawing(CadDocument.open(a.drawing))
    # Surrogate escapes are recorded, not replaced or transmitted.
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=True,indent=2);f.write('\n')
    print(json.dumps(dict(report=str(a.output),active_keys=len(report['jwf']['active_keys']),diagnostics=len(doc.diagnostics),settings_applied=False),ensure_ascii=True))
