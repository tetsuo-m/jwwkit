"""A5 lossless candidate preparation with explicit conservative refusal boundaries."""
import copy
import hashlib
import struct
import json
import math
from dataclasses import replace
from pathlib import Path
from jwwkit.cad_model import CadDocument
from jwwkit.reader.archive import Cursor
from jwwkit.writer.header import group_index, scale_offsets, name_spans
from jwwkit.writer.preserved import entity_record
from jwwkit.model.common_entities import CadBlockDefinition, model_entity
from jwwkit.model.editing import transform, children
from jwwkit.model.preflight import check
from jwwkit.model.block_names import block_name_info, definition_name

def settings_policy_value(value):
    if type(value) is not str or value not in ('strict','destination'):
        raise ValueError('settings_policy must be strict or destination')
    return value


def global_settings_bytes(document, serialized=None):
    """All header bytes except explicit group/name resources; include E123 bytes."""
    if serialized is None:
        data=document._source_bytes;end=document._source_records['header_end']
        groups=document._source_header['layer_groups'];names=list(document._source_records['layer_names'])
    else:
        from jwwkit.reader.archive import read_records_bytes
        parsed=read_records_bytes(serialized);data=serialized;end=parsed['header_end']
        groups=document.header['layer_groups'];names=list(document._source_records['layer_names'])
        for slot,value in document._name_edits.items():names[slot]=value
    offsets=scale_offsets(data,groups);spans=name_spans(data,names)
    return data[:offsets[0]-8]+data[offsets[-1]-8+148:spans[0][0]]+data[spans[-1][1]:end]


def settings_review(source,destination,policy):
    """Read-only plan evidence. Never authorize overwriting destination settings."""
    policy=settings_policy_value(policy)
    left=opaque_settings(source);right=opaque_settings(destination)
    from itertools import zip_longest
    differences=[dict(compared_byte_index=i,source=a,destination=b)
        for i,(a,b) in enumerate(zip_longest(left,right)) if a!=b]
    return dict(settings_policy=policy,source_compared_settings_sha256=hashlib.sha256(left).hexdigest(),
        destination_compared_settings_sha256=hashlib.sha256(right).hexdigest(),
        source_global_settings_sha256=hashlib.sha256(global_settings_bytes(source)).hexdigest(),
        destination_global_settings_sha256=hashlib.sha256(global_settings_bytes(destination)).hexdigest(),
        source_header_sha256=hashlib.sha256(source._source_bytes[:source._source_records['header_end']]).hexdigest(),
        destination_header_sha256=hashlib.sha256(destination._source_bytes[:destination._source_records['header_end']]).hexdigest(),
        compared_settings_equal=left==right,compared_settings_differences=differences,
        differences_offset_kind='Index in opaque comparison sequence, not an absolute JWW offset',
        rendering_policy='Destination definitions determine appearance; source entity numbers and all representable attributes are retained. No global source settings are imported.')


def opaque_settings(document):
    """Exclude only already-verified memo/paper/group/name regions, compare rest."""
    data=document._source_bytes[:document._source_records['header_end']]
    c=Cursor(data);c.take(12);c.string(preserve_header_bytes=True);start=c.pos
    offsets=scale_offsets(data,document._source_header['layer_groups'])
    # group entries are validated by scale_offsets: 20 + 16*8 bytes each.
    group_end=offsets[-1]-8+20+16*8
    spans=name_spans(data,document._source_records['layer_names'])
    before_names=data[group_end:spans[0][0]]
    if len(before_names)!=156:raise ValueError('Unknown numeric header layout')
    end=spans[-1][1]
    # Published layout + E045 color anchors independently verify the post-name
    # viewport/jump fields, before excluding their 48..320 bytes.
    colors=[struct.unpack_from('<I',data,end+464+i*8)[0] for i in range(10)]
    if colors!=document._source_header['palette']['pen_colors']:
        raise ValueError('Unknown standard palette dependency layout')
    # Print origin/multiplier/anchor (84..112) and viewport/range/jump (48..320)
    # belong to output/navigation state, not imported geometry/style definitions.
    return before_names[:84]+before_names[112:]+data[end:end+48]+data[end+320:]

