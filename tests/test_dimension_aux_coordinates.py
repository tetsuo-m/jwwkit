"""#73: dimension figures (SXF mode 0) whose auxiliary lines/points carry coordinates.

Jw_cad 10.03.6 moves the auxiliaries by the translation of the operation only (how far its base point moves)
and applies no rotation, scale or reflection to them (eight samples in tests/fixtures/archicad_dimensions, see
its README). jwwkit does the same. Scale conversions of a group change or group import, JWS placement and
dimensions with only some auxiliaries at coordinates stay refused, being unverified in Jw_cad.
Dimensions whose auxiliaries are all 0 (the Jw_cad samples of #62) keep the earlier behaviour.
"""
import copy
import hashlib
import math
import unittest
from collections import Counter
from pathlib import Path

from jwwkit import CadDocument
from jwwkit.model.editing import commit, entity_record
from jwwkit.reader.archive import read_records_bytes
from jwwkit.safe_edit import write_plan
from test_v600_schema700 import TempDirTestCase

HERE = Path(__file__).resolve().parent
ARCHICAD = HERE / 'fixtures' / 'archicad_dimensions'
JWCAD = HERE / 'fixtures' / 'jwcad_dimensions'
SHA256 = {
    'ac2_resave.jww': 'ff0be0a0d62ef26fc459bce1d5b1edb730ef941537e528e8986bbcac424c8403',
    'ac2_move.jww': 'e6ebb04cc5e061babab4006a02c885b89daba9e39a281ac51c0d7e5513765f5b',
    'ac2_copy.jww': '079f546e88ad99114aed7f7c66d0792f062bcca7b4c05f0f0e17e5c65b8ff160',
    'ac2_rotate.jww': '3ff3e59dd1ed8f2e81b2e0f77476f9d88c7752d7abcf2a8d686e0fb7784581e9',
    'ac2_scale2.jww': 'ba0bfca7811beaffb2c885da2c532d6ca8cdf4e58d788416c12008be16dbf1c5',
    'ac2_rotate_move.jww': '248a47f3dc94318987104a8839bf43f5130dea79372e1cf9dc9cb88ebe77a433',
    'ac2_scale2_move.jww': '36254dfb490a576a8ad9f18e4bf209d6d8528087136fcc4d1a10adfe0e950a2d',
    'ac2_scale21.jww': 'f1a5346a05a6bfae9b944889fb0bc387a3e68ec26caf9789d169ef2f35bd7b5b',
    'ac2_reflect.jww': '6e67fab1f1c61ad3f0e287cbc338fe55176c4ca444439add6db0be04c606c669',
}
# What the samples did to the auxiliaries: the translation of the operation (paper units), or none.
JWCAD_AUX_SHIFT = {'ac2_move.jww': (1.0, 0.5), 'ac2_rotate.jww': (0, 0), 'ac2_scale2.jww': (0, 0),
                   'ac2_rotate_move.jww': (1.0, 0.5), 'ac2_scale2_move.jww': (1.0, 0.5),
                   'ac2_scale21.jww': (0, 0), 'ac2_reflect.jww': (0, 0)}
CENTRE = (-13.31561, -6.67606)  # left end of the 2000 (real) line, element 39 of ac2_resave (README)
TEXT_RULE = 'Unobserved preset dimension rigid profile|Preset text/dimension'
REFUSED = '補助線・補助点に座標がある寸法図形'
SETTINGS = ('Printer_', 'View_', 'Draw_')
AUX_KEYS = ('start_x', 'start_y', 'end_x', 'end_y')


def aux_of(record):
    return ([tuple(a[k] for k in AUX_KEYS) for a in record['aux_lines']],
            [(p['x'], p['y']) for p in record['aux_points']])


def comparable(record):
    """A record with what Jw_cad changes and jwwkit does not taken out: the selection flag 2, the dimension text
    that Jw_cad computes again from the line (its content, and its start and end points: Jw_cad centres the new
    text; the angle to 1e-6 degrees)."""
    r = copy.deepcopy(record)
    parts = [r] + ([r['line'], r['text'], *r['aux_lines'], *r['aux_points']] if r['type'] == 'DIMENSION' else [])
    for part in parts:
        part['base']['flag'] &= ~2
    if r['type'] == 'DIMENSION':
        for key in ('content', 'start_x', 'start_y', 'end_x', 'end_y'):
            r['text'].pop(key)
        r['text']['angle'] = round(r['text']['angle'], 6)
        r['text'].pop('source_strings', None)
    r.pop('source_strings', None)
    return repr(sorted(r.items(), key=str))


