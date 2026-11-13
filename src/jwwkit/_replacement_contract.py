"""Strict recipe and independent result checks for the observed replacement scope."""
from pathlib import Path
import copy,hashlib,math
from jwwkit.cad_model import CadDocument
from jwwkit.alignment import solve_two_point_alignment
from jwwkit.writer.preserved import _document_bytes
from jwwkit.model.group_import import global_settings_bytes
from jwwkit.workflow_settings import _verify_resolved,_hash,_copy,_canonical,_assert_live_snapshot

def require(ok,message):
    if not ok:raise ValueError(message)
def group(value):
    require(type(value)is int and 0<=value<16,'Group must be integer 0..15')
    return value

def reference_rows(doc):
    from jwwkit.safe_edit import entity_view
    return [dict(index=i,real_mm=list(doc.convert_point((e.geometry['x'],e.geometry['y']),layer_group=3,from_units='paper',to_units='real')),element=entity_view(e))
     for i,e in enumerate(doc.entities)if e.entity_type=='POINT'and e.attributes['layer_group']==3 and e.attributes['layer']==0
     and e.geometry['is_temporary']and e.geometry['code']==0]

def points(doc,indices):
    rows={r['index']:r for r in reference_rows(doc)}
    require(type(indices)is list and len(indices)==2 and all(type(i)is int and i in rows for i in indices)and len(set(indices))==2,'Two distinct group3/layer0 temporary-point indices required')
    return [rows[i]['real_mm']for i in indices]

def archive_candidates(cad,building):
    counts={g:0 for g in range(16)}
    for r in cad._source_records['entities']:counts[r['base']['layer_group']]+=1
    result=[]
    for g in range(16):
        h=cad.header['layer_groups'][g]
        reason='target_group'if g==building else 'reference_group'if g==3 else 'writing'if h['state']==3 else 'protected'if h['protect']else 'occupied'if counts[g]else None
        result.append(dict(group=g,root_count=counts[g],state=h['state'],protected=h['protect'],eligible=reason is None,reason=reason))
    return result

def _contents(cad):
    from jwwkit.safe_edit import snapshot
    snap=snapshot(cad)
    return dict(snap,entities=[r['record']for r in snap['entities']])

BASE_CONTEXT={'incoming','building_group','source_reference_indices','target_reference_indices','distance_tolerance','angle_tolerance','angle_units','settings_policy'}

