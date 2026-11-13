"""Geometric hypotheses: radial swing, folded double edges and framed parallel rails.

No DAT templates, nominal dimension list, labels, curve-group IDs or reference
regions are used. Constants below are dimensionless feature guards, not a
substitute for the explicitly supplied metric tolerances.
"""
import math
from jwwkit._tategu_geometry import dot,sub,cross,distance,arc_point,point_segment,box


def axis(line):
    v=sub(line['b'],line['a']);length=math.hypot(*v);u=(v[0]/length,v[1]/length)
    if u[1]<0 or abs(u[1])<1e-12 and u[0]<0:u=(-u[0],-u[1])
    return u


def parallel_vectors(a,b,eps):
    length=max(math.hypot(*a),math.hypot(*b))
    return length>0 and math.atan2(abs(cross(a,b)),abs(dot(a,b)))<=math.atan(eps/length)


def project(lines,u,eps,reference_length=1.):
    v=(-u[1],u[0]);parallel=[];normal=[];diagonal=[]
    for r in lines:
        a,b=r['a'],r['b'];d=sub(b,a)
        p0,p1=dot(a,u),dot(b,u);q0,q1=dot(a,v),dot(b,v)
        item=dict(record=r,lo=min(p0,p1),hi=max(p0,p1),q=(q0+q1)/2,
                  qlo=min(q0,q1),qhi=max(q0,q1),p=(p0+p1)/2)
        reference=(u[0]*reference_length,u[1]*reference_length)
        if parallel_vectors(d,reference,eps):parallel.append(item)
        elif parallel_vectors(d,(-reference[1],reference[0]),eps):normal.append(item)
        else:diagonal.append(item)
    return parallel,normal,diagonal


def point(u,p,q):return (u[0]*p-u[1]*q,u[1]*p+u[0]*q)


def support(rows,u,lo,hi,qlo,qhi,margin,always=()):
    ids=set(always)
    for r in rows:
        if r['kind']!='LINE':continue
        values=[(dot(p,u),dot(p,(-u[1],u[0])))for p in (r['a'],r['b'])]
        if all(lo-margin<=p<=hi+margin and qlo-margin<=q<=qhi+margin for p,q in values):ids.add(r['index'])
    return sorted(ids)


def hypothesis(kind,width,endpoints,ids,evidence,*,direction=None,ambiguities=(),method):
    return dict(type_candidates=[kind],clear_width_mm=width,
        position_real_mm=[(endpoints[0][i]+endpoints[1][i])/2 for i in (0,1)],
        opening_endpoints_real_mm=[list(p)for p in endpoints],element_indices=sorted(ids),
        opening_direction=direction,evidence=evidence,ambiguities=list(ambiguities),measurement_method=method)


def swing(rows,eps,width_eps):
    arcs=[r for r in rows if r['kind']=='ARC'];lines=[r for r in rows if r['kind']=='LINE'];out=[]
    for arc in arcs:
        verified=[];fallback=[]
        h=arc['center'];radius=arc['radius']
        ends=[arc_point(arc,arc['start']),arc_point(arc,arc['start']+arc['sweep'])]
        for n,leafend in enumerate(ends):
            leaves=[r for r in lines if min(distance(r['a'],h)+distance(r['b'],leafend),distance(r['b'],h)+distance(r['a'],leafend))<=2*eps]
            if not leaves:continue
            closed=ends[1-n];u=((closed[0]-h[0])/radius,(closed[1]-h[1])/radius)
            parallel,caps,_=project(lines,u,eps,radius);origin=dot(h,u);qhinge=dot(h,(-u[1],u[0]))
            left=[c for c in caps if abs(c['p']-origin)<=width_eps and c['record']['length']<radius/2]
            right=[c for c in caps if abs(c['p']-(origin+radius))<=width_eps and c['record']['length']<radius/2]
            for a in left:
                for b in right:
                    if abs(a['qlo']-b['qlo'])>eps or abs(a['qhi']-b['qhi'])>eps:continue
                    if not a['qlo']-eps<=qhinge<=a['qhi']+eps:continue
                    measured=b['p']-a['p'];depth=a['qhi']-a['qlo']
                    if measured<=eps or depth<=eps or abs(measured-radius)>width_eps:continue
                    qcenter=(a['qlo']+a['qhi'])/2
                    endpoints=[point(u,a['p'],qcenter),point(u,b['p'],qcenter)]
                    leaf=leaves[0];leaf_u=((leafend[0]-h[0])/radius,(leafend[1]-h[1])/radius)
                    direction=dict(hinge_real_mm=list(h),closed_ray_degrees=math.degrees(math.atan2(u[1],u[0]))%360,
                        leaf_ray_degrees=math.degrees(math.atan2(leaf_u[1],leaf_u[0]))%360,
                        signed_rotation_degrees=math.degrees(math.atan2(cross(u,leaf_u),dot(u,leaf_u))),
                        handedness=None,inside_outside=None,reason='建物の内外基準がないため右勝手/内開き等へ読み替えない')
                    leafq=dot(leafend,(-u[1],u[0]));qmin=min(a['qlo'],leafq);qmax=max(a['qhi'],leafq)
                    ids=support(rows,u,a['p'],b['p'],qmin,qmax,depth+eps,
                        always=[arc['index'],leaf['index'],a['record']['index'],b['record']['index']])
                    verified.append(hypothesis('開戸',measured,endpoints,ids,
                        ['円弧の中心から端点へ伸びる扉線を確認','閉鎖側の両端に同じ見込の枠内面線を確認',
                         '幅は枠内面の投影間隔。半径/全体外形だけでは決めない'],
                        direction=direction,method='paired_jamb_faces_with_radial_swing'))
            if not verified:
                fallback.append(hypothesis('開戸',None,[h,closed],[arc['index'],leaves[0]['index']],
                    ['円弧中心と端点を結ぶ扉線は確認できる'],
                    direction=dict(hinge_real_mm=list(h),handedness=None,inside_outside=None),
                    ambiguities=['枠内面が両端で確定しないため半径を内法に読み替えない'],
                    method='radial_swing_unverified_opening'))
        # A closed-position line can also join an arc endpoint. An unverified
        # reverse interpretation adds no evidence once the two jamb faces
        # establish the opening for this same arc. Keep all verified variants.
        out.extend(verified or fallback)
    return out


