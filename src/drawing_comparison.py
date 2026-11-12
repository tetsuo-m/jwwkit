"""Read-only correspondence of independent, strictly readable JWW drawings.

LINE/CIRCLE/ARC/POINT/TEXT, dimensions, blocks and solids, plus saved settings.
Unsupported roots and non-unique correspondences remain explicit; this is not
the source-index edit audit and does not change its acceptance conditions.
"""
from pathlib import Path
from collections import defaultdict, Counter
import copy
import hashlib
import itertools
import json
import math
from cad_model import CadDocument

__all__ = ['compare_drawings', 'write_comparison']
_SUPPORTED = frozenset(('LINE', 'CIRCLE', 'ARC', 'POINT', 'TEXT', 'DIMENSION', 'BLOCK', 'SOLID', 'CIRCLE_SOLID'))


def _hash(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False, separators=(',', ':'))


def _finite(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(name + ' must be finite and not bool')
    return float(value)


def _scope(value):
    if value is None:
        return dict(groups=list(range(16)), layers=None)
    if not isinstance(value, dict) or set(value) - {'groups', 'layers'}:
        raise ValueError('scope accepts groups and layers only')
    groups = value.get('groups', list(range(16)))
    if not isinstance(groups, (list, tuple)) or any(type(g) is not int or not 0 <= g < 16 for g in groups) or len(set(groups)) != len(groups):
        raise ValueError('groups must be distinct integers 0..15')
    layers = value.get('layers')
    if layers is not None:
        if not isinstance(layers, (list, tuple)):
            raise ValueError('layers must be group/layer pairs')
        pairs = []
        for pair in layers:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2 or any(type(i) is not int or not 0 <= i < 16 for i in pair):
                raise ValueError('layers must contain valid group/layer pairs')
            if pair[0] not in groups:
                raise ValueError('layer group outside groups selection')
            pairs.append(tuple(pair))
        if len(set(pairs)) != len(pairs):
            raise ValueError('duplicate layer selection')
        layers = sorted(pairs)
    return dict(groups=sorted(groups), layers=layers)


def _selected(group, layer, scope):
    return group in scope['groups'] and (scope['layers'] is None or (group, layer) in scope['layers'])


def _differences(a, b, path='', size_tolerance=0):
    if isinstance(a, dict) and isinstance(b, dict):
        return [r for k in sorted(a.keys() | b.keys()) for r in _differences(a.get(k), b.get(k), path + '.' + k, size_tolerance)]
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        if len(a) != len(b):
            return [dict(field=path, before=a, after=b)]
        return [r for i, (x, y) in enumerate(zip(a, b)) for r in _differences(x, y, path + '[' + str(i) + ']', size_tolerance)]
    if a == b:
        if isinstance(a, float) and isinstance(b, float) and a == 0 and math.copysign(1, a) != math.copysign(1, b):
            return [dict(field=path, before_hex=a.hex(), after_hex=b.hex(), reason='signed_zero_representation')]
        return []
    # Explicit tolerance is restricted to text dimensions, not arbitrary numeric attributes.
    if path.split('.')[-1] in ('size_x', 'size_y', 'spacing') and type(a) in (int, float) and type(b) in (int, float) and abs(a-b) <= size_tolerance:
        return []
    return [dict(field=path, before=a, after=b)]


def _rows(doc, scope, units, transform, *, _entities=None, _scale=None, _stack=(), _budget=None):
    from model.common_entities import model_entity
    from _comparison_composites import enrich
    if _budget is None:_budget=[0]
    angle, dx, dy = transform
    co, si = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    colors, styles = {}, {}
    sx_colors = {r['code']:r for r in doc.get_sxf_colors(include_unnamed=True)}
    sx_styles = {r['code']:r for r in doc.get_sxf_linetypes(include_unnamed=True)}
    rows = []
    for index, entity in enumerate(doc.entities if _entities is None else _entities):
        base = dict(entity.attributes)
        if not _selected(base['layer_group'], base['layer'], scope):
            continue
        _budget[0]+=1
        if _budget[0]>200000:raise ValueError('Composite expansion exceeds 200000 records; narrow scope')
        g = copy.deepcopy(dict(entity.geometry)); kind = entity.entity_type
        row = dict(index=index, source_index=entity.source_index, type=kind, attributes=base,
                   geometry_paper_mm=g, raw_record=copy.deepcopy(entity.raw), status='supported')
        rows.append(row)
        if kind not in _SUPPORTED or (kind == 'TEXT' and g['content'].startswith('^@BM')):
            row.update(status='unsupported', reason='Initial comparison excludes this root type or image dependency')
            continue
        scale = _scale if _scale is not None else doc.get_group_scale(base['layer_group']) if units == 'real' else 1.0
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError('Invalid selected group scale')
        def point(x, y):
            x, y = _finite(x, 'coordinate')*scale, _finite(y, 'coordinate')*scale
            return [co*x-si*y+dx, si*x+co*y+dy]
        pts, lengths, angles = [], [], []
        attrs = copy.deepcopy(base); content = None
        if kind in ('DIMENSION','BLOCK','SOLID','CIRCLE_SOLID'):
            def children(records, child_scale, child_transform=transform, stack=_stack):
                return _rows(doc,_scope(None),units,child_transform,_entities=[model_entity(r) for r in records],
                             _scale=child_scale,_stack=stack,_budget=_budget)
            try:
                pts,lengths,angles,anchor,extra,content=enrich(doc,row,scale,transform,point,children,_stack)
            except ValueError as exc:
                row.update(status='unsupported',reason=str(exc));continue
            attrs.update(extra)
        elif kind == 'LINE':
            pts = sorted([point(g['start_x'],g['start_y']), point(g['end_x'],g['end_y'])])
            anchor = [(pts[0][i]+pts[1][i])/2 for i in (0,1)]
        elif kind in ('CIRCLE','ARC'):
            center = point(g['center_x'],g['center_y'])
            radius = _finite(g['radius'],'radius')*scale; flat = _finite(g['flatness'],'flatness')
            tilt = _finite(g['tilt_angle'],'tilt')+math.radians(angle)
            if radius < 0 or flat <= 0:
                raise ValueError('Invalid circle/ellipse geometry')
            a,b = max(radius,radius*flat),min(radius,radius*flat)
            orient = 0.0 if a == b else (tilt + (math.pi/2 if flat > 1 else 0)) % math.pi
            pts=[center];lengths=[a,b];angles=[(orient,math.pi)];anchor=center
            if kind == 'ARC':
                start = _finite(g['start_angle'],'arc start');sweep=_finite(g['arc_angle'],'arc sweep')
                if abs(sweep)>2*math.pi:
                    row.update(status='unsupported',reason='Arc with more than one full turn is unverified');continue
                def on(t):
                    x,y=radius*math.cos(t),radius*flat*math.sin(t)
                    return [center[0]+math.cos(tilt)*x-math.sin(tilt)*y,center[1]+math.sin(tilt)*x+math.cos(tilt)*y]
                pts += sorted([on(start),on(start+sweep)])+[on(start+sweep/2)]
                angles.append((abs(sweep),0))
        elif kind == 'POINT':
            pts=[point(g['x'],g['y'])];anchor=pts[0]
            attrs.update({k:g[k] for k in ('is_temporary','code','angle','scale')})
            if g['code']:attrs['angle']=(attrs['angle']+angle)%360
        else:
            pts=[point(g['start_x'],g['start_y'])];anchor=pts[0]
            angles=[((math.radians(_finite(g['angle'],'text angle')+angle))%(2*math.pi),2*math.pi)]
            content=g['content']
            attrs.update({k:g[k] for k in ('text_type','size_x','size_y','spacing','font_name')})
            preset=g['text_type']%10000
            if 1<=preset<=10:attrs['text_preset_dependency']=doc.get_text_preset(preset)
        color=base['pen_color']
        if color not in colors:
            if 0<=color<len(doc.header['palette']['pen_colors']):colors[color]=doc.header['palette']['pen_colors'][color]
            elif color in sx_colors:colors[color]=sx_colors[color]
            else:colors[color]={'unresolved_color_definition':color}
        attrs['color_dependency']=({'explicit_RGB':g['color']} if kind in ('SOLID','CIRCLE_SOLID') and color==10 else copy.deepcopy(colors[color]))
        if isinstance(attrs['color_dependency'],dict) and 'unresolved_color_definition' in attrs['color_dependency']:
            row.update(status='unsupported',reason='Selected color number has no verified definition');continue
        if kind not in ('TEXT','POINT','BLOCK','CIRCLE_SOLID') and base['pen_style']>=31:
            style=base['pen_style'];attrs['SXF_style_dependency']=copy.deepcopy(sx_styles.get(style,{'unresolved_style':style}))
            if style not in sx_styles:
                row.update(status='unsupported',reason='Selected line style number has no verified definition');continue
        elif kind not in ('TEXT','POINT','BLOCK','CIRCLE_SOLID') and not 1<=base['pen_style']<=9:
            row.update(status='unsupported',reason='Unverified standard line style number');continue
        row.update(comparison_geometry=dict(points=pts,lengths=lengths,angles=angles),anchor=anchor,
                   comparison_attributes=attrs,content=content)
    return rows


def _geometry(a,b,position_tolerance,angle_tolerance):
    if a['type']!=b['type']:return None
    x,y=a['comparison_geometry'],b['comparison_geometry']
    def distance(ps,qs):return max([math.dist(p,q) for p,q in zip(ps,qs)]+[0])
    dp=distance(x['points'],y['points'])
    if a['type']=='LINE':dp=min(dp,distance(x['points'],list(reversed(y['points']))))
    if a['type']=='ARC':dp=min(dp,distance(x['points'],[y['points'][0],y['points'][2],y['points'][1],y['points'][3]]))
    if a['type']=='SOLID':
        if len(x['points'])!=len(y['points']):return None
        ps=y['points'];dp=min(distance(x['points'],seq[n:]+seq[:n]) for seq in (ps,list(reversed(ps))) for n in range(len(ps)))
    if a['type']=='CIRCLE_SOLID' and len(x['points'])==4 and len(y['points'])==4:
        dp=min(dp,distance(x['points'],[y['points'][0],y['points'][2],y['points'][1],y['points'][3]]))
    if len(x['points'])!=len(y['points']) or len(x['lengths'])!=len(y['lengths']) or len(x['angles'])!=len(y['angles']):return None
    dl=max([abs(u-v) for u,v in zip(x['lengths'],y['lengths'])]+[0])
    da=0
    for (u,period),(v,_) in zip(x['angles'],y['angles']):
        diff=abs(u-v)
        if period:diff=min(diff%period,(-diff)%period)
        da=max(da,diff)
    if not (dp<=position_tolerance and dl<=position_tolerance and da<=angle_tolerance):return None
    result=dict(max_position_error=dp,max_length_error=dl,max_angle_error_rad=da)
    if a['type'] in ('DIMENSION','BLOCK'):
        from _comparison_composites import child_correspondence
        nested=child_correspondence(a,b,position_tolerance,angle_tolerance)
        if nested is None:return None
        result.update(nested)
    return result


def _signature(row):
    from _comparison_composites import semantic_key
    return _json(semantic_key(row))


def _components(edges):
    neighbors=defaultdict(set)
    for a,b in edges:neighbors[('A',a)].add(('B',b));neighbors[('B',b)].add(('A',a))
    seen=set()
    for root in sorted(neighbors):
        if root in seen:continue
        stack=[root];part=[];seen.add(root)
        while stack:
            node=stack.pop();part.append(node)
            for nxt in sorted(neighbors[node]):
                if nxt not in seen:seen.add(nxt);stack.append(nxt)
        yield sorted(n for side,n in part if side=='A'),sorted(n for side,n in part if side=='B')


def _coverage(a,b,tol):
    p,q=a['comparison_geometry']['points'];r,s=b['comparison_geometry']['points']
    length=math.dist(p,q)
    if not length or not math.dist(r,s):return False
    ux,uy=(q[0]-p[0])/length,(q[1]-p[1])/length
    cross=lambda t:abs((t[0]-p[0])*uy-(t[1]-p[1])*ux)
    if max(cross(r),cross(s))>tol:return False
    lo,hi=sorted(((t[0]-p[0])*ux+(t[1]-p[1])*uy for t in (r,s)))
    return min(length,hi)-max(0,lo)>0


def _coverage_result(left,right,tol,size_tolerance):
    all_rows=left+right
    longest=max(all_rows,key=lambda r:math.dist(*r['comparison_geometry']['points']))
    p,q=longest['comparison_geometry']['points'];length=math.dist(p,q)
    ux,uy=(q[0]-p[0])/length,(q[1]-p[1])/length
    def intervals(rows):
        out=[]
        for row in rows:
            points=row['comparison_geometry']['points']
            if any(abs((t[0]-p[0])*uy-(t[1]-p[1])*ux)>tol for t in points):return None
            out.append(sorted((t[0]-p[0])*ux+(t[1]-p[1])*uy for t in points))
        return sorted(out)
    a,b=intervals(left),intervals(right)
    if a is None or b is None:return dict(accepted=False,reason='pairwise collinear candidates do not share one common axis')
    def covered(src,dst):
        for lo,hi in src:
            cursor=lo
            for x,y in dst:
                if y<cursor:continue
                if x>cursor+tol:break
                cursor=max(cursor,y)
                if cursor>=hi-tol:break
            if cursor<hi-tol:return False
        return True
    ab,ba=covered(a,b),covered(b,a)
    # Union coverage alone would hide duplicated overlapping lines.
    def overlapping(intervals):
        end=-math.inf
        for lo,hi in intervals:
            if lo<end-tol:return True
            end=max(end,hi)
        return False
    # Equal total length can hide different local multiplicities. Unmatched
    # internally overlapping partitions remain conservative holds.
    multiple=overlapping(a) or overlapping(b) or abs(sum(y-x for x,y in a)-sum(y-x for x,y in b))>tol
    uniform=lambda rows:all(not _differences(rows[0]['comparison_attributes'],r['comparison_attributes'],size_tolerance=size_tolerance) for r in rows[1:])
    ok=ab and ba and not multiple and uniform(left) and uniform(right)
    return dict(accepted=ok,A_fully_covered_by_B=ab,B_fully_covered_by_A=ba,multiplicity_difference=multiple,
                attributes_uniform_A=uniform(left),attributes_uniform_B=uniform(right),
                intervals_A=a,intervals_B=b,reason=None if ok else 'partial coverage, duplicate multiplicity or non-unique/uniform destination attributes')


def _settings(a,b,sa,sb):
    rows=[]
    for group in sorted(set(sa['groups'])&set(sb['groups'])):
        fields=lambda d:dict(name=d.get_group_name(group),scale=d.get_group_scale(group),
            state=d.header['layer_groups'][group]['state'],protect=d.header['layer_groups'][group]['protect'],
            write_layer=d.header['layer_groups'][group]['write_layer'])
        rows+=_differences(fields(a),fields(b),f'groups[{group}]')
        for layer in range(16):
            if not (_selected(group,layer,sa) and _selected(group,layer,sb)):continue
            def layer_fields(d):
                r=copy.deepcopy(d.header['layer_groups'][group]['layers'][layer]);r['name']=d.get_layer_name(group,layer);return r
            rows+=_differences(layer_fields(a),layer_fields(b),f'groups[{group}].layers[{layer}]')
    return rows


def compare_drawings(left, right, *, left_scope=None, right_scope=None, units='real',
                     position_tolerance=0.0, angle_tolerance_degrees=0.0,
                     text_size_tolerance=0.0, right_transform=None,
                     line_coverage=True, max_candidate_pairs=2000000):
    """独立JWW2図面を読取り比較し、5分類・保留・群/層設定差をJSON互換辞書へ返す。

    scopes: {'groups':[0,...], 'layers':[(group,layer),...]}; omitted means all.
    position tolerance/translation use units (real mm by default); text size
    tolerance uses paper mm, angles use degrees. No implicit alignment/scaling.
    right_transform accepts rotation_degrees and translation=(x,y) only.
    Unsupported selected roots make complete=False and are never omitted.
    """
    if units not in ('real','paper'):raise ValueError('units must be real or paper')
    pt=_finite(position_tolerance,'position_tolerance');at=_finite(angle_tolerance_degrees,'angle tolerance');st=_finite(text_size_tolerance,'text size tolerance')
    if min(pt,at,st)<0 or at>180:raise ValueError('Nonnegative tolerances required; angle <=180')
    if type(line_coverage) is not bool or type(max_candidate_pairs) is not int or max_candidate_pairs<1:raise ValueError('Invalid coverage flag/candidate limit')
    if right_transform is not None and not isinstance(right_transform,dict):raise ValueError('right_transform must be a mapping or None')
    transform=dict(right_transform or {})
    if set(transform)-{'rotation_degrees','translation'}:raise ValueError('Only explicit rigid right transform is supported')
    shift=transform.get('translation',(0,0))
    if not isinstance(shift,(list,tuple)) or len(shift)!=2:raise ValueError('translation requires two coordinates')
    tr=(_finite(transform.get('rotation_degrees',0),'rotation'),_finite(shift[0],'dx'),_finite(shift[1],'dy'))
    sa,sb=_scope(left_scope),_scope(right_scope)
    paths=[Path(left).resolve(),Path(right).resolve()];hashes=[_hash(p) for p in paths]
    docs=[CadDocument.open(p) for p in paths]
    ra,rb=_rows(docs[0],sa,units,(0,0,0)),_rows(docs[1],sb,units,tr)
    aa={r['index']:r for r in ra if r['status']=='supported'};bb={r['index']:r for r in rb if r['status']=='supported'}
    remaining_a=set(aa);remaining_b=set(bb);matches=[];ambiguous=[];partial=[]
    def add(ids,jds,kind='one_to_one',geometry_errors=None):
        la=[aa[i] for i in ids];lb=[bb[j] for j in jds]
        from _comparison_composites import changes
        if len(ids)==len(jds)==1 and la[0]['type'] in ('DIMENSION','BLOCK') and geometry_errors is None:
            geometry_errors=_geometry(la[0],lb[0],pt,math.radians(at))
        attrs,content_changes,definition_storage=changes(la[0],lb[0],geometry_errors,st)
        content_changed=bool(content_changes)
        category='text_changed' if content_changed else 'attributes_changed' if attrs else 'unchanged'
        matches.append(dict(category=category,left_indices=ids,right_indices=jds,correspondence=kind,
            attribute_changes=attrs,content_before=la[0]['content'] if content_changed else None,
            content_after=lb[0]['content'] if content_changed else None,geometry_errors=geometry_errors,
            content_changes=content_changes,definition_representation_differences=definition_storage,
            representation_differences=_differences(la[0]['geometry_paper_mm'],lb[0]['geometry_paper_mm']) if len(ids)==len(jds)==1 else [],
            multiplicity_note='indices of identical duplicates are bookkeeping, not persistent identities' if kind=='duplicate_multiplicity' else None))
        remaining_a.difference_update(ids);remaining_b.difference_update(jds)
    # Exact semantic keys resolve repeated unchanged geometry before ambiguous
    # weaker geometric candidates. Signatures do not round coordinates.
    def sig(r):return _signature(r)
    ga,gb=defaultdict(list),defaultdict(list)
    for i,r in aa.items():ga[sig(r)].append(i)
    for j,r in bb.items():gb[sig(r)].append(j)
    for key in sorted(ga.keys()&gb.keys()):
        n=min(len(ga[key]),len(gb[key]))
        for i,j in zip(ga[key][:n],gb[key][:n]):add([i],[j],'duplicate_multiplicity' if max(len(ga[key]),len(gb[key]))>1 else 'one_to_one')
    buckets=defaultdict(list)
    def bucket(r):return (r['type'],*(math.floor(x/pt) for x in r['anchor'])) if pt else (r['type'],*r['anchor'])
    for j in sorted(remaining_b):buckets[bucket(bb[j])].append(j)
    edges={};examined=0
    for i in sorted(remaining_a):
        key=bucket(aa[i]);keys=[key] if not pt else [(key[0],key[1]+x,key[2]+y) for x,y in itertools.product((-1,0,1),repeat=2)]
        for k in keys:
            for j in buckets[k]:
                examined+=1
                if examined>max_candidate_pairs:raise ValueError('Candidate limit exceeded; narrow scopes or raise explicit limit')
                err=_geometry(aa[i],bb[j],pt,math.radians(at))
                if err is not None:edges[i,j]=err
    # Only forced, mutually unique correspondences; no nearest-neighbour guess.
    while edges:
        ca=Counter(i for i,j in edges);cb=Counter(j for i,j in edges)
        forced=[(i,j) for i,j in sorted(edges) if ca[i]==cb[j]==1 and not edges[i,j].get('nested_ambiguous')]
        if not forced:break
        for i,j in forced:add([i],[j],geometry_errors=edges[i,j])
        edges={k:v for k,v in edges.items() if k[0] in remaining_a and k[1] in remaining_b}
    for ids,jds in _components(edges):
        ambiguous.append(dict(reason='non_unique_geometry_or_compound_child_correspondence',left_indices=ids,right_indices=jds))
        remaining_a.difference_update(ids);remaining_b.difference_update(jds)
    if line_coverage:
        le=[i for i in sorted(remaining_a) if aa[i]['type']=='LINE'];re=[j for j in sorted(remaining_b) if bb[j]['type']=='LINE'];ce=[]
        for i in le:
            for j in re:
                examined+=1
                if examined>max_candidate_pairs:raise ValueError('Candidate limit exceeded during line coverage')
                if _coverage(aa[i],bb[j],pt):ce.append((i,j))
        for ids,jds in _components(ce):
            evidence=_coverage_result([aa[i] for i in ids],[bb[j] for j in jds],pt,st)
            if evidence['accepted']:
                add(ids,jds,'line_partition_equivalent',geometry_errors=evidence)
            else:
                partial.append(dict(left_indices=ids,right_indices=jds,evidence=evidence))
                remaining_a.difference_update(ids);remaining_b.difference_update(jds)
    deleted=sorted(remaining_a);added=sorted(remaining_b)
    unsupported=[dict(side=side,index=r['index'],type=r['type'],reason=r['reason']) for side,rs in [('left',ra),('right',rb)] for r in rs if r['status']=='unsupported']
    settings=_settings(docs[0],docs[1],sa,sb)
    if hashes!=[_hash(p) for p in paths]:raise ValueError('Input changed during comparison; discard result')
    counts=Counter(m['category'] for m in matches)
    summary={k:counts[k] for k in ('unchanged','attributes_changed','text_changed')};summary.update(added=len(added),deleted=len(deleted),ambiguous_components=len(ambiguous),partial_line_components=len(partial),unsupported_elements=len(unsupported),settings_changed_fields=len(settings),line_partition_equivalent=sum(m['correspondence']=='line_partition_equivalent' for m in matches))
    differences_a=set(deleted);differences_b=set(added)
    for m in matches:
        if m['category']!='unchanged':differences_a.update(m['left_indices']);differences_b.update(m['right_indices'])
    for part in ambiguous+partial:differences_a.update(part['left_indices']);differences_b.update(part['right_indices'])
    classified_left=Counter();classified_right=Counter()
    for match in matches:
        classified_left[match['category']]+=len(match['left_indices']);classified_right[match['category']]+=len(match['right_indices'])
    classified_left.update(deleted=len(deleted));classified_right.update(added=len(added))
    classified_left.update(unsupported=sum(r['side']=='left' for r in unsupported),ambiguous=sum(len(r['left_indices']) for r in ambiguous),partial=sum(len(r['left_indices']) for r in partial))
    classified_right.update(unsupported=sum(r['side']=='right' for r in unsupported),ambiguous=sum(len(r['right_indices']) for r in ambiguous),partial=sum(len(r['right_indices']) for r in partial))
    assert sum(classified_left.values())==len(ra) and sum(classified_right.values())==len(rb)
    from _comparison_composites import definitions_report
    definition_report=definitions_report(ra,rb,pt,math.radians(at),st)
    def outside_references(doc,rows):
        used=set()
        def visit(r):
            if r['status']=='supported' and r['type']=='BLOCK':used.add(r['definition_identity']['number'])
            for child in r.get('children',[]):visit(child)
        for row in rows:visit(row)
        return [copy.deepcopy(d) for d in doc._source_records['block_defs'] if d['number'] not in used]
    definition_report['outside_selected_references']={side:outside_references(doc,rows) for side,doc,rows in zip(('left','right'),docs,(ra,rb))}
    result=dict(schema=1,kind='independent_JWW_comparison',complete=not (unsupported or ambiguous or partial or definition_report['ambiguous']),
        inputs=[dict(side=s,path=str(p),sha256=h,version=d.version) for s,p,h,d in zip(('left','right'),paths,hashes,docs)],
        options=dict(left_scope=sa,right_scope=sb,units=units,position_tolerance=pt,angle_tolerance_degrees=at,text_size_tolerance_paper_mm=st,right_transform=dict(rotation_degrees=tr[0],translation=list(tr[1:])),line_coverage=line_coverage),
        summary=summary,element_accounting=dict(left=dict(classified_left),right=dict(classified_right),left_selected=len(ra),right_selected=len(rb)),matches=sorted(matches,key=lambda r:(r['left_indices'],r['right_indices'])),added=added,deleted=deleted,
        ambiguous=ambiguous,partial_lines=partial,unsupported=unsupported,settings_differences=settings,definitions=definition_report,
        left_entities=ra,right_entities=rb,A_difference_indices=sorted(differences_a),B_difference_indices=sorted(differences_b),
        group_scale_tables=[[dict(group=g,scale=d.get_group_scale(g)) for g in sc['groups']] for d,sc in zip(docs,(sa,sb))],
        settings_scope_unpaired_groups=sorted(set(sa['groups'])^set(sb['groups'])),
        header_observations=[dict(sha256=hashlib.sha256(d._source_bytes[:d._source_records['header_end']]).hexdigest()) for d in docs],
        limitations=['Complete refers only to selected supported scope, not byte/rendering equivalence.',
            'Images, unverified dimension modes/fill representations and unresolved/cyclic block dependencies remain unsupported.',
            'Definitions reachable from selected references are compared structurally in local paper-mm; orphan definitions are outside scope.',
            'Mode0 dimension auxiliary positions are unused storage representation; child attributes are still compared.',
            'Unknown global header settings and standard linetype/print state are not semantically decoded; header hashes only.',
            'Group/layer settings compared at common selected group/layer numbers; no inferred group mapping.',
            'No implicit flag/Unicode normalization; no original drawing changes or review JWW generation.'])
    _json(result)
    return result


def write_comparison(result, output):
    """比較結果を新規.jsonへ保存する。既存ファイル・図面への出力は拒否する。"""
    if not isinstance(result,dict) or result.get('schema')!=1 or result.get('kind')!='independent_JWW_comparison':raise ValueError('Not an independent drawing comparison result')
    path=Path(output)
    if path.suffix.lower()!='.json':raise ValueError('Comparison output must be a new .json file')
    data=json.dumps(result,ensure_ascii=True,sort_keys=True,indent=2,allow_nan=False)+'\n'
    with path.open('x',encoding='utf-8') as f:f.write(data)
    return path
