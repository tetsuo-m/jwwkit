"""Read-only drawing summary. Stored names differ from display placeholders."""
from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path

from writer.header import group_index
from writer.preserved import entity_record


def get_layer_name(document, layer_group, layer):
    slot=group_index(layer_group)*16+group_index(layer)
    return document._name_edits.get(slot, document._source_records['layer_names'][slot])


def get_group_name(document, layer_group):
    slot=256+group_index(layer_group)
    return document._name_edits.get(slot, document._source_records['layer_names'][slot])


def summarize(document):
    if document.includes_metadata:
        raise ValueError('Summary requires the default metadata-excluding model')
    numbers={d.number for d in document.block_definitions}
    if len(numbers)!=len(document.block_definitions):raise ValueError('Duplicate definition numbers')
    def validate(record):
        def finite(value):
            if isinstance(value,float) and not math.isfinite(value):raise ValueError('Nonfinite summary input')
            if isinstance(value,dict):
                for v in value.values():finite(v)
            elif isinstance(value,(list,tuple)):
                for v in value:finite(v)
        finite(record)
        group_index(record['base']['layer']);group_index(record['base']['layer_group'])
        if record['type']=='BLOCK' and record['def_number'] not in numbers:raise ValueError('Unresolved block reference')
    for e in document.entities:validate(entity_record(e))
    for d in document.block_definitions:
        for e in d.entities:validate(entity_record(e))
    counts=Counter(e.entity_type for e in document.entities)
    per_layer={}
    for e in document.entities:
        key=(e.attributes['layer_group'],e.attributes['layer'])
        per_layer.setdefault(key,Counter())[e.entity_type]+=1
    groups=[]
    for group in range(16):
        layers=[];group_counts=Counter()
        for layer in range(16):
            types=per_layer.get((group,layer),Counter());group_counts.update(types)
            layers.append(dict(index=layer,name=get_layer_name(document,group,layer),
                               count=sum(types.values()),by_type=dict(sorted(types.items()))))
        groups.append(dict(index=group,name=get_group_name(document,group),
                           scale=document.get_group_scale(group),count=sum(group_counts.values()),
                           by_type=dict(sorted(group_counts.items())),layers=layers))
    def text_row(index,e,member=None):
        raw=entity_record(e) if member is None else copy.deepcopy(member)
        return dict(entity_index=index,content=raw['content'],attributes=raw['base'],
                    geometry={k:v for k,v in raw.items() if k not in ('type','base')})
    texts=[text_row(i,e) for i,e in enumerate(document.entities) if e.entity_type=='TEXT']
    dimensions=[text_row(i,e,e.geometry['text']) for i,e in enumerate(document.entities) if e.entity_type=='DIMENSION']
    definitions=[]
    source_defs={d['number']:d for d in document._source_records['block_defs']}
    source_defs.update(document._new_block_records)
    for d in document.block_definitions:
        direct_refs=sum(e.entity_type=='BLOCK' and e.geometry['def_number']==d.number for e in document.entities)
        stored=source_defs[d.number];name=d.name_info
        definitions.append(dict(number=d.number,raw_name=d.name,display_name=name.display_name,
                                compound_kind=name.compound_kind,marker_status=name.marker_status,
                                timestamp=stored['timestamp'],stored_is_referenced=stored['is_referenced'],
                                direct_reference_count=direct_refs,entity_count=len(d.entities),
                                by_type=dict(sorted(Counter(e.entity_type for e in d.entities).items())),
                                texts=[text_row(i,e) for i,e in enumerate(d.entities) if e.entity_type=='TEXT'],
                                dimension_texts=[text_row(i,e,e.geometry['text']) for i,e in enumerate(d.entities) if e.entity_type=='DIMENSION']))
    return dict(schema_version=1,source=str(document.source),
                source_snapshot_sha256=hashlib.sha256(document._source_bytes).hexdigest(),
                version=document.version,paper_size=document.header['paper_size'],
                scope='Direct drawing entities; metadata settings and definition children excluded from main counts',
                entity_count=len(document.entities),by_type=dict(sorted(counts.items())),
                metadata_settings_excluded=len(document.metadata_settings),layer_groups=groups,
                texts=texts,dimension_texts=dimensions,
                block_reference_counts=document.block_reference_counts(),block_definitions=definitions,
                diagnostics=copy.deepcopy(list(document.diagnostics)))


def write_summary(document,path):
    # ASCII escaping retains malformed CP932 surrogateescape characters without
    # replacement or invalid UTF-8 output. Fully serialize before creating output.
    data=summarize(document)
    content=json.dumps(data,ensure_ascii=True,allow_nan=False,indent=2)+'\n'
    target=Path(path)
    with target.open('x',encoding='utf-8',newline='\n') as stream:stream.write(content)
    return data
