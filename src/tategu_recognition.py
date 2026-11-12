"""Read-only planar building-opening hypotheses from geometry and typed flag bits.

The caller must explicitly bind tolerances to the file or memory model. This
module does not load answer drawings, reference tables, DAT files or presets
of nominal opening widths. Curve-group numbers are descriptive output only.
"""
from pathlib import Path
import copy,hashlib,json,math
from cad_model import CadDocument
from writer.preserved import entity_record,_document_bytes
from _tategu_geometry import real_record,components,box
from _tategu_features import swing,folded,framed

__all__=['tategu_input_fingerprint','recognize_planar_tategu']


def _canonical(value):return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode('ascii')


def tategu_input_fingerprint(source,*,binding='file'):
    """Read-only fingerprint for an explicit per-input tolerance binding."""
    document=source if isinstance(source,CadDocument)else CadDocument.open(source)
    if binding=='file':
        if document._source_bytes is None or _document_bytes(document)!=document._source_bytes:
            raise ValueError('File-bound recognition requires the original unedited model')
        if document.source.read_bytes()!=document._source_bytes:raise ValueError('Recognition input file changed')
        return hashlib.sha256(document._source_bytes).hexdigest()
    if binding=='memory_model':
        return hashlib.sha256(_canonical(dict(records=[entity_record(e)for e in document.entities],
            scales=[document.get_group_scale(g)for g in range(16)]))).hexdigest()
    raise ValueError('Binding must be file or memory_model')


def _tolerances(document,config):
    value=copy.deepcopy(config)
    keys={'schema_version','binding','coincidence_mm','width_error_mm','position_error_mm','angle_rule'}
    if type(value)is not dict or set(value)!=keys or type(value['schema_version'])is not int or value['schema_version']!=1:
        raise ValueError('Explicit input-bound recognition tolerances required')
    binding=value['binding']
    if type(binding)is not dict or set(binding)!={'kind','sha256'}:raise ValueError('Invalid tolerance binding')
    if binding['sha256']!=tategu_input_fingerprint(document,binding=binding['kind']):
        raise ValueError('Tolerances are bound to a different input; explicit approval is required')
    for key in ('coincidence_mm','width_error_mm','position_error_mm'):
        if type(value[key])not in (int,float)or not math.isfinite(value[key])or value[key]<0:
            raise ValueError('Invalid recognition tolerance: '+key)
    if value['coincidence_mm']<=0:raise ValueError('Positive coincidence tolerance required')
    if value['angle_rule']!='atan(epsilon/longer_length)':raise ValueError('Unverified angular tolerance rule')
    return value


def _contained_fragments(parts,eps):
    """Attach fully contained decorations only to a unique multi-element body.

    No distance gap is bridged and no curve-group number is used. A four-line
    surrounding rectangle cannot swallow symbols as a parent body.
    """
    boxes=[box(p)for p in parts];parents={};ambiguous=[]
    for i,part in enumerate(parts):
        candidates=[];a=boxes[i]
        for j,body in enumerate(parts):
            if i==j or len(body)<=len(part)or len(body)<6:continue
            b=boxes[j]
            if b[0]-eps<=a[0]and b[1]-eps<=a[1]and b[2]+eps>=a[2]and b[3]+eps>=a[3]:candidates.append(j)
        if len(candidates)==1:parents[i]=candidates[0]
        elif candidates:ambiguous.append(dict(element_indices=[r['index']for r in part],reason='Decoration has multiple containing bodies'))
    merged={}
    for i,part in enumerate(parts):
        target=i
        while target in parents:target=parents[target]
        merged.setdefault(target,[]).extend(part)
    return list(merged.values()),ambiguous


def _deduplicate(hypotheses,eps,width_eps):
    kept=[]
    for h in sorted(hypotheses,key=lambda x:(x['position_real_mm'],x['type_candidates'],x['clear_width_mm']if x['clear_width_mm']is not None else float('inf'))):
        h['element_indices']=sorted(set(h['element_indices']))
        duplicate=next((old for old in kept if old['type_candidates']==h['type_candidates'] and
            ((old['clear_width_mm']is None and h['clear_width_mm']is None)or
             (old['clear_width_mm']is not None and h['clear_width_mm']is not None and abs(old['clear_width_mm']-h['clear_width_mm'])<=width_eps)) and
            math.dist(old['position_real_mm'],h['position_real_mm'])<=eps and
            len(set(old['element_indices'])&set(h['element_indices']))>=min(len(old['element_indices']),len(h['element_indices']))/2),None)
        if duplicate is None:kept.append(h)
        else:
            duplicate['element_indices']=sorted(set(duplicate['element_indices'])|set(h['element_indices']))
            duplicate['evidence']=list(dict.fromkeys(duplicate['evidence']+h['evidence']))
    # Alternative interpretations of a shared opening stay alternatives.
    result=[]
    while kept:
        h=kept.pop(0);alternatives=[h];rest=[]
        for other in kept:
            common=set(h['element_indices'])&set(other['element_indices'])
            if common and len(common)>=min(len(h['element_indices']),len(other['element_indices']))/2:alternatives.append(other)
            else:rest.append(other)
        kept=rest
        if len(alternatives)>1:
            kinds=sorted({kind for a in alternatives for kind in a['type_candidates']})
            widths=[a['clear_width_mm']for a in alternatives]
            h=dict(h,type_candidates=kinds,alternatives=alternatives,
                ambiguities=['複数の種類または内法測定位置が同じ図形に当てはまる'],
                clear_width_mm=widths[0]if None not in widths and max(widths)-min(widths)<=width_eps else None)
        result.append(h)
    return result


