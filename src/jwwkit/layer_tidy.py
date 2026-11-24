"""Tidy a target drawing's layer groups/layers after a sample drawing (#56).

The sample holds only the architecture, already sorted into groups and layers. Elements of the target that
match a sample element by shape and position (real mm, every element whatever its display state) are moved to
that element's group and layer; only the group and layer change. Elements with no counterpart in the sample
(electrical symbols and so on) stay where they are, or move to a chosen empty group/layer.

Matching uses the shape description and the shape test of compare_drawings (``_rows``/``_geometry``, the same
units, tolerance and supported kinds) and looks, for every target element, at all sample elements of the same
shape and place:
- the text content (also inside blocks and dimensions) and the point kind (temporary or not) must be the same;
- if they all have one destination, the element goes there (several target copies may share it: an overlap);
- if not, and only then, the elements whose other attributes (pen colour, style, width, flags) are equal decide
  it when that leaves one destination (attribute tie-break, #56 decision); otherwise it is ambiguous.
Lines that are split differently use compare_drawings' line partitions, and a target line wholly inside one
sample line is matched to it (one-sided cover). Nothing is guessed: ambiguous elements, lines that only partly
overlap, unsupported elements, moves between groups of different scales and moves the editing API refuses are
listed and left alone. The result is a review and a safe_edit plan; executing the plan needs the usual approval.

This module uses internal parts of drawing_comparison (_rows, _geometry, _scope) and
_comparison_composites.changes so that it judges shapes exactly as compare_drawings does. When the comparison
changes, run this module's tests (tests/test_layer_tidy.py) too.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from jwwkit.cad_model import CadDocument
from jwwkit.drawing_comparison import _geometry, _rows, _scope, compare_drawings

__all__ = ['analyze', 'write_plan', 'TidyRefused']

# Floating-point noise allowed on top of position_tolerance when testing that a point lies on a line (real mm).
# Jw_cad stores split points as computed doubles, so an exact zero cannot be asked for.
COVER_EPSILON = 1e-9
REASONS = {
    'ambiguous': 'The destination is not unique (sample elements of the same shape on different layers)',
    'partial_line': 'A line only partly overlaps a sample line',
    'unsupported': 'compare_drawings does not support this element',
    'scale': 'The source group and the destination group have different scales',
    'edit_refused': 'The editing API refuses to change this element',
    'content_differs': 'Same place as a sample element but a different text content or point kind',
}
# Upper limit of element pairs tested (as compare_drawings' max_candidate_pairs).
MAX_PAIRS = 2_000_000
# Grid cell (real mm) for finding lines near a point.
LINE_CELL = 500.0
TIEBREAK_ATTRIBUTES = ('pen_color', 'pen_style', 'pen_width', 'flag')


def _slot(entity):
    return (entity.attributes['layer_group'], entity.attributes['layer'])


def _move_kwargs(entity, slot):
    """The set_entity_attributes arguments for one move: the layer alone when the group stays the same.

    The editing API refuses any group argument for dimensions with a text type (even the same group), but
    accepts a layer-only change, so a move inside one group must not name the group.
    """
    if entity.attributes['layer_group'] == slot[0]:
        return dict(layer=slot[1])
    return dict(layer_group=slot[0], layer=slot[1])


def _row_slot(row):
    return (row['attributes']['layer_group'], row['attributes']['layer'])


def _scale(document, group):
    return document.get_group_scale(group)


class _Budget:
    def __init__(self):
        self.used = 0

    def spend(self, n=1):
        self.used += n
        if self.used > MAX_PAIRS:
            raise ValueError(f'More than {MAX_PAIRS} element pairs to test; the drawings are too large for one run')


def _same_shape_candidates(sample_rows, target_rows, tolerance, budget):
    """{target index: [sample rows of the same shape and place]} using compare_drawings' _geometry."""
    def cell(point):
        if tolerance > 0:
            return (math.floor(point[0] / tolerance), math.floor(point[1] / tolerance))
        return (point[0], point[1])
    buckets = defaultdict(list)
    for row in sample_rows:
        buckets[(row['type'], cell(row['anchor']))].append(row)
    out = {}
    for row in target_rows:
        cx, cy = cell(row['anchor'])
        keys = [(row['type'], (cx + dx, cy + dy)) for dx in (-1, 0, 1) for dy in (-1, 0, 1)] if tolerance > 0 \
            else [(row['type'], (cx, cy))]
        found = []
        for key in keys:
            for candidate in buckets.get(key, ()):
                budget.spend()
                errors = _geometry(candidate, row, tolerance, 0.0)
                if errors is not None:
                    found.append((candidate, errors))
        out[row['index']] = found
    return out


