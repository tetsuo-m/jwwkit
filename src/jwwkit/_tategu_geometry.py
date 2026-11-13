"""Real-mm geometry primitives for read-only planar-symbol analysis."""
import math

TAU=2*math.pi


def dot(a,b):return a[0]*b[0]+a[1]*b[1]
def sub(a,b):return (a[0]-b[0],a[1]-b[1])
def cross(a,b):return a[0]*b[1]-a[1]*b[0]
def distance(a,b):return math.hypot(a[0]-b[0],a[1]-b[1])


def arc_point(r,angle):return (r['center'][0]+r['radius']*math.cos(angle),r['center'][1]+r['radius']*math.sin(angle))


def on_arc(r,point,eps):
    if abs(distance(r['center'],point)-r['radius'])>eps:return False
    if r['kind']=='CIRCLE':return True
    a=math.atan2(point[1]-r['center'][1],point[0]-r['center'][0]);s=r['start'];sweep=r['sweep']
    if sweep<0:s+=sweep;sweep=-sweep
    return (a-s)%TAU<=sweep+eps/r['radius'] or (s-a)%TAU<=eps/r['radius']


def bounds(r):
    if r['kind']=='LINE':points=[r['a'],r['b']]
    else:
        angles=[r['start'],r['start']+r['sweep']]
        angles.extend(a for a in (0,math.pi/2,math.pi,3*math.pi/2) if on_arc(r,arc_point(r,a),1e-10))
        points=[arc_point(r,a) for a in angles]
    return (min(p[0]for p in points),min(p[1]for p in points),max(p[0]for p in points),max(p[1]for p in points))


def box(rows):
    boxes=[r['bbox'] for r in rows]
    return (min(b[0]for b in boxes),min(b[1]for b in boxes),max(b[2]for b in boxes),max(b[3]for b in boxes))


def point_segment(p,a,b):
    v=sub(b,a);length2=dot(v,v)
    if not length2:return distance(p,a)
    t=max(0.,min(1.,dot(sub(p,a),v)/length2))
    return distance(p,(a[0]+t*v[0],a[1]+t*v[1]))


def contacts(a,b,eps):
    ba,bb=a['bbox'],b['bbox']
    if ba[2]+eps<bb[0]or bb[2]+eps<ba[0]or ba[3]+eps<bb[1]or bb[3]+eps<ba[1]:return False
    if a['kind']=='LINE'and b['kind']=='LINE':
        p,r=a['a'],sub(a['b'],a['a']);q,s=b['a'],sub(b['b'],b['a']);den=cross(r,s)
        if den:
            t=cross(sub(q,p),s)/den;u=cross(sub(q,p),r)/den
            if 0<=t<=1 and 0<=u<=1:return True
        return min(point_segment(a['a'],b['a'],b['b']),point_segment(a['b'],b['a'],b['b']),
                   point_segment(b['a'],a['a'],a['b']),point_segment(b['b'],a['a'],a['b']))<=eps
    if b['kind']=='LINE':a,b=b,a
    if a['kind']=='LINE':
        p=a['a'];v=sub(a['b'],p);f=sub(p,b['center']);aa=dot(v,v)
        if not aa:return on_arc(b,p,eps)
        if on_arc(b,a['a'],eps)or on_arc(b,a['b'],eps):return True
        if b['kind']=='ARC' and any(point_segment(arc_point(b,t),a['a'],a['b'])<=eps for t in (b['start'],b['start']+b['sweep'])):return True
        bb=2*dot(f,v);cc=dot(f,f)-b['radius']**2;discriminant=bb*bb-4*aa*cc
        if discriminant<0:return False
        for t in ((-bb-math.sqrt(discriminant))/(2*aa),(-bb+math.sqrt(discriminant))/(2*aa)):
            if 0<=t<=1 and on_arc(b,(p[0]+t*v[0],p[1]+t*v[1]),eps):return True
        return False
    d=distance(a['center'],b['center'])
    if d<=eps and abs(a['radius']-b['radius'])<=eps:return any(on_arc(b,arc_point(a,t),eps)for t in (a['start'],a['start']+a['sweep']))
    if d==0 or d>a['radius']+b['radius']+eps or d<abs(a['radius']-b['radius'])-eps:return False
    x=(a['radius']**2-b['radius']**2+d*d)/(2*d);h2=a['radius']**2-x*x
    if h2<0:return False
    u=((b['center'][0]-a['center'][0])/d,(b['center'][1]-a['center'][1])/d)
    for sign in (-1,1):
        point=(a['center'][0]+x*u[0]-sign*math.sqrt(h2)*u[1],a['center'][1]+x*u[1]+sign*math.sqrt(h2)*u[0])
        if on_arc(a,point,eps)and on_arc(b,point,eps):return True
    return False


def components(rows,eps,max_pairs):
    n=len(rows)
    if n*(n-1)//2>max_pairs:raise ValueError('Planar recognition contact-pair limit exceeded')
    parent=list(range(n))
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i in range(n):
        for j in range(i):
            if contacts(rows[i],rows[j],eps):parent[root(i)]=root(j)
    groups={}
    for i,r in enumerate(rows):groups.setdefault(root(i),[]).append(r)
    return list(groups.values())


def real_record(entity,index,scale,marked):
    g=entity.geometry;kind=entity.entity_type
    r=dict(index=index,kind=kind,marked=marked,curve_group=entity.attributes['group'])
    if kind=='LINE':
        r.update(a=(g['start_x']*scale,g['start_y']*scale),b=(g['end_x']*scale,g['end_y']*scale))
        if not all(math.isfinite(v)for p in (r['a'],r['b'])for v in p):raise ValueError('Nonfinite line')
        r['length']=distance(r['a'],r['b'])
        if not r['length']:raise ValueError('Zero-length line')
    else:
        if g['flatness']!=1:raise ValueError('Elliptical symbols are outside the first planar recognizer')
        r.update(center=(g['center_x']*scale,g['center_y']*scale),radius=g['radius']*scale,
            start=g['start_angle']+g['tilt_angle'],sweep=TAU if kind=='CIRCLE'else g['arc_angle'])
        if not all(math.isfinite(v)for v in (*r['center'],r['radius'],r['start'],r['sweep']))or r['radius']<=0 or not 0<abs(r['sweep'])<=TAU:
            raise ValueError('Unverified circular symbol geometry')
    r['bbox']=bounds(r)
    return r