def folded(rows,eps):
    lines=[r for r in rows if r['kind']=='LINE'];out=[]
    for base in lines:
        u=axis(base);length=base['length'];pa,pb=sorted((dot(base['a'],u),dot(base['b'],u)))
        parallel,normal,diagonal=project(lines,u,eps,length)
        long_diagonal=[d for d in diagonal if .1*length<=d['record']['length']<=.9*length]
        if len(long_diagonal)<4:continue
        endpoint_groups=[]
        for endpoint in (base['a'],base['b']):
            near=[d for d in long_diagonal if min(distance(endpoint,d['record']['a']),distance(endpoint,d['record']['b']))<=eps]
            if not near:break
            p=dot(endpoint,u)
            local=[d for d in long_diagonal if min(abs(d['lo']-p),abs(d['hi']-p))<=length*.25]
            doubled=False
            for i,a in enumerate(local):
                for b in local[:i]:
                    av=sub(a['record']['b'],a['record']['a']);bv=sub(b['record']['b'],b['record']['a'])
                    if parallel_vectors(av,bv,eps):
                        separation=point_segment(a['record']['a'],b['record']['a'],b['record']['b'])
                        if eps<separation<min(a['record']['length'],b['record']['length'])*.25:doubled=True
            if not doubled:break
            endpoint_groups.append(local)
        if len(endpoint_groups)!=2:continue
        if {d['record']['index']for d in endpoint_groups[0]}&{d['record']['index']for d in endpoint_groups[1]}:continue
        q=dot(base['a'],(-u[1],u[0]));diagonal_ids={d['record']['index']for part in endpoint_groups for d in part}
        local=[base]+[d['record']for part in endpoint_groups for d in part]
        bb=box(local);ids=[r['index']for r in rows if r['bbox'][0]>=bb[0]-eps and r['bbox'][1]>=bb[1]-eps and r['bbox'][2]<=bb[2]+eps and r['bbox'][3]<=bb[3]+eps]
        ids.extend(n['record']['index']for n in normal if n['record']['length']<=length*.25 and pa-eps<=n['p']<=pb+eps and n['qlo']-eps<=q<=n['qhi']+eps)
        ids=sorted(set(ids))
        # Baseline joins both folded double-edge assemblies; it is not a bounding-box dimension.
        out.append(hypothesis('折れ戸',length,[point(u,pa,q),point(u,pb,q)],ids,
            ['直線の開口基準線の両端に、斜めの二重線の組を確認','両端の折れた戸先形状と基準線の接続を確認',
             '幅は両端取付位置を結ぶ基準線長。全体外形幅ではない'],
            direction=dict(axis_degrees=math.degrees(math.atan2(u[1],u[0]))%180,
                side_of_fold='positive'if sum(d['q']-q for d in long_diagonal)>0 else 'negative',
                handedness=None,inside_outside=None),method='baseline_between_folded_leaf_assemblies'))
    return out