def _content_same(sample_row, target_row, errors):
    """Same text content (also inside blocks/dimensions) and the same point kind (temporary, symbol code)."""
    from jwwkit._comparison_composites import changes
    attributes, content_changes, _ = changes(sample_row, target_row, errors, 0.0)
    if content_changes:
        return False
    if sample_row['type'] == 'POINT':
        return not any(c['field'].endswith(('.is_temporary', '.code')) for c in attributes)
    return True


def _key(row):
    return tuple(row['attributes'][k] for k in TIEBREAK_ATTRIBUTES)


def _real_line(document, entity):
    g = entity.attributes['layer_group']
    geometry = entity.geometry
    a = document.convert_point((geometry['start_x'], geometry['start_y']), layer_group=g, from_units='paper', to_units='real')
    b = document.convert_point((geometry['end_x'], geometry['end_y']), layer_group=g, from_units='paper', to_units='real')
    return a, b


def _on_line(line, point):
    """(distance from the infinite line, position along the segment) of a point."""
    (ax, ay), (bx, by) = line
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    px, py = point[0] - ax, point[1] - ay
    return abs(dx * py - dy * px) / length, (dx * px + dy * py) / length, length


def _relation(sample_line, target_line, tolerance):
    """'covered' (the target lies wholly on the sample line), 'partial' (same straight line, overlapping
    in part), or None."""
    limit = tolerance + COVER_EPSILON
    if math.dist(*sample_line) == 0 or math.dist(*target_line) == 0:
        return None
    d1, t1, length = _on_line(sample_line, target_line[0])
    d2, t2, _ = _on_line(sample_line, target_line[1])
    if d1 > limit or d2 > limit:
        return None
    low, high = min(t1, t2), max(t1, t2)
    if low >= -limit and high <= length + limit:
        return 'covered'
    if min(high, length) - max(low, 0.0) > limit:
        return 'partial'
    return None


def _cells(line, budget, ring):
    """Grid cells (LINE_CELL real mm) along a line, widened by ``ring`` cells on every side."""
    (ax, ay), (bx, by) = line
    length = math.dist(line[0], line[1])
    steps = max(1, math.ceil(length / (LINE_CELL / 2)))
    if steps > MAX_PAIRS // 2:
        raise ValueError(f'A line about {length / 1e6:.0f} km long (real) is too long to search; check the drawing '
                         'for a line far away from the rest')
    budget.spend(steps)
    cells = set()
    for k in range(steps + 1):
        x, y = ax + (bx - ax) * k / steps, ay + (by - ay) * k / steps
        cx, cy = math.floor(x / LINE_CELL), math.floor(y / LINE_CELL)
        cells.update((cx + dx, cy + dy) for dx in range(-ring, ring + 1) for dy in range(-ring, ring + 1))
    return cells


def _line_index(document, indices, budget, tolerance):
    """Grid of real-mm cells -> sample line indices passing within one cell (plus the tolerance) of the cell.
    Only the sample side is widened, so a target line finds the sample lines along its own cells."""
    ring = 1 + math.ceil((tolerance + COVER_EPSILON) / LINE_CELL)
    grid = defaultdict(list)
    lines = {}
    for i in indices:
        line = _real_line(document, document.entities[i])
        lines[i] = line
        for cell in _cells(line, budget, ring):
            grid[cell].append(i)
    return grid, lines

def _check_settings(value, what):
    if value not in ('keep', 'sample'):
        raise ValueError(f"{what} must be 'keep' or 'sample'")


