"""Local, noninteractive plan/verify/execute helpers. Human approval is external."""
from pathlib import Path
import copy,hashlib,json
from jwwkit.cad_model import CadDocument,JwsDocument

__all__=['file_sha256','entity_view','snapshot','diff_report','write_plan','verify_plan','execute_plan','save_checked']
_OLD_OPS=frozenset(('set_text','move_entities','set_entity_attributes','delete_entities',
               'copy_entities','rotate_entities','reflect_entities','scale_entities',
               'replace_entities_with_block','place_jws','gui_acceptance'))
_ADD_OPS=frozenset(('add_line','add_text','add_circle','add_arc','add_point','add_circle_solid','add_solid'))
_GROUP_OPS=frozenset(('set_layer_name','set_group_name','set_group_scale','set_group_state','set_layer_state'))
_SINGLE_OPS=frozenset(('set_text','set_entity_attributes','set_dimension_text','set_block_layer_priority'))
_OPS=_OLD_OPS|_ADD_OPS|_GROUP_OPS|{'set_dimension_text','set_block_layer_priority','add_block_definition','place_block','align_two_points','import_group'}
_NEW_ENTITY_OPS=_ADD_OPS|{'copy_entities','place_jws','place_block','import_group'}
_COMMON_EXTRA_OPS=frozenset(('delete_entity','move_entity','transform_entities','recalculate_text_endpoint'))

def file_sha256(path):
    """Read a local file and return its SHA256; never write the input."""
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def _canonical(value):return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False)
def _hash(value):return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()
def _json(value):return json.loads(_canonical(value))
def _require(condition,message):
    if not condition:raise ValueError(message)

def entity_view(entity):
    """Copy the current type/attributes/geometry; geometry coordinates are paper mm."""
    return copy.deepcopy(dict(type=entity.entity_type,attributes=dict(entity.attributes),geometry_paper_mm=dict(entity.geometry)))

def snapshot(cad):
    """Capture entities, definitions, names, group scales and group/layer states."""
    return _json(dict(entities=[dict(source_index=e.source_index,record=entity_view(e)) for e in cad.entities],
        definitions=[dict(number=d.number,name=d.name,attributes=dict(d.attributes),entities=[entity_view(e) for e in d.entities]) for d in cad.block_definitions],
        groups=[dict(name=cad.get_group_name(g),scale=cad.get_group_scale(g),layers=[cad.get_layer_name(g,l) for l in range(16)],
            state=cad.header['layer_groups'][g]['state'],layer_states=[l['state'] for l in cad.header['layer_groups'][g]['layers']]) for g in range(16)]))

def diff_report(before,after):
    """Count modified/deleted original entities and new entities; report definitions separately."""
    old={e['source_index']:e['record'] for e in before['entities']}
    _require(None not in old and len(old)==len(before['entities']),'Before snapshot must be a freshly opened document with unique source indices')
    current={e['source_index']:e['record'] for e in after['entities'] if e['source_index'] is not None}
    _require(len(current)==sum(e['source_index'] is not None for e in after['entities']),'Duplicate current source indices')
    _require(set(current)<=set(old),'Unknown original source indices')
    modified=[dict(source_index=k,before=v,after=current[k]) for k,v in old.items() if k in current and v!=current[k]]
    deleted=[dict(source_index=k,before=v) for k,v in old.items() if k not in current]
    added=[e['record'] for e in after['entities'] if e['source_index'] is None]
    group_changes=[dict(layer_group=g,before=a,after=b) for g,(a,b) in enumerate(zip(before['groups'],after['groups'])) if a!=b]
    return dict(modified_count=len(modified),deleted_count=len(deleted),added_count=len(added),
        changed_entity_count=len(modified)+len(deleted)+len(added),modified=modified,deleted=deleted,added=added,
        definitions_changed=before['definitions']!=after['definitions'],definitions_before=before['definitions'],definitions_after=after['definitions'],
        groups_changed=bool(group_changes),changed_group_count=len(group_changes),group_changes=group_changes)

