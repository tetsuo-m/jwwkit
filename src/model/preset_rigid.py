"""E131 observed preset profiles: rigid transforms only, attributes untouched."""
import math

TEXT_FLAGS={2:{0,32,2048},3:{0,32},4:{0},5:{2048}}


def unit_rotation(matrix):
    a,b,c,d=matrix
    return (all(math.isfinite(v) for v in matrix) and a==d and b==-c and
            a*d-b*c>0 and abs(math.hypot(a,c)-1.)<=1e-12)


def validate_text(record):
    if record['content'].startswith('^'):
        raise ValueError('Controlled/image text rigid transformation unverified')
    if record['text_type'] not in TEXT_FLAGS or record['base']['flag'] not in TEXT_FLAGS[record['text_type']]:
        raise ValueError('Unobserved preset text type/flag for rigid transformation')


def validate_dimension(record):
    """Observed mode0/type3/8192 layout; auxiliaries remain opaque stored data."""
    if (record['text']['text_type']!=3 or record['base']['flag']!=8192 or record['sxf_mode']!=0
            or len(record['aux_lines'])!=2 or len(record['aux_points'])!=4):
        raise ValueError('Unobserved preset dimension rigid profile')
    layer=record['base']['layer'];group=record['base']['layer_group']
    def base_matches(child,style,color,width,flag):
        b=child['base']
        return (b['group']==0 and b['pen_style']==style and b['pen_color']==color and b['pen_width']==width
                and b['flag']==flag and b['layer']==layer and b['layer_group']==group)
    if not (base_matches(record,1,2,0,8192) and base_matches(record['line'],1,1,0,8192)
            and base_matches(record['text'],2,2,67,16400)):
        raise ValueError('Unobserved preset dimension attributes for rigid transformation')
    if any(not base_matches(child,1,2,0,0) for child in (*record['aux_lines'],*record['aux_points'])):
        raise ValueError('Unobserved preset dimension auxiliary attributes')
    if any(p['code']!=0 or p['is_temporary'] or p['angle']!=0 or p['scale']!=0 for p in record['aux_points']):
        raise ValueError('Unobserved preset dimension marker representation')
    if not math.isfinite(record['text']['angle']):raise ValueError('Non-finite dimension text angle')


def has_preset(record):
    return ((record['type']=='TEXT' and record['text_type']!=0) or
            (record['type']=='DIMENSION' and record['text']['text_type']!=0))
