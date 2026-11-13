"""Independent prescribed rigid-transform oracle. Never calls editing code."""
import math
import struct


def exact(a,b):
    if isinstance(a,dict) and isinstance(b,dict):return a.keys()==b.keys() and all(exact(v,b[k]) for k,v in a.items())
    if isinstance(a,(list,tuple)) and isinstance(b,(list,tuple)):
        return len(a)==len(b) and all(exact(v,w) for v,w in zip(a,b))
    if isinstance(a,float) and isinstance(b,float):return struct.pack('<d',a)==struct.pack('<d',b)
    return a==b


def audit_records(before,after,*,base_point_real,translation_real,rotation,group_scale,definition_mapping=None):
    """Require prescribed point transform plus exact non-geometric fields.

    Units: input records paper mm, base/translation real mm, angle radians.
    Mode0 unused members must be bitwise preserved, including signed zeros.
    """
    if len(before)!=len(after):raise ValueError('Rigid audit population differs')
    co,si=math.cos(rotation),math.sin(rotation);bx,by=(v/group_scale for v in base_point_real)
    dx,dy=(v/group_scale for v in translation_real);errors=[];points=0;max_point=0.;max_angle=0.
    mapping=definition_mapping or {}
    def fail(path,message):errors.append(dict(field=path,reason=message))
    def point(old,new,x,y,path):
        nonlocal points,max_point
        u,v=old[x]-bx,old[y]-by
        expected=(bx+co*u-si*v+dx,by+si*u+co*v+dy)
        residual=math.hypot(new[x]-expected[0],new[y]-expected[1])*group_scale
        points+=1;max_point=max(max_point,residual)
        if not math.isfinite(residual) or residual>1e-6:fail(path+x+'/'+y,'Prescribed rigid point differs')
    def angle(old,new,key,offset,period,path):
        nonlocal max_angle
        error=abs((new[key]-old[key]-offset+period/2)%period-period/2)*360/period
        max_angle=max(max_angle,error)
        if not math.isfinite(error) or error>1e-8:fail(path+key,'Prescribed angle differs')
    def node(old,new,path):
        if set(old)!=set(new) or old['type']!=new['type']:
            fail(path,'Record fields/type differ');return
        kind=old['type'];handled={'type'}
        if kind=='DIMENSION':
            node(old['line'],new['line'],path+'line.');node(old['text'],new['text'],path+'text.')
            handled|={'line','text'}
            if old['sxf_mode']!=0:raise ValueError('Only mode0 dimensions have a prescribed Task C rigid policy')
            # Rest of this node is exact, so all unused members remain opaque.
        else:
            pairs={'LINE':[('start_x','start_y'),('end_x','end_y')],
                'TEXT':[('start_x','start_y'),('end_x','end_y')], 'POINT':[('x','y')],
                'CIRCLE':[('center_x','center_y')],'ARC':[('center_x','center_y')],
                'SOLID':[(f'point{i}_x',f'point{i}_y') for i in range(1,5)],'BLOCK':[('ref_x','ref_y')]}
            if kind not in pairs:raise ValueError('Task C rigid oracle unsupported type: '+kind)
            for x,y in pairs[kind]:point(old,new,x,y,path);handled|={x,y}
            if kind=='TEXT':angle(old,new,'angle',math.degrees(rotation),360.,path);handled.add('angle')
            if kind in ('CIRCLE','ARC'):
                angle(old,new,'tilt_angle',rotation,2*math.pi,path);handled.add('tilt_angle')
            if kind=='BLOCK':
                angle(old,new,'rotation',rotation,2*math.pi,path);handled.add('rotation')
                if new['def_number']!=mapping.get(old['def_number'],old['def_number']):fail(path+'def_number','Definition mapping differs')
                handled.add('def_number')
        for key in set(old)-handled:
            if not exact(old[key],new[key]):fail(path+key,'Preserved field differs')
    for i,(old,new) in enumerate(zip(before,after)):node(old,new,f'entities[{i}].')
    return dict(passed=not errors,checked_entities=len(before),checked_points=points,
                maximum_point_error_real_mm=max_point,maximum_angle_error_degrees=max_angle,
                point_tolerance_real_mm=1e-6,angle_tolerance_degrees=1e-8,errors=errors,
                mode0_auxiliary_policy='preserve_saved_members_verbatim')