def drawing_records(data):
    return [e for e in read_records_bytes(data)['entities']
            if not (e['type'] == 'TEXT' and str(e['content']).startswith(SETTINGS))]


class ArchicadSampleTests(TempDirTestCase):
    def test_fixtures_are_the_reviewed_samples(self):
        for name, digest in SHA256.items():
            self.assertEqual(hashlib.sha256((ARCHICAD / name).read_bytes()).hexdigest(), digest, name)

    def opened(self):
        """ac2_resave with the outer line type of its dimensions set to 1: their stored 0 is refused by the
        pre-edit check (#69), which is not what this test is about."""
        doc = CadDocument.open(ARCHICAD / 'ac2_resave.jww')
        dims = [i for i, e in enumerate(doc.entities) if e.entity_type == 'DIMENSION']
        for i in dims:
            doc.set_entity_attributes(i, linetype=1)
        return doc, dims

    def same_as_jwcad(self, got, want):
        def key(r):
            if r['type'] == 'DIMENSION':
                r = copy.deepcopy(r); r['base']['pen_style'] = 0  # set to 1 above; Jw_cad keeps the stored 0
            return comparable(r)
        mine = Counter(key(r) for r in drawing_records(got))
        theirs = Counter(key(r) for r in drawing_records(want))
        self.assertEqual(mine, theirs)

    def test_move_moves_the_auxiliaries_like_jwcad(self):
        doc, dims = self.opened()
        doc.move_entities(list(range(len(doc.entities))), (100, 50), units='real')
        doc.save(self.folder / 'moved.jww')
        got = (self.folder / 'moved.jww').read_bytes()
        self.same_as_jwcad(got, (ARCHICAD / 'ac2_move.jww').read_bytes())
        source = [r for r in drawing_records((ARCHICAD / 'ac2_resave.jww').read_bytes()) if r['type'] == 'DIMENSION']
        moved = [r for r in drawing_records(got) if r['type'] == 'DIMENSION']
        for before, r in zip(source, moved):
            line = tuple(r['line'][k] for k in AUX_KEYS)
            self.assertEqual(aux_of(r), ([line, line], [line[:2], line[2:], line[:2], line[2:]]))
            # jwwkit moves the dimension text as it is (Jw_cad writes a new value and centres it).
            self.assertEqual((r['text']['start_x'], r['text']['start_y'], r['text']['content']),
                             (before['text']['start_x'] + 1.0, before['text']['start_y'] + 0.5, before['text']['content']))

    def test_copy_moves_the_auxiliaries_of_the_copies_like_jwcad(self):
        doc, dims = self.opened()
        doc.copy_entities(list(range(len(doc.entities))), (1.0, 0.5))
        doc.save(self.folder / 'copied.jww')
        self.same_as_jwcad((self.folder / 'copied.jww').read_bytes(), (ARCHICAD / 'ac2_copy.jww').read_bytes())

    def test_jwcad_moves_the_auxiliaries_by_the_translation_only(self):
        """The rule read from the samples: each auxiliary point moved by the operation's translation, or not at all."""
        def points(records):
            out = []
            for r in records:
                if r['type'] == 'DIMENSION':
                    lines, pts = aux_of(r)
                    out += [q for a in lines for q in (a[:2], a[2:])] + pts
            return sorted(out)
        before = points(drawing_records((ARCHICAD / 'ac2_resave.jww').read_bytes()))
        for name, (dx, dy) in JWCAD_AUX_SHIFT.items():
            with self.subTest(sample=name):
                after = points(drawing_records((ARCHICAD / name).read_bytes()))
                self.assertEqual(after, sorted((x + dx, y + dy) for x, y in before))

    def test_rotating_scaling_or_reflecting_these_text_typed_dimensions_stays_refused(self):
        """The Archicad dimensions have a text type (10000): their rotation, scale and reflection stay refused by
        the rules for dimension text, whatever happens to the auxiliaries."""
        operations = dict(
            rotate=lambda d, ix: d.rotate_entities(ix, math.pi / 6, base_point=CENTRE),
            scale2=lambda d, ix: d.scale_entities(ix, 2, base_point=CENTRE),
            rotate_move=lambda d, ix: d.transform_entities(ix, base_point=CENTRE, rotation=math.pi / 6,
                                                          translation=(1.0, 0.5)),
            scale2_move=lambda d, ix: d.transform_entities(ix, base_point=CENTRE, scale_x=2, scale_y=2,
                                                          translation=(1.0, 0.5)),
            scale21=lambda d, ix: d.scale_entities(ix, 2, 1, base_point=CENTRE),
            reflect=lambda d, ix: d.reflect_entities(ix, axis_point=CENTRE, axis_angle=0),
        )
        for name, operation in operations.items():
            with self.subTest(operation=name):
                doc, dims = self.opened()
                before = [entity_record(e) for e in doc.entities]
                with self.assertRaisesRegex(ValueError, TEXT_RULE):
                    operation(doc, dims)
                self.assertEqual([entity_record(e) for e in doc.entities], before)


