"""Typed numeric, text, flag, direction and saved-state query predicates."""
import copy
import math
from .query_text import normalize, width_fold, no_inline_flags,normalization_options,equivalent_text


def leaf(compiler,node):
    from .query import NA,Uncertain,_keys,_number
    field=node.get('field');document=compiler.document
    canonical=copy.deepcopy(node)
    def content(entity):
        if entity.entity_type=='TEXT':return entity.geometry
        if entity.entity_type=='DIMENSION':return entity.geometry.get('text')
        return None
    if field=='text':
        _keys(node,{'field','match','value','width_fold','ignore_case','normalization'},{'field','match','value'})
        match=node['match'];value=node['value'];fold=node.get('width_fold',False);ignore=node.get('ignore_case',False)
        if match not in ('contains','prefix','exact','regex') or type(value)is not str:
            raise ValueError('Invalid text search mode/value')
        if type(fold)is not bool or type(ignore)is not bool:raise ValueError('Text switches must be booleans')
        if len(value)>16384:raise ValueError('Search text exceeds 16384 characters')
        options=None
        if 'normalization'in node:
            if 'width_fold'in node or 'ignore_case'in node:raise ValueError('Do not mix normalization with legacy text switches')
            options=normalization_options(node['normalization'],match)
            canonical['normalization']=options;compiler.text_equivalence=True
            if options['hyphens']=='dash_and_prolonged':compiler.text_warnings.add('Prolonged sound marks and hyphens are treated alike; meaning may differ')
            ignore=options['case']=='regex_ignorecase'
        else:canonical.update(width_fold=fold,ignore_case=ignore)
        transform=lambda text:equivalent_text(text,options)if options is not None else normalize(text,fold,ignore)
        if match=='regex':
            if len(value)>512 or len(compiler.regexes)>=8:raise ValueError('Regex pattern/count limit exceeded')
            no_inline_flags(value)
            if fold and width_fold(value)!=value:raise ValueError('Write regex against width-folded text; pattern is not rewritten')
            if options is not None and equivalent_text(value,options)!=value:raise ValueError('Write regex against normalized subjects; pattern is never rewritten')
            task=dict(pattern=value,ignore_case=ignore,fold=fold,matches={},normalization=options)
            compiler.regexes.append(task)
        else:
            original_value=value;value=transform(value)
            if options is not None and original_value and not value:raise ValueError('Normalization erased the entire search value')
        def evaluate(entity,index):
            geometry=content(entity)
            if geometry is None:return NA if entity.entity_type not in ('TEXT','DIMENSION') else Uncertain('Missing dimension text')
            text=geometry.get('content')
            if type(text)is not str:return Uncertain('Invalid text content')
            if len(text)>16384:raise ValueError('Search input text exceeds 16384 characters')
            if match=='regex':return task['matches'][index]
            text=transform(text)
            if match=='contains':return value in text
            if match=='prefix':return text.startswith(value)
            return value==text
        if options is not None:
            def explanation(entity,index):
                raw=content(entity)['content']
                return dict(index=index,field='text',match=match,original_text=raw,effective_text=transform(raw),
                    input_value=node['value'],effective_value=value,normalization=copy.deepcopy(options),
                    reason='regex_on_normalized_subject'if match=='regex'else 'literal_on_normalized_text',
                    warnings=['Prolonged sound marks and hyphens are treated alike; meaning may differ']if options['hyphens']=='dash_and_prolonged'else [])
            compiler.text_explanations.append((evaluate,explanation))
        return evaluate,canonical
    if field=='flag_bits':
        _keys(node,{'field','mask','mode'},{'field','mask','mode'})
        mask=node['mask'];mode=node['mode']
        if type(mask)is not int or not 1<=mask<=65535 or mode not in ('all_set','all_clear'):
            raise ValueError('Flag mask must be uint16 nonzero; mode all_set/all_clear')
        def evaluate(entity,index):
            value=entity.attributes.get('flag')
            if type(value)is not int or not 0<=value<=65535:return Uncertain('Invalid stored flag')
            return value & mask == (mask if mode=='all_set' else 0)
        return evaluate,canonical
    if field in ('group_state','layer_state'):
        from .display_state import state_value
        _keys(node,{'field','in'},{'field','in'})
        values=node['in']
        if type(values)is not list or not 1<=len(values)<=1024:raise ValueError('State in requires 1..1024 values')
        values=[state_value(v) for v in values];canonical['in']=list(dict.fromkeys(values));accepted=set(values)
        cache={}
        def evaluate(entity,index):
            group=entity.attributes.get('layer_group');layer=entity.attributes.get('layer')
            if type(group)is not int or not 0<=group<16 or type(layer)is not int or not 0<=layer<16:
                return Uncertain('Invalid group/layer for display state')
            key=(group,layer if field=='layer_state' else None)
            if key not in cache:
                stored=document.header['layer_groups'][group]
                if field=='layer_state':stored=stored['layers'][layer]
                cache[key]=state_value(stored['state'])
            return cache[key] in accepted
        return evaluate,canonical
    if field=='line_angle':
        _keys(node,{'field','min','max','units','tolerance','wrap'}, {'field','min','max','units','tolerance'})
        units=node['units'];low=_number(node['min']);high=_number(node['max']);tol=_number(node['tolerance'])
        wrap=node.get('wrap',False)
        if units not in ('deg','rad') or type(wrap)is not bool:raise ValueError('Invalid line angle units/wrap')
        factor=1 if units=='deg' else 180/math.pi
        low*=factor;high*=factor;tol*=factor
        if not 0<=low<180 or not 0<=high<180 or not 0<=tol<=90 or wrap!=(low>high):
            raise ValueError('Line angle bounds are [0,180), tolerance [0,90]; crossing zero requires wrap=true')
        canonical.update(wrap=wrap)
        def evaluate(entity,index):
            if entity.entity_type!='LINE':return NA
            geometry=entity.geometry
            dx=geometry['end_x']-geometry['start_x'];dy=geometry['end_y']-geometry['start_y']
            if not math.isfinite(dx) or not math.isfinite(dy) or dx==dy==0:return Uncertain('Zero-length/nonfinite line has no direction')
            # Positive isotropic group scale leaves this real-coordinate orientation unchanged.
            if index not in compiler.definition_keys:
                scale=compiler.scale(entity.attributes['layer_group'])
                if isinstance(scale,Uncertain):return scale
            angle=math.degrees(math.atan2(dy,dx))%180
            inside=(angle>=low or angle<=high) if wrap else low<=angle<=high
            distance=min(abs(angle-low),180-abs(angle-low),abs(angle-high),180-abs(angle-high))
            return inside or distance<=tol
        return evaluate,canonical
    if field=='rect':
        _keys(node,{'field','bounds','units','mode'},{'field','bounds','units','mode'})
        bounds=node['bounds'];units=node['units'];mode=node['mode']
        if type(bounds)is not list or len(bounds)!=4:raise ValueError('Rectangle requires four bounds')
        bounds=tuple(_number(v) for v in bounds)
        if bounds[0]>bounds[2] or bounds[1]>bounds[3] or units not in ('real','paper') or mode not in ('anchor','intersects','contained'):
            raise ValueError('Invalid rectangle bounds/units/mode')
        compiler.real_requested |= units=='real'
        def evaluate(entity,index):
            scale=compiler.scale(entity.attributes['layer_group']) if units=='real' else 1
            if isinstance(scale,Uncertain):return scale
            rect=tuple(v/scale for v in bounds)
            if mode!='anchor':
                from .spatial import matches
                try:return matches(entity,rect,mode)
                except ValueError as exc:return Uncertain(str(exc))
            geometry=entity.geometry;kind=entity.entity_type
            if kind=='DIMENSION':geometry=geometry['line'];kind='LINE'
            keys={'LINE':('start_x','start_y'),'TEXT':('start_x','start_y'),
                  'CIRCLE':('center_x','center_y'),'ARC':('center_x','center_y'),
                  'POINT':('x','y'),'BLOCK':('ref_x','ref_y'),
                  'SOLID':('point1_x','point1_y'),'CIRCLE_SOLID':('center_x','center_y')}
            if kind not in keys:return Uncertain('Unverified rectangle anchor')
            x,y=(geometry[k] for k in keys[kind])
            if not math.isfinite(x) or not math.isfinite(y):return Uncertain('Nonfinite rectangle anchor')
            return rect[0]<=x<=rect[2] and rect[1]<=y<=rect[3]
        return evaluate,canonical
    if field not in ('length','radius','text_width','text_height','pen_width'):
        raise ValueError('Unknown search field: '+str(field))
    allowed={'field','min','max','units'} | ({'basis'} if field.startswith('text_') else set())
    _keys(node,allowed,{'field','units'})
    if not ('min' in node or 'max' in node):raise ValueError('A numeric range needs min and/or max')
    low=_number(node['min']) if 'min'in node else None;high=_number(node['max']) if 'max'in node else None
    if (low is not None and low<0) or (high is not None and high<0) or (low is not None and high is not None and low>high):
        raise ValueError('Invalid nonnegative numeric range')
    units=node['units'];expected=('real','paper') if field in ('length','radius') else ('stored',) if field=='pen_width' else ('paper',)
    if units not in expected:raise ValueError('Explicit valid units required for '+field)
    compiler.real_requested |= units=='real'
    basis=node.get('basis','effective')
    if field.startswith('text_'):
        if basis not in ('stored','effective'):raise ValueError('Unknown text size basis')
        canonical['basis']=basis
    presets={}
    def evaluate(entity,index):
        kind=entity.entity_type;geometry=entity.geometry
        if field=='pen_width':value=entity.attributes.get('pen_width')
        elif field.startswith('text_'):
            geometry=content(entity)
            if geometry is None:return NA if kind not in ('TEXT','DIMENSION') else Uncertain('Missing dimension text')
            if basis=='effective':
                text_type=geometry.get('text_type')
                if type(text_type)is not int or not 0<=text_type<=10:return Uncertain('Unverified text preset')
                if text_type:
                    if text_type not in presets:
                        try:presets[text_type]=document.get_text_preset(text_type)
                        except ValueError as exc:return Uncertain(str(exc))
                    geometry=presets[text_type]
            value=geometry.get('size_x' if field=='text_width' else 'size_y')
        else:
            if kind not in (('LINE','CIRCLE','ARC') if field=='length' else ('CIRCLE','ARC')):return NA
            if kind=='LINE':value=math.hypot(geometry['end_x']-geometry['start_x'],geometry['end_y']-geometry['start_y'])
            else:
                if geometry.get('flatness')!=1:return Uncertain('Ellipse length/radius is not a verified circular measure')
                radius=geometry['radius']
                if not math.isfinite(radius) or radius<=0:return Uncertain('Degenerate/nonfinite circular radius')
                if field=='radius':value=radius
                else:
                    sweep=2*math.pi if kind=='CIRCLE' else abs(geometry['arc_angle'])
                    if not 0<sweep<=2*math.pi:return Uncertain('Unverified arc sweep')
                    value=radius*sweep
            if units=='real':
                scale=compiler.scale(entity.attributes['layer_group'])
                if isinstance(scale,Uncertain):return scale
                value*=scale
        if type(value)not in (int,float) or not math.isfinite(value) or value<0:return Uncertain('Invalid numeric stored field: '+field)
        return (low is None or value>=low) and (high is None or value<=high)
    return evaluate,canonical
