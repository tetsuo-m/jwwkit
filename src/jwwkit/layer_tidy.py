"""Tidy a target drawing's layer groups/layers after a sample drawing (#56).

The sample holds only the architecture, already sorted into groups and layers. Elements of the target that
match a sample element by shape and position (real mm, every element whatever its display state) are moved to
that element's group and layer; only the group and layer change. Elements with no counterpart in the sample
(electrical symbols and so on) stay where they are, or move to a chosen empty group/layer.

Matching uses compare_drawings (exact, then unique same-shape pairs, then lines split differently that cover
each other) and adds one rule of its own: a target line wholly covered by sample lines whose destinations are
one and the same. Nothing is guessed: pairs whose destination is not unique, partly overlapping lines,
unsupported elements, moves between groups of different scales and moves the editing API refuses are listed
and left alone. The result is a review and a safe_edit plan; executing the plan needs the usual approval.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from jwwkit.cad_model import CadDocument
from jwwkit.drawing_comparison import compare_drawings

__all__ = ['analyze', 'write_plan']

# Floating-point noise allowed on top of position_tolerance when testing that a point lies on a line (real mm).
# Jw_cad stores split points as computed doubles, so an exact zero cannot be asked for.
COVER_EPSILON = 1e-9
REASONS = {
    'ambiguous': 'The destination is not unique (several sample elements of the same shape on different layers)',
    'partial_line': 'A line only partly overlaps the sample lines',
    'unsupported': 'compare_drawings does not support this element',
    'scale': 'The source group and the destination group have different scales',
    'edit_refused': 'The editing API refuses to change this element',
}


def _slot(entity):
    return (entity.attributes['layer_group'], entity.attributes['layer'])


def _scale(document, group):
    return document.get_group_scale(group)


def _real_line(document, entity):
    g = entity.attributes['layer_group']
    geometry = entity.geometry
    a = document.convert_point((geometry['start_x'], geometry['start_y']), layer_group=g, from_units='paper', to_units='real')
    b = document.convert_point((geometry['end_x'], geometry['end_y']), layer_group=g, from_units='paper', to_units='real')
    return a, b


def _covers(line, point, tolerance):
    (ax, ay), (bx, by) = line
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length == 0:
        return False
    px, py = point[0] - ax, point[1] - ay
    distance = abs(dx * py - dy * px) / length
    along = (dx * px + dy * py) / length
    limit = tolerance + COVER_EPSILON
    return distance <= limit and -limit <= along <= length + limit


def _one_sided_cover(sample, target, candidates, sample_lines, tolerance):
    """Target lines wholly inside one sample line. Returns {target index: [sample indices covering it]}."""
    out = {}
    lines = [(i, _real_line(sample, sample.entities[i])) for i in sample_lines]
    for t in candidates:
        entity = target.entities[t]
        if entity.entity_type != 'LINE':
            continue
        a, b = _real_line(target, entity)
        covering = [i for i, line in lines if _covers(line, a, tolerance) and _covers(line, b, tolerance)]
        if covering:
            out[t] = covering
    return out


def _check_settings(value, what):
    if value not in ('keep', 'sample'):
        raise ValueError(f"{what} must be 'keep' or 'sample'")


def analyze(sample, target, *, position_tolerance=0.0, unmatched='keep', layer_settings='keep',
            group_settings='keep', strict=False):
    """Match the target against the sample and decide where each target element goes. No file is written.

    unmatched: 'keep', or ('move', layer_group, layer) for target elements with no counterpart in the sample.
    layer_settings / group_settings: 'keep' (report differences only) or 'sample' (make the destination
    layers/groups take the sample's state and name; group scales are never changed).
    """
    _check_settings(layer_settings, 'layer_settings')
    _check_settings(group_settings, 'group_settings')
    if type(strict) is not bool:
        raise ValueError('strict must be True or False')
    if unmatched != 'keep':
        if (not isinstance(unmatched, (tuple, list)) or len(unmatched) != 3 or unmatched[0] != 'move'
                or any(type(v) is not int or not 0 <= v < 16 for v in unmatched[1:])):
            raise ValueError("unmatched must be 'keep' or ('move', layer_group, layer)")
    if type(position_tolerance) not in (int, float) or not math.isfinite(position_tolerance) or position_tolerance < 0:
        raise ValueError('position_tolerance must be a finite number of 0 or more (real mm)')
    sample_path, target_path = Path(sample).resolve(), Path(target).resolve()
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (sample_path, target_path)}
    comparison = compare_drawings(sample_path, target_path, units='real', position_tolerance=position_tolerance,
                                  line_coverage=True)
    s_doc, t_doc = CadDocument.open(sample_path), CadDocument.open(target_path)
    for p, h in hashes.items():
        if hashlib.sha256(p.read_bytes()).hexdigest() != h:
            raise ValueError('An input drawing changed while it was being read')
    if len(s_doc.entities) != len(comparison['left_entities']) or len(t_doc.entities) != len(comparison['right_entities']):
        raise ValueError('Element numbering of compare_drawings and CadDocument differ')

    destination = {}      # target index -> (group, layer)
    how = {}              # target index -> how it was matched
    listed = defaultdict(list)  # reason -> target indices left alone
    sample_matched = set()

    def assign(target_indices, sample_indices, kind):
        slots = {_slot(s_doc.entities[i]) for i in sample_indices}
        if len(slots) != 1:
            for t in target_indices:
                listed['ambiguous'].append(t)
            return
        slot = slots.pop()
        sample_matched.update(sample_indices)
        for t in target_indices:
            destination[t] = slot
            how[t] = kind

    for match in comparison['matches']:
        kind = 'line_partition' if match['category'] == 'line_partition_equivalent' else 'shape'
        if len(match['right_indices']) > 1 and kind == 'shape':
            kind = 'overlap'
        assign(match['right_indices'], match['left_indices'], kind)
    for component in comparison['ambiguous']:
        # Same shapes on both sides: move them only if every sample element of the group has one destination.
        assign(component['right_indices'], component['left_indices'], 'overlap')
    partial_targets = [t for c in comparison['partial_lines'] for t in c['right_indices']]
    leftover = sorted(set(comparison['added']) | set(partial_targets))
    sample_lines = [i for i, e in enumerate(s_doc.entities) if e.entity_type == 'LINE']
    covered = _one_sided_cover(s_doc, t_doc, leftover, sample_lines, position_tolerance)
    for t, sample_indices in covered.items():
        assign([t], sample_indices, 'line_cover')
    for t in partial_targets:
        if t not in destination and t not in listed['ambiguous']:
            listed['partial_line'].append(t)
    unsupported_targets = [u['index'] for u in comparison['unsupported'] if u['side'] == 'right']
    listed['unsupported'].extend(t for t in unsupported_targets if t not in destination)
    decided = set(destination) | {t for v in listed.values() for t in v}
    unmatched_targets = [t for t in sorted(set(comparison['added'])) if t not in decided]
    sample_only = [i for i in comparison['deleted'] if i not in sample_matched]

    # (b) move the unmatched elements to an empty group/layer that the sample does not use.
    if unmatched != 'keep':
        slot = (unmatched[1], unmatched[2])
        if any(_slot(e) == slot for e in t_doc.entities):
            raise ValueError(f'The layer {slot} for unmatched elements is not empty in the target drawing')
        if any(_slot(e) == slot for e in s_doc.entities):
            raise ValueError(f'The layer {slot} for unmatched elements is used in the sample drawing')
        for t in unmatched_targets:
            destination[t] = slot
            how[t] = 'unmatched'

    # Groups of different scales: refuse (no conversion).
    for t, slot in list(destination.items()):
        source_group = t_doc.entities[t].attributes['layer_group']
        scales = {_scale(t_doc, source_group), _scale(t_doc, slot[0])}
        if how[t] != 'unmatched':
            scales.add(_scale(s_doc, slot[0]))
        if len(scales) != 1:
            del destination[t]
            listed['scale'].append(t)

    already = sorted(t for t, slot in destination.items() if _slot(t_doc.entities[t]) == slot)
    moves = {t: slot for t, slot in destination.items() if _slot(t_doc.entities[t]) != slot}

    # Ask the editing API on a staged copy; elements it refuses are listed (or the whole run stops).
    staged = CadDocument.open(target_path)
    for t in sorted(moves):
        try:
            staged.set_entity_attributes(t, layer_group=moves[t][0], layer=moves[t][1])
        except ValueError as exc:
            listed['edit_refused'].append(t)
            how[t] = f'edit_refused: {str(exc)[:160]}'
    for t in listed['edit_refused']:
        moves.pop(t, None)
    if strict and any(listed.values()):
        reasons = {k: len(v) for k, v in listed.items() if v}
        raise ValueError(f'strict=True: some target elements cannot be moved {reasons}')

    used = sorted(set(moves.values()))
    settings = _settings_review(s_doc, t_doc, used, layer_settings, group_settings)
    attribute_counts = Counter(c['field'] for m in comparison['matches'] for c in m['attribute_changes']
                               if c['field'] not in ('.layer_group', '.layer'))
    review = dict(
        schema='jwwkit.layer_tidy.review/1',
        sample=dict(path=str(sample_path), sha256=hashes[sample_path], elements=len(s_doc.entities)),
        target=dict(path=str(target_path), sha256=hashes[target_path], elements=len(t_doc.entities)),
        options=dict(position_tolerance=position_tolerance, units='real',
                     unmatched=list(unmatched) if unmatched != 'keep' else 'keep',
                     layer_settings=layer_settings, group_settings=group_settings, strict=strict),
        counts=dict(
            move=len(moves),
            move_by_destination={f'{g}-{l}': n for (g, l), n in sorted(Counter(moves.values()).items())},
            move_by_match=dict(Counter(how[t] for t in moves)),
            already_in_place=len(already),
            unmatched=len(unmatched_targets),
            unmatched_action='keep' if unmatched == 'keep' else f'move to {unmatched[1]}-{unmatched[2]}',
            left_alone={k: len(v) for k, v in listed.items() if v},
            refused_for_scale=len(listed['scale']),
            sample_only=len(sample_only),
            sample_only_by_type=dict(Counter(s_doc.entities[i].entity_type for i in sample_only)),
            attribute_differences_in_matches=dict(attribute_counts),
        ),
        left_alone=[dict(index=t, reason=REASONS[k] if not how.get(t, '').startswith('edit_refused') else how[t],
                         kind=k, type=t_doc.entities[t].entity_type, slot=list(_slot(t_doc.entities[t])))
                    for k, v in listed.items() for t in sorted(v)],
        settings=settings,
        compare_complete=comparison['complete'],
    )
    return dict(review=review, moves=moves, settings_actions=settings['actions'], target=target_path)


def _state_value(state):
    return state['raw_value'] if isinstance(state, dict) else state


def _settings_review(s_doc, t_doc, slots, layer_settings, group_settings):
    """Differences of the destination layers/groups (state and name) and, for 'sample', the actions."""
    rows, actions = [], []
    groups = sorted({g for g, _ in slots})
    for g in groups:
        before = dict(state=_state_value(t_doc.get_group_state(g)), name=t_doc.get_group_name(g))
        sample = dict(state=_state_value(s_doc.get_group_state(g)), name=s_doc.get_group_name(g))
        if before != sample:
            rows.append(dict(kind='group', layer_group=g, target=before, sample=sample))
            if group_settings == 'sample':
                if before['name'] != sample['name']:
                    actions.append(dict(op='set_group_name', kwargs=dict(layer_group=g, name=sample['name'])))
                if before['state'] != sample['state']:
                    actions.append(dict(op='set_group_state', kwargs=dict(layer_group=g, state=sample['state'])))
    for g, l in slots:
        before = dict(state=_state_value(t_doc.get_layer_state(g, l)), name=t_doc.get_layer_name(g, l))
        sample = dict(state=_state_value(s_doc.get_layer_state(g, l)), name=s_doc.get_layer_name(g, l))
        if before != sample:
            rows.append(dict(kind='layer', layer_group=g, layer=l, target=before, sample=sample))
            if layer_settings == 'sample':
                if before['name'] != sample['name']:
                    actions.append(dict(op='set_layer_name', kwargs=dict(layer_group=g, layer=l, name=sample['name'])))
                if before['state'] != sample['state']:
                    actions.append(dict(op='set_layer_state', kwargs=dict(layer_group=g, layer=l, state=sample['state'])))
    # Try the setting actions on a staged copy; refused ones (writing state, protection) are listed, not applied.
    staged = copy.copy(t_doc)
    staged.header = copy.deepcopy(t_doc.header)
    staged._name_edits = dict(t_doc._name_edits)
    staged._state_edits = dict(t_doc._state_edits)
    accepted, refused = [], []
    for action in actions:
        try:
            getattr(staged, action['op'])(**action['kwargs'])
            accepted.append(action)
        except ValueError as exc:
            refused.append(dict(action=action, reason=str(exc)[:200]))
    return dict(differences=rows, actions=accepted, refused=refused)


def write_plan(sample, target, output, plan_path, *, review_path=None, **options):
    """Analyze, then write the safe_edit plan (approval needed to execute) and the review JSON.

    One set_entity_attributes action per destination layer, then the layer/group setting actions.
    Returns dict(plan=<safe_edit receipt>, review=<review>, review_path=<path>).
    """
    from jwwkit import safe_edit
    result = analyze(sample, target, **options)
    by_slot = defaultdict(list)
    for t, slot in result['moves'].items():
        by_slot[slot].append(t)
    actions = [dict(op='set_entity_attributes', indices=sorted(indices), kwargs=dict(layer_group=g, layer=l))
               for (g, l), indices in sorted(by_slot.items())]
    actions += copy.deepcopy(result['settings_actions'])
    if not actions:
        raise ValueError('Nothing to change: every matched element is already in place')
    targets = sorted(result['moves'])
    document = CadDocument.open(result['target'])
    receipt = safe_edit.write_plan(document, targets, actions, output, plan_path)
    review = result['review']
    review['plan_sha256'] = receipt['sha256']
    review_path = Path(review_path) if review_path is not None else Path(plan_path).with_suffix('.review.json')
    with review_path.open('x', encoding='utf-8') as stream:
        json.dump(review, stream, ensure_ascii=False, indent=2)
    return dict(plan=receipt, review=review, review_path=str(review_path))