def definition_records(document):
    originals={r['number']:r for r in document._source_records['block_defs']}
    result={}
    for d in document.block_definitions:
        r=copy.deepcopy(originals.get(d.number,document._new_block_records.get(d.number)))
        if r is None:raise ValueError('Unmanaged definition')
        r.update(name=d.name,base=dict(d.attributes),entities=[entity_record(e) for e in d.entities])
        result[d.number]=r
    return result

def content(record):
    r=copy.deepcopy(record);r.pop('number');return r

def definition_signature(records,number,cache=None,stack=()):
    """Normalize reference IDs by full child contents, never by names alone."""
    cache={} if cache is None else cache
    if number in stack or len(stack)>64:raise ValueError('Cyclic/deep definition graph unsupported')
    if number in cache:return cache[number]
    if number not in records:raise ValueError('Unresolved definition in comparison')
    r=content(records[number])
    for child in r['entities']:
        if child['type']=='BLOCK':
            child['def_number']=dict(full_definition_sha256=definition_signature(records,child['def_number'],cache,stack+(number,)))
    result=hashlib.sha256(json.dumps(r,ensure_ascii=True,sort_keys=True,allow_nan=False,separators=(',',':')).encode('utf-8')).hexdigest()
    cache[number]=result;return result

def _observed_preset3(source,record,source_group):
    """E120's 21 native clipboard controls; no inferred style/flag profiles."""
    from jwwkit.reader.text_presets import read_text_presets
    if record['text']['text_type']!=3 or record['base']['flag']!=8192:return False
    layer=record['base']['layer']
    def base_matches(r,style,color,width,flag):
        b=r['base']
        return (b['group']==0 and b['pen_style']==style and b['pen_color']==color
            and b['pen_width']==width and b['flag']==flag
            and b['layer']==layer and b['layer_group']==source_group)
    if not (base_matches(record,1,2,0,8192) and base_matches(record['line'],1,1,0,8192)
        and base_matches(record['text'],2,2,67,16400)):return False
    for child in (*record['aux_lines'],*record['aux_points']):
        if not base_matches(child,1,2,0,0):return False
    if any(p['code']!=0 or p['is_temporary'] or p['angle']!=0 or p['scale']!=0 for p in record['aux_points']):return False
    text=record['text']
    # E131 native rigid controls preserve type3/font/size/flags at rotated angles.
    if text['font_name']!='ＭＳ ゴシック' or not math.isfinite(text['angle']):return False
    preset=read_text_presets(source._source_bytes,source._source_records['header_end'],source.version)[2]
    return (all(text[k]==preset[k] for k in ('size_x','size_y','spacing'))
        and text['base']['pen_color']==preset['color'])


