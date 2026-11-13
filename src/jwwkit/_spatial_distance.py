"""Analytic distances to qualified U2 logical geometry. Never infer missing shapes."""
import math
from jwwkit._geometry_math import finite,arc_point,on_sweep,cross


def segment(p,a,b):
    dx,dy=finite(b[0]-a[0]),finite(b[1]-a[1]);length=finite(math.hypot(dx,dy))
    if length==0:return finite(math.dist(p,a))
    ux,uy=dx/length,dy/length
    along=finite(finite(p[0]-a[0])*ux+finite(p[1]-a[1])*uy)
    if along<=0:return finite(math.dist(p,a))
    if along>=length:return finite(math.dist(p,b))
    return finite(abs(finite(p[0]-a[0])*uy-finite(p[1]-a[1])*ux))


def polygon(p,vertices):
    edges=list(zip(vertices,vertices[1:]+vertices[:1]))
    d=min(segment(p,a,b)for a,b in edges)
    if d==0:return 0.
    inside=False
    for a,b in edges:
        if (a[1]>p[1])!=(b[1]>p[1]):
            x=finite(a[0]+finite(p[1]-a[1])*finite(b[0]-a[0])/finite(b[1]-a[1]))
            if p[0]<x:inside=not inside
    return 0. if inside else d


def arc(p,c):
    center=c['center'];radius=c['radius'];rho=finite(math.dist(p,center))
    if c['kind']=='circle' or rho==0:return abs(rho-radius)
    angle=math.atan2(p[1]-center[1],p[0]-center[0])
    if on_sweep(angle,c['start_angle'],c['sweep_angle']):return abs(rho-radius)
    return min(finite(math.dist(p,arc_point(center,radius,t)))for t in (c['start_angle'],c['start_angle']+c['sweep_angle']))


def contour(p,c):
    if c['kind']=='point':return finite(math.dist(p,c['point']))
    if c['kind']in ('circle','arc'):return finite(arc(p,c))
    if c['kind']=='polyline':
        points=c['points']
        if c.get('filled')or c.get('role')=='text_frame':return polygon(p,points)
        pairs=list(zip(points,points[1:]))
        if c.get('closed'):pairs.append((points[-1],points[0]))
        if not pairs:raise ValueError('Empty contour')
        return min(segment(p,a,b)for a,b in pairs)
    raise ValueError('Unverified distance contour')


def solid_circle(p,contours):
    outer=contours[0];rho=finite(math.dist(p,outer['center']));radius=outer['radius']
    if len(contours)==2 and contours[1].get('role')=='hole':
        inner=contours[1]['radius']
        return inner-rho if rho<inner else rho-radius if rho>radius else 0.
    if outer['kind']=='circle':return max(0.,rho-radius)
    if len(contours)!=2 or contours[1].get('role')!='chord':raise ValueError('Unverified circular fill boundary')
    a,b=contours[1]['points'];middle=arc_point(outer['center'],radius,outer['start_angle']+outer['sweep_angle']/2)
    side=finite(cross(a,b,middle));query_side=finite(cross(a,b,p))
    if side==0:raise ValueError('Circular segment side is numerically indeterminate')
    if rho<=radius and (query_side==0 or (side>0)==(query_side>0)):return 0.
    return min(arc(p,outer),segment(p,a,b))


def unknown(reason,*,upper=None,parts=None):
    return dict(status='undetermined',value=None,lower_bound=0.,upper_bound=upper,reason=str(reason),
                parts=[]if parts is None else parts,unknown_parts=True,distance_kind='shape_distance')


def distance(g,p,text_mode='glyph'):
    """A composite is a union. Known parts provide an upper bound only."""
    parts=g.get('parts',[])
    if parts:
        values=[dict(distance(child,p,text_mode),child_path=child['child_path'],kind=child['kind'])for child in parts]
        exact=[x['value']for x in values if x['status']=='exact']
        unresolved=any(x['status']!='exact' or x['unknown_parts']for x in values)
        bounds=[x['upper_bound']for x in values if x['upper_bound']is not None]
        upper=min(bounds)if bounds else None
        if unresolved and upper!=0:return unknown('A child distance is undetermined; known parts give only an upper bound',upper=upper,parts=values)
        if not exact and upper!=0:return unknown('No exact child distance',parts=values)
        value=0. if upper==0 else min(exact)
        return dict(status='exact',value=value,lower_bound=value,upper_bound=value,reason=None,parts=values,
                    unknown_parts=unresolved,distance_kind='composite_shape_and_text_frame_distance'if text_mode=='frame'else 'composite_shape_distance')
    try:
        field=g['contours']
        if field['status']!='exact':
            result=unknown(field.get('reason','No exact contour'))
            if g['kind']=='text'and text_mode=='frame':result['distance_kind']='text_frame_distance'
            return result
        contours=field['value']
        if not contours:raise ValueError('No distance contour')
        value=solid_circle(p,contours)if g['kind']=='circle_solid'else min(contour(p,c)for c in contours)
        value=finite(value)
        if value<0:raise ValueError('Negative geometric distance')
        kind='text_frame_distance'if g['kind']=='text'and text_mode=='frame'else 'shape_distance'
        return dict(status='exact',value=value,lower_bound=value,upper_bound=value,reason=None,parts=[],unknown_parts=False,distance_kind=kind)
    except (ValueError,KeyError,TypeError,OverflowError)as exc:return unknown(exc)
