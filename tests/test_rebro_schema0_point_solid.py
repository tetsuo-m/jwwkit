"""Issue #36: schema-0 points and solids for rebro_schema0 and the schema normalization (v700 only).

Accepted are only the forms observed in 37 real drawings (Issue #35): points of line type 1 that are
not temporary and carry no symbol fields, solids of line type 1 and circle solids of line type 101,
neither with an RGB colour. Everything else stays rejected: other forms, dimension and block
declarations, line types 31 and 49, images, and points or solids in v600.
"""
import copy
import hashlib
import re
import struct
import sys
import tempfile
import unittest
from pathlib import Path

from jwwkit import CadDocument, template_path
from jwwkit.line_document import BlockDefinition, BlockReference, Circle, Dimension, Line, Point, Solid, Text
from jwwkit.reader.archive import RecordError, read_records_bytes
from jwwkit.writer.preserved import serialize_body
from jwwkit._normalization_inspection import inspect_bytes

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
HINT_700 = 'v700 CDataSen/CDataEnko/CDataMoji/CDataTen/CDataSolid'


def circle_solid(**changes):
    record = dict(type='CIRCLE_SOLID',
                  base=dict(group=0, pen_style=101, pen_color=2, pen_width=0, layer=0, layer_group=0, flag=0),
                  center_x=5.0, center_y=5.0, radius=2.0, flatness=1.0, tilt_angle=0.0,
                  start_angle=0.0, arc_angle=0.0, solid_mode=100.0, color=None)
    record['base'].update(changes.pop('base', {}))
    record.update(changes)
    return record


def with_style(record, style, **fields):
    record = copy.deepcopy(record)
    record['base']['pen_style'] = style
    record.update(fields)
    return record


def accepted_records():
    """Every kind rebro_schema0 accepts in v700, in the observed forms."""
    return [Line((0, 0), (10, 0)).record(), Circle((5, 5), 2).record(),
            Circle((10, 10), 3, is_full_circle=False, arc_angle=1).record(),
            Text((0, 0), (5, 0), 'synthetic').record(), Point((1, 1)).record(),
            Solid(((0, 0), (1, 0), (1, 1), (0, 1))).record(), circle_solid()]


def declaration_offsets(data):
    """Offsets of the class declarations (WORD 0xFFFF, schema, name length, CData name), found in the bytes
    so that drawings the reader rejects can be built too."""
    return [m.start() for m in re.finditer(rb'\xff\xff..(..)CData', data, re.S)]


def drawing(records, definitions=(), *, version=700, zero=True):
    """Template header + serialized body; with zero=True every class declaration's schema is 0."""
    template = template_path().read_bytes()
    end = read_records_bytes(template)['header_end']
    header = bytearray(template[:end])
    struct.pack_into('<I', header, 8, 600)
    base = bytes(header) + serialize_body(list(records), list(definitions), 600, encoding='cp932')
    data = bytearray(base)
    struct.pack_into('<I', data, 8, version)
    for offset in declaration_offsets(base[end:]):
        struct.pack_into('<H', data, end + offset + 2, 0 if zero else version)
    if version == 700:
        data += bytes(4)  # no images
    return bytes(data)


