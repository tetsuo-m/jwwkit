"""Bounded, read-only JSON search. No expressions or user callbacks are executed."""
import copy
import hashlib
import json
import math
import time

VERSION = 1
KINDS = frozenset(('LINE','CIRCLE','ARC','POINT','TEXT','DIMENSION','BLOCK','SOLID','CIRCLE_SOLID'))
NA = object()


class Uncertain:
    def __init__(self, reason): self.reason = reason


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('Duplicate JSON key: '+key)
        result[key] = value
    return result


def json_query(value):
    """Detached JSON tree; duplicate textual keys, NaN and non-JSON data are rejected."""
    try:
        if isinstance(value, str):
            if len(value)>1048576:raise ValueError('Query JSON exceeds 1 MiB')
            value = json.loads(value, object_pairs_hook=_pairs,
                               parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
        # No tuple/set/custom mappings in the JSON language (legacy lists are converted separately).
        budget=[0,0]
        def check(v,depth=0):
            budget[0]+=1
            if depth>40 or budget[0]>20000:raise ValueError('Query JSON structure limit exceeded')
            if type(v)is str:
                budget[1]+=len(v)
                if budget[1]>1048576:raise ValueError('Query strings exceed 1 MiB')
            if type(v) is dict:
                if not all(type(k) is str for k in v): raise ValueError('JSON keys must be strings')
                for x in v.values(): check(x,depth+1)
            elif type(v) is list:
                for x in v: check(x,depth+1)
            elif type(v) not in (str, int, float, bool, type(None)):
                raise ValueError('Only JSON values are accepted')
        check(value)
        return json.loads(json.dumps(value, ensure_ascii=True, allow_nan=False))
    except (TypeError, RecursionError, OverflowError) as exc:
        raise ValueError('Invalid/overdeep JSON search condition') from exc


def _number(value):
    try:valid=type(value) in (int,float) and math.isfinite(value)
    except OverflowError:valid=False
    if not valid:
        raise ValueError('Finite numeric search value required')
    return value


def _keys(node, allowed, required):
    if not required <= node.keys() or not node.keys() <= allowed:
        raise ValueError('Invalid query fields: '+str(sorted(node)))


class Compiler:
    def __init__(self, document):
        self.document = document
        self.count = 0
        self.resolutions = []
        self.regexes=[]
        self.real_requested=False
        self.scales={}
        self.list_values=0
        self.definition_keys=set()
        self.text_equivalence=False;self.text_explanations=[];self.text_warnings=set()

    def scale(self, group):
        if type(group)is not int or not 0<=group<16:return Uncertain('Invalid group for real units')
        if group not in self.scales:
            try:
                value=self.document.get_group_scale(group)
                if type(value)not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError('Invalid group scale')
                self.scales[group]=value
            except ValueError as exc:self.scales[group]=Uncertain(str(exc))
        return self.scales[group]

    def compile(self, node, depth=0):
        self.count += 1
        if depth > 16 or self.count > 128: raise ValueError('Query depth/node limit exceeded')
        if type(node) is not dict: raise ValueError('Query node must be an object')
        logical = node.keys() & {'all','any','not'}
        if logical:
            if len(node) != 1: raise ValueError('Logical nodes must have exactly one key')
            op = next(iter(logical)); value = node[op]
            if op == 'not':
                child, canonical = self.compile(value,depth+1)
                def evaluate(e, i):
                    result = child(e,i)
                    return not result if type(result) is bool else result
                return evaluate, {op:canonical}
            if type(value) is not list or not value: raise ValueError('all/any requires a nonempty list')
            children = [self.compile(x,depth+1) for x in value]
            def evaluate(e, i):
                unknown = None; missing = False
                for child, _ in children:
                    result = child(e,i)
                    if type(result) is bool:
                        if result == (op == 'any'): return result
                    elif result is NA: missing = True
                    else: unknown = unknown or result
                return unknown if unknown is not None else NA if missing else op == 'all'
            return evaluate, {op:[c for _,c in children]}
        return self.leaf(node)

    def leaf(self, node):
        field = node.get('field')
        if 'in' in node and type(node['in'])is list:
            self.list_values+=len(node['in'])
            if self.list_values>8192:raise ValueError('Total in-list value limit exceeded')
        if field not in ('entity_type','layer_group','layer','color','linetype','block_name'):
            from .query_fields import leaf
            return leaf(self,node)
        allowed={'field','in'} | ({'name_kind'} if field=='block_name' else set())
        _keys(node,allowed,{'field','in'})
        values=node['in']
        if type(values) is not list or not 1 <= len(values) <= 1024:
            raise ValueError('in requires 1..1024 values')
        canonical=copy.deepcopy(node)
        if field=='entity_type':
            if any(type(v) is not str or v.upper() not in KINDS for v in values):
                raise ValueError('Unknown entity type')
            values=[v.upper() for v in values]
        elif field in ('layer_group','layer'):
            if any(type(v) is not int or not 0<=v<16 for v in values):
                raise ValueError('Group/layer values must be integers 0..15')
        elif field in ('color','linetype'):
            from .preflight import color_code,linetype_code
            resolver=color_code if field=='color' else linetype_code
            values=[resolver(self.document,v,**({'rgb':True} if field=='color' else {})) for v in values]
            self.resolutions.append(dict(field=field,input=node['in'],codes=values))
        elif field=='block_name':
            if any(type(v) is not str for v in values): raise ValueError('Block names must be strings')
            name_kind=node.get('name_kind','stored')
            if name_kind not in ('stored','display'): raise ValueError('Unknown block name kind')
            canonical['name_kind']=name_kind
            from .block_names import block_name_info
            if len({d.number for d in self.document.block_definitions})!=len(self.document.block_definitions):
                raise ValueError('Duplicate block definition numbers')
            names={d.number: d.name if name_kind=='stored' else block_name_info(d.name).display_name
                   for d in self.document.block_definitions}
        canonical['in']=list(dict.fromkeys(values)); accepted=set(values)
        def evaluate(entity, index):
            if field=='entity_type': return entity.entity_type in accepted
            if field=='block_name':
                if entity.entity_type!='BLOCK': return NA
                number=entity.geometry.get('def_number')
                if number not in names: return Uncertain('Unresolved block definition')
                return names[number] in accepted
            if field=='linetype' and entity.entity_type not in ('LINE','CIRCLE','ARC','SOLID','DIMENSION'):
                return NA
            key={'color':'pen_color','linetype':'pen_style'}.get(field,field)
            value=entity.attributes.get(key)
            if type(value) is not int: return Uncertain('Invalid stored attribute: '+key)
            return value in accepted
        return evaluate, canonical


def search(document, query, *, scope='drawing', limits=None, _indices=None):
    if scope not in ('drawing','definitions','drawing_and_definitions'):raise ValueError('Invalid search scope')
    effective_limits=dict(total_seconds=30.,regex_seconds=5.)
    if limits is not None:
        if type(limits)is not dict or not limits.keys()<=effective_limits.keys():raise ValueError('Unknown search limits')
        for key,value in limits.items():
            if not 0<_number(value)<=30:raise ValueError('Search time limits must be positive and <=30 seconds')
            effective_limits[key]=value
    start=time.perf_counter(); original=json_query(query)
    compiler=Compiler(document);evaluate,canonical=compiler.compile(original)
    if scope!='drawing' and compiler.real_requested:
        raise ValueError('Definition search supports local paper units only; real units are ambiguous')
    hits=[];unresolved=[];not_applicable=0;examined=0
    indices=range(len(document.entities)) if _indices is None else _indices
    entries=[];identifiers={}
    if scope!='definitions':
        for index in indices:
            identifiers[index]=dict(scope='drawing',index=index,source_index=document.entities[index].source_index)
            entries.append((index,document.entities[index]))
    if scope!='drawing':
        numbers=[d.number for d in document.block_definitions]
        if len(numbers)!=len(set(numbers)):raise ValueError('Duplicate block definition numbers')
        key=len(document.entities)
        for definition in document.block_definitions:
            for child,entity in enumerate(definition.entities):
                identifiers[key]=dict(scope='definition',definition_number=definition.number,entity_path=[child])
                compiler.definition_keys.add(key);entries.append((key,entity));key+=1
    def deadline():
        remaining=effective_limits['total_seconds']-(time.perf_counter()-start)
        if remaining<=0:raise TimeoutError('Search deadline exceeded; no partial result')
        return remaining
    if compiler.regexes:
        from .query_text import normalize,regex_results,equivalent_text
        requests=[];candidate_keys=[];characters=0
        for task in compiler.regexes:
            texts=[];keys=[]
            for index,entity in entries:
                if index%1024==0:deadline()
                geometry=entity.geometry if entity.entity_type=='TEXT' else entity.geometry.get('text',{}) if entity.entity_type=='DIMENSION' else {}
                text=geometry.get('content')
                if type(text)is not str:continue
                if len(text)>16384:raise ValueError('Regex input text exceeds 16384 characters')
                text=equivalent_text(text,task['normalization'])if task.get('normalization')is not None else normalize(text,task['fold'])
                characters+=len(text)
                if characters>8000000:raise ValueError('Regex input exceeds 8000000 characters')
                texts.append(text);keys.append(index)
            requests.append(dict(pattern=task['pattern'],ignore_case=task['ignore_case'],texts=texts));candidate_keys.append(keys)
        results=regex_results(requests,timeout=min(effective_limits['regex_seconds'],deadline()))
        for task,keys,matches in zip(compiler.regexes,candidate_keys,results):task['matches']=dict(zip(keys,matches))
    for index,entity in entries:
        if examined%1024==0:deadline()
        result=evaluate(entity,index);examined+=1
        if result is True:hits.append(identifiers[index])
        elif result is NA:not_applicable+=1
        elif isinstance(result,Uncertain):unresolved.append(dict(identifiers[index],reason=result.reason))
    deadline()
    from .query_text import rules
    rule_record=rules();extra={}
    if compiler.text_equivalence:
        from .query_text import equivalence_rules
        rule_record=dict(rule_record,engine='json-search-2',text_equivalence=dict(equivalence_rules(),warnings=sorted(compiler.text_warnings)))
        selected={h['index']for h in hits if h['scope']=='drawing'}
        definition_hits={(h['definition_number'],tuple(h['entity_path']))for h in hits if h['scope']=='definition'}
        selected.update(k for k,v in identifiers.items()if v['scope']=='definition'and (v['definition_number'],tuple(v['entity_path']))in definition_hits)
        details=[];count=0
        for index,entity in entries:
            if index not in selected:continue
            for evaluate,explain in compiler.text_explanations:
                if evaluate(entity,index)is True:
                    count+=1
                    if len(details)<100:details.append(dict(explain(entity,index),identifier=identifiers[index]))
            if count%1024==0:deadline()
        extra['text_match_details']=dict(items=details,total=count,returned=len(details),truncated=count>len(details),limit=100)
    deadline()
    return dict(query_schema_version=2 if compiler.text_equivalence else VERSION,input_query=original,effective_query=canonical,
        scope=scope,resolutions=compiler.resolutions,hits=hits,match_count=len(hits),
        not_applicable_count=not_applicable,unresolved=unresolved,complete=not unresolved,
        examined_count=examined,elapsed_seconds=time.perf_counter()-start,
        limits=effective_limits,rules=rule_record,model_state='current_in_memory',**extra,
        constraints=dict(nodes=128,depth=16,list_per_leaf=1024,list_total=8192,
            regex_patterns=8,regex_pattern_chars=512,text_chars=16384,regex_input_chars=8000000),
        includes_metadata=document.includes_metadata,
        source_snapshot_sha256=hashlib.sha256(document._source_bytes or b'').hexdigest())


def find(document, *, query=None, **filters):
    """Compatibility bridge; old scalar-only calls continue through the original function."""
    from .editing import find_entities
    fields={'entity_type':'entity_type','layer_group':'layer_group','layer':'layer',
            'color':'color','linetype':'linetype','block_name':'block_name'}
    leaves=[]
    for name,field in fields.items():
        if isinstance(filters.get(name),(list,tuple)):
            leaves.append(dict(field=field,**{'in':list(filters[name])}));filters[name]=None
    if query is None and not leaves:return find_entities(document,**filters)
    if query is not None:leaves.append(json_query(query))
    condition=leaves[0] if len(leaves)==1 else {'all':leaves}
    # Validate all new conditions, even if a legacy filter selects no entities.
    indices=find_entities(document,**filters)
    result=search(document,condition,_indices=indices)
    if not result['complete']: raise ValueError('Search incomplete: '+str(result['unresolved'][:5]))
    return tuple(hit['index'] for hit in result['hits'])
