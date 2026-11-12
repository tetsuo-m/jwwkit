"""Observed header display states; writing selections are read-only here."""
import copy
from writer.header import group_index

NAMES={0:'hidden',1:'display_only',2:'editable',3:'writing'}

def state_value(value):
    if type(value) is str:
        reverse={name:raw for raw,name in NAMES.items()}
        if value not in reverse:raise ValueError('Unknown display state name')
        return reverse[value]
    if type(value) is not int or value not in NAMES:
        raise ValueError('Display state must be hidden/display_only/editable/writing or integer 0..3')
    return value

def describe(raw):
    raw=state_value(raw)
    return dict(raw_value=raw,state=NAMES[raw],visible=raw!=0,editable=raw in (2,3),selected_for_writing=raw==3)

def get_state(document,layer_group,layer=None):
    g=group_index(layer_group);group=document.header['layer_groups'][g]
    if layer is None:return describe(group['state'])
    l=group_index(layer);result=describe(group['layers'][l]['state'])
    parent=describe(group['state'])
    result.update(effective_visible=parent['visible'] and result['visible'],
        effective_editable=parent['editable'] and result['editable'])
    return result

def set_state(document,layer_group,state,layer=None):
    g=group_index(layer_group);l=None if layer is None else group_index(layer)
    value=state_value(state);group=document.header['layer_groups'][g]
    record=group if l is None else group['layers'][l]
    old=state_value(record['state'])
    if old==value:return
    if old==3 or value==3:
        raise ValueError('Writing-group/layer selection cannot be changed by display-state API')
    if group['protect'] or record['protect']:
        raise ValueError('Protected group/layer display changes are unverified')
    staged=copy.copy(document);staged.header=copy.deepcopy(document.header)
    staged._state_edits=dict(document._state_edits);staged._state_edits[g,l]=value
    target=staged.header['layer_groups'][g]
    if l is not None:target=target['layers'][l]
    target['state']=value
    from writer.preserved import _document_bytes
    _document_bytes(staged)
    document.header=staged.header;document._state_edits=staged._state_edits
