"""Analytic two-dimensional primitives; no drawing/GUI or external implementation."""
import math

TAU = 2 * math.pi
IDENTITY = (1., 0., 0., 1., 0., 0.)


def finite(value):
    if type(value) not in (int, float) or not math.isfinite(value): raise ValueError('Nonfinite/non-numeric geometry value')
    return value


def point(matrix, x, y):
    x, y = finite(x), finite(y); a,b,c,d,tx,ty = matrix
    return [finite(a*x+b*y+tx), finite(c*x+d*y+ty)]


def compose(parent, child):
    a,b,c,d,x,y = parent; e,f,g,h,u,v = child
    return tuple(finite(z) for z in (a*e+b*g, a*f+b*h, c*e+d*g, c*f+d*h, a*u+b*v+x, c*u+d*v+y))


def block_matrix(r):
    sx,sy,angle,x,y = [finite(r[k]) for k in ('scale_x','scale_y','rotation','ref_x','ref_y')]
    if sx == 0 or sy == 0: raise ValueError('Zero block scale has unverified geometry')
    cs,sn = math.cos(angle),math.sin(angle)
    return (sx*cs,-sy*sn,sx*sn,sy*cs,x,y), abs(sx) == abs(sy)


def bounds(points):
    for p in points:
        for v in p:finite(v)
    return [min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)]


def union(boxes):
    return [min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]


def arc_point(center, radius, angle):
    return [finite(center[0]+radius*math.cos(angle)),finite(center[1]+radius*math.sin(angle))]


def on_sweep(angle, start, sweep):
    if abs(sweep) >= TAU: return True
    delta = (angle-start) % TAU if sweep >= 0 else (start-angle) % TAU
    return delta <= abs(sweep) or abs(delta-TAU) <= 8*math.ulp(TAU)


def arc_bounds(center, radius, start, sweep):
    pts = [arc_point(center,radius,start),arc_point(center,radius,start+sweep)]
    pts.extend(arc_point(center,radius,a) for a in (0.,math.pi/2,math.pi,3*math.pi/2) if on_sweep(a,start,sweep))
    return bounds(pts)


def cross(a,b,c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def polygon(points):
    clean=[]
    for p in points:
        if not clean or p != clean[-1]: clean.append(p)
    if len(clean)>1 and clean[0]==clean[-1]: clean.pop()
    if len(clean)<3 or len(set(map(tuple,clean)))!=len(clean): raise ValueError('Degenerate solid polygon')
    for i in range(len(clean)):
        a,b=clean[i],clean[(i+1)%len(clean)]
        for j in range(i+1,len(clean)):
            if j==i+1 or i==0 and j==len(clean)-1:continue
            c,d=clean[j],clean[(j+1)%len(clean)]
            if cross(a,b,c)*cross(a,b,d)<=0 and cross(c,d,a)*cross(c,d,b)<=0:
                if max(min(a[0],b[0]),min(c[0],d[0]))<=min(max(a[0],b[0]),max(c[0],d[0])) and max(min(a[1],b[1]),min(c[1],d[1]))<=min(max(a[1],b[1]),max(c[1],d[1])):
                    raise ValueError('Self-intersecting/ambiguous solid perimeter')
    weights=[clean[i][0]*clean[(i+1)%len(clean)][1]-clean[(i+1)%len(clean)][0]*clean[i][1] for i in range(len(clean))]
    twice=finite(sum(weights))
    if twice==0:raise ValueError('Zero-area solid polygon')
    centroid=[sum((clean[i][k]+clean[(i+1)%len(clean)][k])*weights[i] for i in range(len(clean)))/(3*twice) for k in (0,1)]
    return clean,[finite(v)for v in centroid],'ccw' if twice>0 else 'cw'


def segment_distance(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1];n=dx*dx+dy*dy
    t=max(0.,min(1.,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/n)) if n else 0.
    return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)


def polygon_distance(p,vertices,boundary=False):
    distance=min(segment_distance(p,a,b) for a,b in zip(vertices,vertices[1:]+vertices[:1]))
    if boundary or distance==0:return distance
    inside=False
    for a,b in zip(vertices,vertices[1:]+vertices[:1]):
        if (a[1]>p[1])!=(b[1]>p[1]) and p[0] < a[0]+(p[1]-a[1])*(b[0]-a[0])/(b[1]-a[1]):inside=not inside
    return 0. if inside else distance