def save_checked(cad,before,source_sha256,output,*,approved_plan_sha256=None,alignment_results=(),import_results=(),workflow_plan=None):
    """Save a new path, reload all public fields, verify input and write a new changes JSON."""
    output=Path(output);report_path=output.with_suffix('.changes.json')
    if output.exists() or report_path.exists():raise FileExistsError('Existing output or changes report; refusing overwrite')
    _require(file_sha256(cad.source)==source_sha256,'Source changed before save')
    expected=snapshot(cad);report=diff_report(before,expected)
    if alignment_results:report['alignment_results']=_json(alignment_results)
    if import_results:report['import_results']=_json(import_results)
    if workflow_plan is not None:
        from jwwkit._replacement_contract import audit_result
        _require(workflow_plan.get('schema_version')==4 and workflow_plan['source_sha256']==source_sha256
                 and Path(workflow_plan['output']).resolve()==output.resolve(),'Invalid workflow save context')
        audit_result(cad,workflow_plan)
    cad.save(output);reloaded=CadDocument.open(output);actual=snapshot(reloaded)
    _require([e['record'] for e in expected['entities']]==[e['record'] for e in actual['entities']],'Saved entity fields differ')
    _require(expected['definitions']==actual['definitions'],'Saved definition fields differ')
    _require(expected['groups']==actual['groups'],'Saved names, scales or display states differ')
    if workflow_plan is not None:
        try:workflow_audit=audit_result(reloaded,workflow_plan)
        except Exception as exc:raise RuntimeError('Workflow saved-output verification failed; output retained at '+str(output))from exc
        report['workflow']=_json(workflow_plan['workflow'])
        report['workflow_sha256']=workflow_plan['workflow_sha256']
        report['workflow_audit']=workflow_audit
    _require(file_sha256(cad.source)==source_sha256,'Source changed during save')
    report.update(source_sha256=source_sha256,output_sha256=file_sha256(output),saved_all_fields_match=True,approved_plan_sha256=approved_plan_sha256)
    with report_path.open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=True,indent=2,allow_nan=False)
    return report

def _targets(cad,indices):
    _require(isinstance(indices,list) and all(type(i) is int and 0<=i<len(cad.entities) for i in indices),'Invalid target indices')
    _require(indices==sorted(set(indices)),'Target indices must be unique and sorted')
    rows=[]
    for i in indices:
        row=dict(index=i,source_index=cad.entities[i].source_index,record=entity_view(cad.entities[i]))
        if cad.entities[i].entity_type=='LINE':row['endpoints_real_mm']=cad.line_points(i,units='real')
        row=_json(row);row['sha256']=_hash(row);rows.append(row)
    return rows

def _actions(actions,targets,*,common_result=False):
    _require(isinstance(actions,list) and actions,'Actions must be a nonempty list')
    aliases=set();definition_aliases=set()
    for a in actions:
        _require(isinstance(a,dict) and set(a)<= {'op','indices','kwargs','as'},'Invalid action fields')
        _require(a.get('op') in (_OPS|_COMMON_EXTRA_OPS if common_result else _OPS) and isinstance(a.get('kwargs',{}),dict),'Unsupported operation or kwargs')
        op=a['op'];kw=a.get('kwargs',{})
        selects=op not in (_ADD_OPS|_GROUP_OPS|{'place_jws','place_block','gui_acceptance','import_group'})
        if op=='add_block_definition':
            selects='indices' in a
            _require(selects != ('entities' in kw),'Definition requires either selected indices or declarative children, not both')
            if not selects:
                children=kw['entities']
                _require(isinstance(children,list) and children,'Definition needs nonempty declarative children')
                for child in children:
                    _require(isinstance(child,dict) and set(child)=={'op','kwargs'} and child['op'] in _ADD_OPS and isinstance(child['kwargs'],dict),'Only declared geometry constructors are allowed for definition children')
        if selects:
            indices=a.get('indices');_require(isinstance(indices,list) and indices,'Action requires selected indices')
            _require(all((type(i) is int and i in targets) or (type(i) is str and i in aliases) for i in indices),'Action targets an unapproved element or undefined alias')
            if op in ('delete_entity','move_entity','recalculate_text_endpoint'):_require(len(indices)==1,'Single method requires exactly one target')
        else:
            _require('indices' not in a,'This operation does not accept element indices')
        if op=='place_block':
            number=kw.get('def_number')
            _require(type(number) is int or (type(number) is str and number in definition_aliases),'Definition must be an existing number or a previously declared definition alias')
        if 'as' in a:
            alias=a['as'];_require(op in (_NEW_ENTITY_OPS|{'add_block_definition'}) and type(alias) is str and alias and alias not in (aliases|definition_aliases),'Invalid or duplicate new-entity alias')
            if op=='add_block_definition':definition_aliases.add(alias)
            else:aliases.add(alias)
    if any(a['op']=='gui_acceptance' for a in actions):_require(len(actions)==1,'GUI plan cannot contain edit actions')

