"""Read-only SXF tables from the observed JWW600/700 preserved header.

Screen/print ColorRefs, raw widths and marker radii remain distinct. This
reader grants no editing permission and does not create missing definitions.
"""
import math
from .archive import Cursor, RecordError

def _rgb(value):
    return [value&255,(value>>8)&255,(value>>16)&255]

def read_sxf_tables(data, header_end):
    c=Cursor(data)
    if c.take(8)!=b'JwwData.' or c.unpack('<I')[0] not in (600,700):
        raise RecordError('SXF tables require observed JWW600/700 header')
    c.string(preserve_header_bytes=True);c.take(2532)
    for _ in range(272):c.string(preserve_header_bytes=True)
    c.take(1140)
    display=[c.unpack('<II') for _ in range(257)]
    colors=[]
    for slot in range(257):
        name=c.string(preserve_header_bytes=True)
        color,width,radius=c.unpack('<IId')
        if not math.isfinite(radius):raise RecordError('Nonfinite SXF point radius')
        colors.append(dict(slot=slot,code=100+slot,name=name,reserved=slot==0,
            display_colorref=display[slot][0],display_rgb=_rgb(display[slot][0]),
            display_width=display[slot][1],print_colorref=color,print_rgb=_rgb(color),
            print_width=width,point_radius=radius))
    patterns=[c.unpack('<IIII') for _ in range(33)]
    styles=[]
    for slot in range(33):
        name=c.string(preserve_header_bytes=True)
        count=c.unpack('<I')[0];lengths=list(c.unpack('<10d'))
        if count>10 or not all(math.isfinite(v) for v in lengths):
            raise RecordError('Unsupported SXF segment count/nonfinite pattern')
        styles.append(dict(slot=slot,code=30+slot,name=name,reserved=slot==0,
            patterns=list(patterns[slot]),segment_count=count,lengths=lengths))
    c.take(380)
    if c.pos!=header_end:raise RecordError('SXF header boundary does not match captured source')
    return colors,styles

def select_definition(rows, value):
    """Read a unique exact name/code; never invent a definition or allow edits."""
    if type(value) is int:
        found=[row for row in rows if row['code']==value]
    elif isinstance(value,str) and value:
        found=[row for row in rows if row['name']==value]
    else:raise ValueError('SXF lookup requires an integer code or nonempty exact name')
    if not found:raise ValueError('SXF definition not found: '+repr(value))
    if len(found)!=1:raise ValueError('Ambiguous SXF definition name: '+repr(value))
    return found[0]
