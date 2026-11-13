"""Atomic affine transformations of representable existing records.

Attributes remain exact, including selection flags. Block-child normalization
belongs to grouping and is deliberately not applied to these operations.
"""
import copy
import math
from dataclasses import replace

from .common_entities import model_entity
from .editing import selection
from jwwkit.writer.preserved import entity_record, validate_records
from .preset_rigid import unit_rotation,validate_text,validate_dimension,has_preset


def finite(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(label+' must be finite')
    return float(value)


def pair(value, label):
    values=tuple(value)
    if len(values)!=2:raise ValueError(label+' must contain two values')
    return tuple(finite(x,label) for x in values)


def transform_record(original, matrix, delta):
    r=copy.deepcopy(original); kind=r['type']; a,b,c,d=matrix
    if kind=='SOLID' and r['base']['pen_style']>=101:
        raise ValueError('Unsupported circular-solid storage style')
    if kind=='CIRCLE_SOLID':
        from .circular_solid import transform_circular_solid
        return transform_circular_solid(original,matrix,delta)
    def vector(x,y):return (a*x+b*y,c*x+d*y)
    def point(x,y):
        vx,vy=vector(x,y);return (vx+delta[0],vy+delta[1])
    identity=matrix==(1.,0.,0.,1.)
    rigid=unit_rotation(matrix)
    if has_preset(r) and not rigid:
        raise ValueError('Preset text/dimension supports unit-scale rigid transforms only')
    if kind=='DIMENSION':
        if r['text']['text_type']!=0 and not identity:
            validate_dimension(r)
            r['line']=transform_record(r['line'],matrix,delta)
            # Embedded preset3 has its own native flag16400, not root TEXT flags.
            child=copy.deepcopy(r['text'])
            for x,y in (('start_x','start_y'),('end_x','end_y')):child[x],child[y]=point(child[x],child[y])
            if not identity:child['angle']+=math.degrees(math.atan2(c,a))
            r['text']=child
        else:
            for key in ('line','text'):r[key]=transform_record(r[key],matrix,delta)
        if r['sxf_mode']!=0:
            for key in ('aux_lines','aux_points'):
                r[key]=[transform_record(e,matrix,delta) for e in r[key]]
        return r
    pairs={'LINE':[('start_x','start_y'),('end_x','end_y')],
           'POINT':[('x','y')],'TEXT':[('start_x','start_y'),('end_x','end_y')],
           'CIRCLE':[('center_x','center_y')],'ARC':[('center_x','center_y')],
           'SOLID':[(f'point{i}_x',f'point{i}_y') for i in (1,2,3,4)],
           'BLOCK':[('ref_x','ref_y')]}
    if kind not in pairs:raise ValueError('Unsupported transformation type: '+kind)
    for x,y in pairs[kind]:r[x],r[y]=point(r[x],r[y])
    if identity:return r
    if kind=='POINT' and r['code']:
        raise ValueError('Marker point linear transformation unverified')
    if kind=='TEXT':
        if r['text_type']!=0:
            validate_text(r)
            r['angle']+=math.degrees(math.atan2(c,a))
            return r
        if r['content'].startswith('^'):raise ValueError('Controlled/image text linear transformation unverified')
        if a*d-b*c<0:raise ValueError('Mirrored glyphs cannot be represented by verified text fields')
        t=math.radians(r['angle']);u=vector(math.cos(t),math.sin(t));v=vector(-math.sin(t),math.cos(t))
        lu,lv=math.hypot(*u),math.hypot(*v)
        if abs(u[0]*v[0]+u[1]*v[1])>1e-10*lu*lv:
            raise ValueError('Text transformation requires unrepresentable shear')
        if not rigid:r['size_x']*=lu;r['spacing']*=lu;r['size_y']*=lv
        r['angle']=r['angle']+math.degrees(math.atan2(c,a)) if rigid else math.degrees(math.atan2(u[1],u[0]))
    if kind=='BLOCK':
        if rigid:
            r['rotation']+=math.atan2(c,a)
            return r
        t=r['rotation'];u=vector(math.cos(t)*r['scale_x'],math.sin(t)*r['scale_x'])
        v=vector(-math.sin(t)*r['scale_y'],math.cos(t)*r['scale_y'])
        lu,lv=math.hypot(*u),math.hypot(*v)
        if lu==0 or lv==0 or abs(u[0]*v[0]+u[1]*v[1])>1e-10*lu*lv:
            raise ValueError('Block transformation requires unrepresentable shear or zero scale')
        r.update(rotation=math.atan2(u[1],u[0]),scale_x=lu,
                 scale_y=(u[0]*v[1]-u[1]*v[0])/lu)
    if kind in ('CIRCLE','ARC'):
        if r['radius']<=0 or r['flatness']<=0:raise ValueError('Degenerate ellipse transformation')
        t=r['tilt_angle'];radius=r['radius'];flat=r['flatness']
        u=vector(radius*math.cos(t),radius*math.sin(t))
        v=vector(-radius*flat*math.sin(t),radius*flat*math.cos(t))
        col1=(a,c);col2=(b,d);length1=math.hypot(*col1);length2=math.hypot(*col2)
        conformal=abs(length1-length2)<=1e-12*max(length1,length2) and abs(a*b+c*d)<=1e-12*length1*length2
        reflected=a*d-b*c<0
        if conformal:
            r.update(radius=radius if rigid else radius*length1,
                     tilt_angle=t+math.atan2(c,a) if rigid else math.atan2(u[1],u[0]))
            if reflected:r['start_angle']=-r['start_angle']-r['arc_angle']
        else:
            xx=u[0]**2+v[0]**2;yy=u[1]**2+v[1]**2;xy=u[0]*u[1]+v[0]*v[1]
            tilt=.5*math.atan2(2*xy,xx-yy);q=(math.cos(tilt),math.sin(tilt));perp=(-q[1],q[0])
            major=math.sqrt(max(0,(xx+yy+math.hypot(xx-yy,2*xy))/2))
            if major<=0:raise ValueError('Degenerate ellipse transformation')
            minor=abs(u[0]*v[1]-u[1]*v[0])/major
            if minor<=0:raise ValueError('Degenerate ellipse transformation')
            phase=math.atan2((perp[0]*u[0]+perp[1]*u[1])/minor,
                             (q[0]*u[0]+q[1]*u[1])/major)
            start=phase-r['start_angle']-r['arc_angle'] if reflected else phase+r['start_angle']
            r.update(radius=major,flatness=minor/major,tilt_angle=tilt,start_angle=start)
        # E131 native rigid copies retain even a nonzero full-circle phase.
        # The E088 normalization remains confined to non-rigid transforms.
        if kind=='CIRCLE' and not rigid:r['start_angle']=0.0
    return r


def transform_entities(document, indices, *, base_point=(0,0), translation=(0,0),
                       rotation=0, scale_x=1, scale_y=1, units='paper', copy_entities=False):
    """Apply R(rotation) diag(scale_x,scale_y), then translation, atomically.

For real units the base and translation are converted using each selected
top-level entity's stored group scale. Angles are radians. Negative scales
reflect geometric data; mirrored TEXT is refused rather than made readable.
"""
    indices=selection(document,indices)
    if not indices:raise ValueError('At least one selected entity required')
    if type(copy_entities) is not bool:raise TypeError('copy_entities must be bool')
    base=pair(base_point,'base_point');shift=pair(translation,'translation')
    angle=finite(rotation,'rotation');sx=finite(scale_x,'scale_x');sy=finite(scale_y,'scale_y')
    if sx==0 or sy==0:raise ValueError('Scales must be nonzero')
    co,si=math.cos(angle),math.sin(angle);matrix=(co*sx,-si*sy,si*sx,co*sy)
    updated=[];records=[]
    for index in indices:
        e=document.entities[index];group=e.attributes['layer_group']
        if has_preset(entity_record(e)) and (sx!=1. or sy!=1.):
            raise ValueError('Preset text/dimension scaling or reflection is unverified')
        origin=document.convert_point(base,layer_group=group,from_units=units,to_units='paper')
        delta=document.convert_point(shift,layer_group=group,from_units=units,to_units='paper')
        a,b,c,d=matrix
        offset=(origin[0]+delta[0]-a*origin[0]-b*origin[1],
                origin[1]+delta[1]-c*origin[0]-d*origin[1])
        record=transform_record(entity_record(e),matrix,offset)
        records.append(record);model=model_entity(record)
        updated.append(model if copy_entities else replace(e,geometry=model.geometry,attributes=model.attributes))
    numbers={d.number for d in document.block_definitions}
    validate_records(records,[], 'transform',numbers)
    from jwwkit.writer.mfc import payload_bytes
    for record in records:document._validate_addition(record)
    result=list(document.entities)
    if copy_entities:result.extend(updated)
    else:
        for index,item in zip(indices,updated):result[index]=item
    document.entities=tuple(result)
    return tuple(updated)


def copy_entities(document, indices, delta=(0,0), *, units='paper'):
    return transform_entities(document,indices,translation=delta,units=units,copy_entities=True)


def rotate_entities(document, indices, angle, *, base_point=(0,0),units='paper',copy=False):
    return transform_entities(document,indices,rotation=angle,base_point=base_point,units=units,copy_entities=copy)


def scale_entities(document, indices, scale_x, scale_y=None, *, base_point=(0,0),units='paper',copy=False):
    return transform_entities(document,indices,scale_x=scale_x,scale_y=scale_x if scale_y is None else scale_y,
                              base_point=base_point,units=units,copy_entities=copy)


def reflect_entities(document, indices, *, axis_point=(0,0),axis_angle=0,units='paper',copy=False):
    # Reflection in a line at theta: R(2theta) diag(1,-1).
    return transform_entities(document,indices,base_point=axis_point,rotation=2*finite(axis_angle,'axis_angle'),
                              scale_x=1,scale_y=-1,units=units,copy_entities=copy)