def recognize_planar_tategu(source,*,tolerances,include_unmarked=True,max_candidate_pairs=2000000):
    """Return planar-symbol candidates, evidence and unresolved geometry; never edit.

    Frame measurements use inner faces/profiles, radial leaves or a folded
    opening baseline. Exterior symbol bounds are never substituted for width.
    Caller-supplied reference answers or arbitrary callbacks are not accepted.
    """
    if type(include_unmarked)is not bool or type(max_candidate_pairs)is not int or max_candidate_pairs<1:
        raise ValueError('Invalid recognition options')
    document=source if isinstance(source,CadDocument)else CadDocument.open(source)
    options=_tolerances(document,tolerances);eps=options['coincidence_mm']
    before=tategu_input_fingerprint(document,binding=options['binding']['kind'])
    query={'any':[
        {'all':[{'field':'entity_type','in':['LINE']},{'field':'flag_bits','mask':0x1000,'mode':'all_set'}]},
        {'all':[{'field':'entity_type','in':['ARC','CIRCLE']},{'field':'flag_bits','mask':0x0080,'mode':'all_set'}]},
        {'all':[{'field':'entity_type','in':['TEXT']},{'field':'flag_bits','mask':0x2000,'mode':'all_set'}]}]}
    marked=set(document.find_entities(query=query));rows=[];unsupported=[];excluded=[];ambiguities=[];candidate_list=[]
    for i,e in enumerate(document.entities):
        if e.entity_type not in ('LINE','ARC','CIRCLE'):
            if i in marked:unsupported.append(dict(index=i,kind=e.entity_type,reason='Marked text is not geometry; no symbol-code interpretation in this stage'))
            elif e.entity_type not in ('TEXT','POINT'):unsupported.append(dict(index=i,kind=e.entity_type,reason='Non-planar-primitive/composite kind outside first recognizer'))
            continue
        if i not in marked and not include_unmarked:continue
        try:
            scale=document.get_group_scale(e.attributes['layer_group'])
            if not math.isfinite(scale)or scale<=0:raise ValueError('Invalid group scale')
            rows.append(real_record(e,i,scale,i in marked))
        except ValueError as exc:unsupported.append(dict(index=i,kind=e.entity_type,reason=str(exc)))
    for marked_pool in (True,False):
        pool=[r for r in rows if r['marked']==marked_pool]
        parts,uncertain=_contained_fragments(components(pool,eps,max_candidate_pairs),eps);ambiguities.extend(uncertain)
        for part in parts:
            if len(part)>512:
                unsupported.append(dict(element_indices=[r['index']for r in part],reason='Connected geometry exceeds the first recognizer component limit (512)'))
                continue
            try:
                hypotheses=swing(part,eps,options['width_error_mm'])
                hypotheses+=folded(part,eps)+framed(part,eps)
            except ValueError as exc:
                unsupported.append(dict(element_indices=[r['index']for r in part],reason=str(exc)))
                continue
            hypotheses=_deduplicate(hypotheses,eps,options['width_error_mm'])
            if not hypotheses:
                excluded.append(dict(element_indices=sorted(r['index']for r in part),bbox_real_mm=list(box(part)),
                    marked=marked_pool,reason='No supported radial leaf, folded double-edge baseline or framed pane/offset-rail evidence'))
            for h in hypotheses:
                h.update(candidate_id='C'+str(len(candidate_list)+1).zfill(3),
                    candidate_source='typed_flag_bits'if marked_pool else 'unmarked_geometry',
                    curve_group_numbers=sorted({document.entities[i].attributes['group']for i in h['element_indices']}),
                    curve_group_used_for_classification=False,confidence='ambiguous'if h['ambiguities']else 'geometry_supported')
                signatures=[]
                for r in part:
                    if r['index']not in h['element_indices']:continue
                    if r['kind']=='LINE':signature=('LINE',tuple(sorted((r['a'],r['b']))))
                    else:signature=(r['kind'],r['center'],r['radius'],r['start'],r['sweep'])
                    signatures.append(signature)
                if len(signatures)!=len(set(signatures)):
                    h['ambiguities'].append('重複する保存図形があり、重ね描きと複数建具を一意に分離できない')
                    h['confidence']='ambiguous'
                candidate_list.append(h)
            if hypotheses:
                used={i for h in hypotheses for i in h['element_indices']}
                unassigned=sorted(r['index']for r in part if r['index']not in used)
                if unassigned:excluded.append(dict(element_indices=unassigned,marked=marked_pool,
                    reason='Connected context/fragments not assigned to a supported hypothesis'))
    after=tategu_input_fingerprint(document,binding=options['binding']['kind'])
    if before!=after:raise ValueError('Recognition input changed; discard result')
    return dict(schema_version=1,input_fingerprint=before,tolerances=options,
        recognized_candidates=candidate_list,excluded=excluded,unsupported=unsupported,
        unresolved_associations=ambiguities,complete=not unsupported and not ambiguities and not any(c['ambiguities']for c in candidate_list) and not any(x['marked']for x in excluded),
        typed_flag_query=query,marked_element_indices=sorted(marked),
        group_numbers_used_for_classification=False,nominal_widths_or_DAT_templates_used=False,
        limitations=['Planar feature hypotheses only; no elevations/sections/template reproduction.',
            'No automatic application of a tolerance set to another input.',
            'Opening handedness/inside-outside needs an external convention; not inferred.',
            'Unmatched marked fragments are reported; exclusion is not proof that an item is not a door.'])
