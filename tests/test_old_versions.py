"""Issue #17: read-only support for old JWW file versions (v230/v300/v351/v420).

Accepted (file version, class schema) pairs: (230,230) (300,300) (351,351) from real
drawings (#8), and (230,700) (300,700) (351,700) (420,700) from Jw_cad 10.03.6 saving in
the old formats ((420,700) from one sample only). Old versions are read-only: unedited
save-as is byte-identical, editing and version conversion are rejected.
"""
import copy
from dataclasses import replace
import struct
import unittest
from pathlib import Path
from unittest.mock import patch

from jwwkit import CadDocument, template_path
from jwwkit.drawing_comparison import compare_drawings
from jwwkit.line_document import Line
from jwwkit.jwf import JwfDocument
from jwwkit.read_view import create_read_view
from jwwkit.reader.jws import JwsDocument
from jwwkit.reader.archive import (Cursor, RecordError, header_layout, read_document, read_records,
                                   read_records_bytes)
from jwwkit.reader.sxf import read_sxf_tables
from jwwkit.reader.text_presets import read_text_presets
from jwwkit.spatial_search import at_point
from jwwkit.writer.preserved import capture_source, serialize_body
from jwwkit._commands.check_installation import old_version_header

from test_v600_schema700 import EDIT_OPERATIONS, FIXTURES, TempDirTestCase, fixture, synthetic

OLD = (230, 300, 351, 420)
# Public element counts of the fixtures (the 6 metadata settings texts are excluded).
PUBLIC_TYPES = {'LINE': 14, 'ARC': 2, 'POINT': 9, 'TEXT': 3, 'BLOCK': 1, 'CIRCLE_SOLID': 1, 'DIMENSION': 3}


def legacy_v600_v700_header(data):
    """The fixed-length header reading used before #17 (v600/v700 only)."""
    c = Cursor(data)
    c.take(12)
    memo = c.string(preserve_header_bytes=True)
    c.take(2532)
    layer_names = [c.string(preserve_header_bytes=True) for _ in range(272)]
    c.take(1140 + 257 * 8)
    color_names = []
    for _ in range(257):
        color_names.append(c.string(preserve_header_bytes=True))
        c.take(16)
    c.take(33 * 16)
    line_type_names = []
    for _ in range(33):
        line_type_names.append(c.string(preserve_header_bytes=True))
        c.take(84)
    c.take(380)
    return dict(header_end=c.pos, memo=memo, layer_names=layer_names, color_names=color_names,
                line_type_names=line_type_names)


def patch_schemas(data, schema, index=None):
    """Rewrite the declaration schema words (all, or only declaration number index)."""
    out = bytearray(data)
    declarations = read_records_bytes(bytes(data))['class_declarations']
    for i, declaration in enumerate(declarations):
        if index is None or i == index:
            struct.pack_into('<H', out, declaration['offset'] + 2, schema)
    return bytes(out)


class HeaderTableTests(unittest.TestCase):
    def test_table_lengths_match_the_previous_v600_v700_constants(self):
        for version in (600, 700):
            skips = [s[1] for s in header_layout(version) if s[0] == 'skip']
            self.assertEqual(skips[0], 2532)
            self.assertEqual(sum(skips[1:7]), 1140)
            self.assertEqual(skips[7:], [257 * 8, 33 * 16, 380])
            self.assertEqual([s[1:] for s in header_layout(version) if s[0] == 'strings'],
                             [('layer_names', 272, 0), ('color_names', 257, 16), ('line_type_names', 33, 84)])

    def test_v600_v700_reading_is_unchanged(self):
        sources = [fixture(600).read_bytes(), fixture(700).read_bytes(), template_path().read_bytes(),
                   synthetic(600, 700), synthetic(700, 700)]
        for data in sources:
            with self.subTest(version=struct.unpack_from('<I', data, 8)[0]):
                parsed = read_records_bytes(data)
                before = legacy_v600_v700_header(data)
                self.assertEqual({k: parsed[k] for k in before}, before)
                self.assertEqual(read_text_presets(data, parsed['header_end'], parsed['version']),
                                 read_text_presets(data, before['header_end'], parsed['version']))
                colors, styles = read_sxf_tables(data, parsed['header_end'])
                self.assertEqual(([c['name'] for c in colors], [s['name'] for s in styles]),
                                 (before['color_names'], before['line_type_names']))

    def test_headers_rebuilt_by_the_table_match_the_old_fixture_lengths(self):
        source = fixture(700).read_bytes()
        end = read_records_bytes(source)['header_end']
        for version in (*OLD, 600):
            with self.subTest(version=version):
                data = fixture(version).read_bytes()
                parsed = read_records_bytes(data)
                rebuilt = old_version_header(source[:end], version)
                self.assertEqual(len(rebuilt), parsed['header_end'])
                again = Cursor(rebuilt)
                again.take(12)
                self.assertEqual(again.string(preserve_header_bytes=True), parsed['memo'])


