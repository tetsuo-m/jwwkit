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
                    before = [entity_record(e) for e in CadDocument.open(FIXTURES / name).entities]
                    after = [entity_record(e) for e in CadDocument.open(path).entities]
                    self.assertEqual(len(after), 2 * count if edit == 'copy' else count)
                    self.assertTrue(all(11 <= a['base']['pen_style'] <= 19 for a in after))
                    for a, b in zip(after, before):
                        if edit == 'layer':
                            self.assertEqual(a['base']['layer'], 3)
                        elif edit == 'color':
                            self.assertEqual(a['base']['pen_color'], 5)
                        elif edit == 'linetype':
                            self.assertNotEqual(a['base']['pen_style'], b['base']['pen_style'])
                        elif edit == 'move':
                            key = 'start_x' if a['type'] == 'LINE' else 'center_x'
                            self.assertAlmostEqual(a[key], b[key] + 10)
                        else:
                            self.assertEqual(a, b)   # copy: the originals stay

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
        # Reading only: any drawing, any version may be searched; the query condition too.
        self.assertEqual(tuple(CadDocument.open(fixture(600)).find_entities(linetype=18)), ())
        from jwwkit.model.query import find
        self.assertEqual(sorted(find(doc, linetype=[11, 19])), sorted(doc.find_entities(linetype=11) + doc.find_entities(linetype=19)))
        for value in (10, 20):
            with self.assertRaisesRegex(ValueError, NOT_DEFINED + f': {value}'):
                doc.find_entities(linetype=value)

    def test_outside_the_range_they_stay_refused(self):
        from jwwkit.line_document import Line
        doc = CadDocument.open(FIXTURES / 'sxf_random.jww')
        cases = dict(
            block=lambda d: d.add_block_definition('記号A', [Line((0, 0), (10, 0), linetype=11)]),
            into_block=lambda d: d.replace_entities_with_block([0], '置換A', base_point=(0, 0)),
            solid=lambda d: d.add_solid([(0, 0), (1, 0), (1, 1), (0, 1)], linetype=11),
            zero=lambda d: d.set_entity_attributes(0, linetype=0),
            ten=lambda d: d.set_entity_attributes(0, linetype=10),
            ten_added=lambda d: d.add_line((0, 0), (1, 0), linetype=10),
            ten_circle=lambda d: d.add_circle((0, 0), 1, linetype=10),
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

    def test_a_reused_block_definition_keeps_its_children_checked(self):
        """Making a block that reuses a same-name definition: its children are checked as children of a block."""
        from dataclasses import replace
        doc = CadDocument.open(FIXTURES / 'sxf_random.jww')
        doc.add_line((0, 0), (10, 0), linetype=2)
        doc.replace_entities_with_block([len(doc.entities) - 1], '記号A', base_point=(0, 0))
        definition = next(d for d in doc.block_definitions if d.name_info.display_name == '記号A')
        child = definition.entities[0]
        changed = replace(child, attributes=dict(child.attributes, pen_style=11))   # as if read from a drawing
        doc.block_definitions = tuple(replace(d, entities=(changed,)) if d.number == definition.number else d
                                      for d in doc.block_definitions)
        doc.add_line((0, 0), (10, 0), linetype=11)
        before = [entity_record(e) for e in doc.entities]
        with self.assertRaisesRegex(ValueError, NOT_DEFINED + ': 11'):
            doc.replace_entities_with_block([len(doc.entities) - 1], '記号A', base_point=(0, 0))
        self.assertEqual([entity_record(e) for e in doc.entities], before)

    def test_template_drawings_take_them_only_where_they_are_accepted(self):
        from jwwkit.line_document import JwwDocument, Line, Text
        from jwwkit.model.point import Point
        built = JwwDocument()
        built.add_circle((0, 0), 1, linetype=12)
        built.add_arc((0, 0), 1, 0.0, 1.0, linetype=18)
        built.save(self.folder / 'template_arcs.jww')
        self.assertEqual(styles(CadDocument.open(self.folder / 'template_arcs.jww')), [('CIRCLE', 12), ('ARC', 18)])
        cases = dict(
            block=lambda d: d.add_block_definition('記号B', [Line((0, 0), (10, 0), linetype=11)]),
            dimension=lambda d: d.add_dimension(Line((0, 10), (4, 10), linetype=11, flag=8192),
                                                Text((1, 11), (2, 11), '400', text_type=3, flag=16400),
                                                aux_lines=[Line((0, 0), (0, 0)) for _ in range(2)],
                                                aux_points=[Point((0, 0)) for _ in range(4)]),
            solid=lambda d: d.add_solid([(0, 0), (1, 0), (1, 1), (0, 1)], linetype=11),
            ten=lambda d: d.add_line((0, 0), (1, 0), linetype=10),
        )
        for name, operation in cases.items():
            with self.subTest(case=name):
                with self.assertRaisesRegex(ValueError, NOT_DEFINED):
                    operation(JwwDocument())
        # Copying a drawing into the template writes the template's header: the definitions would not be kept.
        source = JwwDocument()
        source.add_line((0, 0), (10, 0), linetype=11)
        source.save(self.folder / 'source.jww')
        for name, operation in (('open', lambda: JwwDocument.open(self.folder / 'source.jww')),
                                ('from_cad_document', lambda: JwwDocument.from_cad_document(CadDocument.open(self.folder / 'source.jww')))):
            with self.subTest(copy=name):
                with self.assertRaisesRegex(ValueError, 'Random/double-length'):
                    operation()

    def test_other_kinds_and_places_stay_refused(self):
        doc = CadDocument.open(FIXTURES / 'sxf_random.jww')
        doc.add_text((0, 0), content='A', size_x=3, size_y=3)
        doc.add_point((0, 0))
        for kind in ('TEXT', 'POINT'):
            index = next(i for i, e in enumerate(doc.entities) if e.entity_type == kind)
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, '線種変更は未対応'):
                    doc.set_entity_attributes(index, linetype=11)
        dims = Path(__file__).resolve().parent / 'fixtures' / 'jwcad_dimensions' / 'd1.jww'
        doc = CadDocument.open(dims)
        v600 = CadDocument.open(fixture(600))
        for name, operation in (('circle', lambda d: d.add_circle((0, 0), 1, linetype=11)),
                                ('arc', lambda d: d.add_arc((0, 0), 1, 0.0, 1.0, linetype=19))):
            with self.subTest(v600=name):
                with self.assertRaisesRegex(ValueError, NOT_DEFINED):
                    operation(v600)
        # A dimension part changed beside the edit API is refused at the save (v700).
        from dataclasses import replace
        from jwwkit.model.common_entities import model_entity
        index = next(i for i, e in enumerate(doc.entities) if e.entity_type == 'DIMENSION')
        record = entity_record(doc.entities[index]); record['line']['base']['pen_style'] = 11
        updated = model_entity(record)
        entities = list(doc.entities)
        entities[index] = replace(entities[index], attributes=updated.attributes, geometry=updated.geometry)
        doc.entities = tuple(entities)
        with self.assertRaisesRegex(ValueError, NOT_DEFINED + ': 11'):
            doc.save(self.folder / 'dimension_part.jww')

    def test_the_drawing_comparison_still_reports_them_unsupported(self):
        """compare_drawings is not changed here (#80)."""
        from jwwkit.drawing_comparison import compare_drawings
        path = FIXTURES / 'sxf_random.jww'
        result = compare_drawings(path, path)
        self.assertEqual(len([u for u in result['unsupported'] if u['side'] == 'left']), 9)


if __name__ == '__main__':
    unittest.main()
