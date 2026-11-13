"""Shared definition and storage checks, before any public mutation commits."""
import copy
from functools import lru_cache
from jwwkit.reader.sxf import read_sxf_tables
from jwwkit.writer.preserved import validate_records,serialize_body
from jwwkit.reader.archive import Cursor,read_entity_sequences

@lru_cache(maxsize=32)
def _tables(header):
    colors,styles=read_sxf_tables(header,len(header))
    return tuple((r['code'],r['name']) for r in colors if r['name'] and not r['reserved']),tuple((r['code'],r['name']) for r in styles if r['name'] and not r['reserved'])

def _header(document):
    if hasattr(document,'_source_records'):
        return document._source_bytes[:document._source_records['header_end']]
    return document._header

def _code(value,table,standard,label):
    if isinstance(value,str):
        found=[code for code,name in table if name==value and value]
        if len(found)!=1:raise ValueError(label+' SXF name is missing or ambiguous: '+repr(value))
        return found[0]
    if type(value) is not int:raise ValueError(label+' must be an integer or exact SXF name')
    if value not in standard and value not in {code for code,_ in table}:
        raise ValueError(label+' is not defined in this drawing: '+str(value))
    return value

def color_code(document,value,*,rgb=False):
    colors,_=_tables(_header(document))
    # Standard palette has ten stored slots (0..9); color10 is a SOLID
    # payload discriminator, not an extra palette definition.
    return _code(value,colors,range(11 if rgb else 10),'Color')

def linetype_code(document,value):
    _,styles=_tables(_header(document))
    return _code(value,styles,range(1,10),'Linetype')

def attributes(document,values,kind):
    result=copy.deepcopy(values)
    for key,maximum in (('width',65535),('layer',15),('layer_group',15),('group',0xffffffff),('flag',65535)):
        if key in result and (type(result[key]) is not int or not 0<=result[key]<=maximum):
            raise ValueError('Invalid stored attribute: '+key)
    if 'color' in result:result['color']=color_code(document,result['color'],rgb=kind in ('SOLID','CIRCLE_SOLID'))
    if 'linetype' in result and kind in ('LINE','CIRCLE','ARC','SOLID','DIMENSION'):
        result['linetype']=linetype_code(document,result['linetype'])
    return result

def normalize_record(document,record,*,dimension_member=False):
    """Canonicalize only explicit color/style names in a private candidate."""
    r=copy.deepcopy(record);kind=r['type'];base=r['base']
    base['pen_color']=color_code(document,base['pen_color'],rgb=kind in ('SOLID','CIRCLE_SOLID'))
    if kind in ('LINE','CIRCLE','ARC','SOLID','DIMENSION'):
        # Zero-filled DIMENSION auxiliary LINEs are structural placeholders.
        placeholder=dimension_member and kind=='LINE' and base['pen_style']==0 and r['start_x']==r['end_x'] and r['start_y']==r['end_y']
        if not placeholder:base['pen_style']=linetype_code(document,base['pen_style'])
    if kind=='DIMENSION':
        for key in ('line','text'):r[key]=normalize_record(document,r[key],dimension_member=True)
        for key in ('aux_lines','aux_points'):r[key]=[normalize_record(document,x,dimension_member=True) for x in r[key]]
    if kind=='BLOCK_DEF':r['entities']=[normalize_record(document,x) for x in r['entities']]
    return r

