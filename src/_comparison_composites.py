"""Internal read-only compound comparison. No writer/transform permissions added."""
import copy
import math
from collections import defaultdict,Counter


def enrich(doc,row,scale,transform,point,children,stack):
    from drawing_comparison import _finite,_json
    g=row['geometry_paper_mm'];kind=row['type'];base=row['attributes'];angle=transform[0]
    if kind=='DIMENSION':
        if g['sxf_mode']!=0:raise ValueError('Dimension mode other than observed mode0 is not semantically verified')
        records=[g['line'],g['text'],*g['aux_lines'],*g['aux_points']]
        paths=['line','text',*[f'aux_lines[{i}]' for i in range(len(g['aux_lines']))],*[f'aux_points[{i}]' for i in range(len(g['aux_points']))]]
        row['children']=children(records,scale)
        for path,child in zip(paths,row['children']):child['child_path']=path
        row['active_child_paths']=['line','text']
        if any(c['status']!='supported' for c in row['children']):raise ValueError('Unsupported dimension child: '+str([(c['child_path'],c.get('reason')) for c in row['children'] if c['status']!='supported']))
        anchor=row['children'][0]['anchor']
        return [anchor],[],[],anchor,dict(sxf_mode=g['sxf_mode']),None
    if kind=='BLOCK':
        style=base['pen_style']
        if style not in (0,1,2,3,64,65,66,67) or base['pen_width']!=0 or base['flag']!=0:
            raise ValueError('Unverified block reference layer-priority attributes')
        number=g['def_number']
        if number in stack:raise ValueError('Cyclic block definition dependency')
        if len(stack)>=64:raise ValueError('Block dependency depth exceeds 64')
        definitions=[d for d in doc._source_records['block_defs'] if d['number']==number]
        if len(definitions)!=1:raise ValueError('Missing or duplicate block definition number')
        definition=definitions[0]
        # Definition coordinates are paper-mm local coordinates, independent
        # of each child's saved layer-group scale. Structure is not flattened.
        row['children']=children(definition['entities'],1.,(0.,0.,0.),(*stack,number))
        for i,child in enumerate(row['children']):child['child_path']=f'definition.entities[{i}]'
        if any(c['status']!='supported' for c in row['children']):raise ValueError('Unsupported definition child: '+str([(c['child_path'],c.get('reason')) for c in row['children'] if c['status']!='supported']))
        row['definition_storage']=copy.deepcopy(definition)
        row['definition_identity']=dict(number=number,name=definition['name'])
        pos=point(g['ref_x'],g['ref_y']);rotation=(_finite(g['rotation'],'block rotation')+math.radians(angle))%(2*math.pi)
        sx,sy=(_finite(g[k],k) for k in ('scale_x','scale_y'))
        if sx==0 or sy==0:raise ValueError('Degenerate zero block scale')
        attrs=dict(layer_priority=bool(style&64),saved_scale_x=sx,saved_scale_y=sy,
                   definition=dict(name=definition['name'],base=copy.deepcopy(definition['base'])))
        return [pos],[sx*scale,sy*scale],[(rotation,2*math.pi)],pos,attrs,None
    if kind=='SOLID':
        pts=[point(g[f'point{i}_x'],g[f'point{i}_y']) for i in (1,3,2,4)]
        # Native perimeter slot order is 1,3,2,4. Keep the raw slots in JSON.
        clean=[]
        for p in pts:
            if not clean or p!=clean[-1]:clean.append(p)
        if len(clean)>1 and clean[0]==clean[-1]:clean.pop()
        pts=min((seq[n:]+seq[:n] for seq in (clean,list(reversed(clean))) for n in range(len(clean))),key=_json)
        anchor=[sum(p[i] for p in pts)/len(pts) for i in (0,1)]
        return pts,[],[],anchor,dict(explicit_color=g['color']),None
    if kind!='CIRCLE_SOLID':raise ValueError('Unknown compound type')
    from model.circular_solid import validate_circular_solid
    validate_circular_solid(row['raw_record'])
    center=point(g['center_x'],g['center_y']);radius=_finite(g['radius'],'radius')*scale
    flat=_finite(g['flatness'],'flatness');tilt=_finite(g['tilt_angle'],'tilt')+math.radians(angle)
    a,b=max(radius,radius*flat),min(radius,radius*flat)
    orientation=0. if a==b else (tilt+(math.pi/2 if flat>1 else 0))%math.pi
    pts=[center];lengths=[a,b];angles=[(orientation,math.pi)]
    attrs=dict(explicit_color=g['color'],fill_representation='ring' if base['pen_style']==105 else g['solid_mode'])
    if base['pen_style']==105:lengths.append(g['solid_mode']*scale)
    elif g['solid_mode']==5.:
        start,sweep=g['start_angle'],g['arc_angle']
        def on(t):
            x,y=radius*math.cos(t),radius*flat*math.sin(t)
            return [center[0]+math.cos(tilt)*x-math.sin(tilt)*y,center[1]+math.sin(tilt)*x+math.cos(tilt)*y]
        pts+=sorted([on(start),on(start+sweep)])+[on(start+sweep/2)]
        angles.append((abs(sweep),0))
    return pts,lengths,angles,center,attrs,None


