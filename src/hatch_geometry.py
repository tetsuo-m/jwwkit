"""Explicit rectangular hatch LINEs in paper coordinates, without association.

GUI pattern agreement: angle 45, pitch 10, spacing 1, origin (0,0), 1/2/3 lines.
Also angle 30, pitch 7, origin (0,0), single lines (fixture 021).
Angle 30, pitch 7, snapped top-left origin verified in fixture 023.
Other parameters are mathematical geometry, not verified Jw GUI semantics.
"""
import math
from line_document import Line


def rectangle_hatch_lines(bounds, *, angle_degrees=45, pitch=10, origin=(0,0),
                          lines_per_group=1, line_spacing=1, max_lines=10000,
                          **attributes):
    """Clip parallel lines to (xmin,ymin,xmax,ymax); do not add boundary.

    Normal coordinates are dot(normal,origin)+k*pitch plus symmetric offsets.
    Lines point along angle_degrees, tangent points are omitted. Default flag32.
    """
    if len(bounds)!=4 or len(origin)!=2:
        raise ValueError('Four bounds and a 2D origin required')
    values=(*bounds,*origin,angle_degrees,pitch,line_spacing)
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in values):
        raise ValueError('Finite numeric geometry required')
    xmin,ymin,xmax,ymax=bounds
    if xmin>=xmax or ymin>=ymax or pitch<=0 or line_spacing<=0:
        raise ValueError('Ordered nonempty bounds and positive spacing required')
    if type(lines_per_group) is not int or lines_per_group not in (1,2,3):
        raise ValueError('One, two or three lines per group required')
    if type(max_lines) is not int or max_lines<1:
        raise ValueError('Positive integer line limit required')
    if (lines_per_group-1)*line_spacing>=pitch:
        raise ValueError('Group width must be smaller than pitch')
    theta=math.radians(angle_degrees%360)
    d=(math.cos(theta),math.sin(theta))
    n=(-d[1],d[0])
    phase=n[0]*origin[0]+n[1]*origin[1]
    q=[n[0]*x+n[1]*y for x in (xmin,xmax) for y in (ymin,ymax)]
    if not all(math.isfinite(v) for v in (*q,phase)):
        raise ValueError('Projected coordinates overflow')
    intervals=[]
    count=0
    for i in range(lines_per_group):
        offset=(i-(lines_per_group-1)/2)*line_spacing
        lo,hi=(min(q)-phase-offset)/pitch,(max(q)-phase-offset)/pitch
        if not math.isfinite(lo) or not math.isfinite(hi):
            raise ValueError('Pattern count overflow')
        first,last=math.ceil(lo-1e-12),math.floor(hi+1e-12)
        count+=max(0,last-first+1)
        if count>max_lines:
            raise ValueError('Hatch exceeds line limit')
        intervals.append((offset,first,last))
    result=[]
    attrs=dict(attributes)
    attrs.setdefault('flag',32)
    for offset,first,last in intervals:
        for k in range(first,last+1):
            c=phase+k*pitch+offset
            base=(n[0]*c,n[1]*c)
            low,high=-math.inf,math.inf
            for b,v,a,z in zip(base,d,(xmin,ymin),(xmax,ymax)):
                if abs(v)<1e-14:
                    if b<a-1e-9 or b>z+1e-9:
                        high=-math.inf
                        break
                else:
                    t0,t1=(a-b)/v,(z-b)/v
                    low=max(low,min(t0,t1))
                    high=min(high,max(t0,t1))
            if high-low<=1e-9:
                continue
            start=tuple(min(z,max(a,b+v*low)) for b,v,a,z in zip(base,d,(xmin,ymin),(xmax,ymax)))
            end=tuple(min(z,max(a,b+v*high)) for b,v,a,z in zip(base,d,(xmin,ymin),(xmax,ymax)))
            line=Line(start,end,**attrs)
            line.record()
            result.append((c,line))
    return [line for _,line in sorted(result,key=lambda item:item[0])]
