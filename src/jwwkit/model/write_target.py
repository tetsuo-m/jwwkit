"""Move the write group / write layer the way Jw_cad 10.03.6 does (#63).

Observed with Jw_cad 10.03.6 (v700 samples W1-W7 in tests/fixtures/jwcad_write):
- the drawing's write group is the only group in state 3 (writing); in every group the only layer in
  state 3 is that group's write layer;
- switching sets the new group/layer to 3 whatever its state was (hidden or display-only too) and the
  old one to 2 (editable); the old state of the new target is not kept; nothing else changes;
- on every save Jw_cad puts its 6 settings texts (metadata_settings) on the write group and layer.
  jwwkit does the same, but only when set_write_target moves the write target.
Any other layout (no single writing group, a write layer not in state 3, protected groups/layers,
settings texts elsewhere, v600 or older) is refused.
"""
import copy

from jwwkit.writer.header import group_index

RESAVE_HINT = '; open and save the drawing in Jw_cad in the Ver.7.00 format to use it'


def _check_layout(header, group):
    """The observed Jw_cad layout of one group: exactly one layer in state 3, the group's write layer."""
    g = header['layer_groups'][group]
    writing = [i for i, layer in enumerate(g['layers']) if layer['state'] == 3]
    if writing != [g['write_layer']]:
        raise ValueError(f'Write layer of group {group} is not in the observed Jw_cad layout '
                         '(exactly one layer in the writing state, the group\'s write layer)')


def current_write_target(header):
    groups = header['layer_groups']
    writing = [i for i, g in enumerate(groups) if g['state'] == 3]
    wg = header['write_layer_group']
    if type(wg) is not int or writing != [wg]:
        raise ValueError('Write group is not in the observed Jw_cad layout '
                         '(exactly one group in the writing state, the drawing\'s write group)')
    _check_layout(header, wg)
    return wg, groups[wg]['write_layer']


def set_write_target(document, layer_group, layer):
    g, l = group_index(layer_group), group_index(layer)
    version = document._source_records['version'] if document._source_records else document.version
    if version != 700:
        raise ValueError(f'Moving the write group/layer is verified only for JWW v700 (this drawing is v{version})'
                         + RESAVE_HINT)
    header = document.header
    old_g, old_l = current_write_target(header)
    _check_layout(header, g)
    if (old_g, old_l) == (g, l):
        return
    groups = header['layer_groups']
    old_target_layer = groups[g]['write_layer']
    for gi, li in {(old_g, None), (old_g, old_l), (g, None), (g, l), (g, old_target_layer)}:
        record = groups[gi] if li is None else groups[gi]['layers'][li]
        if groups[gi]['protect'] or record['protect']:
            raise ValueError('Protected group/layer: moving the write group/layer there is unverified')
        if (gi, li) in document._state_edits:
            raise ValueError('A display state of this group/layer was already changed; move the write '
                             'group/layer first, then change the states')
    source_target = current_write_target(document._source_header)
    for index in document._source_metadata_indices:
        base = document._source_records['entities'][index]['base']
        if (base['layer_group'], base['layer']) != source_target:
            raise ValueError('Jw_cad settings texts are not on the write group/layer; this layout is unverified')
    staged = copy.copy(document)
    staged.header = copy.deepcopy(header)
    _move(staged.header, g, l)
    staged._write_moves = document._write_moves + ((g, l),)
    from jwwkit.writer.preserved import _document_bytes
    _document_bytes(staged)
    document.header = staged.header
    document._write_moves = staged._write_moves


def _move(header, g, l):
    """One switch as Jw_cad does it: the new group/layer to 3, the old one to 2, nothing else."""
    groups = header['layer_groups']
    old_g = header['write_layer_group']
    if old_g != g:
        groups[old_g]['state'] = 2
        groups[g]['state'] = 3
        header['write_layer_group'] = g
    old_l = groups[g]['write_layer']
    if old_l != l:
        groups[g]['layers'][old_l]['state'] = 2
        groups[g]['layers'][l]['state'] = 3
        groups[g]['write_layer'] = l


def apply_to_header(expected, moves):
    """Replay the moves, in order, on a copy of the source header."""
    for g, l in moves:
        _move(expected, g, l)