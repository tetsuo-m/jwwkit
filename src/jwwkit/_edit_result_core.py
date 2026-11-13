"""Private atomic adapter for the 31 approved CadDocument methods only."""
import copy,hashlib,inspect,json
from dataclasses import is_dataclass,asdict
from types import SimpleNamespace
from pathlib import Path
from jwwkit.cad_model import CadDocument
from jwwkit.model.common_entities import CadEntity,CadBlockDefinition

NAMES=('delete_entity','delete_entities','move_entities','move_entity','transform_entities','copy_entities',
 'align_two_points','rotate_entities','reflect_entities','scale_entities','set_entity_attributes','set_text',
 'recalculate_text_endpoint','set_group_scale','add_line','add_text','add_circle','add_point','add_solid',
 'add_circle_solid','set_group_state','set_layer_state','set_layer_name','set_group_name','add_block_definition',
 'add_arc','set_dimension_text','place_block','replace_entities_with_block','set_block_layer_priority','import_group')
METHODS={name:getattr(CadDocument,name)for name in NAMES}
ADDITIONS={'add_line','add_text','add_circle','add_arc','add_point','add_solid','add_circle_solid','place_block'}
RESOURCES={'set_group_scale':'group','set_group_name':'group','set_group_state':'group',
 'set_layer_name':'layer','set_layer_state':'layer','add_block_definition':'definition'}

