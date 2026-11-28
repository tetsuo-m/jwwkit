"""#68: Jw_cad's random lines (11-15) and double-length lines (16-19) on v700 lines, arcs and circles of the drawing.

The samples in tests/fixtures/sxf_linetypes were drawn by the owner in Jw_cad 10.03.6 (see its README).
"""
import hashlib
import shutil
import unittest
from pathlib import Path

from jwwkit import CadDocument
from jwwkit.model.editing import entity_record
from test_v600_schema700 import TempDirTestCase, fixture

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'sxf_linetypes'
SHA256 = {
    'sxf_random.jww': '75a8844a8090eacb3cdf41b37fd221e804b1f3a656ec86fe3e07720f52943a56',
    'sxf_random_enko.jww': '2566d0feac2b6b56f0198d8d81c73e65a9ede0e302e158caa8015889bb628283',
    'sxf_zenbu2.jww': '75b1b0d6aebf9bb5c67c9b8f4683e513516560adfd654aab2a82264f35462a9b',
}
EXTENDED = list(range(11, 20))
NOT_DEFINED = 'Linetype is not defined in this drawing'


def styles(doc):
    return [(e.entity_type, entity_record(e)['base']['pen_style']) for e in doc.entities]


class RandomDoubleLinetypeTests(TempDirTestCase):
    def test_fixtures_are_the_reviewed_samples(self):
        for name, digest in SHA256.items():
            self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(), digest, name)

    def test_the_samples_hold_11_to_19_on_lines_arcs_and_circles(self):
        self.assertEqual(styles(CadDocument.open(FIXTURES / 'sxf_random.jww')), [('LINE', n) for n in EXTENDED])
        enko = styles(CadDocument.open(FIXTURES / 'sxf_random_enko.jww'))
        for kind in ('ARC', 'CIRCLE'):
            self.assertEqual(sorted(n for k, n in enko if k == kind), EXTENDED)

    def test_edits_of_the_drawn_elements_are_accepted_and_saved(self):
        edits = dict(layer=lambda d, i: d.set_entity_attributes(i, layer=3),
                     color=lambda d, i: d.set_entity_attributes(i, color=5),
                     linetype=lambda d, i: d.set_entity_attributes(i, linetype=19 if entity_record(d.entities[i])['base']['pen_style'] != 19 else 11),
                     move=lambda d, i: d.move_entities([i], (10, 5)),
                     copy=lambda d, i: d.copy_entities([i], (10, 5)))
        for name in ('sxf_random.jww', 'sxf_random_enko.jww'):
            for edit, operation in edits.items():
                with self.subTest(sample=name, edit=edit):
                    doc = CadDocument.open(FIXTURES / name)
                    count = len(doc.entities)
                    for i in range(count):
                        operation(doc, i)
                    path = self.folder / f'{edit}_{name}'
                    doc.save(path)
                    again = CadDocument.open(path)
                    self.assertGreaterEqual(len(again.entities), count)
                    self.assertTrue(all(11 <= s <= 19 for _, s in styles(again)))

    def test_back_to_the_drawn_linetypes_gives_the_sample_bytes(self):
        for name in ('sxf_random.jww', 'sxf_random_enko.jww'):
            with self.subTest(sample=name):
                doc = CadDocument.open(FIXTURES / name)
                drawn = [s for _, s in styles(doc)]
                for i in range(len(doc.entities)):
                    doc.set_entity_attributes(i, linetype=1)
                doc.save(self.folder / f'solid_{name}')
                doc = CadDocument.open(self.folder / f'solid_{name}')
                self.assertEqual({s for _, s in styles(doc)}, {1})
                for i, s in enumerate(drawn):
                    doc.set_entity_attributes(i, linetype=s)
                doc.save(self.folder / f'back_{name}')
                self.assertEqual((self.folder / f'back_{name}').read_bytes(), (FIXTURES / name).read_bytes())

    def test_new_elements_store_the_number_jwcad_stores(self):
        doc = CadDocument.open(FIXTURES / 'sxf_zenbu2.jww')
        for n in EXTENDED:
            doc.add_line((0, n), (10, n), linetype=n)
            doc.add_circle((20, n), 1, linetype=n)
            doc.add_arc((30, n), 1, 0.0, 1.0, linetype=n)
        doc.save(self.folder / 'added.jww')
        added = styles(CadDocument.open(self.folder / 'added.jww'))[31:]
        drawn = styles(CadDocument.open(FIXTURES / 'sxf_random.jww')) + styles(CadDocument.open(FIXTURES / 'sxf_random_enko.jww'))
        self.assertEqual(sorted(added), sorted(drawn))

    def test_a_new_drawing_from_the_template_takes_them_too(self):
        from jwwkit.line_document import JwwDocument
        built = JwwDocument()
        for n in EXTENDED:
            built.add_line((0, n), (10, n), linetype=n)
        built.save(self.folder / 'template.jww')
        self.assertEqual(styles(CadDocument.open(self.folder / 'template.jww')), [('LINE', n) for n in EXTENDED])

    def test_a_search_may_name_them(self):
        doc = CadDocument.open(FIXTURES / 'sxf_random_enko.jww')
        for n in EXTENDED:
            found = doc.find_entities(linetype=n)
            self.assertEqual(sorted(doc.entities[i].entity_type for i in found), ['ARC', 'CIRCLE'])
        # Reading only: any drawing, any version may be searched.
        self.assertEqual(tuple(CadDocument.open(fixture(600)).find_entities(linetype=18)), ())

    def test_outside_the_range_they_stay_refused(self):
        from jwwkit.line_document import Line
        doc = CadDocument.open(FIXTURES / 'sxf_random.jww')
        cases = dict(
            block=lambda d: d.add_block_definition('記号A', [Line((0, 0), (10, 0), linetype=11)]),
            into_block=lambda d: d.replace_entities_with_block([0], '置換A', base_point=(0, 0)),
            solid=lambda d: d.add_solid([(0, 0), (1, 0), (1, 1), (0, 1)], linetype=11),
            zero=lambda d: d.set_entity_attributes(0, linetype=0),
            twenty=lambda d: d.set_entity_attributes(0, linetype=20),
        )
        for name, operation in cases.items():
            with self.subTest(case=name):
                doc = CadDocument.open(FIXTURES / 'sxf_random.jww')
                before = [entity_record(e) for e in doc.entities]
                with self.assertRaisesRegex(ValueError, NOT_DEFINED):
                    operation(doc)
                self.assertEqual([entity_record(e) for e in doc.entities], before)
        # Unnamed rows of the drawing's SXF linetype table stay refused; named ones are accepted as before.
        doc = CadDocument.open(FIXTURES / 'sxf_zenbu2.jww')
        doc.set_entity_attributes(0, linetype=46)
        with self.assertRaisesRegex(ValueError, NOT_DEFINED + ': 47'):
            doc.set_entity_attributes(0, linetype=47)

    def test_dimensions_and_v600_stay_refused(self):
        dims = Path(__file__).resolve().parent / 'fixtures' / 'jwcad_dimensions' / 'd1.jww'
        doc = CadDocument.open(dims)
        index = next(i for i, e in enumerate(doc.entities) if e.entity_type == 'DIMENSION')
        with self.assertRaisesRegex(ValueError, NOT_DEFINED + ': 11'):
            doc.set_entity_attributes(index, linetype=11)
        v600 = CadDocument.open(fixture(600))
        line = next(i for i, e in enumerate(v600.entities) if e.entity_type == 'LINE')
        with self.assertRaisesRegex(ValueError, NOT_DEFINED + ': 11'):
            v600.set_entity_attributes(line, linetype=11)
        with self.assertRaisesRegex(ValueError, NOT_DEFINED + ': 18'):
            v600.add_line((0, 0), (1, 0), linetype=18)

    def test_the_save_checks_the_same_way(self):
        """A stored record changed beside the edit API: 11-19 are kept out of the save only where they are accepted."""
        from dataclasses import replace
        from jwwkit.model.common_entities import model_entity
        v600 = CadDocument.open(fixture(600))
        line = next(i for i, e in enumerate(v600.entities) if e.entity_type == 'LINE')
        record = entity_record(v600.entities[line]); record['base']['pen_style'] = 11
        updated = model_entity(record)
        entities = list(v600.entities)
        entities[line] = replace(entities[line], attributes=updated.attributes, geometry=updated.geometry)
        v600.entities = tuple(entities)
        with self.assertRaisesRegex(ValueError, NOT_DEFINED + ': 11'):
            v600.save(self.folder / 'v600.jww')
        self.assertFalse((self.folder / 'v600.jww').exists())

    def test_the_drawing_comparison_still_reports_them_unsupported(self):
        """compare_drawings is not changed here (#80)."""
        from jwwkit.drawing_comparison import compare_drawings
        path = FIXTURES / 'sxf_random.jww'
        result = compare_drawings(path, path)
        self.assertEqual(len([u for u in result['unsupported'] if u['side'] == 'left']), 9)


if __name__ == '__main__':
    unittest.main()
