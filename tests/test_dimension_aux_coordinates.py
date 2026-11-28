"""#73: a dimension figure (SXF mode 0) whose auxiliary lines/points carry coordinates is refused for geometry
changes, because jwwkit moves only its line and text and would leave the auxiliaries behind.

The inputs are made here from the public Jw_cad samples (tests/fixtures/jwcad_dimensions): one dimension of
d10 (text type 0) and one of d1 (text types 1-10) gets coordinates in its auxiliaries and is saved to a
temporary folder. Dimensions whose auxiliaries are all 0 (the Jw_cad samples) keep moving as before.
"""
import math
import unittest
from pathlib import Path

from jwwkit import CadDocument
from jwwkit.model.editing import AUX_COORDINATE_MESSAGE, commit, entity_record
from jwwkit.safe_edit import write_plan
from test_v600_schema700 import TempDirTestCase

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'jwcad_dimensions'
REFUSED = '補助線・補助点に座標がある寸法図形'
# Scaling a dimension with a text type was refused before #73, with its own message; either refusal is right.
REFUSED_OR_PRESET = REFUSED + '|Preset text/dimension scaling or reflection is unverified'


def give_aux_coordinates(record):
    """Auxiliaries on the dimension line and its ends, as in an Archicad export resaved by Jw_cad (#69)."""
    line = record['line']
    for aux in record['aux_lines']:
        for key in ('start_x', 'start_y', 'end_x', 'end_y'):
            aux[key] = line[key]
    for point, (x, y) in zip(record['aux_points'], [('start_x', 'start_y'), ('end_x', 'end_y')] * 2):
        point['x'], point['y'] = line[x], line[y]


class AuxCoordinateDimensionTests(TempDirTestCase):
    def make(self, source, text_type):
        """Save a copy of source in which the first dimension of text_type has auxiliary coordinates."""
        doc = CadDocument.open(FIXTURES / source)
        index = next(i for i, e in enumerate(doc.entities)
                     if e.entity_type == 'DIMENSION' and e.geometry['text']['text_type'] == text_type)
        record = entity_record(doc.entities[index])
        give_aux_coordinates(record)
        commit(doc, index, doc.entities[index], record)
        path = self.folder / f'aux_{source[:-4]}_{text_type}.jww'
        doc.save(path)
        return path, index

    def inputs(self):
        return [self.make('d10.jww', 0), self.make('d1.jww', 3), self.make('d1.jww', 1)]

    def assert_refused(self, path, index, operation, pattern=REFUSED):
        doc = CadDocument.open(path)
        before = [entity_record(e) for e in doc.entities]
        with self.assertRaisesRegex(ValueError, pattern):
            operation(doc, index)
        self.assertEqual([entity_record(e) for e in doc.entities], before)

    def test_geometry_changes_are_refused_and_change_nothing(self):
        operations = dict(
            move_entity=lambda d, i: d.move_entity(i, (10, 5)),
            move_entities=lambda d, i: d.move_entities([i], (10, 5)),
            move_real=lambda d, i: d.move_entities([i], (100, 50), units='real'),
            copy=lambda d, i: d.copy_entities([i], (10, 0)),
            translate=lambda d, i: d.transform_entities([i], translation=(3, 4)),
            align=lambda d, i: d.align_two_points([i], [(0, 0), (100, 0)], [(10, 5), (110, 5)],
                                                  distance_tolerance=1e-6, angle_tolerance=1e-9),
            rotate=lambda d, i: d.rotate_entities([i], math.pi / 2),
            scale=lambda d, i: d.scale_entities([i], 2),
        )
        for path, index in self.inputs():
            for name, operation in operations.items():
                with self.subTest(source=path.name, operation=name):
                    pattern = REFUSED_OR_PRESET if name == 'scale' and 'd1' in path.name else REFUSED
                    self.assert_refused(path, index, operation, pattern)

    def test_text_type_0_scale_cases_are_refused(self):
        path, index = self.make('d10.jww', 0)
        self.assert_refused(path, index, lambda d, i: d.scale_entities([i], 2, 3))

        def real_group_change(d, i):
            group = d.entities[i].attributes['layer_group']
            other = 1 if group != 1 else 2
            d.set_group_scale(other, d.get_group_scale(group) * 2)
            d.set_entity_attributes(i, layer_group=other, preserve='real')
        self.assert_refused(path, index, real_group_change)

    def test_group_import_with_a_scale_conversion_is_refused(self):
        path, index = self.make('d10.jww', 0)
        source = CadDocument.open(path)
        group = source.entities[index].attributes['layer_group']
        destination = CadDocument.open(FIXTURES / 'd0.jww')
        destination.set_group_scale(5, source.get_group_scale(group) * 2)
        before = [entity_record(e) for e in destination.entities]
        with self.assertRaisesRegex(ValueError, REFUSED):
            destination.import_group(path, group, 5, settings_policy='destination')
        self.assertEqual([entity_record(e) for e in destination.entities], before)

    def test_safe_edit_plans_stop_the_same_way(self):
        for path, index in self.inputs():
            for op, kwargs in (('move_entities', dict(delta=[10, 0])), ('copy_entities', dict(delta=[10, 0])),
                               ('rotate_entities', dict(angle=0.5)), ('scale_entities', dict(scale_x=2))):
                with self.subTest(source=path.name, op=op):
                    doc = CadDocument.open(path)
                    plan = self.folder / f'plan_{path.stem}_{op}.json'
                    pattern = REFUSED_OR_PRESET if op == 'scale_entities' and 'd1' in path.name else REFUSED
                    with self.assertRaisesRegex(ValueError, pattern):
                        write_plan(doc, [index], [dict(op=op, indices=[index], kwargs=kwargs)],
                                   self.folder / f'out_{path.stem}_{op}.jww', plan)
                    self.assertFalse(plan.exists())

    def test_changes_that_keep_the_geometry_still_work(self):
        path, index = self.make('d10.jww', 0)
        doc = CadDocument.open(path)
        doc.move_entities([index], (0, 0))
        doc.set_entity_attributes(index, layer=4)
        self.assertEqual(doc.entities[index].attributes['layer'], 4)
        # Turning it into a block converts the auxiliaries with the dimension, as Jw_cad does (d1_block, #73).
        doc = CadDocument.open(path)
        doc.replace_entities_with_block([index], 'aux_block', base_point=(10, 5))
        doc.save(self.folder / 'aux_block.jww')
        saved = CadDocument.open(self.folder / 'aux_block.jww')
        self.assertEqual(len(saved.block_definitions), len(CadDocument.open(path).block_definitions) + 1)

    def test_dimensions_with_all_zero_auxiliaries_still_move(self):
        for source in ('d1.jww', 'd8.jww', 'd10.jww'):
            with self.subTest(source=source):
                doc = CadDocument.open(FIXTURES / source)
                dims = [i for i, e in enumerate(doc.entities) if e.entity_type == 'DIMENSION']
                doc.move_entities(dims, (10, 5))
                doc.save(self.folder / f'moved_{source}')

    def test_message(self):
        self.assertIn('Jw_cadで操作してください', AUX_COORDINATE_MESSAGE)


if __name__ == '__main__':
    unittest.main()