def canonical(v):return json.dumps(v,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(v):return hashlib.sha256(canonical(v).encode('ascii')).hexdigest()
def detached(v):return json.loads(canonical(v))
def equal(a,b):return canonical(a)==canonical(b)

def copying(name,parameters):
    return name=='copy_entities'or name=='transform_entities'and parameters.get('options',{}).get('copy_entities',False)or name in ('rotate_entities','reflect_entities','scale_entities')and parameters.get('options',{}).get('copy',False)

def options(limit,mode):
    if type(limit)is not int or not 0<=limit<=1000 or mode not in ('details','summary','count'):
        raise ValueError('limit must be integer 0..1000; mode details/summary/count')

def capture(cad):
    from jwwkit.safe_edit import snapshot
    from jwwkit.model.group_import import definition_records
    s=snapshot(cad)
    state=dict(entities=s['entities'],groups=s['groups'],definitions=list(definition_records(cad).values()),
               metadata=cad.metadata_settings,version=cad.version,origin_sha256=hashlib.sha256(cad._source_bytes).hexdigest())
    return detached(state)

def _rows(before,after,pairs):
    changes=[];paired_old=set();paired_new=set();counts=dict(added=0,modified=0,deleted=0,rejected=0,unchanged=0)
    for i,j in pairs:
        paired_old.add(i);paired_new.add(j)
        if equal(before['entities'][i],after['entities'][j]):counts['unchanged']+=1
        else:
            counts['modified']+=1;changes.append(dict(resource_type='entity',change='modified',before_index=i,after_index=j,before=before['entities'][i],after=after['entities'][j]))
    for i,e in enumerate(before['entities']):
        if i not in paired_old:counts['deleted']+=1;changes.append(dict(resource_type='entity',change='deleted',before_index=i,after_index=None,before=e,after=None))
    for j,e in enumerate(after['entities']):
        if j not in paired_new:counts['added']+=1;changes.append(dict(resource_type='entity',change='added',before_index=None,after_index=j,before=None,after=e))
    resources=dict(definitions=0,groups=0,layers=0)
    old={x['number']:x for x in before['definitions']};new={x['number']:x for x in after['definitions']}
    for number in sorted(old.keys()|new.keys()):
        a=old.get(number);b=new.get(number)
        if not equal(a,b):resources['definitions']+=1;changes.append(dict(resource_type='definition',number=number,change='added'if a is None else 'deleted'if b is None else 'modified',before=a,after=b))
    for g,(a,b)in enumerate(zip(before['groups'],after['groups'])):
        ga={k:a[k]for k in ('name','scale','state')};gb={k:b[k]for k in ga}
        if not equal(ga,gb):resources['groups']+=1;changes.append(dict(resource_type='group',layer_group=g,change='modified',before=ga,after=gb))
        for l in range(16):
            la=dict(name=a['layers'][l],state=a['layer_states'][l]);lb=dict(name=b['layers'][l],state=b['layer_states'][l])
            if not equal(la,lb):resources['layers']+=1;changes.append(dict(resource_type='layer',layer_group=g,layer=l,change='modified',before=la,after=lb))
    return counts,resources,changes

def net_rows(before,after):
    old=[x['source_index']for x in before['entities']]
    if None in old or len(set(old))!=len(old):raise RuntimeError('Net plan result needs fresh unique source indices')
    current={x['source_index']:j for j,x in enumerate(after['entities'])if x['source_index']is not None}
    if len(current)!=sum(x['source_index']is not None for x in after['entities'])or not current.keys()<=set(old):raise RuntimeError('Invalid original lineage after execution')
    return _rows(before,after,[(i,current[k])for i,k in enumerate(old)if k in current])

def result(operation,status,phase,before=None,after=None):
    return dict(schema_version=1,operation=operation,status=status,phase=phase,
        counts=dict(added=0,modified=0,deleted=0,rejected=0,unchanged=len(before['entities'])if before else 0),
        resource_counts=dict(definitions=0,groups=0,layers=0),changes=[],rejections=[],resource_rejections=[],warnings=[],warning_count=0,
        rejected_operation_count=0,rejected_addition_count=0,before_model_sha256=digest(before)if before else None,
        after_model_sha256=digest(after or before)if before else None,approval_plan_sha256=None,
        detail_page=dict(total=0,returned=0,truncated=False,has_more=False,continuation_supported=False),operation_data=None)

def bounded(items,limit,mode):
    output=[];size=0
    if mode=='details':
        for row in items[:limit]:
            amount=len(canonical(row).encode('ascii'))
            if size+amount>1048576:break
            output.append(detached(row));size+=amount
    return output,dict(total=len(items),returned=len(output),truncated=len(output)<len(items),has_more=len(output)<len(items),continuation_supported=False,max_bytes=1048576)

def present(value,limit=100,mode='details'):
    options(limit,mode);v=copy.deepcopy(value);v['changes'],v['detail_page']=bounded(v['changes'],limit,mode)
    v['error_summary']=None
    if v['rejections']:
        first=v['rejections'][0];message=first.get('message','')
        v['error_summary']=dict(code=first.get('code'),exception_type=first.get('exception_type'),message=message[:4096],message_truncated=len(message)>4096)
    v['warning_codes']=sorted({x['code']for x in v['warnings']})
    for key in ('warnings','rejections','resource_rejections'):
        rows=v[key];v[key],page=bounded(rows,limit,mode);v[key+'_details']=page
    if mode!='details':v['operation_data']=None
    return v

def data(value):
    from jwwkit.safe_edit import entity_view
    if isinstance(value,CadEntity):return dict(entity_view(value),source_index=value.source_index)
    if isinstance(value,CadBlockDefinition):return dict(number=value.number,name=value.name,attributes=dict(value.attributes),entities=[data(e)for e in value.entities])
    from jwwkit.model.block_operations import RecordChild
    if isinstance(value,RecordChild):return dict(record=data(value.value))
    if is_dataclass(value):return dict(model_type=type(value).__name__,values=data(asdict(value)))
    if isinstance(value,Path):return str(value)
    if isinstance(value,(list,tuple)):return [data(x)for x in value]
    if isinstance(value,dict):return {str(k):data(v)for k,v in value.items()}
    if value is None or type(value)in (str,int,float,bool):return value
    raise TypeError('Unrepresentable operation return type: '+type(value).__name__)

class Rejected(Exception):
    def __init__(self,record):self.record=record;super().__init__(record['rejections'][0]['message'])

class Failed(Exception):
    def __init__(self,record):self.record=record;super().__init__(record['rejections'][0]['message'])

def refusal(name,before,bound,exc,code='EDIT_REFUSED'):
    r=result(name,'rejected','memory',before);r['rejected_operation_count']=1
    args=bound.arguments if bound else {};targets=[args['index']]if 'index'in args else args.get('indices')
    valid=isinstance(targets,(list,tuple))and all(type(i)is int and 0<=i<len(before['entities'])for i in targets)and len(set(targets))==len(targets)
    r['counts']['rejected']=len(targets)if valid else 0 if name in ADDITIONS or name in RESOURCES else None
    r['rejected_addition_count']=1 if name in ADDITIONS else len(targets)if copying(name,args)and valid else None if name=='import_group'else 0
    if name in RESOURCES:
        try:request={k:data(v)for k,v in args.items()if k!='self'}
        except TypeError:request=dict(unrepresentable_input=True)
        r['resource_rejections']=[dict(resource_type=RESOURCES[name],request=request)]
    r['rejections']=[dict(code=code,exception_type=type(exc).__name__,message=str(exc),targets=targets if valid else None)]
    return r

def apply_method(cad,name,/,*args,**kwargs):
    """Private: called only inside the approved plan engine or its dry run."""
    before=capture(cad);bound=None
    if type(cad)is not CadDocument or name not in METHODS:raise Rejected(refusal(name,before,None,ValueError('PLAN_OPERATION_UNSUPPORTED'),'PLAN_OPERATION_UNSUPPORTED'))
    staged=copy.deepcopy(cad);args=copy.deepcopy(args);kwargs=copy.deepcopy(kwargs)
    try:
        try:
            bound=inspect.signature(METHODS[name]).bind(staged,*args,**kwargs)
            bound=SimpleNamespace(arguments=copy.deepcopy({k:v for k,v in bound.arguments.items()if k!='self'}))
        except TypeError as exc:raise Rejected(refusal(name,before,None,exc,'INVALID_ARGUMENTS'))from exc
        try:
            returned=METHODS[name](staged,*args,**kwargs)
            if name=='align_two_points'and not returned['passed']:raise ValueError('; '.join(returned['reasons']))
        except (ValueError,TypeError,IndexError)as exc:raise Rejected(refusal(name,before,bound,exc))from exc
        try:
            from jwwkit.writer.preserved import _document_bytes
            _document_bytes(staged)
        except (ValueError,TypeError,IndexError)as exc:raise Rejected(refusal(name,before,bound,exc,'SAVE_PREFLIGHT_REFUSED'))from exc
        after=capture(staged);n=len(cad.entities);m=len(staged.entities);deleted=set()
        if name=='delete_entity':deleted={bound.arguments['index']}
        elif name in ('delete_entities','replace_entities_with_block'):
            deleted=set(bound.arguments['indices'])
            if name=='replace_entities_with_block':deleted.remove(min(deleted))
        pairs=[(i,j)for j,i in enumerate(i for i in range(n)if i not in deleted)]
        expected=n+1 if name in ADDITIONS else n+len(bound.arguments['indices'])if copying(name,bound.arguments) else n+returned['added_count']if name=='import_group'else n-len(deleted)
        if m!=expected:raise RuntimeError('Unexpected root population after method')
        counts,resources,changes=_rows(before,after,pairs)
        r=result(name,'applied'if changes else 'unchanged','memory',before,after)
        r.update(counts=counts,resource_counts=resources,changes=changes,operation_data=data(returned))
        if name=='set_group_scale'and resources['groups']:r['warnings'].append(dict(code='GROUP_SCALE_PAPER_FIXED',message='Paper coordinates remain fixed; real coordinates change with group scale.'))
        if name=='import_group'and bound.arguments.get('settings_policy')=='destination':r['warnings'].append(dict(code='DESTINATION_RENDERING_SETTINGS',message='Imported attribute codes retain their values; appearance follows destination settings.'))
        if name=='replace_entities_with_block'and any(before['entities'][i]['record']['attributes']['flag']&2 for i in bound.arguments['indices']):r['warnings'].append(dict(code='BLOCK_FLAG2_NORMALIZATION',message='Only observed definition-child flag2 normalization follows Jw_cad control.'))
        r['warning_count']=len(r['warnings'])
        # Preserve identities of surviving unchanged roots for existing aliases.
        roots=list(staged.entities)
        for i,j in pairs:
            if equal(before['entities'][i],after['entities'][j]):roots[j]=cad.entities[i]
        staged.entities=tuple(roots)
        completed=(r,returned)
        cad.__dict__=staged.__dict__
        return completed
    except Rejected:raise
    except Exception as exc:
        r=result(name,'failed','memory',before);r['rejections']=[dict(code='EDIT_EXECUTION_FAILED',exception_type=type(exc).__name__,message=str(exc))]
        raise Failed(r)from exc