def _resource_targets(cad,actions):
    """Review non-element targets separately, including stored coordinates at changed scales."""
    before=snapshot(cad);rows=[]
    for action_index,a in enumerate(actions):
        op=a['op'];kw=a.get('kwargs',{})
        named=[]
        def names(value,path='kwargs'):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key=='block_renames':continue
                    if key in ('color','linetype') and isinstance(item,str):
                        definition=(cad.get_sxf_color(item) if key=='color' else cad.get_sxf_linetype(item))
                        named.append(dict(path=path+'.'+key,requested=item,definition=definition))
                    else:names(item,path+'.'+key)
            elif isinstance(value,list):
                for i,item in enumerate(value):names(item,path+'['+str(i)+']')
        names(kw)
        if named:
            item=_json(dict(action_index=action_index,kind='sxf_attribute_definitions',resolved_names=named))
            item['sha256']=_hash(item);rows.append(item)
        if op in _GROUP_OPS:
            from jwwkit.writer.header import group_index
            g=group_index(kw['layer_group'])
            row=dict(action_index=action_index,kind=op,layer_group=g,before=before['groups'][g])
            if op in ('set_layer_name','set_layer_state'):row['layer']=group_index(kw['layer'])
            if op in ('set_group_state','set_layer_state'):
                from jwwkit.model.display_state import state_value,describe
                row['requested_state']=describe(state_value(kw['state']))
                row['coordinate_effect']='No entity, scale, name, writing selection or protection changes.'
            if op=='set_group_scale':
                row['affected_entities']=[dict(index=i,source_index=e.source_index,record=entity_view(e)) for i,e in enumerate(cad.entities) if e.attributes['layer_group']==g]
                referenced={e.geometry['def_number'] for e in cad.entities if e.entity_type=='BLOCK' and e.attributes['layer_group']==g}
                row['referenced_definitions']=[d for d in before['definitions'] if d['number'] in referenced]
                row['coordinate_effect']='Paper geometry stays fixed; real mm change with this group scale.'
        elif op=='import_group':
            from jwwkit.writer.header import group_index
            from jwwkit.model.group_import import definition_records
            src=CadDocument.open(kw['path']);sg=group_index(kw['source_group']);tg=group_index(kw['target_group'])
            row=dict(action_index=action_index,kind=op,target_group_before=before['groups'][tg],
                definitions_before=before['definitions'],source=str(Path(kw['path']).resolve()),
                source_sha256=hashlib.sha256(src._source_bytes).hexdigest(),source_group=src.header['layer_groups'][sg],
                incoming_entities=[entity_view(e) for e in src.entities if e.attributes['layer_group']==sg],
                source_definitions=list(definition_records(src).values()),
                sync_options={k:kw.get(k,d) for k,d in [('sync_scale',False),('sync_group_name',True),('sync_layer_names',True)]})
            # Historical plans without the new option retain their old review.
            if 'settings_policy' in kw:
                from jwwkit.model.group_import import settings_review
                row['settings']=settings_review(src,cad,kw['settings_policy'])
        elif op in ('place_block','add_block_definition','replace_entities_with_block'):
            row=dict(action_index=action_index,kind=op,definitions_before=before['definitions'])
            if op=='place_block' and type(kw['def_number']) is int:
                _require(any(d['number']==kw['def_number'] for d in before['definitions']),'Existing block definition is missing')
                row['def_number']=kw['def_number']
            if op=='add_block_definition':row['children_coordinate_units']='Definition local paper mm after explicit constructor unit conversion; selected entities use their current paper coordinates.'
        elif op=='align_two_points':
            from jwwkit.alignment import solve_two_point_alignment
            fit=solve_two_point_alignment(**kw)
            _require(fit['passed'],'Alignment refused: '+ '; '.join(fit['reasons']))
            row=dict(action_index=action_index,kind=op,alignment=fit)
        else:continue
        row=_json(row);row['sha256']=_hash(row);rows.append(row)
    return rows

