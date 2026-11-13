"""Approval-plan entry points for common results; no public direct-edit bypass."""
import copy,json
from pathlib import Path
from jwwkit._edit_result_core import (NAMES,Rejected,Failed,capture,net_rows,result,present,options,bounded,digest)

__all__=['write_edit_plan','preview_plan_result','execute_plan_result','EditExecutionError']

class EditExecutionError(RuntimeError):
    """Unexpected failure: caller must stop; .result preserves diagnostic evidence."""
    def __init__(self,record):self.result=record;super().__init__('Edit result execution failed; inspect exception.result')

def _record_path(source,output,plan_path,dependencies,config=None):
    record=Path(output).with_suffix('.edit-result.json').resolve()
    protected={Path(source).resolve(),Path(output).resolve(),Path(plan_path).resolve(),Path(output).with_suffix('.changes.json').resolve(),*(Path(p).resolve()for p in dependencies)}
    if config is not None:protected.add(Path(config).resolve())
    if record in protected:raise ValueError('Common result record overlaps protected input/output')
    if record.exists():raise FileExistsError(record)
    return record

def _combine(before,after,records,phase,approval=None):
    counts,resources,changes=net_rows(before,after)
    r=result('plan','applied'if changes else 'unchanged',phase,before,after)
    warnings=[dict(x,operation_index=i)for i,step in enumerate(records)for x in step['warnings']]
    r.update(counts=counts,resource_counts=resources,changes=changes,warnings=warnings,warning_count=len(warnings),approval_plan_sha256=approval,
        operation_count=len(records),operation_totals={k:sum(x['counts'][k]for x in records)for k in ('added','modified','deleted')},
        files_created=[],validation=dict(saved=False,reloaded=False,all_fields_match=False),record_written=False)
    return r

def _planned(r):
    r=copy.deepcopy(r);r.update(status='planned',phase='plan',projected_counts=r['counts'],projected_resource_counts=r['resource_counts'],
        projected_after_model_sha256=r['after_model_sha256'],after_model_sha256=r['before_model_sha256'],changes_phase='projected')
    r['counts']=dict(added=0,modified=0,deleted=0,rejected=0,unchanged=r['projected_counts']['modified']+r['projected_counts']['deleted']+r['projected_counts']['unchanged'])
    r['resource_counts']=dict(definitions=0,groups=0,layers=0)
    if 'operation_totals'in r:
        r['projected_operation_totals']=r['operation_totals'];r['operation_totals']=dict(added=0,modified=0,deleted=0)
    return r

def _render(r,records,limit,mode):
    r=present(r,limit,mode)
    prepared=[present(_planned(x)if r['status']=='planned'else x,limit,mode)for x in records[:limit]]if mode=='details'else []
    r['operations'],r['operations_page']=bounded(prepared,limit,mode)
    r['operations_page'].update(total=len(records),truncated=len(r['operations'])<len(records),has_more=len(r['operations'])<len(records))
    # operation_data may be a large collection of legacy return models.
    for x in r['operations']:
        if r['status']in ('rejected','failed')and not r.get('transaction_committed',False):x.update(transaction_committed=False,discarded=True)
        if x['operation_data']is not None and len(json.dumps(x['operation_data'],ensure_ascii=True))>1048576:
            x['operation_data']=None;x['operation_data_omitted']=True
    return r

def _error(exc,context,records,limit,mode):
    before=context.get('before')
    if isinstance(exc,Rejected):r=copy.deepcopy(exc.record)
    elif context.get('phase')is None and isinstance(exc,(ValueError,TypeError,IndexError,FileExistsError)):
        r=result('plan','rejected','plan',before);r['counts']['rejected']=None;r['rejected_operation_count']=1
        r['rejections']=[dict(code='PLAN_OPERATION_UNSUPPORTED'if str(exc).startswith('PLAN_OPERATION_UNSUPPORTED')else 'PLAN_VALIDATION_REFUSED',exception_type=type(exc).__name__,message=str(exc))]
    else:
        r=result('plan','failed','memory',before);r['rejections']=[dict(code='EXECUTION_FAILED',exception_type=type(exc).__name__,message=str(exc))]
        if isinstance(exc,Failed):r['rejections']=exc.record['rejections']
    r.update(transaction_committed=False,prior_operations_discarded=bool(records),record_written=False,files_created=[],validation=dict(saved=False,reloaded=False,all_fields_match=False))
    r.update(operation_count=len(records)+(1 if isinstance(exc,(Rejected,Failed))else 0),action_count=len(context['plan']['actions'])if context.get('plan')else None,
        operation_totals=dict(added=0,modified=0,deleted=0),staged_operation_totals={k:sum(x['counts'][k]for x in records)for k in ('added','modified','deleted')})
    if before:
        r['before_model_sha256']=digest(before);r['after_model_sha256']=digest(before)
        r['counts'].update(added=0,modified=0,deleted=0,unchanged=len(before['entities']))
    plan=context.get('plan')
    if plan:
        from jwwkit.safe_edit import file_sha256
        for p in (Path(plan['output']),Path(plan['output']).with_suffix('.changes.json')):
            try:
                if p.is_file():r['files_created'].append(dict(path=str(p),sha256=file_sha256(p),retained=True,verified=context.get('phase')=='verified'))
            except OSError as read_error:r['status']='failed';r['files_created'].append(dict(path=str(p),inspection_error=str(read_error),verified=False))
        if r['files_created']:
            verified=context.get('phase')=='verified'and not any('inspection_error'in x for x in r['files_created'])
            r['phase']='verified'if verified else 'saved'
            r['after_model_sha256']=None;r['counts'].update(added=None,modified=None,deleted=None,unchanged=None)
            r['validation']['saved']=True
            if verified and context.get('after'):
                r['counts'],r['resource_counts'],r['changes']=net_rows(before,context['after'])
                r['after_model_sha256']=digest(context['after']);r['validation'].update(reloaded=True,all_fields_match=True)
                r.update(transaction_committed=True,prior_operations_discarded=False)
                r['operation_totals']=r['staged_operation_totals']
    rendered=_render(r,records,limit,mode)
    if rendered['status']=='failed':raise EditExecutionError(rendered)from exc
    return rendered