def check(document,record,*,defined_numbers=None,version=None,encoding=None):
    """Check all integer slots and payload encoding without changing a record."""
    canonical=normalize_record(document,record)
    if canonical!=record:raise ValueError('Resolve color/linetype names before committing the record')
    def slots(r,dimension_member=False):
        b=r['base']
        if r['type']=='SOLID':
            from .solid import Solid
            rgb=r.get('color')
            if rgb is not None:
                if type(rgb) is not int or not 0<=rgb<=0xffffff:raise ValueError('Invalid solid RGB')
                rgb=(rgb&255,(rgb>>8)&255,(rgb>>16)&255)
            Solid(tuple((r[f'point{i}_x'],r[f'point{i}_y']) for i in range(1,5)),
                  rgb=rgb,color=b['pen_color'],linetype=b['pen_style'],flag=b['flag'],
                  layer=b['layer'],layer_group=b['layer_group']).record()
        for key,maximum in (('group',0xffffffff),('pen_style',255),('pen_color',65535),('pen_width',65535),('layer',15),('layer_group',15),('flag',65535)):
            if type(b[key]) is not int or not 0<=b[key]<=maximum:raise ValueError('Invalid stored attribute: '+key)
        if r['type']=='POINT':
            if type(r['code']) is not int or not 0<=r['code']<=0xffffffff:raise ValueError('Marker code must be uint32')
            if type(r['is_temporary']) is not bool:raise ValueError('Point temporary flag must be bool')
            if b['pen_style']!=(100 if r['code'] else 1):raise ValueError('Point style is a marker discriminator, not a linetype')
            if not r['code'] and (r['angle']!=0 or r['scale']!=0):raise ValueError('Ordinary points have no stored marker angle/scale')
        if r['type'] in ('CIRCLE','ARC') and type(r['is_full_circle']) is not bool:raise ValueError('Circle full flag must be bool')
        for key in (('text_type',) if r['type']=='TEXT' else ('def_number',) if r['type']=='BLOCK' else ('number','timestamp') if r['type']=='BLOCK_DEF' else ()):
            if type(r[key]) is not int or not 0<=r[key]<=0xffffffff:raise ValueError(key+' must be uint32')
        if r['type']=='BLOCK' and b['pen_style'] not in (0,1,2,3,64,65,66,67):raise ValueError('Unverified block reference style')
        if r['type']=='DIMENSION':
            for x in [r['line'],r['text'],*r['aux_lines'],*r['aux_points']]:slots(x,True)
        if r['type']=='BLOCK_DEF':
            for x in r['entities']:slots(x)
    slots(record)
    numbers=defined_numbers if defined_numbers is not None else {d.number for d in getattr(document,'block_definitions',())}
    if record['type']=='BLOCK_DEF':
        validate_records(record['entities'],[],'candidate.children',numbers)
    else:validate_records([record],[],'candidate',numbers)
    if version is None:version=document.version if hasattr(document,'version') else 700
    if encoding is None:encoding=document._source_records['body_encoding'] if hasattr(document,'_source_records') else 'utf-16le'
    entities,definitions=([],[record]) if record['type']=='BLOCK_DEF' else ([record],[])
    body=serialize_body(entities,definitions,version,encoding=encoding)
    c=Cursor(body);parsed_entities,parsed_definitions,_=read_entity_sequences(c,version)
    if parsed_entities!=entities or parsed_definitions!=definitions or c.pos!=len(body)-(4 if version==700 else 0):
        raise ValueError('Candidate cannot roundtrip without losing stored fields')

def normalize_model(document,model):
    """Independent mutable template model; caller-owned objects are untouched."""
    result=copy.deepcopy(model)
    from .solid import Solid
    if isinstance(result,Solid):
        result.color=color_code(document,result.color,rgb=True)
        result.linetype=linetype_code(document,result.linetype if result.linetype is not None else (31 if result.color>=100 else 1))
    record=result.record();kind=record['type']
    if hasattr(result,'color'):result.color=color_code(document,result.color,rgb=kind in ('SOLID','CIRCLE_SOLID'))
    if hasattr(result,'linetype') and kind in ('LINE','CIRCLE','ARC','SOLID','DIMENSION'):
        result.linetype=linetype_code(document,result.linetype)
    if kind=='DIMENSION':
        for key in ('line','text'):setattr(result,key,normalize_model(document,getattr(result,key)))
        for key in ('aux_lines','aux_points'):setattr(result,key,[normalize_model(document,x) for x in getattr(result,key)])
    check(document,result.record())
    return result
