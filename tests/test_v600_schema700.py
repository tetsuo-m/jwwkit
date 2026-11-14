"""Issue #11: Jw_cad v6-format files whose class declarations use schema 700.

Jw_cad 10.03.6 writes every class declaration with schema 700 even when saving in
the v6 format. jwwkit accepts exactly (file version 600, class schema 700), with
every declaration at 700, for reading and unedited save-as only.
"""
import collections
import inspect
import struct
import tempfile
import unittest
from pathlib import Path

from jwwkit import CadDocument, template_path
from jwwkit.line_document import (BlockDefinition, BlockReference, Circle, Dimension, Line,
                                  Point, Solid, Text)
import hashlib

from jwwkit.legacy_document import LegacyDocument
from jwwkit.reader.archive import (Cursor, RecordError, read_document, read_entity_sequences,
                                   read_records_bytes)
from jwwkit.reader.jws import JwsDocument
from jwwkit.writer.preserved import serialize_body
from jwwkit._normalization_inspection import inspect_bytes

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'jwcad_saved'
EXPECTED_TYPES = {'LINE': 14, 'ARC': 2, 'POINT': 9, 'TEXT': 9, 'BLOCK': 1, 'CIRCLE_SOLID': 1, 'DIMENSION': 3}
FIXTURE_SHA256 = {
    230: '017ddc5979706e3a317b80c9c9b1bbf177f6a5ef0a437131c98c511ffb638873',
    300: 'f5c9d26bf91bec9273b160bbf44176dc680a8e35f76faf1ca55bf3ba12e25f31',
    351: 'ca95bf5aa14207eb75aec86c771cb4453b5a57ccf62c817a8d7853e08f8e8f00',
    420: 'be8e693155a12812c3d1c356251aec4e405f257476447e852fd98c1466ea8a33',
    600: '97bc00f8cf7c2e205ee9fcdb4961962267432b6bb501dc311e5a9b4ade12354e',
    700: '55ee22c21dd86cd5b78c5846160a470213e311e93c39b48e6fe9d0df04496cfd',
}
IMAGE_TEXT = '^@BM%temp%synthetic_image.jpg,100,48.062,0,0,1,0,255,255,255'


def fixture(version):
    return FIXTURES / f'jwcad10036_save_v{version}.jww'


def synthetic(file_version=600, schemas=700, *, trailer=None, basic=False):
    """Template header + serialized body; declaration schema words patched afterwards."""
    template = template_path().read_bytes()
    end = read_records_bytes(template)['header_end']
    header = bytearray(template[:end])
    line = Line((0, 0), (10, 0))
    records = [line.record(), Circle((5, 5), 2).record(),
               Circle((10, 10), 3, is_full_circle=False, arc_angle=1).record(),
               Text((0, 0), (5, 0), 'synthetic').record(), Text((0, 10), (5, 10), IMAGE_TEXT).record(),
               Point((1, 1)).record(), Solid(((0, 0), (1, 0), (1, 1), (0, 1))).record(),
               Dimension(Line((0, 20), (10, 20)), Text((4, 21), (6, 21), '10')).record(),
               BlockReference((3, 3), 1).record()]
    definitions = [BlockDefinition(1, 'synthetic block', [Line((0, 0), (1, 1))]).record(True)]
    if basic:  # only the classes LegacyDocument accepts, no block definitions
        records, definitions = [line.record(), Text((0, 0), (5, 0), 'synthetic').record()], []
    struct.pack_into('<I', header, 8, 600)
    base = bytes(header) + serialize_body(records, definitions, 600, encoding='cp932')
    declarations = read_records_bytes(base)['class_declarations']
    data = bytearray(base)
    struct.pack_into('<I', data, 8, file_version)
    for index, declaration in enumerate(declarations):
        schema = schemas[index] if isinstance(schemas, (list, tuple)) else schemas
        struct.pack_into('<H', data, declaration['offset'] + 2, schema)
    if file_version == 700:
        data += bytes(4) if trailer is None else trailer
    elif trailer is not None:
        data += trailer
    return bytes(data)