def write_plan(cad,indices,actions,output,plan_path,*,dependencies=(),selection=None,selection_limits=None,workflow=None,common_result=False):
    """Write a new review JSON only; no editing/input(). Return path, file hash and plan."""
    _require(type(common_result)is bool,'common_result must be bool')
    _require(not(common_result and workflow is not None),'Use existing workflow schema4 plans with execute_plan_result; common schema5 is separate')
    source=Path(cad.source).resolve();source_hash=file_sha256(source)
    before=snapshot(cad)
    fresh=CadDocument.open(source)
    _require(before==snapshot(fresh) and cad.header==fresh.header and cad.version==fresh.version,'Plan requires an unedited source model')
    _require(cad.summary()['source_snapshot_sha256']==source_hash,'Source changed since opening')
    selection_record=None
    if selection is not None:
        selection_record=_selection_record(cad,selection,selection_limits)
        selected=[h['index'] for h in selection_record['hits']]
        if indices is None:indices=selected
        else:
            indices=list(indices)
            _require(indices==selected,'Explicit targets do not equal the search selection')
    elif selection_limits is not None:
        raise ValueError('selection_limits requires a selection query')
    indices=list(indices);targets=_targets(cad,indices);actions=_json(actions);_actions(actions,set(indices),common_result=common_result)
    paths={Path(p).resolve() for p in dependencies};figures=[]
    for a in actions:
        if a['op']=='import_group':
            p=Path(a['kwargs']['path']).resolve();a['kwargs']['path']=str(p);paths.add(p)
        if a['op']=='place_jws':
            p=Path(a['kwargs']['path']).resolve();a['kwargs']['path']=str(p);paths.add(p)
            f=JwsDocument.open(p)
            figures.append(dict(path=str(p),sha256=f.sha256,version=f.version,entities=[entity_view(e) for e in f.entities],definitions=[dict(name=d.name,entities=[entity_view(e) for e in d.entities]) for d in f.block_definitions]))
    deps=[dict(path=str(p),sha256=file_sha256(p)) for p in sorted(paths)]
    for figure in figures:_require(file_sha256(figure['path'])==figure['sha256'],'Figure changed while planning')
    output=Path(output).resolve();plan_path=Path(plan_path).resolve()
    _require(output!=source and plan_path!=source and output!=plan_path,'Input, output and plan must be distinct')
    _require(output.with_suffix('.changes.json') not in {source,plan_path},'Changes report overlaps input or plan')
    _require(output not in paths and plan_path not in paths,'Output/plan overlaps a protected dependency')
    for p in (output,output.with_suffix('.changes.json'),plan_path):
        if p.exists():raise FileExistsError(p)
    resources=_resource_targets(cad,actions)
    for row in resources:
        if row.get('kind')=='import_group':_require(file_sha256(row['source'])==row['source_sha256'],'Import source changed while planning')
    plan=dict(schema_version=2,source=str(source),source_sha256=source_hash,targets=targets,
        targets_sha256=_hash(targets),snapshot_sha256=_hash(before),actions=actions,output=str(output),dependencies=deps,new_figures=figures,
        resource_targets=resources,resource_targets_sha256=_hash(resources))
    if selection_record is not None:
        selection_record['targets_sha256']=plan['targets_sha256']
        plan.update(schema_version=3,selection=selection_record,selection_sha256=_hash(selection_record))
    if workflow is not None:
        workflow=_json(workflow)
        plan.update(schema_version=4,workflow=workflow,workflow_sha256=_hash(workflow),selection=selection_record,
                    selection_sha256=_hash(selection_record)if selection_record is not None else None)
        from jwwkit._replacement_contract import validate_plan
        validate_plan(cad,plan,planning=True)
        _require(plan_path!=Path(workflow['settings']['config_snapshot']['config_path']).resolve(),'Plan overlaps workflow configuration')
    if common_result:
        from jwwkit._edit_result_core import NAMES
        _require(all(a['op']in NAMES for a in actions),'PLAN_OPERATION_UNSUPPORTED for common results')
        plan.update(schema_version=5,result_contract_version=1,selection=selection_record,
                    selection_sha256=_hash(selection_record)if selection_record is not None else None)
    if not any(a['op']=='gui_acceptance' for a in actions):
        from dataclasses import replace
        staged=replace(cad,header=copy.deepcopy(cad.header),_name_edits=dict(cad._name_edits),
            _group_scale_edits=dict(cad._group_scale_edits),_new_block_records=copy.deepcopy(cad._new_block_records))
        _apply_edit_actions(staged,plan,operation_results=[] )if common_result else _apply_edit_actions(staged,plan)
    with plan_path.open('x',encoding='utf-8') as stream:json.dump(plan,stream,ensure_ascii=True,indent=2,allow_nan=False)
    _require(file_sha256(source)==source_hash,'Source changed while writing plan')
    if workflow is not None:
        from jwwkit.workflow_settings import _assert_live_snapshot
        _assert_live_snapshot(workflow['settings'])
    return dict(path=str(plan_path),sha256=file_sha256(plan_path),plan=plan)