class OldFixtureTests(TempDirTestCase):
    def test_old_fixtures_open_with_expected_records(self):
        for version in OLD:
            with self.subTest(version=version):
                document = CadDocument.open(fixture(version))
                parsed = document._source_records
                self.assertEqual((document.version, parsed['class_schema']), (version, 700))
                self.assertEqual({d['schema'] for d in parsed['class_declarations']}, {700})
                self.assertEqual(document.diagnostics, ())
                self.assertEqual(document.entity_counts, PUBLIC_TYPES)
                self.assertEqual(len(document.block_definitions), 1)
                self.assertEqual([e.entity_type for e in document.block_definitions[0].entities], ['LINE'] * 4)
                dimensions = [r for r in parsed['entities'] if r['type'] == 'DIMENSION']
                if version >= 420:
                    self.assertTrue(all(r['sxf_mode'] == 0 and len(r['aux_lines']) == 2 for r in dimensions))
                else:
                    self.assertTrue(all(r['sxf_mode'] is None and r['aux_lines'] == r['aux_points'] == []
                                        for r in dimensions))
                pen_widths = {r['base']['pen_width'] for r in parsed['entities']}
                if version < 351:
                    self.assertEqual(pen_widths, {0})

    def test_unedited_save_is_byte_identical(self):
        for version in OLD:
            for include_metadata in (False, True):
                with self.subTest(version=version, include_metadata=include_metadata):
                    document = CadDocument.open(fixture(version), include_metadata=include_metadata)
                    target = self.folder / f'v{version}_{include_metadata}.jww'
                    document.save(target)
                    self.assertEqual(target.read_bytes(), fixture(version).read_bytes())

    def test_editing_apis_are_rejected_before_changes(self):
        for version in OLD:
            for name, operation in EDIT_OPERATIONS.items():
                with self.subTest(version=version, api=name):
                    document = CadDocument.open(fixture(version))
                    before = (document.entities, document.block_definitions, copy.deepcopy(document.header))
                    with self.assertRaises(ValueError) as caught:
                        operation(document)
                    self.assertIn('Ver.7.00', str(caught.exception))
                    self.assertEqual((document.entities, document.block_definitions, document.header), before)
            with self.subTest(version=version, api='import_group'):
                document = CadDocument.open(fixture(version))
                with self.assertRaises(ValueError) as caught:
                    document.import_group(fixture(700), 0, 1)
                self.assertIn('Ver.7.00', str(caught.exception))

    def test_jws_placement_is_rejected_before_changes(self):
        header = (b'JwsData.' + b'.' * 192 + struct.pack('<I', 600) + struct.pack('<dd', 0, 0)
                  + struct.pack('<16d', *([1.0] * 16)) + bytes(72) + struct.pack('<4d', 0, 0, 1, 1))
        figure = JwsDocument.from_bytes(header + serialize_body([Line((0, 0), (1, 1)).record()], [], 600,
                                                                encoding='cp932'))
        for version in OLD:
            with self.subTest(version=version):
                document = CadDocument.open(fixture(version))
                before = (document.entities, document.block_definitions, dict(document._new_block_records))
                with self.assertRaises(ValueError) as caught:
                    figure.place_as_block(document, 'jws figure', (5, 5))
                self.assertIn('Ver.7.00', str(caught.exception))
                self.assertEqual((document.entities, document.block_definitions, dict(document._new_block_records)),
                                 before)

    def test_jwf_comparison_without_a_v230_palette_gives_a_reason(self):
        jwf = self.write('colors.jwf', b'LCOLLOR_1=0 0 0 1' + bytes([10]))
        rows = JwfDocument.open(jwf).compare_drawing(CadDocument.open(fixture(230)))['rows']
        self.assertEqual([(r['status'], r['reason']) for r in rows],
                         [('unresolved', 'Drawing pen palette is unavailable (ezjww returns none for v230)')])
        rows = JwfDocument.open(jwf).compare_drawing(CadDocument.open(fixture(351)))['rows']
        self.assertNotIn('unresolved', {r['status'] for r in rows if r.get('field') != 3})

    def test_direct_changes_and_version_conversion_are_not_saved(self):
        for version in OLD:
            for change in ('entity', 'header', 'version'):
                with self.subTest(version=version, change=change):
                    document = CadDocument.open(fixture(version))
                    if change == 'entity':
                        index = next(i for i, e in enumerate(document.entities) if e.entity_type == 'LINE')
                        entities = list(document.entities)
                        geometry = dict(entities[index].geometry, start_x=entities[index].geometry['start_x'] + 1)
                        entities[index] = replace(entities[index], geometry=geometry)
                        document.entities = tuple(entities)
                    elif change == 'header':
                        document.header['layer_groups'][5]['scale'] = 7.0
                    else:
                        document.version = 700
                    target = self.folder / f'v{version}_{change}.jww'
                    with self.assertRaises(ValueError) as caught:
                        document.save(target)
                    self.assertIn('read-only', str(caught.exception))
                    self.assertFalse(target.exists())

    def test_text_presets_match_the_v700_fixture(self):
        expected = CadDocument.open(fixture(700))
        for version in OLD:
            with self.subTest(version=version):
                document = CadDocument.open(fixture(version))
                self.assertEqual([document.get_text_preset(i) for i in range(1, 11)],
                                 [expected.get_text_preset(i) for i in range(1, 11)])

    def test_sxf_tables(self):
        self.assertEqual(CadDocument.open(fixture(351)).get_sxf_colors(include_unnamed=True), [])
        self.assertEqual(CadDocument.open(fixture(420)).get_sxf_colors(include_unnamed=True),
                         CadDocument.open(fixture(700)).get_sxf_colors(include_unnamed=True))

    def test_summary_search_and_range_search(self):
        expected = CadDocument.open(fixture(700))
        query = {'field': 'length', 'min': 0, 'max': 1e9, 'units': 'real'}
        text_query = {'all': [{'field': 'entity_type', 'in': ['TEXT', 'DIMENSION']},
                              {'field': 'text_height', 'min': 0, 'max': 1000, 'units': 'paper'}]}
        reference = at_point(create_read_view(expected), (0, 0), tolerance=1e9, units='paper', limit=1000, mode='summary')
        for version in OLD:
            with self.subTest(version=version):
                document = CadDocument.open(fixture(version))
                self.assertEqual(document.summary()['by_type'], expected.summary()['by_type'])
                self.assertEqual(document.find_entities(entity_type='LINE'), expected.find_entities(entity_type='LINE'))
                for q in (query, text_query):
                    result = document.search_entities(q)
                    self.assertTrue(result['complete'])
                    self.assertEqual([h['index'] for h in result['hits']],
                                     [h['index'] for h in expected.search_entities(q)['hits']])
                found = at_point(create_read_view(document), (0, 0), tolerance=1e9, units='paper', limit=1000,
                                 mode='summary')
                self.assertEqual((found['examined_count'], found['unresolved_count']),
                                 (reference['examined_count'], reference['unresolved_count']))

    def test_comparison_with_the_v700_fixture(self):
        result = compare_drawings(fixture(420), fixture(700))
        self.assertTrue(result['complete'])
        self.assertEqual(result['summary']['unchanged'], 33)
        for version in (300, 351):
            with self.subTest(version=version):
                result = compare_drawings(fixture(version), fixture(700))
                self.assertTrue(result['complete'])
                # Dimensions without an SXF part (sxf_mode None) differ from the v700 mode-0 ones.
                self.assertEqual((result['summary']['added'], result['summary']['deleted']), (3, 3))
        # ezjww returns no palette for v230, so pen colors are unresolved (not guessed).
        result = compare_drawings(fixture(230), fixture(700))
        self.assertFalse(result['complete'])
        self.assertIn('Selected color number has no verified definition',
                      {u['reason'] for u in result['unsupported']})