def editing_methods():
    """The CadDocument methods that start with self._require_editable()."""
    names = []
    for name, member in inspect.getmembers(CadDocument, inspect.isfunction):
        try:
            source = inspect.getsource(member)
        except (OSError, TypeError):  # generated dataclass methods have no source
            continue
        if 'self._require_editable()' in source:
            names.append(name)
    return names


def dummy_arguments(function):
    args, kwargs = [], {}
    for parameter in list(inspect.signature(function).parameters.values())[1:]:
        if parameter.default is not inspect.Parameter.empty or parameter.kind in (
                parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            continue
        if parameter.kind == parameter.KEYWORD_ONLY:
            kwargs[parameter.name] = None
        else:
            args.append(None)
    return args, kwargs


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, data):
        path = self.folder / name
        path.write_bytes(data)
        return path


class JwcadSavedV600Tests(TempDirTestCase):
    def test_fixture_hashes_and_declarations(self):
        for version in (230, 300, 351, 420, 600, 700):
            data = fixture(version).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), FIXTURE_SHA256[version])
            self.assertEqual(struct.unpack_from('<I', data, 8)[0], version)
        parsed = read_records_bytes(fixture(600).read_bytes())
        self.assertEqual(parsed['version'], 600)
        self.assertEqual(parsed['class_schema'], 700)
        self.assertEqual({d['schema'] for d in parsed['class_declarations']}, {700})
        self.assertEqual(len(parsed['class_declarations']), 8)
        self.assertEqual(parsed['raw_trailer'], b'')
        self.assertEqual(read_records_bytes(fixture(700).read_bytes())['class_schema'], 700)

    def test_opens_with_expected_records(self):
        document = CadDocument.open(fixture(600))
        self.assertEqual(document.version, 600)
        self.assertEqual(document.diagnostics, ())
        counts = collections.Counter(r['type'] for r in document._source_records['entities'])
        self.assertEqual(dict(counts), EXPECTED_TYPES)
        self.assertEqual(len(document.block_definitions), 1)
        self.assertEqual(len(document.block_definitions[0].entities), 4)
        dimension = next(r for r in document._source_records['entities'] if r['type'] == 'DIMENSION')
        self.assertEqual((dimension['sxf_mode'], len(dimension['aux_lines']), len(dimension['aux_points'])), (0, 2, 4))

    def test_unedited_save_is_byte_identical_and_keeps_schema_700(self):
        for include_metadata in (False, True):
            document = CadDocument.open(fixture(600), include_metadata=include_metadata)
            target = self.folder / f'copy_{include_metadata}.jww'
            document.save(target)
            self.assertEqual(target.read_bytes(), fixture(600).read_bytes())
            again = read_records_bytes(target.read_bytes())
            self.assertEqual({d['schema'] for d in again['class_declarations']}, {700})
            self.assertEqual(again['raw_trailer'], b'')
            self.assertEqual(CadDocument.open(target).entities, document.entities if not include_metadata
                             else CadDocument.open(fixture(600)).entities)

    def test_all_editing_apis_are_rejected_before_changes(self):
        methods = editing_methods()
        self.assertEqual(len(methods), 31)
        document = CadDocument.open(fixture(600))
        before = (document.entities, document.block_definitions, document.header)
        for name in methods:
            args, kwargs = dummy_arguments(getattr(CadDocument, name))
            with self.subTest(method=name):
                with self.assertRaises(ValueError) as caught:
                    getattr(document, name)(*args, **kwargs)
                self.assertIn('schema 700', str(caught.exception))
                self.assertIn('Ver.7.00 (v7) format', str(caught.exception))
        self.assertEqual((document.entities, document.block_definitions, document.header), before)
        target = self.folder / 'after_rejections.jww'
        document.save(target)
        self.assertEqual(target.read_bytes(), fixture(600).read_bytes())

    def test_direct_model_changes_cannot_be_saved(self):
        import dataclasses
        changes = [
            lambda d: setattr(d, 'entities', d.entities[:-1]),
            lambda d: setattr(d, 'block_definitions', ()),
            lambda d: setattr(d, 'header', dict(d.header, version=700)),
            lambda d: setattr(d, 'version', 700),
            lambda d: d._name_edits.update({0: 'x'}),
            lambda d: setattr(d, 'entities', (dataclasses.replace(
                d.entities[0], geometry=dict(d.entities[0].geometry, start_x=-0.0
                                             if d.entities[0].geometry.get('start_x') == 0 else 0.0)),)
                + d.entities[1:]),
        ]
        for index, change in enumerate(changes):
            document = CadDocument.open(fixture(600))
            change(document)
            with self.subTest(change=index):
                with self.assertRaises(ValueError) as caught:
                    document.save(self.folder / f'changed_{index}.jww')
                self.assertTrue('read-only' in str(caught.exception) or 'byte-identical' in str(caught.exception),
                                str(caught.exception))
                self.assertFalse((self.folder / f'changed_{index}.jww').exists())

    def test_v7_resave_of_the_same_drawing_is_editable(self):
        # The guidance in the rejection message: the same drawing saved by Jw_cad
        # 10.03.6 in the Ver.7.00 format opens, saves unedited and can be edited.
        document = CadDocument.open(fixture(700))
        target = self.folder / 'v700_copy.jww'
        document.save(target)
        self.assertEqual(target.read_bytes(), fixture(700).read_bytes())
        lines = sum(1 for e in document.entities if e.entity_type == 'LINE')
        document.add_line((0, 0), (100, 0))
        edited = self.folder / 'v700_edited.jww'
        document.save(edited)
        again = CadDocument.open(edited)
        self.assertEqual(sum(1 for e in again.entities if e.entity_type == 'LINE'), lines + 1)

    def test_old_format_fixtures_stay_rejected(self):
        for version in (230, 300, 351, 420):
            with self.subTest(version=version):
                with self.assertRaises(RecordError) as caught:
                    CadDocument.open(fixture(version))
                self.assertIn('Only observed v600/v700', str(caught.exception))

    def test_v700_body_without_image_count_equals_v600_body(self):
        # Synthetic-construction check: v6 = v7 with version 600 and no image-count trailer.
        v700, v600 = fixture(700).read_bytes(), fixture(600).read_bytes()
        end = read_records_bytes(v600)['header_end']
        self.assertEqual(read_records_bytes(v700)['header_end'], end)
        self.assertEqual(v700[-4:], bytes(4))
        self.assertEqual(v700[end:-4], v600[end:])
        converted = bytearray(v700[:-4])
        struct.pack_into('<I', converted, 8, 600)
        path = self.write('converted.jww', bytes(converted))
        document = CadDocument.open(path)
        self.assertEqual(document._source_records['class_schema'], 700)
        target = self.folder / 'converted_copy.jww'
        document.save(target)
        self.assertEqual(target.read_bytes(), bytes(converted))

    def test_normalization_inspection_reports_already_standard(self):
        entry, output = inspect_bytes(fixture(600).read_bytes(), 'v600')
        self.assertEqual((entry['status'], entry['reason']), ('not_needed', 'already_standard'))
        self.assertIsNone(output)
        self.assertEqual({d['schema'] for d in entry['declarations']}, {700})


