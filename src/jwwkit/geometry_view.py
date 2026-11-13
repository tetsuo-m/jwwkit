"""Common logical geometry for immutable views; rendered glyphs remain unknown."""
from collections import Counter
import math,time
from jwwkit.read_view import ReadView,_unpack,_integer,_path,_definition_map
from jwwkit._geometry_math import IDENTITY,finite,compose,block_matrix,polygon_distance
from jwwkit._geometry_engine import Engine,FIELDS,GeometryLimit,blank,unknown,item

__all__=['entity_geometry','geometry_page','text_frame_distance']
DEFAULT_FIELDS=('bbox','contours','center','representative_points','text_frame')


def _options(view,units,basis,text_mode,fields,curve_tolerance,limits):
    if not isinstance(view,ReadView):raise TypeError('An immutable ReadView is required')
    if units not in ('real','paper')or basis not in ('current','persisted')or text_mode not in ('glyph','frame'):raise ValueError('Invalid geometry units/basis/text_mode')
    if fields is not None and not isinstance(fields,(list,tuple)):raise ValueError('fields must be a list or tuple of field names')
    fields=tuple(DEFAULT_FIELDS if fields is None else fields)
    if not fields or any(type(f)is not str or f not in FIELDS for f in fields)or len(set(fields))!=len(fields):raise ValueError('Unknown or duplicate requested geometry field')
    if curve_tolerance is not None and (finite(curve_tolerance)<=0):raise ValueError('Positive explicit curve_tolerance required')
    effective=dict(max_segments=10000,max_children=100000,max_depth=64)
    if limits is not None:
        if type(limits)is not dict or not limits.keys()<=effective.keys():raise ValueError('Unknown geometry limit')
        for key,value in limits.items():
            if type(value)is not int or not 1<=value<=effective[key]:raise ValueError('Geometry limits must be positive integers no larger than defaults')
            effective[key]=value
    return dict(units=units,basis=basis,text_mode=text_mode,fields=fields,curve_tolerance=curve_tolerance,limits=effective)


class _Context:
    def __init__(self,view,options):
        self.view=view;self.o=options
        self.header=_unpack(view._header if options['basis']=='current'else view._origin_header)
        self.definitions=_definition_map(_unpack(x)for x in (view._definitions if options['basis']=='current'else view._origin_definitions))
        self.presets=_unpack(view._text_presets)

    def run(self,index,path):
        view=self.view;o=self.o;index=_integer(index,view.entity_count,'view geometry index');path=_path(path)
        blob=view._records[index]if o['basis']=='current'else view._persisted[index]
        if blob is None:return self.unknown_result(index,path,'The current root has no persisted source record')
        root=_unpack(blob);r=root
        try:
            group=root['base']['layer_group'];_integer(group,16,'geometry root group')
            scale=finite(self.header['layer_groups'][group]['scale'])if o['units']=='real'else 1.
            if scale<=0:raise ValueError('Positive real-coordinate group scale required')
            m=(scale,0.,0.,scale,0.,0.);similar=True;pos=0;stack=[]
            while pos<len(path):
                field=path[pos]
                if r['type']=='DIMENSION'and r['sxf_mode']!=0:raise ValueError('Unverified dimension child placement')
                if r['type']=='DIMENSION'and field in ('line','text'):
                    r=r[field];pos+=1
                elif r['type']=='DIMENSION'and field in ('aux_lines','aux_points'):
                    raise ValueError('Mode0 auxiliary storage is inactive, not drawable geometry')
                elif r['type']=='BLOCK'and field=='definition':
                    if pos+1>=len(path):raise ValueError('Missing child index')
                    number=r['def_number'];_integer(number,1<<32,'definition number')
                    if number in stack or len(stack)>=o['limits']['max_depth']:raise ValueError('Cyclic/overdeep definition path')
                    if number not in self.definitions:raise ValueError('Missing definition')
                    base=r['base']
                    if base['pen_style']not in (0,1,2,3,64,65,66,67)or base['flag']!=0 or base['pen_width']!=0:raise ValueError('Unverified block placement attributes')
                    local,uniform=block_matrix(r);m=compose(m,local);similar &= uniform
                    definition=self.definitions[number];j=_integer(path[pos+1],len(definition['entities']),'child index')
                    stack.append(number);r=definition['entities'][j];pos+=2
                else:raise ValueError('Invalid geometry child_path')
            try:
                real_per_unit=finite(self.header['layer_groups'][group]['scale'])/scale
                if real_per_unit<=0:real_per_unit=None
            except (ValueError,TypeError,KeyError,OverflowError):real_per_unit=None
            engine=Engine(self.definitions,self.presets,o['fields'],o['text_mode'],o['curve_tolerance'],o['limits'],real_per_unit=real_per_unit)
            result=engine.build(r,m,similar,tuple(stack),len(stack),tuple(path))
            self.mask(result)
            result.update(schema_version=1,ref=dict(reference_schema=1,scope='view',view_id=view.view_id,element_index=index,child_path=path),
                          units=o['units'],basis=o['basis'],text_mode=o['text_mode'],fields=list(o['fields']),
                          root_selection='current_view',geometry_scope='logical_storage_not_rendered_ink_or_stroke',
                          expansion_count=engine.nodes,complete=all(result[f]['status']in ('exact','approximate','not_applicable')for f in o['fields']))
            if result['bbox']['status']=='exact':
                b=result['bbox']['value'];result['bbox_center']=[b[0]/2+b[2]/2,b[1]/2+b[3]/2]
            return result
        except (ValueError,KeyError,TypeError,OverflowError)as exc:
            return self.unknown_result(index,path,exc)

    def mask(self,result):
        for f in FIELDS:
            if f not in self.o['fields']:result[f]=item('not_requested')
        for p in result.get('parts',[]):self.mask(p)

    def unknown_result(self,index,path,reason):
        value=blank()
        for f in self.o['fields']:value[f]=unknown(reason)
        return dict(value,schema_version=1,ref=dict(reference_schema=1,scope='view',view_id=self.view.view_id,element_index=index,child_path=path),
                    kind='undetermined',parts=[],units=self.o['units'],basis=self.o['basis'],text_mode=self.o['text_mode'],
                    fields=list(self.o['fields']),complete=False,root_selection='current_view')