def give_aux_coordinates(record, mixed=False):
    """Auxiliaries on the dimension line and its ends, as in the Archicad samples; mixed leaves one point at 0."""
    line = record['line']
    for aux in record['aux_lines']:
        for key in AUX_KEYS:
            aux[key] = line[key]
    for point, (x, y) in zip(record['aux_points'], [('start_x', 'start_y'), ('end_x', 'end_y')] * 2):
        point['x'], point['y'] = line[x], line[y]
    if mixed:
        record['aux_points'][3]['x'] = record['aux_points'][3]['y'] = 0.0


class TextType0Tests(TempDirTestCase):
    """A text type 0 dimension of d10 given auxiliary coordinates (made here, saved to a temporary folder)."""

    def make(self, mixed=False):
        doc = CadDocument.open(JWCAD / 'd10.jww')
        index = next(i for i, e in enumerate(doc.entities) if e.entity_type == 'DIMENSION')
        record = entity_record(doc.entities[index])
        give_aux_coordinates(record, mixed)
        commit(doc, index, doc.entities[index], record)
        path = self.folder / ('mixed.jww' if mixed else 'aux.jww')
        doc.save(path)
        return path, index

    def test_a_move_moves_the_auxiliaries(self):
        path, index = self.make()
        for name, operation in (('move_entity', lambda d: d.move_entity(index, (10, 5))),
                                ('move_entities', lambda d: d.move_entities([index], (10, 5))),
                                ('translate', lambda d: d.transform_entities([index], translation=(10, 5))),
                                ('align', lambda d: d.align_two_points([index], [(0, 0), (100, 0)], [(10, 5), (110, 5)],
                                                                       distance_tolerance=1e-6, angle_tolerance=1e-9))):
                # align_two_points works in real units; the expected move is read from the dimension line.
            with self.subTest(operation=name):
                doc = CadDocument.open(path)
                before = entity_record(doc.entities[index])
                operation(doc)
                after = entity_record(doc.entities[index])
                self.assertNotEqual(after['line'], before['line'])
                # The auxiliaries were made on the line and its ends: after the move they are there again.
                line = tuple(after['line'][k] for k in AUX_KEYS)
                self.assertEqual(aux_of(after), ([line, line], [line[:2], line[2:], line[:2], line[2:]]))

    def test_a_copy_moves_the_auxiliaries_of_the_copy(self):
        path, index = self.make()
        doc = CadDocument.open(path)
        original = entity_record(doc.entities[index])
        doc.copy_entities([index], (10, 5))
        self.assertEqual(entity_record(doc.entities[index]), original)
        copied = entity_record(doc.entities[-1])
        self.assertEqual(aux_of(copied)[1], [(x + 10, y + 5) for x, y in aux_of(original)[1]])

    def test_the_auxiliaries_move_by_the_translation_only_like_jwcad(self):
        path, index = self.make()
        doc = CadDocument.open(path)
        scale = doc.get_group_scale(doc.entities[index].attributes['layer_group'])
        cases = dict(  # name: (operation, translation of the auxiliaries in paper units)
            rotate=(lambda d: d.rotate_entities([index], math.pi / 6, base_point=(3, 4)), (0, 0)),
            scale=(lambda d: d.scale_entities([index], 2, base_point=(3, 4)), (0, 0)),
            unequal_scale=(lambda d: d.scale_entities([index], 2, 1, base_point=(3, 4)), (0, 0)),
            rotate_move=(lambda d: d.transform_entities([index], base_point=(3, 4), rotation=math.pi / 6,
                                                       translation=(1.0, 0.5)), (1.0, 0.5)),
            scale_move=(lambda d: d.transform_entities([index], base_point=(3, 4), scale_x=2, scale_y=2,
                                                      translation=(1.0, 0.5)), (1.0, 0.5)),
            align_with_rotation=(lambda d: d.align_two_points([index], [(0, 0), (100, 0)], [(10, 5), (10, 105)],
                                                              distance_tolerance=1e-6, angle_tolerance=math.pi),
                                 (10 / scale, 5 / scale)),
        )
        for name, (operation, (dx, dy)) in cases.items():
            with self.subTest(operation=name):
                doc = CadDocument.open(path)
                before = entity_record(doc.entities[index])
                operation(doc)
                after = entity_record(doc.entities[index])
                self.assertNotEqual(after['line'], before['line'])
                lines, points = aux_of(before)
                got_lines, got_points = aux_of(after)
                wanted = [(a[0] + dx, a[1] + dy, a[2] + dx, a[3] + dy) for a in lines] + [(x + dx, y + dy) for x, y in points]
                for want, got in zip(wanted, got_lines + got_points):
                    for w, g in zip(want, got):
                        self.assertAlmostEqual(w, g, places=9)

    def test_reflecting_text_type_0_stays_refused_by_its_text(self):
        path, index = self.make()
        doc = CadDocument.open(path)
        with self.assertRaisesRegex(ValueError, 'Mirrored glyphs'):
            doc.reflect_entities([index], axis_angle=0.3)

    def assert_refused(self, path, index, operation):
        doc = CadDocument.open(path)
        before = [entity_record(e) for e in doc.entities]
        with self.assertRaisesRegex(ValueError, REFUSED):
            operation(doc)
        self.assertEqual([entity_record(e) for e in doc.entities], before)

    def test_scale_conversions_of_a_group_change_are_refused_and_change_nothing(self):
        path, index = self.make()

        def real_group_change(d):
            group = d.entities[index].attributes['layer_group']
            other = 1 if group != 1 else 2
            d.set_group_scale(other, d.get_group_scale(group) * 2)
            d.set_entity_attributes(index, layer_group=other, preserve='real')
        self.assert_refused(path, index, real_group_change)

    def test_group_import_with_a_scale_conversion_is_refused(self):
        path, index = self.make()
        source = CadDocument.open(path)
        group = source.entities[index].attributes['layer_group']
        destination = CadDocument.open(JWCAD / 'd0.jww')
        destination.set_group_scale(5, source.get_group_scale(group) * 2)
        before = [entity_record(e) for e in destination.entities]
        with self.assertRaisesRegex(ValueError, REFUSED):
            destination.import_group(path, group, 5, settings_policy='destination')
        self.assertEqual([entity_record(e) for e in destination.entities], before)

    def test_mixed_auxiliaries_are_refused_even_for_a_move(self):
        path, index = self.make(mixed=True)
        self.assert_refused(path, index, lambda d: d.move_entities([index], (10, 5)))
        self.assert_refused(path, index, lambda d: d.copy_entities([index], (10, 5)))

    def test_safe_edit_plans_follow_the_same_rules(self):
        path, index = self.make()
        doc = CadDocument.open(path)
        receipt = write_plan(doc, [index], [dict(op='move_entities', indices=[index], kwargs=dict(delta=[10, 0]))],
                             self.folder / 'moved.jww', self.folder / 'move_plan.json')
        self.assertTrue(Path(receipt['path']).exists())
        receipt = write_plan(CadDocument.open(path), [index],
                             [dict(op='rotate_entities', indices=[index], kwargs=dict(angle=0.5))],
                             self.folder / 'rotated.jww', self.folder / 'rotate_plan.json')
        self.assertTrue(Path(receipt['path']).exists())
        mixed, mixed_index = self.make(mixed=True)
        plan = self.folder / 'mixed_plan.json'
        with self.assertRaisesRegex(ValueError, REFUSED):
            write_plan(CadDocument.open(mixed), [mixed_index],
                       [dict(op='move_entities', indices=[mixed_index], kwargs=dict(delta=[10, 0]))],
                       self.folder / 'mixed_out.jww', plan)
        self.assertFalse(plan.exists())

    def test_mixed_auxiliaries_are_refused_for_any_change_of_coordinates_only(self):
        path, index = self.make(mixed=True)
        for name, operation in (('rotate', lambda d: d.rotate_entities([index], 0.5, base_point=(3, 4))),
                                ('scale', lambda d: d.scale_entities([index], 2, base_point=(3, 4)))):
            with self.subTest(operation=name):
                self.assert_refused(path, index, operation)
        # Changes that keep every coordinate are not geometry changes.
        doc = CadDocument.open(path)
        before = entity_record(doc.entities[index])
        doc.transform_entities([index])
        doc.move_entities([index], (0, 0))
        self.assertEqual(entity_record(doc.entities[index]), before)

    def test_a_refusal_among_several_elements_changes_nothing(self):
        path, index = self.make(mixed=True)
        doc = CadDocument.open(path)
        others = [i for i in range(len(doc.entities)) if i != index]
        for name, operation in (('move', lambda d: d.move_entities(others + [index], (10, 5))),
                                ('translate', lambda d: d.transform_entities(others + [index], translation=(10, 5))),
                                ('copy', lambda d: d.copy_entities(others + [index], (10, 5)))):
            with self.subTest(operation=name):
                doc = CadDocument.open(path)
                before = [entity_record(e) for e in doc.entities]
                with self.assertRaisesRegex(ValueError, REFUSED):
                    operation(doc)
                self.assertEqual([entity_record(e) for e in doc.entities], before)

    def test_an_approved_move_plan_moves_the_auxiliaries(self):
        from jwwkit.safe_edit import execute_plan
        path, index = self.make()
        for op, kwargs in (('move_entities', dict(delta=[10, 5])), ('copy_entities', dict(delta=[10, 5]))):
            with self.subTest(op=op):
                out = self.folder / f'plan_{op}.jww'
                receipt = write_plan(CadDocument.open(path), [index], [dict(op=op, indices=[index], kwargs=kwargs)],
                                     out, self.folder / f'plan_{op}.json')
                execute_plan(receipt['path'], approved_sha256=receipt['sha256'])
                saved = [entity_record(e) for e in CadDocument.open(out).entities]
                moved = saved[index] if op == 'move_entities' else saved[-1]
                line = tuple(moved['line'][k] for k in AUX_KEYS)
                self.assertEqual(aux_of(moved), ([line, line], [line[:2], line[2:], line[:2], line[2:]]))
        for op, kwargs in (('scale_entities', dict(scale_x=2, scale_y=3)),):
            with self.subTest(op=op):
                receipt = write_plan(CadDocument.open(path), [index], [dict(op=op, indices=[index], kwargs=kwargs)],
                                     self.folder / f'plan_{op}.jww', self.folder / f'plan_{op}.json')
                self.assertTrue(Path(receipt['path']).exists())

    def test_block_conversion_converts_the_auxiliaries_as_before(self):
        path, index = self.make()
        doc = CadDocument.open(path)
        doc.replace_entities_with_block([index], 'aux_block', base_point=(10, 5))
        doc.save(self.folder / 'block.jww')
        inside = [e for d in read_records_bytes((self.folder / 'block.jww').read_bytes())['block_defs']
                  for e in d['entities'] if e['type'] == 'DIMENSION']
        self.assertEqual(len(inside), 1)
        line = tuple(inside[0]['line'][k] for k in AUX_KEYS)
        self.assertEqual(aux_of(inside[0])[0], [line, line])

    def test_dimensions_with_all_zero_auxiliaries_keep_them_at_zero(self):
        for source in ('d1.jww', 'd8.jww', 'd10.jww'):
            with self.subTest(source=source):
                doc = CadDocument.open(JWCAD / source)
                dims = [i for i, e in enumerate(doc.entities) if e.entity_type == 'DIMENSION']
                doc.move_entities(dims, (10, 5))
                for i in dims:
                    lines, points = aux_of(entity_record(doc.entities[i]))
                    self.assertEqual({v for a in lines for v in a} | {v for p in points for v in p}, {0.0})


if __name__ == '__main__':
    unittest.main()