def analyze(sample, target, *, position_tolerance=0.0, unmatched='keep', layer_settings='keep',
            group_settings='keep', strict=False):
    """Match the target against the sample and decide where each target element goes. No file is written.

    unmatched: 'keep', or ('move', layer_group, layer) for target elements with no counterpart in the sample.
    layer_settings / group_settings: 'keep' (report differences only) or 'sample' (make the destination
    layers/groups of matched elements take the sample's state and name; group scales are never changed).
    strict: stop if the editing API refuses an element or a setting (other reasons are only listed).
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
    s_doc, t_doc = CadDocument.open(sample_path), CadDocument.open(target_path)
    s_rows = _rows(s_doc, _scope(None), 'real', (0, 0, 0))
    t_rows = _rows(t_doc, _scope(None), 'real', (0, 0, 0))
    if [r['index'] for r in s_rows] != list(range(len(s_doc.entities))) or \
            [r['index'] for r in t_rows] != list(range(len(t_doc.entities))):
        raise ValueError('Element numbering of the comparison rows and CadDocument differ')
    s_ok = [r for r in s_rows if r['status'] == 'supported']
    t_ok = [r for r in t_rows if r['status'] == 'supported']
    budget = _Budget()
    candidates = _same_shape_candidates(s_ok, t_ok, position_tolerance, budget)

    destination, how, listed = {}, {}, defaultdict(list)
    tiebreak = {}  # target -> the one sample element chosen by attributes (must be one-to-one)
    sample_used = set()
    attribute_fields = Counter()
    leftover = []
    from jwwkit._comparison_composites import changes
    for row in t_ok:
        t = row['index']
        if any(e.get('nested_ambiguous') for _, e in candidates[t]):
            # The children of a block/dimension do not pair one-to-one, so their texts cannot be compared.
            listed['ambiguous'].append(t)
            continue
        same = [(s, e) for s, e in candidates[t] if _content_same(s, row, e)]
        if not same:
            if candidates[t]:
                listed['content_differs'].append(t)
            else:
                leftover.append(t)
            continue
        slots = {_row_slot(s) for s, _ in same}
        chosen = same
        here = [(s, e) for s, e in same if _row_slot(s) == _row_slot(row) and _key(s) == _key(row)]
        if len(slots) > 1 and here:
            # Already in the layer of an identical sample element: in place, not a tie-break candidate.
            destination[t] = _row_slot(row)
            how[t] = 'shape'
            sample_used.add(here[0][0]['index'])
            continue
        if len(slots) == 1:
            kind = 'shape' if len(same) == 1 else 'overlap'
        else:
            # Shape and position leave the destination open: only here, the other attributes decide (#56).
            chosen = [(s, e) for s, e in same if _key(s) == _key(row)]
            if len(chosen) != 1:
                listed['ambiguous'].append(t)
                continue
            tiebreak[t] = chosen[0][0]['index']
            slots = {_row_slot(chosen[0][0])}
            kind = 'attribute_tiebreak'
        destination[t] = slots.pop()
        how[t] = kind
        sample_used.update(s['index'] for s, _ in chosen)
        attributes, _, _ = changes(chosen[0][0], row, chosen[0][1], 0.0)
        attribute_fields.update(c['field'] for c in attributes if not c['field'].endswith(('.layer_group', '.layer')))
    # A target copy that repeats a sample element which another target element also matched: an overlap.
    shared = Counter(tuple(sorted(s['index'] for s, _ in candidates[t] if _content_same(s, t_rows[t], _)))
                     for t in destination)
    for t in destination:
        key = tuple(sorted(s['index'] for s, e in candidates[t] if _content_same(s, t_rows[t], e)))
        if how[t] == 'shape' and shared[key] > 1:
            how[t] = 'overlap'

    # Lines split differently: compare_drawings' line partitions (both sides cover each other).
    leftover_lines = [t for t in leftover if t_doc.entities[t].entity_type == 'LINE']
    if leftover_lines:
        comparison = compare_drawings(sample_path, target_path, units='real', position_tolerance=position_tolerance,
                                      line_coverage=True)
        waiting = set(leftover_lines)
        for match in comparison['matches']:
            if match.get('correspondence') == 'line_partition_equivalent' and set(match['right_indices']) <= waiting:
                slots = {_slot(s_doc.entities[i]) for i in match['left_indices']}
                if len(slots) == 1:
                    slot = slots.pop()
                    for t in match['right_indices']:
                        destination[t] = slot
                        how[t] = 'line_partition'
                    sample_used.update(match['left_indices'])
    # One-sided cover: a target line wholly on one sample line; partial overlaps are listed.
    remaining = [t for t in leftover if t not in destination]
    sample_lines = [r['index'] for r in s_ok if r['type'] == 'LINE']
    grid, s_lines = _line_index(s_doc, sample_lines, budget, position_tolerance)
    unmatched_targets = []
    for t in remaining:
        if t_doc.entities[t].entity_type != 'LINE':
            unmatched_targets.append(t)
            continue
        line = _real_line(t_doc, t_doc.entities[t])
        near = {i for cell in _cells(line, budget, 0) for i in grid.get(cell, ())}
        budget.spend(len(near))
        covering, partial = [], False
        for i in sorted(near):
            relation = _relation(s_lines[i], line, position_tolerance)
            if relation == 'covered':
                covering.append(i)
            elif relation == 'partial':
                partial = True
        if covering:
            rows = [s_rows[i] for i in covering]
            slots = {_row_slot(r) for r in rows}
            # No attribute tie-break for covered pieces: it is approved for same-shape elements only.
            if len(slots) == 1:
                destination[t] = slots.pop()
                how[t] = 'line_cover'
                sample_used.update(r['index'] for r in rows)
            else:
                listed['ambiguous'].append(t)
        elif partial:
            listed['partial_line'].append(t)
        else:
            unmatched_targets.append(t)
    # The attribute tie-break must pair one to one: a sample element chosen by two target elements is open.
    chosen_by = Counter(tiebreak.values())
    for t, s in tiebreak.items():
        if chosen_by[s] > 1 and t in destination:
            del destination[t]
            listed['ambiguous'].append(t)
    listed['unsupported'].extend(r['index'] for r in t_rows if r['status'] != 'supported')
    seen = {s['index'] for found in candidates.values() for s, _ in found}
    sample_only = [r['index'] for r in s_ok if r['index'] not in sample_used and r['index'] not in seen]
    sample_unsupported = sum(r['status'] != 'supported' for r in s_rows)

    # (b) move the unmatched elements to a group/layer that the sample does not use. It need not be empty before;
    # after tidying it must hold unmatched elements only (checked below, once every refusal is known).
    if unmatched != 'keep':
        slot = (unmatched[1], unmatched[2])
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

    # Ask the editing API on a staged copy; elements it refuses are listed (strict=True stops).
    staged = CadDocument.open(target_path)
    for t in sorted(moves):
        try:
            staged.set_entity_attributes(t, **_move_kwargs(t_doc.entities[t], moves[t]))
        except ValueError:
            listed['edit_refused'].append(t)
    for t in listed['edit_refused']:
        moves.pop(t, None)
    # (b): elements that would stay in the chosen layer without being unmatched elements refuse the whole run.
    stay = Counter()
    if unmatched != 'keep':
        chosen_slot = (unmatched[1], unmatched[2])
        for t, entity in enumerate(t_doc.entities):
            if _slot(entity) != chosen_slot or t in moves or how.get(t) == 'unmatched':
                continue
            stay[next((k for k, v in listed.items() if t in v), 'matched_in_place')] += 1

    # Layer/group settings: only the destinations of matched (architecture) elements, never (b)'s layer.
    used = sorted({slot for t, slot in moves.items() if how[t] != 'unmatched'})
    settings = _settings_review(s_doc, t_doc, used, layer_settings, group_settings)
    if strict and (listed['edit_refused'] or settings['refused']):
        raise ValueError(f'strict=True: the editing API refuses {len(listed["edit_refused"])} element(s) and '
                         f'{len(settings["refused"])} setting change(s)')
    for p, h in hashes.items():
        if hashlib.sha256(p.read_bytes()).hexdigest() != h:
            raise ValueError('An input drawing changed while it was being read')
    review = dict(
        schema='jwwkit.layer_tidy.review/1',
        sample=dict(sha256=hashes[sample_path], elements=len(s_doc.entities), unsupported=sample_unsupported),
        target=dict(sha256=hashes[target_path], elements=len(t_doc.entities)),
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
            attribute_differences_in_matches=dict(attribute_fields),
        ),
        left_alone=[dict(index=t, kind=k, reason=REASONS[k], type=t_doc.entities[t].entity_type,
                         slot=list(_slot(t_doc.entities[t])))
                    for k, v in listed.items() for t in sorted(v)],
        settings=settings['review'],
    )
    if unmatched != 'keep':
        review['unmatched_layer'] = dict(refused=bool(stay), would_stay=dict(stay))
    if stay:
        raise TidyRefused(f'The layer {unmatched[1]}-{unmatched[2]} for unmatched elements would still hold elements '
                          f'that are not unmatched after tidying ({dict(stay)}); choose another layer', review)
    return dict(review=review, moves=moves, settings_actions=settings['actions'], target=target_path)


class TidyRefused(ValueError):
    """The run is refused; ``review`` holds the counts (write_plan still writes it)."""

    def __init__(self, message, review):
        super().__init__(message)
        self.review = review


def _state_value(state):
    return state['raw_value'] if isinstance(state, dict) else state


def _settings_review(s_doc, t_doc, slots, layer_settings, group_settings):
    """Differences of the destination layers/groups (state, and whether the name differs) and, for 'sample',
    the actions. The review holds no names (they may be private); the names are only in the plan's actions."""
    rows, actions = [], []
    groups = sorted({g for g, _ in slots})
    for g in groups:
        before = dict(state=_state_value(t_doc.get_group_state(g)), name=t_doc.get_group_name(g))
        sample = dict(state=_state_value(s_doc.get_group_state(g)), name=s_doc.get_group_name(g))
        if before != sample:
            rows.append(dict(kind='group', layer_group=g, target_state=before['state'], sample_state=sample['state'],
                             name_differs=before['name'] != sample['name']))
            if group_settings == 'sample':
                if before['name'] != sample['name']:
                    actions.append(dict(op='set_group_name', kwargs=dict(layer_group=g, name=sample['name'])))
                if before['state'] != sample['state']:
                    actions.append(dict(op='set_group_state', kwargs=dict(layer_group=g, state=sample['state'])))
    for g, l in slots:
        before = dict(state=_state_value(t_doc.get_layer_state(g, l)), name=t_doc.get_layer_name(g, l))
        sample = dict(state=_state_value(s_doc.get_layer_state(g, l)), name=s_doc.get_layer_name(g, l))
        if before != sample:
            rows.append(dict(kind='layer', layer_group=g, layer=l, target_state=before['state'],
                             sample_state=sample['state'], name_differs=before['name'] != sample['name']))
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
        except ValueError:
            where = {k: v for k, v in action['kwargs'].items() if k in ('layer_group', 'layer')}
            refused.append(dict(op=action['op'], **where, reason='The editing API refuses this change '
                                '(for example the writing state or a protected group/layer)'))
    review = dict(differences=rows, changes=[dict(op=a['op'], **{k: v for k, v in a['kwargs'].items()
                                                                 if k in ('layer_group', 'layer', 'state')})
                                             for a in accepted], refused=refused)
    return dict(review=review, actions=accepted, refused=refused)