def framed(rows,eps):
    lines=[r for r in rows if r['kind']=='LINE'];axes=[];out=[]
    for r in sorted(lines,key=lambda x:-x['length']):
        u=axis(r)
        if not any(parallel_vectors(sub(r['b'],r['a']),(other[0]*length,other[1]*length),eps) for other,length in axes):axes.append((u,r['length']))
    for u,reference_length in axes:
        parallel,normal,_=project(lines,u,eps,reference_length);frames=[];intervals=[]
        for line in parallel:
            match=next((part for part in intervals if abs(part[0]['lo']-line['lo'])<=eps and abs(part[0]['hi']-line['hi'])<=eps),None)
            if match is None:intervals.append([line])
            else:match.append(line)
        for part in intervals:
            if len(part)<3:continue
            lo,hi=part[0]['lo'],part[0]['hi'];qlow=min(p['q']for p in part);qhigh=max(p['q']for p in part)
            if hi-lo<=eps or not eps<qhigh-qlow<(hi-lo)*.5:continue
            caps=[[n for n in normal if abs(n['p']-p)<=eps and sum(n['qlo']-eps<=line['q']<=n['qhi']+eps for line in part)>=2]for p in (lo,hi)]
            if all(caps):frames.append(dict(lo=lo,hi=hi,qlo=qlow,qhi=qhigh,source='continuous_rails_and_inner_jamb_faces',ids=[c[0]['record']['index']for c in caps]))
        # Opposed H/box jamb profiles: the facing ends of the short parallel arms
        # define the clear opening; the outside endpoints are not used as width.
        brackets=[]
        for part in intervals:
            if len(part)<2:continue
            for i,a in enumerate(part):
                for b in part[:i]:
                    qlow,qhigh=sorted((a['q'],b['q']));thick=a['hi']-a['lo'];depth=qhigh-qlow
                    if depth<=eps or thick<=eps or thick>depth*2:continue
                    crosses=[n for n in normal if a['lo']-eps<=n['p']<=a['hi']+eps and n['qlo']<=qlow+eps and n['qhi']>=qhigh-eps]
                    if crosses:brackets.append(dict(lo=a['lo'],hi=a['hi'],qlo=qlow,qhi=qhigh,ids=[a['record']['index'],b['record']['index'],crosses[0]['record']['index']]))
        for i,a in enumerate(brackets):
            if len(brackets)>128:raise ValueError('Jamb-profile hypothesis limit exceeded (128)')
            for b in brackets[:i]:
                if abs(a['qlo']-b['qlo'])>eps or abs(a['qhi']-b['qhi'])>eps:continue
                left,right=sorted((a,b),key=lambda x:x['lo']);lo,hi=left['hi'],right['lo'];depth=a['qhi']-a['qlo']
                if hi-lo<=2*depth:continue
                frames.append(dict(lo=lo,hi=hi,qlo=a['qlo'],qhi=a['qhi'],source='inward_ends_of_opposed_jamb_profiles',ids=left['ids']+right['ids']))
        for frame in frames:
            lo,hi=frame['lo'],frame['hi'];width=hi-lo;depth=frame['qhi']-frame['qlo'];qcenter=(frame['qlo']+frame['qhi'])/2
            interior=[p for p in parallel if p['lo']>=lo-depth-eps and p['hi']<=hi+depth+eps and frame['qlo']-eps<=p['q']<=frame['qhi']+eps]
            partial=[p for p in interior if .25*width<=p['hi']-p['lo']<=.9*width]
            offset_pair=[]
            for a in partial:
                for b in partial:
                    if a is b or abs(a['q']-b['q'])<=eps:continue
                    if abs(a['lo']-lo)>depth+eps or abs(b['hi']-hi)>depth+eps:continue
                    if abs(a['hi']-b['lo'])>depth+eps:continue
                    middle=(a['hi']+b['lo'])/2
                    bridges=[n for n in normal if abs(n['p']-middle)<=depth+eps and n['qlo']<=min(a['q'],b['q'])+eps and n['qhi']>=max(a['q'],b['q'])-eps]
                    if bridges:offset_pair=[a,b];break
                if offset_pair:break
            full=[p for p in interior if abs(p['lo']-lo)<=eps and abs(p['hi']-hi)<=eps]
            if offset_pair:
                kind='引き違い窓';evidence=['両端の枠内面/内向き端から開口区間を測定','異なる見込位置の左右の戸線と中央の重なり/接続を確認']
            elif len(full)>=3:
                kind='フィックス';evidence=['左右の枠内面に接する連続した平行線を3本以上確認','開口全体を連続する線があり、左右にずれた戸線の組は確認されない']
            else:continue
            ids=support(rows,u,lo,hi,frame['qlo'],frame['qhi'],2*depth+eps,always=frame['ids'])
            out.append(hypothesis(kind,width,[point(u,lo,qcenter),point(u,hi,qcenter)],ids,
                evidence+['内法は枠内側の間隔。全体外形・水切り等の出を幅に含めない'],
                direction=dict(axis_degrees=math.degrees(math.atan2(u[1],u[0]))%180,
                    motion='axis_parallel'if kind=='引き違い窓'else 'fixed',handedness=None,inside_outside=None),
                method=frame['source']))
    return out
