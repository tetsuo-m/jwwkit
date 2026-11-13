"""E092 observed style-101 chord/full-disk storage domain.

Field meanings: LibreCAD jwdatafmt.txt (Jw archive serialization reference).
Other styles/modes remain preservation-only; no ring/outside fill inference.
"""
import math

# E092 native placement comparison matched all 26 leaf fields.
OBSERVED_CIRCULAR_SOLID_FLAGS=frozenset((0,2048))

def validate_circular_solid(record):
    style=record['base']['pen_style']
    if style not in (101,105):raise ValueError('Unsupported circular-solid style')
    flag=record['base']['flag']
    native_sxf_flag2=style in (101,105) and record['base']['pen_color'] in (104,107,114) and flag==2
    if type(flag) is not int or flag not in OBSERVED_CIRCULAR_SOLID_FLAGS and not native_sxf_flag2:raise ValueError('Unverified circular-solid flag')
    color=record['base']['pen_color']
    if style==105:
        # E104 native-created full circular ring, plus native resave of
        # translated/rotated storage. Elliptic/partial rings stay closed.
        for key in ('center_x','center_y','radius','flatness','tilt_angle','start_angle','arc_angle','solid_mode'):
            if type(record[key]) not in (int,float) or not math.isfinite(record[key]):raise ValueError('Nonfinite circular ring '+key)
        if (type(color) is not int or color!=107 or flag not in (0,2) or record['color'] is not None
                or record['flatness']!=1. or record['start_angle']!=0. or record['arc_angle']!=2*math.pi
                or not 0<record['solid_mode']<record['radius']):
            raise ValueError('Unobserved circular ring representation')
        return
    if type(color) is not int or not (1<=color<=10 or color in (104,107,114)):raise ValueError('Unverified circular-solid pen color')
    if color>=100:
        # E104 native-created sample and unedited native resave, not a
        # blanket allowance for all named colors or fill representations.
        if flag!=0 and not native_sxf_flag2:raise ValueError('Unverified SXF circular-solid flag')
        if record['flatness']!=1.:raise ValueError('Unobserved SXF elliptic circular-solid representation')
        if color==107 and record['solid_mode']!=100.:raise ValueError('Unobserved SXF fill combination')
        if color in (104,114) and record['solid_mode']!=5.:raise ValueError('Unobserved SXF fill combination')
        if color==114 and record['arc_angle']>=0:raise ValueError('Unobserved SXF lavender positive-sweep combination')
    for key in ('center_x','center_y','radius','flatness','tilt_angle','start_angle','arc_angle','solid_mode'):
        if type(record[key]) not in (int,float) or not math.isfinite(record[key]):raise ValueError('Nonfinite circular-solid '+key)
    if record['radius']<=0 or record['flatness']<=0:raise ValueError('Degenerate circular solid')
    if record['solid_mode'] not in (5.,100.):raise ValueError('Unverified circular-solid fill mode')
    signed_observed=color==114 and record['solid_mode']==5.
    if not (0<record['arc_angle']<=2*math.pi or signed_observed and -2*math.pi<=record['arc_angle']<0):raise ValueError('Unsupported circular-solid sweep')
    if record['solid_mode']==100. and record['arc_angle']!=2*math.pi:raise ValueError('Full circular solid requires complete sweep')
    if record['solid_mode']==100. and record['start_angle']!=0.:raise ValueError('Full circular solid requires zero start angle')
    if record['base']['pen_color']==10:
        if type(record['color']) is not int or not 0<=record['color']<=0xffffff:raise ValueError('Invalid circular-solid RGB')
    elif record['color'] is not None:raise ValueError('RGB requires pen_color 10')

def transform_circular_solid(record,matrix,delta):
    validate_circular_solid(record)
    # A chord-filled ellipse maps to another chord-filled ellipse under every
    # nonsingular affine map. A full disk similarly maps to an elliptic disk.
    # Reuse the independently tested ellipse parameter conversion; preserve all
    # fill/style fields and restrict full disks to a complete perimeter.
    from .transformations import transform_record
    import copy
    if record['base']['pen_style']==105:
        a,b,c,d=matrix;first=math.hypot(a,c);second=math.hypot(b,d)
        if first<=0 or abs(first-second)>1e-12*max(first,second) or abs(a*b+c*d)>1e-12*first*second:
            raise ValueError('Elliptic/sheared circular ring transformation unverified')
        circle=copy.deepcopy(record);circle['type']='CIRCLE';circle['is_full_circle']=True
        transformed=transform_record(circle,matrix,delta)
        transformed['type']='CIRCLE_SOLID';transformed.pop('is_full_circle')
        transformed['solid_mode']=record['solid_mode']*first
        validate_circular_solid(transformed)
        return transformed
    arc=copy.deepcopy(record);arc['type']='ARC';arc['is_full_circle']=False
    transformed=transform_record(arc,matrix,delta)
    transformed['type']='CIRCLE_SOLID';transformed.pop('is_full_circle')
    if record['solid_mode']==100.:transformed['start_angle']=0.
    validate_circular_solid(transformed)
    return transformed