def _selection_record(cad,query,limits):
    """Deterministic search proof; never store volatile elapsed time in an approval fingerprint."""
    result=cad.search_entities(query,scope='drawing',limits=limits)
    _require(result['complete'],'Search selection incomplete; cannot create/execute a plan')
    _require(not result['includes_metadata'],'Search selection must exclude metadata')
    keys=('query_schema_version','input_query','effective_query','scope','resolutions',
          'hits','match_count','complete','rules','limits','constraints','includes_metadata','source_snapshot_sha256')
    return _json({key:result[key] for key in keys})

def verify_plan(plan_path,*,approved_sha256):
    """Reopen and verify the exact file hash approved in chat, source, targets and dependencies."""
    _require(type(approved_sha256) is str and len(approved_sha256)==64 and all(c in '0123456789abcdef' for c in approved_sha256),'Explicit approved plan SHA256 required')
    raw=Path(plan_path).read_bytes();_require(hashlib.sha256(raw).hexdigest()==approved_sha256,'Approved plan file changed')
    from jwwkit.model.query import _pairs
    plan=json.loads(raw,object_pairs_hook=_pairs)
    keys={'schema_version','source','source_sha256','targets','targets_sha256','snapshot_sha256','actions','output','dependencies','new_figures'}
    version=plan.get('schema_version')
    if version in (2,3,4,5):keys|={'resource_targets','resource_targets_sha256'}
    if version in (3,4,5):keys|={'selection','selection_sha256'}
    if version==4:keys|={'workflow','workflow_sha256'}
    if version==5:keys|={'result_contract_version'}
    _require(set(plan)==keys and type(version) is int and version in (1,2,3,4,5),'Unsupported plan schema')
    if version==5:_require(type(plan['result_contract_version'])is int and plan['result_contract_version']==1,'Unsupported common result contract')
    _require(file_sha256(plan['source'])==plan['source_sha256'],'Source changed since planning')
    cad=CadDocument.open(plan['source']);indices=[t['index'] for t in plan['targets']]
    targets=_targets(cad,indices)
    _require(targets==plan['targets'] and _hash(targets)==plan['targets_sha256'],'Target contents changed since planning')
    _require(_hash(snapshot(cad))==plan['snapshot_sha256'],'Document snapshot changed since planning')
    if version==3:_require(type(plan['selection'])is dict,'Schema3 requires a search selection')
    if version in (3,4,5)and plan['selection']is not None:
        selection=plan['selection']
        _require(_hash(selection)==plan['selection_sha256'],'Search selection record changed')
        checked=_selection_record(cad,selection['input_query'],selection['limits'])
        checked['targets_sha256']=plan['targets_sha256']
        _require(checked==selection and _hash(checked)==plan['selection_sha256'],
                 'Search selection/rules/targets changed; replan and obtain approval')
        _require([h['index'] for h in checked['hits']]==indices,'Search target indices changed')
    elif version in (4,5):_require(plan['selection_sha256']is None,'Absent selection cannot have a hash')
    _actions(plan['actions'],set(indices),common_result=version==5)
    if version==5:
        from jwwkit._edit_result_core import NAMES
        _require(all(a['op']in NAMES for a in plan['actions']),'PLAN_OPERATION_UNSUPPORTED for common results')
    if version==1:
        _require(all(a['op'] in _OLD_OPS for a in plan['actions']),'New operations require schema 2 resource review')
        def uses_named_attributes(value):
            if isinstance(value,dict):return any((k in ('color','linetype') and isinstance(v,str)) or uses_named_attributes(v) for k,v in value.items())
            if isinstance(value,list):return any(uses_named_attributes(v) for v in value)
            return False
        _require(not uses_named_attributes(plan['actions']),'Named attributes require schema 2 resource review')
    else:
        resources=_resource_targets(cad,plan['actions'])
        _require(resources==plan['resource_targets'] and _hash(resources)==plan['resource_targets_sha256'],'Resource target contents changed since planning')
    for dep in plan['dependencies']:_require(file_sha256(dep['path'])==dep['sha256'],'Dependency changed since planning: '+dep['path'])
    protected={dep['path'] for dep in plan['dependencies']}
    for a in plan['actions']:
        if a['op'] in ('place_jws','import_group'):_require(a['kwargs']['path'] in protected,'Missing import/figure dependency')
    output=Path(plan['output']).resolve();source=Path(plan['source']).resolve();plan_file=Path(plan_path).resolve()
    _require(output!=source and output!=plan_file and plan_file!=source,'Input, output and plan must be distinct')
    _require(output.with_suffix('.changes.json') not in {source,plan_file},'Changes report overlaps input or plan')
    _require(all(p not in {Path(x).resolve() for x in protected} for p in (output,output.with_suffix('.changes.json'))),'Output/report overlaps a protected dependency')
    for p in (Path(plan['output']),Path(plan['output']).with_suffix('.changes.json')):
        if p.exists():raise FileExistsError(p)
    if version==4:
        from jwwkit._replacement_contract import validate_plan
        validate_plan(cad,plan)
        _require(Path(plan_path).resolve()!=Path(plan['workflow']['settings']['config_snapshot']['config_path']).resolve(),'Plan overlaps workflow configuration')
    return cad,plan