def semantic_key(row):
    """Canonical semantic multiset; never include archive numbers/dates/order."""
    from drawing_comparison import _json
    children=row.get('children',[])
    if row['type']=='DIMENSION':
        # mode0 auxiliary positions are unused, but their attributes matter.
        nested=[[c['child_path'],semantic_key(c) if c['child_path'] in row['active_child_paths'] else [c['type'],c['comparison_attributes'],c['content']]] for c in children]
    else:nested=sorted([semantic_key(c) for c in children],key=_json)
    return [row['type'],row['comparison_geometry'],row['comparison_attributes'],row['content'],nested]


def child_correspondence(a,b,pt,at):
    from drawing_comparison import _geometry,_signature,_json
    left,right=a.get('children',[]),b.get('children',[])
    if len(left)!=len(right):return None
    if a['type']=='DIMENSION':
        pairs=[]
        for i,(x,y) in enumerate(zip(left,right)):
            if x['child_path']!=y['child_path']:return None
            err=_geometry(x,y,pt,at) if x['child_path'] in a['active_child_paths'] else dict(unused_mode0_geometry=True)
            if err is None:return None
            pairs.append(dict(left=i,right=i,errors=err))
        return dict(child_pairs=pairs,nested_ambiguous=any(p['errors'].get('nested_ambiguous',False) for p in pairs))
    la=set(range(len(left)));rb=set(range(len(right)));pairs=[]
    # Exact children first, including duplicates as a multiset, then geometric
    # candidates. This prevents order/number changes from inventing differences.
    ga,gb=defaultdict(list),defaultdict(list)
    for i,r in enumerate(left):ga[_signature(r)].append(i)
    for j,r in enumerate(right):gb[_signature(r)].append(j)
    for key in sorted(ga.keys()&gb.keys()):
        for i,j in zip(ga[key],gb[key]):pairs.append(dict(left=i,right=j,errors=_geometry(left[i],right[j],pt,at)));la.remove(i);rb.remove(j)
    if not la:return dict(child_pairs=pairs,nested_ambiguous=False)
    edges={}
    if len(la)*len(rb)>200000:raise ValueError('Definition child candidate limit exceeded')
    for i in sorted(la):
        for j in sorted(rb):
            err=_geometry(left[i],right[j],pt,at)
            if err is not None:edges[i,j]=err
    ca=Counter(i for i,j in edges);cb=Counter(j for i,j in edges)
    if any(i not in ca for i in la) or any(j not in cb for j in rb):return None
    ambiguous=any(ca[i]!=1 for i in la) or any(cb[j]!=1 for j in rb)
    if ambiguous:return dict(child_pairs=pairs,nested_ambiguous=True)
    for (i,j),err in sorted(edges.items()):pairs.append(dict(left=i,right=j,errors=err))
    return dict(child_pairs=pairs,nested_ambiguous=any(p['errors'].get('nested_ambiguous',False) for p in pairs))