class SyntheticSchemaPairTests(TempDirTestCase):
    def test_synthetic_600_700_all_types_open_and_save(self):
        data = synthetic(600, 700)
        path = self.write('synthetic.jww', data)
        document = CadDocument.open(path)
        self.assertEqual(document._source_records['class_schema'], 700)
        types = collections.Counter(r['type'] for r in document._source_records['entities'])
        self.assertEqual(dict(types), {'LINE': 1, 'CIRCLE': 1, 'ARC': 1, 'TEXT': 2, 'POINT': 1, 'SOLID': 1,
                                       'DIMENSION': 1, 'BLOCK': 1})
        texts = [r['content'] for r in document._source_records['entities'] if r['type'] == 'TEXT']
        self.assertIn(IMAGE_TEXT, texts)
        target = self.folder / 'synthetic_copy.jww'
        document.save(target)
        self.assertEqual(target.read_bytes(), data)
        with self.assertRaises(ValueError):
            document.add_line((0, 0), (1, 1))

    def test_same_drawing_with_schema_600_stays_editable(self):
        document = CadDocument.open(self.write('plain600.jww', synthetic(600, 600)))
        self.assertEqual(document._source_records['class_schema'], 600)
        document.add_line((0, 0), (1, 1))
        document.save(self.folder / 'plain600_edited.jww')

    def test_unaccepted_pairs_are_rejected(self):
        cases = {
            'schema0': (synthetic(600, 0), 'schema_profile="rebro_schema0"'),
            'schema351': (synthetic(600, 351), 'Unsupported class schema: 351'),
            'schema420': (synthetic(600, 420), 'Unsupported class schema: 420'),
            'v700_schema600': (synthetic(700, 600), 'Unsupported class schema: 600'),
            'mixed': (synthetic(600, [700, 600, 700, 700, 700, 700, 700, 700]), 'Unsupported class schema mix'),
            'mixed_first600': (synthetic(600, [600, 700, 700, 700, 700, 700, 700, 700]), 'Unsupported class schema mix'),
            'trailing_image_count': (synthetic(600, 700, trailer=bytes(4)), 'Unsupported trailer/layout'),
        }
        for name, (data, message) in cases.items():
            with self.subTest(case=name):
                path = self.write(f'{name}.jww', data)
                with self.assertRaises(RecordError) as caught:
                    CadDocument.open(path)
                self.assertIn(message, str(caught.exception))
                with self.assertRaises(RecordError):
                    read_records_bytes(data)

    def test_read_document_rejects_mixed_schemas(self):
        for schemas in ([700, 600, 700, 700, 700, 700, 700, 700], [600, 700, 700, 700, 700, 700, 700, 700]):
            path = self.write(f'mixed_{schemas[0]}.jww', synthetic(600, schemas))
            with self.assertRaises(RecordError) as caught:
                read_document(path)
            self.assertIn('Unsupported class schema mix', str(caught.exception))

    def test_legacy_document_rejects_schema_700(self):
        plain = self.write('legacy600.jww', synthetic(600, 600, basic=True))
        LegacyDocument.open(plain)
        path = self.write('legacy700.jww', synthetic(600, 700, basic=True))
        with self.assertRaises(ValueError) as caught:
            LegacyDocument.open(path)
        self.assertIn('read-only', str(caught.exception))

    def test_rebro_profile_does_not_accept_schema_700(self):
        path = self.write('rebro.jww', synthetic(600, 700))
        with self.assertRaises(RecordError) as caught:
            CadDocument.open(path, schema_profile='rebro_schema0')
        self.assertIn('Unsupported class schema: 700', str(caught.exception))

    def test_jws_reader_is_not_widened(self):
        body = serialize_body([Line((0, 0), (1, 1)).record()], [], 600, encoding='cp932')
        offset = body.index(b'CDataSen') - 4
        self.assertEqual(struct.unpack_from('<H', body, offset)[0], 600)
        patched = bytearray(body)
        struct.pack_into('<H', patched, offset, 700)
        with self.assertRaises(RecordError):
            read_entity_sequences(Cursor(bytes(patched)), 600)
        header = (b'JwsData.' + b'.' * 192 + struct.pack('<I', 600) + struct.pack('<dd', 0, 0)
                  + struct.pack('<16d', *([1.0] * 16)) + bytes(72) + struct.pack('<4d', 0, 0, 1, 1))
        read_entity_sequences(Cursor(body), 600)  # the unpatched body is valid
        JwsDocument.from_bytes(header + body)
        with self.assertRaises(RecordError) as caught:
            JwsDocument.from_bytes(header + bytes(patched))
        self.assertIn('Unsupported class schema: 700', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