def write_plan(sample, target, output, plan_path, *, review_path=None, **options):
    """Analyze, then write the review JSON and the safe_edit plan (approval needed to execute).

    One set_entity_attributes action per destination layer (two when some of its elements are already in the
    destination group: those get the layer alone), then the layer/group setting actions. If there is
    nothing to change, the review is still written and the error says why (counts of each reason).
    Returns dict(plan=<safe_edit receipt>, review=<review>, review_path=<path>).
    """
    from jwwkit import safe_edit
    review_path = Path(review_path) if review_path is not None else Path(plan_path).with_suffix('.review.json')
    resolved = review_path.resolve()
    if resolved in {Path(p).resolve() for p in (sample, target, output, plan_path)}:
        raise ValueError('The review path must differ from the drawings and the plan')
    if review_path.exists():
        raise FileExistsError(review_path)
    try:
        result = analyze(sample, target, **options)
    except TidyRefused as exc:
        exc.review['plan_sha256'] = None
        with review_path.open('x', encoding='utf-8') as stream:
            json.dump(exc.review, stream, ensure_ascii=False, indent=2)
        raise TidyRefused(f'{exc}; no plan was written (review: {review_path})', exc.review) from exc
    review = result['review']
    document = CadDocument.open(result['target'])
    by_slot = defaultdict(list)
    for t, slot in result['moves'].items():
        kwargs = _move_kwargs(document.entities[t], slot)
        by_slot[slot, 'layer_group' in kwargs].append(t)
    actions = [dict(op='set_entity_attributes', indices=sorted(indices),
                    kwargs=dict(layer_group=g, layer=l) if group else dict(layer=l))
               for ((g, l), group), indices in sorted(by_slot.items())]
    actions += copy.deepcopy(result['settings_actions'])
    if not actions:
        review['plan_sha256'] = None
        with review_path.open('x', encoding='utf-8') as stream:
            json.dump(review, stream, ensure_ascii=False, indent=2)
        counts = review['counts']
        raise ValueError(f'Nothing to change; no plan was written (review: {review_path}). '
                         f"already in place {counts['already_in_place']}, not in the sample {counts['unmatched']}, "
                         f"left alone {counts['left_alone']}, refused for scale {counts['refused_for_scale']}")
    targets = sorted(result['moves'])
    receipt = safe_edit.write_plan(document, targets, actions, output, plan_path)
    if receipt['plan']['source_sha256'] != review['target']['sha256']:
        raise ValueError('The target drawing changed between the analysis and the plan')
    review['plan_sha256'] = receipt['sha256']
    with review_path.open('x', encoding='utf-8') as stream:
        json.dump(review, stream, ensure_ascii=False, indent=2)
    return dict(plan=receipt, review=review, review_path=str(review_path))