def changes(a,b,errors,size_tolerance,path=''):
    """Compound members remain children of one counted root. Keep child paths."""
    from drawing_comparison import _differences,_geometry
    attrs=_differences(a['comparison_attributes'],b['comparison_attributes'],path,size_tolerance)
    contents=[];storage=[]
    if a['content']!=b['content']:contents.append(dict(field=path+'.content',before=a['content'],after=b['content']))
    if a['type']=='BLOCK':
        storage=_differences(a['definition_storage'],b['definition_storage'],path+'.definition_storage')
    for p in (errors or {}).get('child_pairs',[]):
        i,j=p['left'],p['right'];x,y=a['children'][i],b['children'][j]
        child_path=path+'.'+x['child_path']
        ac,cc,sc=changes(x,y,p['errors'],size_tolerance,child_path)
        attrs+=ac;contents+=cc;storage+=sc
    return attrs,contents,storage


def definitions_report(left,right,pt,at,st):
    """Selected transitive definitions, independently of archive reference IDs."""
    from drawing_comparison import _json,_differences
    def collect(rows):
        found={}
        def visit(r):
            if r['status']!='supported':return
            if r['type']=='BLOCK':found.setdefault(r['definition_identity']['number'],r)
            for c in r.get('children',[]):visit(c)
        for r in rows:visit(r)
        return found
    aa,bb=collect(left),collect(right);la=set(aa);rb=set(bb);pairs=[];ambiguous=[]
    def key(r):return _json([r['comparison_attributes']['definition'],sorted([semantic_key(c) for c in r['children']],key=_json)])
    ga,gb=defaultdict(list),defaultdict(list)
    for n,r in aa.items():ga[key(r)].append(n)
    for n,r in bb.items():gb[key(r)].append(n)
    for k in sorted(ga.keys()&gb.keys()):
        for i,j in zip(sorted(ga[k]),sorted(gb[k])):pairs.append((i,j));la.remove(i);rb.remove(j)
    # A unique saved name allows reporting a changed definition; it never
    # makes changed geometry equal. Duplicate names remain explicit holds.
    names_a,names_b=defaultdict(list),defaultdict(list)
    for i in sorted(la):names_a[aa[i]['definition_identity']['name']].append(i)
    for j in sorted(rb):names_b[bb[j]['definition_identity']['name']].append(j)
    for name in sorted(names_a.keys()&names_b.keys()):
        ids,jds=names_a[name],names_b[name]
        if len(ids)==len(jds)==1:pairs.append((ids[0],jds[0]))
        else:ambiguous.append(dict(name=name,left_numbers=ids,right_numbers=jds))
        la.difference_update(ids);rb.difference_update(jds)
    rows=[]
    for i,j in sorted(pairs):
        a,b=aa[i],bb[j];err=child_correspondence(a,b,pt,at)
        is_ambiguous=bool(err and err.get('nested_ambiguous'))
        if is_ambiguous:ambiguous.append(dict(left_numbers=[i],right_numbers=[j],reason='non_unique_definition_children'))
        attrs=_differences(a['comparison_attributes']['definition'],b['comparison_attributes']['definition'],'.definition',st)
        contents=[]
        if err and not is_ambiguous:
            for p in err['child_pairs']:
                ac,cc,_=changes(a['children'][p['left']],b['children'][p['right']],p['errors'],st,'.definition.entities['+str(p['left'])+']')
                attrs+=ac;contents+=cc
        rows.append(dict(left_number=i,right_number=j,number_changed=i!=j,name_before=a['definition_identity']['name'],name_after=b['definition_identity']['name'],
                         geometry_equal=err is not None and not is_ambiguous,attribute_changes=attrs,content_changes=contents,
                         semantic_equal=err is not None and not is_ambiguous and not attrs and not contents,
                         storage_differences=_differences(a['definition_storage'],b['definition_storage']),
                         before=a['definition_storage'],after=b['definition_storage']))
    return dict(matches=rows,left_only=sorted(la),right_only=sorted(rb),ambiguous=ambiguous)