def preview_plan_result(plan_path,*,plan_sha256,limit=100,mode='details'):
    """Dry-run a SHA-bound plan without saving or granting execution approval."""
    options(limit,mode);records=[];context={}
    try:
        from jwwkit.safe_edit import verify_plan,_apply_edit_actions
        cad,plan=verify_plan(plan_path,approved_sha256=plan_sha256)
        if any(a['op']not in NAMES for a in plan['actions']):raise ValueError('PLAN_OPERATION_UNSUPPORTED: common CadDocument methods only')
        _record_path(plan['source'],plan['output'],plan_path,[d['path']for d in plan['dependencies']],plan['workflow']['settings']['config_snapshot']['config_path']if plan.get('workflow')else None)
        before=capture(cad);context.update(before=before,plan=plan,phase='preview')
        _apply_edit_actions(cad,plan,operation_results=records)
        r=_planned(_combine(before,capture(cad),records,'memory'))
        r['plan']=dict(path=str(Path(plan_path).resolve()),sha256=plan_sha256)
        r['action_count']=len(plan['actions'])
        r['operation_data']=dict(planned_output=plan['output'],planned_result_record=str(Path(plan['output']).with_suffix('.edit-result.json')))
        return _render(r,records,limit,mode)
    except Exception as exc:return _error(exc,context,records,limit,mode)

def write_edit_plan(cad,indices,actions,output,plan_path,*,dependencies=(),selection=None,selection_limits=None,limit=100,mode='details'):
    """Write a schema5 review plan and return projected common results, without saving a drawing."""
    options(limit,mode)
    try:
        from jwwkit.cad_model import CadDocument
        if type(cad)is not CadDocument:raise ValueError('PLAN_OPERATION_UNSUPPORTED: CadDocument only')
        if isinstance(actions,list)and any(isinstance(a,dict)and a.get('op')not in NAMES for a in actions):raise ValueError('PLAN_OPERATION_UNSUPPORTED: common CadDocument methods only')
        dependencies=list(dependencies)
        incoming=[a['kwargs']['path']for a in actions if isinstance(a,dict)and a.get('op')=='import_group'and isinstance(a.get('kwargs'),dict)and 'path'in a['kwargs']]
        _record_path(cad.source,output,plan_path,[*dependencies,*incoming])
        from jwwkit.safe_edit import write_plan
        receipt=write_plan(cad,indices,actions,output,plan_path,dependencies=dependencies,selection=selection,selection_limits=selection_limits,common_result=True)
    except Exception as exc:return _error(exc,{},[],limit,mode)
    return preview_plan_result(receipt['path'],plan_sha256=receipt['sha256'],limit=limit,mode=mode)

def execute_plan_result(plan_path,*,approved_sha256,limit=100,mode='details'):
    """After external chat approval, verify, stage, save/reload and record common results."""
    options(limit,mode);records=[];context={}
    try:
        from jwwkit.safe_edit import verify_plan,_execute_plan,file_sha256
        cad,plan=verify_plan(plan_path,approved_sha256=approved_sha256)
        if any(a['op']not in NAMES for a in plan['actions']):raise ValueError('PLAN_OPERATION_UNSUPPORTED: common CadDocument methods only')
        record_path=_record_path(plan['source'],plan['output'],plan_path,[d['path']for d in plan['dependencies']],plan['workflow']['settings']['config_snapshot']['config_path']if plan.get('workflow')else None)
        saved=_execute_plan(plan_path,approved_sha256=approved_sha256,operation_results=records,execution_context=context)
        r=_combine(context['before'],context['after'],records,'verified',approved_sha256)
        r.update(transaction_committed=True,validation=dict(saved=True,reloaded=True,all_fields_match=True),record_written=True,
            plan=dict(path=str(Path(plan_path).resolve()),sha256=approved_sha256),action_count=len(plan['actions']))
        r['files_created']=[dict(path=str(p),sha256=file_sha256(p),verified=True)for p in (Path(plan['output']),Path(plan['output']).with_suffix('.changes.json'))]
        r['files_created'].append(dict(path=str(record_path),kind='common_result_record'))
        r['operation_data']={k:saved[k]for k in ('source_sha256','output_sha256','saved_all_fields_match')}
        rendered=_render(r,records,limit,mode)
        with record_path.open('x',encoding='utf-8')as stream:json.dump(rendered,stream,ensure_ascii=True,indent=2,allow_nan=False)
        return rendered
    except Exception as exc:return _error(exc,context,records,limit,mode)