def prepare(cad,new,settings,context,*,verification=False):
    """Simulate in memory only. Never select a replacement group during execution."""
    from jwwkit.safe_edit import _targets,_apply_edit_actions
    settings=_verify_resolved(settings);context=_copy(context)
    require(set(context)==BASE_CONTEXT|({'archive_group','archive_selection'}if verification else set()),'Unknown/incomplete replacement context')
    building=group(context['building_group']);require(building!=3,'Building and reference group must differ')
    require(cad.version==new.version==700,'Replacement workflow supports observed v700 scope only')
    require(context['incoming']==str(Path(new.source).resolve()),'Incoming context path mismatch')
    require(context['settings_policy']in ('strict','destination'),'Invalid settings_policy')
    for doc in (cad,new):
        require(doc.get_group_state(building)['raw_value']!=3,'Writing building group cannot be replaced/imported')
        require(not doc.header['layer_groups'][building]['protect'],'Protected building group')
        require(doc.get_group_scale(building)==100,'Replacement requires both original building scales 1/100')
        _document_bytes(doc)
    old=list(cad.find_entities(layer_group=building));added=list(new.find_entities(layer_group=building))
    require(old and added,'Both building groups must be nonempty')
    require(not any(doc.entities[i].entity_type=='BLOCK'for doc,ids in ((cad,old),(new,added))for i in ids),'Building references are outside this replacement workflow scope')
    for doc,indices in ((cad,old),(new,added)):
        for i in indices:
            e=doc.entities[i];text=e.geometry if e.entity_type=='TEXT'else e.geometry.get('text',{})if e.entity_type=='DIMENSION'else {}
            require(not text.get('content','').startswith('^@BM'),'Image-dependent building elements are unsupported, including delete mode')
    kw=dict(source_points=points(new,context['source_reference_indices']),target_points=points(cad,context['target_reference_indices']),
      distance_tolerance=context['distance_tolerance'],angle_tolerance=context['angle_tolerance'],angle_units=context['angle_units'],allow_scale=False)
    fit=solve_two_point_alignment(**kw);require(fit['passed']and fit['applied_scale']==1,'Alignment exceeds explicit tolerances or changes scale')
    fit['measured_endpoint_displacement_mm']=2*fit['source_distance_mm']*math.sin(abs(fit['angle_difference_rad'])/2)
    mode=settings['effective']['old_group_action'];request=settings['effective']['archive_group'];chosen=None;selection=[]
    if mode=='archive':
        require(request is not None,'Archive group must be specified in config, instruction or plan argument')
        candidates=archive_candidates(cad,building);eligible=[r['group']for r in candidates if r['eligible']]
        if verification:
            chosen=group(context['archive_group'])
            require(chosen in eligible,'Fixed archive group is no longer empty/eligible; never select another group')
            require(chosen==(min(eligible)if request=='first_empty'else request),'Archive selection proof changed')
        else:
            require(eligible,'No eligible empty archive group')
            chosen=min(eligible)if request=='first_empty'else group(request)
            require(chosen in eligible,'Specified archive group must be empty, non-writing, unprotected and distinct')
        selection=candidates if request=='first_empty'else [candidates[chosen]]
    if verification:
        require(context['archive_group']==chosen and context['archive_selection']==selection,'Fixed archive context changed')
    else:context.update(archive_group=chosen,archive_selection=selection)
    excluded={building,chosen}if mode=='archive'else{building}
    protected={str(g):cad.snapshot_group(g)for g in range(16)if g not in excluded}
    actions=[]
    if mode=='archive':
        if cad.get_group_scale(chosen)!=100:actions.append(dict(op='set_group_scale',kwargs=dict(layer_group=chosen,scale=100)))
        actions.extend([dict(op='set_entity_attributes',indices=old,kwargs=dict(layer_group=chosen,preserve='paper')),
                        dict(op='set_group_state',kwargs=dict(layer_group=chosen,state='hidden'))])
    actions.extend([dict(op='import_group',**{'as':'incoming'},kwargs=dict(path=context['incoming'],source_group=building,target_group=building,
                   sync_scale=False,sync_group_name=False,sync_layer_names=False,settings_policy=context['settings_policy'])),
                   dict(op='align_two_points',indices=['incoming'],kwargs=kw)])
    if mode=='delete':actions.append(dict(op='delete_entities',indices=old,kwargs={}))
    targets=_targets(cad,old);stage=copy.deepcopy(cad);imports=[]
    _apply_edit_actions(stage,dict(actions=actions,targets=targets),import_results=imports)
    from jwwkit.writer.preserved import entity_record
    from jwwkit.model.rigid_audit import exact,audit_records
    originals=[e for i,e in enumerate(cad.entities)if mode=='archive'or i not in old]
    survivors=[e for e in stage.entities if e.source_index is not None]
    require([e.source_index for e in survivors]==[e.source_index for e in originals],'Original survivor order/population changed')
    old_ids={cad.entities[i].source_index for i in old}
    for before,after in zip(originals,survivors):
        expected=copy.deepcopy(entity_record(before))
        if mode=='archive'and before.source_index in old_ids:expected['base']['layer_group']=chosen
        require(exact(expected,entity_record(after)),'An original element changed beyond the declared archive group')
    imported_records=[entity_record(e)for e in stage.entities if e.source_index is None]
    require(len(imported_records)==len(added)and len(stage.entities)==len(originals)+len(added),'Imported/deleted element counts disagree')
    tr=fit['transform']
    rigid=audit_records([entity_record(new.entities[i])for i in added],imported_records,
      base_point_real=tr['base_point'],translation_real=tr['translation'],rotation=tr['rotation'],group_scale=100,
      definition_mapping=imports[0]['receipt']['definition_mapping'])
    require(rigid['passed'],'Incoming rigid geometry or exact attributes changed')
    require(global_settings_bytes(cad)==global_settings_bytes(stage,_document_bytes(stage)),'Destination global settings bytes changed')
    audits={g:stage.audit_group_unchanged(int(g),snap)for g,snap in protected.items()}
    require(all(a['passed']for a in audits.values()),'A non-target group changed')
    data=_document_bytes(stage)
    review=dict(old_group_action=mode,old_count=len(old),archived_count=len(old)if mode=='archive'else 0,
      deleted_count=len(old)if mode=='delete'else 0,added_count=len(added),expected_entity_count=len(stage.entities),
      old_target_indices=old,old_targets_sha256=_hash(targets),deleted_target_indices=old if mode=='delete'else [],
      expected_contents_sha256=_hash(_contents(stage)),expected_output_sha256=hashlib.sha256(data).hexdigest(),
      global_settings_sha256=hashlib.sha256(global_settings_bytes(cad)).hexdigest(),alignment=fit,incoming_rigid_audit=rigid,
      layer_name_differences=[dict(layer=l,old=cad.get_layer_name(building,l),incoming=new.get_layer_name(building,l))for l in range(16)if cad.get_layer_name(building,l)!=new.get_layer_name(building,l)],
      protected_groups=protected)
    return dict(context=context,actions=actions,targets=targets,review=_copy(review))

