"""Atomic grouping; only independently proven block-child flag normalization."""
import copy
import math
from dataclasses import dataclass, replace
from .editing import selection
from writer.preserved import entity_record

# E085: actual values in the six practical drawings; independently observed
# with Jw_cad's own blockization. Never generalize to unseen combinations.
BLOCK_FLAG_NORMALIZATIONS = {
    'LINE': frozenset((2, 2050, 2066, 8194, 10258, 38914, 63490, 63506)),
    'ARC': frozenset((2, 18)),
    'CIRCLE': frozenset((2, 13330)),
    'POINT': frozenset((2, 66)),
    'TEXT': frozenset((2, 2050, 16402)),
}


def block_reference_counts(document):
    """Count direct drawing references by display name, excluding definition children."""
    names={d.number:d.name_info.display_name for d in document.block_definitions}
    result={}
    for e in document.entities:
        if e.entity_type=='BLOCK':
            if e.geometry['def_number'] not in names:raise ValueError('Unresolved block reference')
            name=names[e.geometry['def_number']];result[name]=result.get(name,0)+1
    return dict(sorted(result.items()))


def number(value,label,positive=False):
    if type(value) not in (int,float) or not math.isfinite(value) or (positive and value<=0):
        raise ValueError(label+' must be finite'+(' and positive' if positive else ''))
    return float(value)


def inverse_record(original,base,rotation,sx,sy):
    r=copy.deepcopy(original);c,s=math.cos(rotation),math.sin(rotation)
    def vector(x,y):return ((c*x+s*y)/sx,(-s*x+c*y)/sy)
    def point(x,y):return vector(x-base[0],y-base[1])
    kind=r['type']
    if kind=='SOLID' and r['base']['pen_style']>=101:
        raise ValueError('Unsupported circular-solid storage style')
    flag = r['base']['flag']
    if flag & 2:
        if flag not in BLOCK_FLAG_NORMALIZATIONS.get(kind, ()):
            raise ValueError(f'Unobserved block flag combination: {kind}/{flag}')
        r['base']['flag'] = flag & ~2
    if kind=='CIRCLE_SOLID':
        from .circular_solid import transform_circular_solid
        matrix=(c/sx,s/sx,-s/sy,c/sy)
        delta=(-(c*base[0]+s*base[1])/sx,(s*base[0]-c*base[1])/sy)
        return transform_circular_solid(r,matrix,delta)
    if kind=='DIMENSION':
        for key in ('line','text'):r[key]=inverse_record(r[key],base,rotation,sx,sy)
        for key in ('aux_lines','aux_points'):r[key]=[inverse_record(x,base,rotation,sx,sy) for x in r[key]]
        return r
    pairs={'LINE':[('start_x','start_y'),('end_x','end_y')],
           'POINT':[('x','y')],'TEXT':[('start_x','start_y'),('end_x','end_y')],
           'CIRCLE':[('center_x','center_y')],'ARC':[('center_x','center_y')],
           'SOLID':[(f'point{i}_x',f'point{i}_y') for i in (1,2,3,4)]}
    if kind not in pairs:raise ValueError('Grouping unsupported entity: '+kind+'; no nested blocks')
    for x,y in pairs[kind]:r[x],r[y]=point(r[x],r[y])
    identity=rotation==0 and sx==sy==1
    if kind=='POINT' and r['code'] and not identity:raise ValueError('Marker-point transform unverified')
    if kind=='TEXT':
        if r['content'].startswith('^'):raise ValueError('Controlled/image text grouping unsupported')
        if not identity and (r['text_type']!=0 or r['base']['flag']):raise ValueError('Preset/flagged text transform unverified')
        if not identity:
            angle=math.radians(r['angle']);u=vector(math.cos(angle),math.sin(angle));v=vector(-math.sin(angle),math.cos(angle));lu,lv=math.hypot(*u),math.hypot(*v)
            if abs(u[0]*v[0]+u[1]*v[1])>1e-10*lu*lv:raise ValueError('Text transform requires unrepresentable shear')
            r['size_x']*=lu;r['spacing']*=lu;r['size_y']*=lv;r['angle']=math.degrees(math.atan2(u[1],u[0]))
    if kind in ('CIRCLE','ARC'):
        if sx==sy:r['radius']/=sx;r['tilt_angle']-=rotation
        else:
            t=r['tilt_angle'];radius=r['radius'];flat=r['flatness'];u=vector(radius*math.cos(t),radius*math.sin(t));v=vector(-radius*flat*math.sin(t),radius*flat*math.cos(t))
            xx=u[0]**2+v[0]**2;yy=u[1]**2+v[1]**2;xy=u[0]*u[1]+v[0]*v[1];tilt=.5*math.atan2(2*xy,xx-yy);q=(math.cos(tilt),math.sin(tilt));major=math.sqrt(max(0,(xx+yy+math.hypot(xx-yy,2*xy))/2))
            if major<=0:raise ValueError('Degenerate ellipse transform')
            minor=abs(u[0]*v[1]-u[1]*v[0])/major;phase=math.atan2(-(q[0]*v[0]+q[1]*v[1]),q[0]*u[0]+q[1]*u[1])
            r.update(radius=major,flatness=minor/major,tilt_angle=tilt,start_angle=r['start_angle']+phase)
    return r


