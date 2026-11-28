"""#73: dimension figures (SXF mode 0) whose auxiliary lines/points carry coordinates.

Jw_cad 10.03.6 moves the auxiliaries with the dimension line in a move/copy, and leaves them where they are
when it rotates or scales about a point (tests/fixtures/archicad_dimensions, see its README). jwwkit does
the same; every other geometry change of such a dimension is refused, being unverified in Jw_cad.
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
}
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

    def test_jwcad_keeps_the_auxiliaries_when_it_rotates_or_scales(self):
        before = [aux_of(r) for r in drawing_records((ARCHICAD / 'ac2_resave.jww').read_bytes()) if r['type'] == 'DIMENSION']
        for name in ('ac2_rotate.jww', 'ac2_scale2.jww'):
            after = [aux_of(r) for r in drawing_records((ARCHICAD / name).read_bytes()) if r['type'] == 'DIMENSION']
            self.assertEqual(sorted(after), sorted(before), name)

    def test_rotating_or_scaling_these_text_typed_dimensions_stays_refused(self):
        centre = (-13.31561, -6.67606)
        for name, operation in (('rotate', lambda d, ix: d.rotate_entities(ix, math.pi / 6, base_point=centre)),
                                ('scale', lambda d, ix: d.scale_entities(ix, 2, base_point=centre))):
            with self.subTest(operation=name):
                doc, dims = self.opened()
                before = [entity_record(e) for e in doc.entities]
                with self.assertRaisesRegex(ValueError, 'Unobserved preset dimension rigid profile|Preset text/dimension'):
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

    def test_rotating_or_scaling_about_a_point_keeps_the_auxiliaries_like_jwcad(self):
        path, index = self.make()
        for name, operation in (('rotate', lambda d: d.rotate_entities([index], math.pi / 6, base_point=(3, 4))),
                                ('scale', lambda d: d.scale_entities([index], 2, base_point=(3, 4)))):
            with self.subTest(operation=name):
                doc = CadDocument.open(path)
                before = entity_record(doc.entities[index])
                operation(doc)
                after = entity_record(doc.entities[index])
                self.assertEqual(aux_of(after), aux_of(before))
                self.assertNotEqual(after['line'], before['line'])

    def assert_refused(self, path, index, operation):
        doc = CadDocument.open(path)
        before = [entity_record(e) for e in doc.entities]
        with self.assertRaisesRegex(ValueError, REFUSED):
            operation(doc)
        self.assertEqual([entity_record(e) for e in doc.entities], before)

    def test_unverified_geometry_changes_are_refused_and_change_nothing(self):
        path, index = self.make()

        def real_group_change(d):
            group = d.entities[index].attributes['layer_group']
            other = 1 if group != 1 else 2
            d.set_group_scale(other, d.get_group_scale(group) * 2)
            d.set_entity_attributes(index, layer_group=other, preserve='real')
        operations = dict(
            rotate_and_translate=lambda d: d.transform_entities([index], rotation=0.5, translation=(1, 2)),
            scale_and_translate=lambda d: d.transform_entities([index], scale_x=2, scale_y=2, translation=(1, 2)),
            unequal_scale=lambda d: d.scale_entities([index], 2, 3),
            reflect=lambda d: d.reflect_entities([index], axis_angle=0.3),
            align_with_rotation=lambda d: d.align_two_points([index], [(0, 0), (100, 0)], [(10, 5), (10, 105)],
                                                            distance_tolerance=1e-6, angle_tolerance=math.pi),
            align_rotation_about_its_first_point=lambda d: d.align_two_points(
                [index], [(0, 0), (100, 0)], [(0, 0), (0, 100)], distance_tolerance=1e-6, angle_tolerance=math.pi),
            real_group_change=real_group_change,
        )
        for name, operation in operations.items():
            with self.subTest(operation=name):
                self.assert_refused(path, index, operation)

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
        for op, kwargs in (('reflect_entities', dict(axis_angle=0.3)),
                           ('scale_entities', dict(scale_x=2, scale_y=3))):
            with self.subTest(op=op):
                plan = self.folder / f'{op}.json'
                with self.assertRaisesRegex(ValueError, REFUSED):
                    write_plan(CadDocument.open(path), [index], [dict(op=op, indices=[index], kwargs=kwargs)],
                               self.folder / f'{op}.jww', plan)
                self.assertFalse(plan.exists())

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
