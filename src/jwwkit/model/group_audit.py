"""Strict saved group contents, including transitive/shared definitions."""
import copy,hashlib,json
from jwwkit.writer.header import group_index,scale_offsets,name_spans
from jwwkit.writer.preserved import _document_bytes
from jwwkit.writer.mfc import records_bytes
from jwwkit.reader.archive import read_records_bytes

def digest(value):
    data=json.dumps(value,sort_keys=True,ensure_ascii=True,separators=(',',':'),allow_nan=False)
    return hashlib.sha256(data.encode('utf-8')).hexdigest()

def snapshot_group(document,layer_group):
    group=group_index(layer_group)
    data=_document_bytes(document)
    checked=read_records_bytes(data)
    offsets=scale_offsets(data,document.header['layer_groups']);start=offsets[group]-8
    names=list(document._source_records['layer_names'])
    for slot,value in document._name_edits.items():names[slot]=value
    spans=name_spans(data,names)
    slots=list(range(group*16,group*16+16))+[256+group]
    definitions={r['number']:r for r in checked['block_defs']};required=set();visiting=set()
    def visit(number):
        if len(visiting)>64:raise ValueError('Deep block graph: complete group audit unavailable')
        if number in visiting:raise ValueError('Cyclic block graph: complete group audit unavailable')
        if number in required:return
        if number not in definitions:raise ValueError('Unresolved group block dependency')
        visiting.add(number)
        for r in definitions[number]['entities']:
            if r['type']=='BLOCK':visit(r['def_number'])
        visiting.remove(number);required.add(number)
    # Include hidden save-state TEXT records as well as public drawing roots.
    records=[r for r in checked['entities'] if r['base']['layer_group']==group]
    for r in records:
        if r['type']=='BLOCK':visit(r['def_number'])
    def stored(r):
        def image(x):
            if x['type']=='TEXT' and x['content'].startswith('^@BM'):return True
            if x['type']=='DIMENSION':return image(x['text'])
            return x['type']=='BLOCK_DEF' and any(image(c) for c in x['entities'])
        if image(r):raise ValueError('Image-dependent group audit requires separate dependency analysis')
        payload=records_bytes([r],version=document.version,encoding=document._source_records['body_encoding'])
        return dict(record=copy.deepcopy(dict(r)),storage_sha256=hashlib.sha256(payload).hexdigest())
    dependencies=set()
    def collect(r):
        dependencies.add(group_index(r['base']['layer_group']))
        if r['type']=='DIMENSION':
            for child in (r['line'],r['text'],*r['aux_lines'],*r['aux_points']):collect(child)
        elif r['type']=='BLOCK_DEF':
            for child in r['entities']:collect(child)
    for r in records:collect(r)
    for number in required:
        for r in definitions[number]['entities']:collect(r)
    def dependency_header(g):
        begin=offsets[g]-8;indices=list(range(g*16,g*16+16))+[256+g]
        return dict(layer_group=g,header=copy.deepcopy(document.header['layer_groups'][g]),
            numeric_header_hex=data[begin:begin+148].hex(),
            saved_names=[dict(slot=s,value=names[s],cstring_hex=data[spans[s][0]:spans[s][1]].hex()) for s in indices])
    result=dict(schema_version=1,layer_group=group,version=document.version,
        group_header=copy.deepcopy(document.header['layer_groups'][group]),
        numeric_header_hex=data[start:start+148].hex(),
        common_header_hex=(data[:offsets[0]-8]+data[offsets[-1]-8+148:spans[0][0]]+
            data[spans[-1][1]:checked['header_end']]).hex(),
        saved_names=[dict(slot=slot,value=names[slot],cstring_hex=data[spans[slot][0]:spans[slot][1]].hex()) for slot in slots],
        referenced_group_headers=[dependency_header(g) for g in sorted(dependencies-{group})],
        common_metadata=[stored(document._source_records['entities'][i]) for i in document._source_metadata_indices],
        entities=[stored(r) for r in records],
        referenced_definitions=[stored(definitions[n]) for n in sorted(required)])
    result['sha256']=digest(result);return result

def differences(a,b,path=''):
    if isinstance(a,dict) and isinstance(b,dict):
        return [d for k in sorted(a.keys()|b.keys()) for d in differences(a.get(k),b.get(k),path+'.'+k)]
    if isinstance(a,list) and isinstance(b,list):
        if len(a)!=len(b):return [dict(field=path+'.length',before=len(a),after=len(b))]
        return [d for i,(x,y) in enumerate(zip(a,b)) for d in differences(x,y,f'{path}[{i}]')]
    # JSON number equality does not distinguish signed zeros. The retained
    # storage hash detects their different saved representation as well.
    return [] if a==b else [dict(field=path,before=a,after=b)]

def audit_group(document,layer_group,before):
    group=group_index(layer_group)
    if not isinstance(before,dict) or before.get('schema_version')!=1 or before.get('layer_group')!=group:
        raise ValueError('Snapshot schema or group does not match')
    old=copy.deepcopy(before);old_hash=old.pop('sha256',None)
    if old_hash!=digest(old):raise ValueError('Group snapshot hash mismatch')
    after=snapshot_group(document,group);new=copy.deepcopy(after);new_hash=new.pop('sha256')
    changed=differences(old,new)
    return dict(passed=old_hash==new_hash,layer_group=group,before_sha256=old_hash,after_sha256=new_hash,
        differences=changed,entity_count_before=len(old['entities']),entity_count_after=len(new['entities']),
        referenced_definition_count_before=len(old['referenced_definitions']),referenced_definition_count_after=len(new['referenced_definitions']),
        scope='Strict group saved values and representations; no normalization; absolute archive indices excluded')