def _apply_edit_actions(cad,plan,*,import_results=None,operation_results=None):
    """Shared in-memory engine: no saving, UI or approval fabrication."""
    ids={t['index']:t['source_index'] for t in plan['targets']};aliases={};definition_aliases={};alignment_results=[]
    source_positions=None
    def selection(values):
        nonlocal source_positions
        # One index per action; keep every match so duplicate/missing lineage
        # retains exactly the old refusal behavior. Invalidate after any action.
        if source_positions is None:
            source_positions={}
            for i,entity in enumerate(cad.entities):
                source_positions.setdefault(entity.source_index,[]).append(i)
        found=[]
        for value in values:
            matches=source_positions.get(ids[value],[])
            _require(len(matches)==1,'Approved original target no longer available');found.extend(matches)
        return found
    # Aliases identify objects, not indices, so deletion/replacement cannot shift them.
    def alias_indices(values):
        result=[]
        for value in values:
            if type(value) is str:
                for obj in aliases[value]:
                    matches=[i for i,e in enumerate(cad.entities) if e is obj]
                    _require(len(matches)==1,'New entity alias no longer available');result+=matches
            else:result+=selection([value])
        return result
    def invoke(name,/,*args,**kwargs):
        if operation_results is None:return getattr(cad,name)(*args,**kwargs)
        from jwwkit._edit_result_core import apply_method
        result,returned=apply_method(cad,name,*args,**kwargs)
        result['action_index']=action_index;operation_results.append(result)
        return returned
    for action_index,a in enumerate(plan['actions']):
        source_positions=None
        op=a['op'];kw=copy.deepcopy(a.get('kwargs',{}));previous=len(cad.entities);before_objects=tuple(cad.entities)
        if op=='import_group':
            imported=invoke('import_group',**kw)
            if import_results is not None:import_results.append(dict(action_index=action_index,receipt=imported))
        elif op=='place_jws':
            path=kw.pop('path');name=kw.pop('name');position=kw.pop('position')
            JwsDocument.open(path).place_as_block(cad,name,position,**kw)
        elif op in _ADD_OPS:
            entity=invoke(op,**kw)
            from jwwkit.writer.preserved import entity_record
            cad._validate_addition(entity_record(entity))
        elif op in _GROUP_OPS:
            invoke(op,**kw)
        elif op=='add_block_definition':
            from jwwkit.model.block_operations import RecordChild,inverse_record
            from jwwkit.writer.preserved import entity_record
            if 'indices' in a:
                records=[entity_record(cad.entities[i]) for i in alias_indices(a['indices'])]
            else:
                specs=kw.pop('entities');staged=copy.copy(cad);staged.entities=()
                records=[]
                for spec in specs:
                    child=getattr(staged,spec['op'])(**copy.deepcopy(spec['kwargs']))
                    record=entity_record(child);staged._validate_addition(record);records.append(record)
            # Only observed bit2 normalization, identical to the existing grouping API.
            children=[RecordChild(inverse_record(r,(0,0),0,1,1)) for r in records]
            definition=invoke('add_block_definition',entities=children,**kw)
            if 'as' in a:definition_aliases[a['as']]=definition.number
        elif op=='place_block':
            if type(kw['def_number']) is str:kw['def_number']=definition_aliases[kw['def_number']]
            entity=invoke('place_block',**kw)
            from jwwkit.writer.preserved import entity_record
            cad._validate_addition(entity_record(entity))
        else:
            chosen=alias_indices(a['indices'])
            if op in _SINGLE_OPS or op in ('delete_entity','move_entity','recalculate_text_endpoint'):
                if op in _COMMON_EXTRA_OPS:_require(len(chosen)==1,'Single method requires one resolved target')
                for i in chosen:invoke(op,i,**kw)
            else:
                result=invoke(op,chosen,**kw)
                if op=='align_two_points':
                    _require(result['passed'],'Alignment tolerance refused during execution')
                    alignment_results.append(dict(action_index=action_index,alignment=result))
        # Existing aliases may refer to transformed frozen models. Rebind them
        # through index positions only while this operation cannot shift indices.
        if op not in ('delete_entities','delete_entity','replace_entities_with_block'):
            for name,objects in list(aliases.items()):
                positions=[i for i,e in enumerate(before_objects) if any(e is o for o in objects)]
                if positions:aliases[name]=[cad.entities[i] for i in positions]
        if 'as' in a and op!='add_block_definition':aliases[a['as']]=list(cad.entities[previous:])
    return alignment_results