def equivalent(a,b,tolerance):
    if isinstance(a,dict) and isinstance(b,dict):
        return a.keys()==b.keys() and all(a[k]==b[k] if k=='base' else equivalent(a[k],b[k],tolerance) for k in a)
    if isinstance(a,(list,tuple)) and isinstance(b,(list,tuple)):
        return len(a)==len(b) and all(equivalent(x,y,tolerance) for x,y in zip(a,b))
    if type(a) in (float,int) and type(b) in (float,int) and (type(a) is float or type(b) is float):return math.isclose(a,b,rel_tol=0,abs_tol=tolerance)
    return a==b


def match_records(wanted,existing,tolerance):
    if len(wanted)!=len(existing):return False
    remaining=list(existing)
    for record in wanted:
        at=next((i for i,x in enumerate(remaining) if equivalent(record,x,tolerance)),None)
        if at is None:return False
        remaining.pop(at)
    return True


@dataclass
class RecordChild:
    value:dict
    def record(self):return copy.deepcopy(self.value)


def replace_entities_with_block(document,indices,name,*,base_point=(0,0),rotation=0,
                                scale_x=1,scale_y=1,layer_group=None,layer=None,
                                layer_priority=True,reuse_existing=True,compound_kind=4,
                                units='paper',match_tolerance=1e-8):
    """Validate all records before commit. Angles radians; positive scales.

    Observed type/flag pairs clear bit2 in definition children only, matching
    Jw_cad's own blockization. Unobserved bit2 combinations are rejected.
    Off priority preserves stored child attributes but Jw_cad uses reference layers
    when displaying/dissolving. Unsupported nested/controlled or sheared text fails.
    """
    indices=selection(document,indices)
    if not indices:raise ValueError('At least one selected entity required')
    if type(layer_priority) is not bool or type(reuse_existing) is not bool:raise TypeError('Priority/reuse must be bool')
    angle=number(rotation,'rotation');sx=number(scale_x,'scale_x',True);sy=number(scale_y,'scale_y',True);tol=number(match_tolerance,'match_tolerance')
    if not 0<=tol<=1e-6:raise ValueError('Match tolerance must be 0..1e-6 paper mm')
    first=document.entities[min(indices)];group=first.attributes['layer_group'] if layer_group is None else layer_group;ref_layer=first.attributes['layer'] if layer is None else layer
    base=document.convert_point(base_point,layer_group=group,from_units=units,to_units='paper')
    from writer.header import group_index
    group_index(ref_layer)
    from .block_names import definition_name,block_name_info
    stored=definition_name(name,compound_kind);display=block_name_info(stored).display_name
    if not display.strip():raise ValueError('A nonempty display name is required')
    matches=[d for d in document.block_definitions if d.name_info.display_name==display]
    if len(matches)>1:raise ValueError('Display name identifies multiple definitions')
    if matches and not reuse_existing:raise ValueError('Same-name definition exists; reuse disabled')
    records=[inverse_record(entity_record(document.entities[i]),base,angle,sx,sy) for i in sorted(indices)]
    staged=replace(document,_new_block_records=copy.deepcopy(document._new_block_records))
    if matches:
        definition=matches[0]
        # compound_kind selects the suffix of a newly created definition only.
        # A reused definition retains its exact stored name/kind unchanged.
        if not match_records(records,[entity_record(e) for e in definition.entities],tol):raise ValueError('Existing definition geometry or attributes mismatch')
    else:definition=staged.add_block_definition(name,[RecordChild(x) for x in records],compound_kind=compound_kind)
    staged.place_block(definition.number,base,layer_group=group,layer=ref_layer,scale_x=sx,scale_y=sy,rotation=angle)
    staged.set_block_layer_priority(len(staged.entities)-1,layer_priority);reference=staged.entities[-1]
    staged._validate_addition(entity_record(reference));reference=replace(reference,source_index=first.source_index)
    selected=set(indices);entities=[]
    for i,e in enumerate(document.entities):
        if i==min(indices):entities.append(reference)
        if i not in selected:entities.append(e)
    from writer.preserved import validate_records
    from writer.mfc import payload_bytes
    existing=[entity_record(e) for e in definition.entities];validate_records(existing,[],'group.children',set())
    for record in existing:document._validate_addition(record)
    document.entities=tuple(entities);document.block_definitions=staged.block_definitions;document._new_block_records=staged._new_block_records
    return reference