class RebroSchema0PointSolidTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)

    def write(self, name, data):
        path = self.folder / name
        path.write_bytes(data)
        return path

    def assert_rejected(self, data, text, name='rejected.jww'):
        path = self.write(name, data)
        with self.assertRaises(RecordError) as caught:
            CadDocument.open(path, schema_profile='rebro_schema0')
        self.assertIn(text, str(caught.exception))
        info, output = inspect_bytes(data, path)
        self.assertEqual((info['status'], output), ('unsupported', None))
        return str(caught.exception), info

    def test_points_and_solids_open_read_only_and_save_unchanged(self):
        data = drawing(accepted_records())
        declared = {d['name'] for d in read_records_bytes(data, schema_profile='rebro_schema0')['class_declarations']}
        self.assertEqual(declared, {'CDataSen', 'CDataEnko', 'CDataMoji', 'CDataTen', 'CDataSolid'})
        path = self.write('rebro.jww', data)
        document = CadDocument.open(path, schema_profile='rebro_schema0')
        self.assertEqual(sorted(e.entity_type for e in document.entities),
                         ['ARC', 'CIRCLE', 'CIRCLE_SOLID', 'LINE', 'POINT', 'SOLID', 'TEXT'])
        target = self.folder / 'saved.jww'
        document.save(target)
        self.assertEqual(target.read_bytes(), data)
        with self.assertRaises(ValueError):
            document.add_line((0, 0), (1, 1))  # still read-only
        with self.assertRaises(RecordError):
            CadDocument.open(path)  # strict still rejects schema 0

    def test_normalized_copy_is_the_drawing_before_zeroing(self):
        before = drawing(accepted_records(), zero=False)
        data = drawing(accepted_records())
        # The test's own declaration search agrees with the reader
        self.assertEqual(declaration_offsets(before), [d['offset'] for d in read_records_bytes(before)['class_declarations']])
        info, output = inspect_bytes(data, self.folder / 'rebro.jww')
        self.assertEqual((info['status'], info['reason']), ('normalize', 'observed_schema0_only'))
        self.assertEqual(output, before)
        self.assertEqual(info['expected_output_sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual({d['name'] for d in info['changed_declarations']},
                         {'CDataSen', 'CDataEnko', 'CDataMoji', 'CDataTen', 'CDataSolid'})
        self.assertEqual(info['unsupported_declarations'], [])
        normalized = CadDocument.open(self.write('normalized.jww', output))  # strict
        original = CadDocument.open(self.write('rebro.jww', data), schema_profile='rebro_schema0')
        self.assertEqual([(e.entity_type, e.geometry, e.attributes) for e in normalized.entities],
                         [(e.entity_type, e.geometry, e.attributes) for e in original.entities])
        saved = self.folder / 'normalized_saved.jww'
        normalized.save(saved)
        self.assertEqual(saved.read_bytes(), output)

    @unittest.skipUnless(sys.platform == 'win32', 'the normalization commit is Windows-only')
    def test_plan_and_execute_normalize_points_and_solids(self):
        from jwwkit.normalization import execute_schema_normalization_plan, write_schema_normalization_plan
        from jwwkit.workflow_settings import load_workflow_settings, resolve_opening_settings
        work = self.folder / 'work'
        work.mkdir()
        (work / 'jww_workflow.toml').write_text('schema_version = 2\n[opening]\nrebro_schema0 = "normalize"\n',
                                                encoding='utf-8')
        source = work / 'rebro.jww'
        source.write_bytes(drawing(accepted_records()))
        plan = work / 'plan.json'
        settings = resolve_opening_settings(load_workflow_settings(work))
        write_schema_normalization_plan([source], work / 'out', plan, opening_settings=settings)
        result = execute_schema_normalization_plan(plan, approved_sha256=hashlib.sha256(plan.read_bytes()).hexdigest())
        self.assertEqual(result['status'], 'completed')
        output = work / 'out' / 'rebro.normalized.jww'
        self.assertEqual(output.read_bytes(), drawing(accepted_records(), zero=False))
        self.assertEqual(source.read_bytes(), drawing(accepted_records()))

    def test_unobserved_point_and_solid_forms_are_rejected(self):
        point, solid = Point((1, 1)).record(), Solid(((0, 0), (1, 0), (1, 1), (0, 1))).record()
        cases = {
            'temporary point': (Point((1, 1), is_temporary=True).record(), 'Unobserved point form for rebro_schema0'),
            'symbol point (line type 100)': (with_style(point, 100, code=5, angle=0.5, scale=1.0),
                                             'Unobserved point form for rebro_schema0'),
            'point line type 2': (with_style(point, 2), 'Unsupported point style'),
            'RGB solid': (Solid(((0, 0), (1, 0), (1, 1), (0, 1)), rgb=(255, 0, 0), color=10).record(),
                          'Unobserved solid form for rebro_schema0'),
            'solid line type 2': (with_style(solid, 2), 'Unobserved solid form for rebro_schema0'),
            'RGB circle solid': (circle_solid(base=dict(pen_color=10), color=0xff0000),
                                 'Unobserved solid form for rebro_schema0'),
            'circle solid line type 105': (circle_solid(base=dict(pen_style=105)),
                                           'Unobserved solid form for rebro_schema0'),
        }
        for name, (record, text) in cases.items():
            with self.subTest(case=name):
                self.assert_rejected(drawing([Line((0, 0), (1, 0)).record(), record]), text)

    def test_point_line_types_31_and_49_keep_the_current_rejection(self):
        for style in (31, 49):
            with self.subTest(style=style):
                record = with_style(Point((1, 1)).record(), style)
                message, info = self.assert_rejected(drawing([Line((0, 0), (1, 0)).record(), record]),
                                                     'Unsupported point style')
                self.assertTrue(message.startswith('Unsupported point style; element=entities[1]'), message)

    def test_dimension_and_block_declarations_stay_rejected(self):
        cases = {
            'dimension': ([Line((0, 0), (1, 0)).record(),
                           Dimension(Line((0, 20), (10, 20)), Text((4, 21), (6, 21), '10')).record()], [],
                          {'CDataSunpou'}),
            'block': ([Line((0, 0), (1, 0)).record(), BlockReference((3, 3), 1).record()],
                      [BlockDefinition(1, 'synthetic block', [Line((0, 0), (1, 1))]).record(True)],
                      {'CDataBlock', 'CDataList'}),
        }
        for name, (records, definitions, classes) in cases.items():
            with self.subTest(case=name):
                message, info = self.assert_rejected(drawing(records, definitions), 'Unsupported class schema: 0, class=')
                self.assertIn(message.split('class=')[1].split(';')[0], classes)
                self.assertIn(HINT_700, message)
                self.assertTrue(info['unsupported_declarations'])
                self.assertEqual({d['reason'] for d in info['unsupported_declarations']},
                                 {'outside_observed_schema0_scope'})

    def test_public_sample_with_dimension_and_block_stays_rejected(self):
        data = bytearray((FIXTURES / 'jwcad_saved' / 'jwcad10036_save_v700.jww').read_bytes())
        for declaration in read_records_bytes(bytes(data))['class_declarations']:
            struct.pack_into('<H', data, declaration['offset'] + 2, 0)
        message, info = self.assert_rejected(bytes(data), 'Unsupported class schema: 0')
        rejected_class = message.split('class=')[1].split(';')[0]
        self.assertIn(rejected_class, {'CDataSunpou', 'CDataBlock', 'CDataList'})

    def test_images_stay_rejected(self):
        data = bytearray((FIXTURES / 'jwcad_images' / 'a5.jww').read_bytes())
        declarations = read_records_bytes(bytes(data))['class_declarations']
        self.assertTrue(declarations)
        for declaration in declarations:
            struct.pack_into('<H', data, declaration['offset'] + 2, 0)
        self.assert_rejected(bytes(data), 'Images unobserved for rebro_schema0')

    def test_v600_points_and_solids_stay_rejected(self):
        for name, record, cls in (('point', Point((1, 1)).record(), 'CDataTen'),
                                  ('solid', Solid(((0, 0), (1, 0), (1, 1), (0, 1))).record(), 'CDataSolid'),
                                  ('circle solid', circle_solid(), 'CDataSolid')):
            with self.subTest(case=name):
                message, info = self.assert_rejected(drawing([Line((0, 0), (1, 0)).record(), record], version=600),
                                                     f'Unsupported class schema: 0, class={cls}')
                self.assertIn('v600 CDataSen/CDataEnko/CDataMoji', message)
        # The three classes are still accepted in v600
        data = drawing([Line((0, 0), (10, 0)).record(), Circle((5, 5), 2).record(),
                        Text((0, 0), (5, 0), 'synthetic').record()], version=600)
        path = self.write('v600.jww', data)
        document = CadDocument.open(path, schema_profile='rebro_schema0')
        target = self.folder / 'v600_saved.jww'
        document.save(target)
        self.assertEqual(target.read_bytes(), data)
        self.assertEqual(inspect_bytes(data, path)[0]['status'], 'normalize')

    def test_rejection_hint_names_the_classes_per_version(self):
        message, _ = self.assert_rejected(
            drawing([Line((0, 0), (1, 0)).record(), Point((1, 1)).record()], version=600), 'class=CDataTen')
        self.assertIn('; schema=0: explicit schema_profile="rebro_schema0" permits only observed '
                      'v600 CDataSen/CDataEnko/CDataMoji and ' + HINT_700 + ' (read-only)', message)


if __name__ == '__main__':
    unittest.main()