def execute_plan(plan_path,*,approved_sha256):
    """Execute only listed supported edit actions after verification, then save/reload/report."""
    return _execute_plan(plan_path,approved_sha256=approved_sha256)

def _execute_plan(plan_path,*,approved_sha256,operation_results=None,execution_context=None):
    cad,plan=verify_plan(plan_path,approved_sha256=approved_sha256);before=snapshot(cad)
    _require(plan['schema_version']!=5 or operation_results is not None,'Common-result plan requires edit_result.execute_plan_result')
    if execution_context is not None:
        from jwwkit._edit_result_core import capture,NAMES
        _require(all(a['op']in NAMES for a in plan['actions']),'PLAN_OPERATION_UNSUPPORTED for common results')
        execution_context.update(before=capture(cad),plan=plan,phase='executing')
    _require(all(a['op']!='gui_acceptance' for a in plan['actions']),'GUI acceptance uses the separate guide/tool after verify_plan')
    import_results=[]
    alignment_results=_apply_edit_actions(cad,plan,import_results=import_results,operation_results=operation_results)if operation_results is not None else _apply_edit_actions(cad,plan,import_results=import_results)
    if execution_context is not None:execution_context.update(after=capture(cad),phase='auditing')
    for dep in plan['dependencies']:_require(file_sha256(dep['path'])==dep['sha256'],'Dependency changed during execution')
    report=diff_report(before,snapshot(cad));allowed={t['source_index'] for t in plan['targets']}
    _require(all(r['source_index'] in allowed for r in report['modified']+report['deleted']),'Non-target entity changed')
    after=snapshot(cad)
    group_fields=set()
    for a in plan['actions']:
        op=a['op'];kw=a.get('kwargs',{})
        if op=='import_group':
            tg=kw['target_group']
            for option,field,default in [('sync_scale','scale',False),('sync_group_name','name',True),('sync_layer_names','layers',True)]:
                if kw.get(option,default):
                    if field=='layers':group_fields.update((tg,'layers',layer) for layer in range(16))
                    else:group_fields.add((tg,field,None))
        if op in _GROUP_OPS:group_fields.add((kw['layer_group'],{'set_group_name':'name','set_group_scale':'scale','set_layer_name':'layers','set_group_state':'state','set_layer_state':'layer_states'}[op],kw.get('layer')))
    for g,(old,new) in enumerate(zip(before['groups'],after['groups'])):
        for field in ('name','scale','state'):
            _require(old[field]==new[field] or (g,field,None) in group_fields,'Unapproved group field changed')
        for layer,(old_name,new_name) in enumerate(zip(old['layers'],new['layers'])):
            _require(old_name==new_name or (g,'layers',layer) in group_fields,'Unapproved layer name changed')
        for layer,(old_state,new_state) in enumerate(zip(old['layer_states'],new['layer_states'])):
            _require(old_state==new_state or (g,'layer_states',layer) in group_fields,'Unapproved layer state changed')
    _require(after['definitions'][:len(before['definitions'])]==before['definitions'],'Existing definition changed')
    if len(after['definitions'])!=len(before['definitions']):
        _require(any(a['op'] in ('add_block_definition','place_jws','replace_entities_with_block','import_group') for a in plan['actions']),'Unapproved definition added')
    if execution_context is not None:execution_context['phase']='saving'
    saved=save_checked(cad,before,plan['source_sha256'],plan['output'],approved_plan_sha256=approved_sha256,alignment_results=alignment_results,import_results=import_results,
                        workflow_plan=plan if plan['schema_version']==4 else None)
    if execution_context is not None:execution_context['phase']='verified'
    return saved
