"""Flatten observed JWS block graphs into one definition, before committing."""
import math
from jwwkit.model.block_operations import inverse_record
from jwwkit.model.transformations import transform_record

# E091 practical_all_flag_census.json: exact kind/value pairs from all stored
# records in the six practical originals. This is preservation permission,
# not an extension of the independent E085 bit2 normalization table.
OBSERVED_PRACTICAL_LEAF_FLAGS = {
    'CIRCLE': frozenset((0,2,16,13328,13330,63504)),
    'LINE': frozenset((0,2,16,2048,2050,2064,2066,8192,8194,10256,10258,
                       18432,34816,38912,38914,38928,51200,63488,63490,63504,63506)),
    'TEXT': frozenset((0,2,32,2048,2050,16400,16402)),
    # E092 native registered-figure all-leaf comparisons, exact additional
    # pairs only: probes 095909_50dfd0 / 100156_8ed1df / 100230_83c5a2.
    'ARC': frozenset((0,2,16,18,12544,13328,14096,17168,23824,62464)),
    'POINT': frozenset((0,2,64,66,15360)),
    'SOLID': frozenset((0,)),
    'CIRCLE_SOLID': frozenset((0,2048)),
}


def flatten(figure, target_scale):
    definitions={d['number']:d for d in figure._records['block_defs']}
    children=[]
    visits=0

    def validate_leaf_flags(record):
        allowed=OBSERVED_PRACTICAL_LEAF_FLAGS.get(record['type'],frozenset())
        if record['base']['flag'] not in allowed:
            raise ValueError('Unobserved JWS leaf flag: '+record['type']+'/'+str(record['base']['flag']))
        if record['type']=='DIMENSION':
            for child in [record['line'],record['text'],*record['aux_lines'],*record['aux_points']]:
                validate_leaf_flags(child)

    def visit(record, matrix, delta, depth=0):
        nonlocal visits
        visits+=1
        if visits>100000:raise ValueError('JWS flatten expansion exceeds 100000 visits')
        if depth>128:raise ValueError('JWS flatten depth exceeds 128')
        if len(children)>=65534:raise ValueError('Flattened JWS exceeds supported sequence count')
        if not all(math.isfinite(x) for x in (*matrix,*delta)):
            raise ValueError('Nonfinite composed JWS transform')
        if record['type']=='BLOCK':
            # Observed business references: selection bit2 and registered-figure
            # bit0x800. References disappear by flattening; leaf flags still use
            # the independent E085 normalization table without extension.
            if record['base']['flag'] not in (0,2,2048,2050):
                raise ValueError('Unobserved JWS block reference flag')
            sx,sy=record['scale_x'],record['scale_y']
            if sx==0 or sy==0:raise ValueError('Zero JWS block scale')
            co,si=math.cos(record['rotation']),math.sin(record['rotation'])
            u,v,w,z=co*sx,-si*sy,si*sx,co*sy
            a,b,c,d=matrix
            combined=(a*u+b*w,a*v+b*z,c*u+d*w,c*v+d*z)
            offset=(a*record['ref_x']+b*record['ref_y']+delta[0],
                    c*record['ref_x']+d*record['ref_y']+delta[1])
            for child in definitions[record['def_number']]['entities']:
                visit(child,combined,offset,depth+1)
        else:
            validate_leaf_flags(record)
            # Normalization of observed kind/flag pairs, with identity geometry,
            # precedes affine geometry conversion. No inherited style substitution.
            child=inverse_record(record,(0.,0.),0.,1.,1.)
            converted=transform_record(child,matrix,delta)
            # E092 native registered-figure controls normalize stored curve
            # angles into [-pi,pi]. Change the output fields, never relax the
            # full-field native comparison or alter the read-only JWS bytes.
            if converted['type'] in ('CIRCLE','ARC','CIRCLE_SOLID'):
                for key in ('start_angle','tilt_angle'):
                    converted[key]=math.atan2(math.sin(converted[key]),math.cos(converted[key]))
            children.append(converted)

    for record in figure._records['entities']:
        ratio=figure.group_scales[record['base']['layer_group']]/target_scale
        visit(record,(ratio,0.,0.,ratio),(-figure.base_point[0]*ratio,-figure.base_point[1]*ratio))
    if not children:raise ValueError('JWS has no placeable leaf elements')
    return children