def prepare(destination,path,source_group,target_group,*,sync_scale=False,
            sync_group_name=True,sync_layer_names=True,block_renames=None,settings_policy='strict'):
    """Return an isolated candidate plus a receipt; never mutate destination/source."""
    source_group=group_index(source_group);target_group=group_index(target_group)
    settings_policy=settings_policy_value(settings_policy)
    for value in (sync_scale,sync_group_name,sync_layer_names):
        if type(value) is not bool:raise TypeError('Sync selections must be bool')
    path=Path(path).resolve();before=hashlib.sha256(path.read_bytes()).hexdigest()
    if path==Path(destination.source).resolve():raise ValueError('Use intra-document copy API for the same file')
    source=CadDocument.open(path)
    if source.includes_metadata or destination.includes_metadata:raise ValueError('Metadata-inclusive model unsupported')
    if source.version!=destination.version:raise ValueError('Cross-version header dependency equivalence unverified')
    review=settings_review(source,destination,settings_policy)
    if settings_policy=='strict' and not review['compared_settings_equal']:
        raise ValueError('Unparsed drawing-wide settings differ; cannot guarantee default color/width/text/linetype preservation')
    selected=[e for e in source.entities if e.attributes['layer_group']==source_group]
    if not selected:raise ValueError('Source group is empty')
    if source._source_records['images']:raise ValueError('Image-bearing source requires dependency selection analysis')
    source_defs=definition_records(source);destination_defs=definition_records(destination)
    required={e.geometry['def_number'] for e in selected if e.entity_type=='BLOCK'}
    complete=set()
    def closure(number,stack=()):
        if len(stack)>64 or number in stack:raise ValueError('Cyclic/deep definition graph unsupported')
        if number not in source_defs:raise ValueError('Unresolved source definition')
        if number in complete:return
        required.add(number)
        for child in source_defs[number]['entities']:
            if child['type']=='BLOCK':closure(child['def_number'],stack+(number,))
        complete.add(number)
    for number in tuple(required):closure(number)
    if any(r['type']=='DIMENSION' and r['text']['text_type']!=0
           for number in required for r in source_defs[number]['entities']):
        raise ValueError('Preset dimensions inside block definitions require separate native verification')
    renames={} if block_renames is None else block_renames
    if not isinstance(renames,dict):raise TypeError('Renames must be a map')
    if any(type(k) is not str or not k or type(v) is not str or not v for k,v in renames.items()):
        raise ValueError('Renames require nonempty exact names')
    known={block_name_info(source_defs[n]['name']).display_name for n in required}
    if set(renames)-known:raise ValueError('Rename targets an unused or missing definition')
    candidate=copy.deepcopy(destination)
    old_scale=candidate.get_group_scale(target_group);source_scale=source.get_group_scale(source_group)
    preset_dimensions=[e for e in selected if e.entity_type=='DIMENSION' and e.geometry['text']['text_type']!=0]
    if preset_dimensions and old_scale!=source_scale:
        raise ValueError('Preset dimension import requires equal original source/target scales, even with sync_scale')
    if sync_scale and old_scale!=source_scale:
        if any(e.attributes['layer_group']==target_group for e in candidate.entities):
            raise ValueError('Synchronizing scale would change existing destination elements in real mm')
        candidate.set_group_scale(target_group,source_scale)
    if sync_group_name:candidate.set_group_name(target_group,source.get_group_name(source_group))
    if sync_layer_names:
        for layer in range(16):candidate.set_layer_name(target_group,layer,source.get_layer_name(source_group,layer))
    proposed=copy.deepcopy(source_defs)
    for number in required:
        info=block_name_info(proposed[number]['name'])
        if info.display_name in renames:
            if info.marker_status=='unrecognized':raise ValueError('Unknown name suffix cannot be renamed losslessly')
            proposed[number]['name']=definition_name(renames[info.display_name],info.compound_kind)
    if source_group!=target_group and any(child['type']=='BLOCK' and child['base']['pen_style']&64 for n in required for child in proposed[n]['entities']):
        raise ValueError('Nested source-group-priority transfer requires native verification')
    mapping={};created=[];reused=[];source_signatures={};destination_signatures={}
    for number in sorted(required):
        record=copy.deepcopy(proposed[number])
        name=block_name_info(record['name']).display_name
        matches=[r for r in destination_defs.values() if block_name_info(r['name']).display_name==name]
        if len(matches)>1:raise ValueError('Ambiguous destination definition name')
        if matches:
            if definition_signature(proposed,number,source_signatures)!=definition_signature(destination_defs,matches[0]['number'],destination_signatures):
                raise ValueError('Same-name definition differs in full contents: '+name)
            mapping[number]=matches[0]['number'];reused.append(mapping[number]);continue
        if any(child['type']=='BLOCK' for child in record['entities']):
            raise ValueError('New nested definition creation is unverified; identical existing graphs only')
        new_number=max(destination_defs,default=-1)+1;record['number']=new_number
        check(candidate,record,defined_numbers=set(destination_defs))
        candidate._new_block_records[new_number]=copy.deepcopy(record)
        candidate.block_definitions+=(CadBlockDefinition(new_number,record['name'],dict(record['base']),tuple(model_entity(e) for e in record['entities'])),)
        destination_defs[new_number]=record;mapping[number]=new_number;created.append(new_number)
    factor=source_scale/candidate.get_group_scale(target_group);added=[]
    for e in selected:
        record=entity_record(e)
        if record['type']=='BLOCK' and record['base']['pen_style']&64 and source_group!=target_group:
            raise ValueError('Source-group-priority block group transfer requires native verification')
        if record['type']=='TEXT' and record['content'].startswith('^'):raise ValueError('Controlled/image text import unsupported')
        preset=record['type']=='DIMENSION' and record['text']['text_type']!=0
        if preset:
            profile1=record['text']['text_type']==1 and record['base']['flag'] in (0,2)
            profile3=_observed_preset3(source,record,source_group)
            if not (source.version==700 and (profile1 or profile3) and factor==1
                and record['sxf_mode']==0
                and len(record['aux_lines'])==2 and len(record['aux_points'])==4
                and all(all(c[k]==0 for k in ('start_x','start_y','end_x','end_y')) for c in record['aux_lines'])
                and all(c['x']==c['y']==0 for c in record['aux_points'])
                and all(record[k]['base']['layer_group']==source_group for k in ('line','text'))):
                raise ValueError('Unverified preset dimension import profile')
            # Preserved internal group indices must retain their original
            # dependency settings in a different document. Do not silently
            # rebind dimension members to unrelated destination groups.
            internal_groups={m['base']['layer_group'] for m in children(record)}
            for dependency in internal_groups-{target_group}:
                if source.header['layer_groups'][dependency]!=destination.header['layer_groups'][dependency]:
                    raise ValueError('Preset dimension internal-group settings differ in destination')
                if (source.get_group_name(dependency)!=destination.get_group_name(dependency)
                    or any(source.get_layer_name(dependency,l)!=destination.get_layer_name(dependency,l) for l in range(16))):
                    raise ValueError('Preset dimension internal-group names differ in destination')
            # E111 preset1: outer group only. E120 native clipboard preset3:
            # outer and TEXT groups, retaining LINE/auxiliary groups and flags.
            # Identity coordinates must not be recalculated (signed zeros too).
            record['base']['layer_group']=target_group
            if profile3:record['text']['base']['layer_group']=target_group
        else:
            if factor!=1:transform(record,factor,(0.,0.))
            members=[record]+(children(record) if record['type']=='DIMENSION' else [])
            if any(m['base']['layer_group']!=source_group for m in members):
                raise ValueError('Mixed-group dimension internals require separate semantic verification')
            for member in members:member['base']['layer_group']=target_group
        if record['type']=='BLOCK':record['def_number']=mapping[record['def_number']]
        check(candidate,record)
        added.append(model_entity(record))
    candidate.entities+=tuple(added)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=before:raise ValueError('Source changed during import planning')
    return candidate,dict(source_sha256=before,added_count=len(added),created_definitions=created,
        reused_definitions=reused,definition_mapping=mapping,source_group=source_group,target_group=target_group,
        preset_dimensions_preserved=len(preset_dimensions),preset3_dimensions=sum(e.geometry['text']['text_type']==3 for e in preset_dimensions),
        preset_dimension_policy='Equal original scales only. Preset1: outer group only. Observed preset3/8192 profile: outer and TEXT groups; LINE/auxiliary groups and every flag retained.',
        paper_scale_factor=factor,settings=review,
        scope='No new nested/image/cross-version input. Opaque equality required unless destination policy is explicit; no original mutation')