class SyntheticOldVersionTests(TempDirTestCase):
    def test_same_schema_pairs_open_and_save(self):
        for version in (230, 300, 351):
            with self.subTest(version=version):
                path = self.write(f'v{version}_same.jww', patch_schemas(fixture(version).read_bytes(), version))
                document = CadDocument.open(path)
                self.assertEqual(document._source_records['class_schema'], version)
                self.assertEqual(document.entity_counts, PUBLIC_TYPES)
                target = self.folder / f'v{version}_same_copy.jww'
                document.save(target)
                self.assertEqual(target.read_bytes(), path.read_bytes())
                with self.assertRaises(ValueError):
                    document.add_line((0, 0), (1, 0))

    def test_unaccepted_pairs_mixes_and_tails_are_rejected(self):
        # (420, 0/1/230/310), (300, 1), (351, 1), (230, 65535) are accepted since #41 (test_old_schema_pairs).
        cases = [(420, 420), (230, 0)]
        for version, schema in cases:
            with self.subTest(version=version, schema=schema):
                with self.assertRaises(RecordError) as caught:
                    read_records_bytes(patch_schemas(fixture(version).read_bytes(), schema))
                self.assertIn('Unsupported class schema', str(caught.exception))
        for version in (230, 351):
            with self.subTest(version=version, case='mix'):
                with self.assertRaises(RecordError) as caught:
                    read_records_bytes(patch_schemas(fixture(version).read_bytes(), version, index=0))
                self.assertIn('Unsupported class schema mix', str(caught.exception))
            with self.subTest(version=version, case='tail'):
                with self.assertRaises(RecordError) as caught:
                    read_records_bytes(fixture(version).read_bytes() + bytes(4))
                self.assertIn('Unsupported trailer/layout', str(caught.exception))

    def test_unobserved_versions_are_rejected(self):
        for version in (220, 252, 500):
            with self.subTest(version=version):
                data = bytearray(fixture(230).read_bytes())
                struct.pack_into('<I', data, 8, version)
                with self.assertRaises(RecordError) as caught:
                    read_records_bytes(bytes(data))
                self.assertIn('Unsupported JWW version', str(caught.exception))

    def test_point_styles_before_252(self):
        data = fixture(230).read_bytes()
        parsed = read_records(fixture(230))
        point = next(s for s in parsed['spans'] if s['class_name'] == 'CDataTen')
        for style, accepted in ((0, True), (1, True), (2, False), (100, False)):
            with self.subTest(style=style):
                changed = bytearray(data)
                changed[point['base_offset'] + 4] = style
                path = self.write(f'point{style}.jww', bytes(changed))
                if accepted:
                    document = CadDocument.open(path)
                    self.assertIn(style, {r['base']['pen_style'] for r in document._source_records['entities']
                                          if r['type'] == 'POINT'})
                    target = self.folder / f'point{style}_copy.jww'
                    document.save(target)
                    self.assertEqual(target.read_bytes(), bytes(changed))
                else:
                    with self.assertRaises(RecordError) as caught:
                        read_records_bytes(bytes(changed))
                    self.assertIn('Unsupported point style before v252', str(caught.exception))

    def test_extended_counts_only_in_230_700(self):
        data = fixture(230).read_bytes()
        end = read_records_bytes(data)['header_end']
        records = [Line((i, 0), (i, 1)).record() for i in range(65535)]
        for schema, accepted in ((700, True), (230, False)):
            with self.subTest(schema=schema):
                body = serialize_body(records, [], 230, encoding='cp932', old_extended_counts=True,
                                      class_schema=schema if schema != 230 else None)
                raw = data[:end] + body
                self.assertEqual(struct.unpack_from('<HI', raw, end), (65535, 65535))
                path = self.write(f'extended{schema}.jww', raw)
                if accepted:
                    source, parsed = capture_source(path)
                    self.assertEqual((len(parsed['entities']), parsed['class_schema']), (65535, 700))
                else:
                    with self.assertRaises(RecordError) as caught:
                        read_records_bytes(raw)
                    self.assertIn('Extended sequence count unobserved for (230, 230)', str(caught.exception))
        with self.assertRaises(ValueError):
            serialize_body(records, [], 230, encoding='cp932')

    def test_noncanonical_count_message_names_the_accepted_pair(self):
        # #46: the form is accepted only for (700, 700); a v600 drawing with it stays rejected.
        data = synthetic(600, 600)
        end = read_records_bytes(data)['header_end']
        count, = struct.unpack_from('<H', data, end)
        broken = data[:end] + struct.pack('<HI', 65535, count) + data[end + 2:]
        with self.assertRaises(RecordError) as caught:
            read_records_bytes(broken)
        self.assertIn('accepted only in v700 drawings whose classes use schema 700', str(caught.exception))

    def test_ezjww_returning_no_elements_is_rejected_with_reason(self):
        import jwwkit.reader.archive as archive
        real = archive.read_native_document

        def empty(path):
            native = real(path)
            native['entities'] = []
            return native
        with patch.object(archive, 'read_native_document', empty):
            with self.assertRaises(RecordError) as caught:
                read_document(fixture(351))
        self.assertIn('ezjww returned no elements', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