def entity_geometry(view,element_index,*,child_path=None,units='real',basis='current',text_mode='glyph',fields=None,curve_tolerance=None,limits=None):
    """Return analytic geometry and separate verified text frames, with per-field status."""
    options=_options(view,units,basis,text_mode,fields,curve_tolerance,limits)
    return _Context(view,options).run(element_index,[]if child_path is None else child_path)


def geometry_page(view,*,units='real',basis='current',text_mode='glyph',fields=None,curve_tolerance=None,limits=None,limit=100,mode='details',max_seconds=30.):
    """Bound detail or count/summarize all current roots. No cursor or spatial search."""
    options=_options(view,units,basis,text_mode,fields,curve_tolerance,limits)
    if type(limit)is not int or not 0<=limit<=1000 or mode not in ('details','count','summary'):raise ValueError('Invalid geometry return mode/limit')
    if not 0<finite(max_seconds)<=300:raise ValueError('max_seconds must be finite in (0,300]')
    start=time.perf_counter();total=view.entity_count
    base=dict(schema_version=1,view_id=view.view_id,source_sha256=view.source_sha256,model_sha256=view.model_sha256,
              units=units,basis=basis,text_mode=text_mode,total=total,mode=mode,limit=limit,root_selection='current_view',
              truncated=mode=='details'and total>limit,details_omitted=mode!='details',continuation_implemented=False)
    if mode=='count':return dict(base,items=[],returned=0,examined=0,geometry_evaluated=False,evaluation_complete=True,determination_complete=None)
    ctx=_Context(view,options);items=[];counts={f:Counter()for f in options['fields']};reasons=Counter();examined=0;undetermined=0
    for i in range(total if mode=='summary'else min(total,limit)):
        if time.perf_counter()-start>max_seconds:break
        result=ctx.run(i,[]);examined+=1
        undetermined+=not result['complete']
        for f in options['fields']:
            v=result[f];counts[f][v['status']]+=1
            if v['status']=='undetermined':reasons[(f,v['reason'])]+=1
        if mode=='details':items.append(result)
    expected=total if mode=='summary'else min(total,limit)
    complete=examined==expected
    summary=dict(field_counts={f:dict(c)for f,c in counts.items()},undetermined_roots=undetermined,
                 reasons=[dict(field=f,reason=r,count=n)for (f,r),n in sorted(reasons.items())])
    return dict(base,items=items,returned=len(items),examined=examined,geometry_evaluated=True,
                evaluation_complete=complete,scope_evaluated='all_roots'if mode=='summary'else 'returned_roots_only',
                determination_complete=complete and undetermined==0,summary=summary,
                stop_reason=None if complete else 'TIME_LIMIT',elapsed_seconds=time.perf_counter()-start)


def text_frame_distance(geometry,point_value,*,boundary=False):
    """Distance to a certified logical text frame in its units; never glyph distance."""
    if type(boundary)is not bool or not isinstance(point_value,(tuple,list))or len(point_value)!=2:raise ValueError('Invalid distance point/boundary')
    p=[finite(v)for v in point_value]
    if type(geometry)is not dict or geometry.get('schema_version')!=1 or geometry.get('units')not in ('real','paper'):raise ValueError('A geometry result is required')
    frame=geometry.get('text_frame',{})
    if frame.get('status')!='exact':return dict(status='undetermined',value=None,distance_kind='text_frame_distance',units=geometry['units'],reason=frame.get('reason','No exact text frame'))
    try:
        corners=frame['value']['corners']
        if len(corners)!=4 or any(len(q)!=2 for q in corners):raise ValueError('Invalid frame corners')
        corners=[[finite(v)for v in q]for q in corners]
        return dict(status='exact',value=polygon_distance(p,corners,boundary),units=geometry['units'],
                    distance_kind='text_frame_boundary_distance'if boundary else 'text_frame_distance',is_glyph_distance=False)
    except (KeyError,TypeError)as exc:raise ValueError('Invalid text frame result')from exc
