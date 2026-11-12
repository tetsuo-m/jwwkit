"""Read-only at-point and nearest search with explicit unresolved candidates."""
from collections import Counter
import math,time
from read_view import _unpack
from geometry_view import _Context,_options
from _geometry_math import finite
from _spatial_distance import distance,unknown
from _spatial_query import select

__all__=['at_point','nearest']


def _point(value):
    if not isinstance(value,(tuple,list))or len(value)!=2:raise ValueError('Point requires two coordinates')
    return [finite(v)for v in value]


def _nonnegative(value):
    value=finite(value)
    if value<0:raise ValueError('Distance tolerance must be nonnegative')
    return value


def _anchor(context,index,p):
    blob=context.view._records[index]if context.o['basis']=='current'else context.view._persisted[index]
    if blob is None:return unknown('No persisted root anchor')
    try:
        r=_unpack(blob);kind=r['type'];g=r;name='stored_anchor'
        if kind=='DIMENSION':g=r['line'];keys=('start_x','start_y');name='dimension_line_start'
        else:
            keys={'LINE':('start_x','start_y'),'TEXT':('start_x','start_y'),'CIRCLE':('center_x','center_y'),
                  'ARC':('center_x','center_y'),'CIRCLE_SOLID':('center_x','center_y'),'POINT':('x','y'),
                  'BLOCK':('ref_x','ref_y'),'SOLID':('point1_x','point1_y')}[kind]
        group=r['base']['layer_group'];scale=context.header['layer_groups'][group]['scale']if context.o['units']=='real'else 1.
        if type(group)is not int or not 0<=group<16 or finite(scale)<=0:raise ValueError('Invalid anchor group scale')
        q=[finite(g[k]*scale)for k in keys];d=finite(math.dist(q,p))
        return dict(status='exact',value=d,lower_bound=d,upper_bound=d,reason=None,parts=[],unknown_parts=False,
                    distance_kind='anchor_distance',anchor=q,anchor_kind=name)
    except (ValueError,KeyError,TypeError,OverflowError)as exc:return unknown(exc)


def _leaves(d):
    for child in d['parts']:
        if child['parts']:yield from _leaves(child)
        else:yield child


def _detail(index,d,view,threshold):
    result=dict(ref=dict(reference_schema=1,scope='view',view_id=view.view_id,element_index=index,child_path=[]),kind=view._kinds[index],
                distance={k:v for k,v in d.items()if k!='parts'})
    matched=[];unresolved=[];match_count=unknown_count=0
    for part in _leaves(d):
        item=dict(child_path=part['child_path'],kind=part['kind'],status=part['status'],value=part['value'],reason=part['reason'])
        if part['status']!='exact':
            unknown_count+=1
            if len(unresolved)<100:unresolved.append(item)
        elif threshold is not None and part['value']<=threshold:
            match_count+=1
            if len(matched)<100:matched.append(item)
    result.update(matched_parts=matched,matched_part_count=match_count,matched_parts_truncated=match_count>len(matched),
                  unresolved_parts=unresolved,unresolved_part_count=unknown_count,unresolved_parts_truncated=unknown_count>len(unresolved))
    return result