def validate_plan(cad,plan,*,planning=False):
    w=plan['workflow'];require(type(w)is dict and set(w)=={'schema_version','name','settings','context','review'},'Invalid workflow record keys')
    require(type(w['schema_version'])is int and w['schema_version']==1 and w['name']=='building_replacement','Unsupported workflow')
    require(_hash(w)==plan['workflow_sha256'],'Workflow hash mismatch')
    settings=_verify_resolved(w['settings'])
    if planning:_assert_live_snapshot(settings)
    new=CadDocument.open(w['context']['incoming'])
    proof=prepare(cad,new,settings,w['context'],verification=True)
    require(_canonical(proof['actions'])==_canonical(plan['actions']),'Workflow settings and edit actions disagree')
    require(proof['targets']==plan['targets'],'Workflow old targets changed')
    require(_canonical(proof['review'])==_canonical(w['review']),'Workflow review/evidence changed')
    require(plan['selection']is None or [h['index']for h in plan['selection']['hits']]==proof['review']['old_target_indices'],'Workflow selection mismatch')
    cfg=Path(settings['config_snapshot']['config_path'])
    for p in (plan['output'],str(Path(plan['output']).with_suffix('.changes.json'))):require(Path(p).resolve()!=cfg,'Output overlaps workflow configuration')
    require(cfg.resolve()not in {Path(d['path']).resolve()for d in plan['dependencies']},'Mutable config must be frozen in plan, not a live dependency')
    return proof

def audit_result(after,plan):
    from jwwkit.safe_edit import file_sha256
    require(file_sha256(plan['source'])==plan['source_sha256'],'Source changed during workflow')
    for dep in plan['dependencies']:require(file_sha256(dep['path'])==dep['sha256'],'Workflow input dependency changed')
    original=CadDocument.open(plan['source']);proof=validate_plan(original,plan)
    review=proof['review'];context=proof['context'];mode=review['old_group_action']
    require(_hash(_contents(after))==review['expected_contents_sha256'],'Replacement result contents differ from approved projection')
    serialized=_document_bytes(after)
    require(hashlib.sha256(serialized).hexdigest()==review['expected_output_sha256'],'Replacement output bytes differ from approved projection')
    groups={g:after.audit_group_unchanged(int(g),snap)for g,snap in review['protected_groups'].items()}
    require(all(a['passed']for a in groups.values()),'Saved non-target group changed')
    require(hashlib.sha256(global_settings_bytes(after,serialized)).hexdigest()==review['global_settings_sha256'],'Saved global settings changed')
    if mode=='archive':
        chosen=context['archive_group'];require(after.get_group_state(chosen)['raw_value']==0 and after.get_group_scale(chosen)==100,'Archive state/scale mismatch')
        require(len(after.find_entities(layer_group=chosen))==review['old_count'],'Archive count mismatch')
    return dict(passed=True,old_group_action=mode,archive_group=context['archive_group'],archived_count=review['archived_count'],deleted_count=review['deleted_count'],
                added_count=review['added_count'],non_target_groups=groups,global_settings_preserved=True,output_sha256=review['expected_output_sha256'])