def _search(view,p,*,operation,tolerance=None,tie_tolerance=None,max_distance=None,units,query,text_mode,target,basis,limit,mode,max_seconds,limits):
    p=_point(p)
    if target not in ('shape','anchors'):raise ValueError('target must be shape or anchors')
    if type(limit)is not int or not 0<=limit<=1000 or mode not in ('details','count','summary'):raise ValueError('Invalid result limit/mode')
    if not 0<finite(max_seconds)<=300:raise ValueError('max_seconds must be in (0,300]')
    if operation=='at_point':tolerance=_nonnegative(tolerance)
    if operation=='nearest':tie_tolerance=_nonnegative(tie_tolerance)
    if max_distance is not None:max_distance=_nonnegative(max_distance)
    options=_options(view,units,basis,text_mode,['contours','text_frame'],None,limits)
    start=time.perf_counter();context=_Context(view,options)
    selection_unknown=[];query_info=None;selection_timeout=False
    try:
        remaining=max_seconds-(time.perf_counter()-start)
        if remaining<=0:raise TimeoutError('Deadline before selection')
        indices,selection_unknown,query_info=select(view,context,query,remaining)
    except TimeoutError:
        indices=[];selection_timeout=True
    computed=[];examined=0
    for index in indices:
        if time.perf_counter()-start>max_seconds:break
        d=_anchor(context,index,p)if target=='anchors'else distance(context.run(index,[]),p,text_mode)
        if target=='anchors':d['distance_kind']='anchor_distance'
        computed.append((index,d));examined+=1
    evaluation_complete=not selection_timeout and examined==len(indices)
    unexamined=None if selection_timeout else len(indices)-examined
    exact=[d['value']for _,d in computed if d['status']=='exact']
    known_min=min(exact)if exact else None
    upper_values=[d['upper_bound']for _,d in computed if d['upper_bound']is not None]
    upper=min(upper_values)if upper_values else None
    uncertainties=bool(selection_unknown)or not evaluation_complete or any(d['status']!='exact'for _,d in computed)
    lower=0. if uncertainties else upper
    minimum=dict(status='exact'if upper is not None and lower==upper else 'empty'if upper is None and not uncertainties else 'undetermined',
                 value=upper if upper is not None and lower==upper else None,lower_bound=lower,upper_bound=upper)
    nearest_threshold=finite(upper+tie_tolerance)if operation=='nearest'and upper is not None else None
    if operation=='nearest'and nearest_threshold is not None and max_distance is not None:nearest_threshold=min(nearest_threshold,max_distance)
    guaranteed_threshold=finite(lower+tie_tolerance)if operation=='nearest'and lower is not None else None
    if operation=='nearest'and guaranteed_threshold is not None and max_distance is not None:guaranteed_threshold=min(guaranteed_threshold,max_distance)
    confirmed=[];provisional=[];unresolved=[];reasons=Counter()
    for index,d in computed:
        if d['status']!='exact'or d['unknown_parts']:
            unresolved.append((index,d));reasons[d['reason']or 'Some composite part details remain undetermined']+=1
        if d['status']!='exact':continue
        if operation=='at_point':
            if d['value']<=tolerance:confirmed.append((index,d))
        elif nearest_threshold is not None and d['value']<=nearest_threshold:
            (confirmed if guaranteed_threshold is not None and d['value']<=guaranteed_threshold else provisional).append((index,d))
    for row in selection_unknown:
        unresolved.append((row['index'],unknown('Query eligibility undetermined: '+row['reason'])))
        reasons['Query eligibility undetermined: '+row['reason']]+=1
    confirmed.sort(key=lambda x:(x[1]['value'],x[0]));provisional.sort(key=lambda x:(x[1]['value'],x[0]));unresolved.sort(key=lambda x:x[0])
    complete=evaluation_complete and not unresolved
    result=dict(schema_version=1,operation=operation,view_id=view.view_id,source_sha256=view.source_sha256,model_sha256=view.model_sha256,
      point=p,units=units,basis=basis,target=target,text_mode=text_mode,tolerance=tolerance,tie_tolerance=tie_tolerance,max_distance=max_distance,
      source_root_count=view.entity_count,scope='drawing_roots',scope_count=None if selection_timeout else len(indices),query=query_info,
      query_complete=not selection_unknown and not selection_timeout,selection_unresolved_count=len(selection_unknown),
      examined_count=examined,unexamined_count=unexamined,evaluation_complete=evaluation_complete,complete=complete,
      known_min_distance=known_min,minimum_distance=minimum if operation=='nearest'else None,
      confirmed_hit_count=len(confirmed),provisional_hit_count=len(provisional),unresolved_count=len(unresolved),
      total_hit_count=len(confirmed)if complete else None,mode=mode,limit=limit,details_omitted=mode!='details',
      confirmed_hits=[],provisional_hits=[],unresolved=[],truncated=False,
      reasons=[dict(reason=k,count=n)for k,n in sorted(reasons.items(),key=lambda x:(-x[1],x[0]))],
      stop_reason=None if evaluation_complete else 'TIME_LIMIT',elapsed_seconds=time.perf_counter()-start,
      distance_scope='logical_geometry_not_printed_stroke_or_glyph_ink',continuation_implemented=False,index_used=False)
    if mode=='details':
        threshold=tolerance if operation=='at_point'else nearest_threshold
        for name,entries in (('confirmed_hits',confirmed),('provisional_hits',provisional),('unresolved',unresolved)):
            result[name]=[_detail(i,d,view,threshold)for i,d in entries[:limit]]
        result['truncated']=any(len(x)>limit for x in (confirmed,provisional,unresolved))
    result['returned_counts']={k:len(result[k])for k in ('confirmed_hits','provisional_hits','unresolved')}
    return result


def at_point(view,point,*,tolerance,units='real',query=None,text_mode='glyph',target='shape',basis='current',limit=100,mode='details',max_seconds=30.,limits=None):
    """Find all roots at geometric distance <= explicit tolerance; retain uncertainty."""
    return _search(view,point,operation='at_point',tolerance=tolerance,units=units,query=query,text_mode=text_mode,target=target,basis=basis,limit=limit,mode=mode,max_seconds=max_seconds,limits=limits)


def nearest(view,point,*,tie_tolerance,max_distance=None,units='real',query=None,text_mode='glyph',target='shape',basis='current',limit=100,mode='details',max_seconds=30.,limits=None):
    """Find every root within explicit tie tolerance of the global minimum."""
    return _search(view,point,operation='nearest',tie_tolerance=tie_tolerance,max_distance=max_distance,units=units,query=query,text_mode=text_mode,target=target,basis=basis,limit=limit,mode=mode,max_seconds=max_seconds,limits=limits)
