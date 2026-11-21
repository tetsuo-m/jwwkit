"""v700 の「要素の個数を普通と違う書き方」（Issue #43・#46）。合成の図面だけを使う。

65535 の印の後に 65535 より小さい値を DWORD で書く形。受け付けるのは、ファイルの版 700・クラスの版 700 の図面で、
図面直下の要素の並び、ブロック定義の並び、ブロック定義の中の並び（定義どうしで同じ書き方）だけ。
- 無編集の保存は、元とバイト単位で一致する（並びごとの書き方を覚えて書き戻す）。
- 編集した後の保存は、元の書き方に合わせる（案 A）。新しい定義の中の並びは、元の定義の中の並びと同じ書き方。
- 普通の書き方の図面は、読取りの結果も保存も変わらない。
- v600・古い版・DWORD の 0xffffffff・定義の中で書き方が混ざる図面は、拒否のまま。
"""
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from jwwkit import CadDocument, JwwDocument
from jwwkit.line_document import Line
from jwwkit.reader.archive import Cursor, RecordError, read_records_bytes
from jwwkit.writer.preserved import capture_source, serialize_body

ALL = dict(entities=True, block_defs=True, definition_entities=True)
NONCANONICAL = 'accepted only in v700 drawings whose classes use schema 700'


def canonical_drawing(path: Path) -> Path:
    document = JwwDocument()
    for index in range(3):
        document.add_line((index, 0), (index, 5))
    document.add_text((0, 10), None, 'synthetic')
    for number in range(3):
        document.add_block_definition(f'B{number}', [Line((0, 0), (1, number + 1)), Line((1, 0), (0, 1))],
                                      number=number)
    document.save(path)
    return path


def with_forms(source: Path, forms, target: Path) -> Path:
    """The same drawing, its lists written with the given count forms (header and records unchanged)."""
    raw, parsed = capture_source(source)
    body = serialize_body(parsed['entities'], parsed['block_defs'], 700, encoding=parsed['body_encoding'],
                          raw_trailer=parsed['raw_trailer'], count_forms=forms)
    target.write_bytes(raw[:parsed['header_end']] + body)
    return target


def definition_count_offset(data: bytes, span) -> int:
    """Offset of the count of the list inside a definition (after its base, number/flag/time and name)."""
    c = Cursor(data)
    c.pos = span['base_offset'] + 15 + 12
    c.string()
    return c.pos


class NoncanonicalCountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The real folder: normalization refuses paths under links (macOS /var -> /private/var).
        cls.folder = Path(tempfile.mkdtemp(prefix='jwwkit-noncanonical-')).resolve()
        cls.canonical = canonical_drawing(cls.folder / 'canonical.jww')
        cls.dword = with_forms(cls.canonical, ALL, cls.folder / 'dword.jww')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def write(self, name, data):
        path = self.folder / name
        path.write_bytes(data)
        return path

    def test_synthetic_drawing_uses_the_form_in_every_list(self):
        data = self.dword.read_bytes()
        parsed = read_records_bytes(data)
        self.assertEqual((parsed['version'], parsed['class_schema']), (700, 700))
        # Independent check of the bytes: marker + DWORD for the top-level list and inside every definition.
        self.assertEqual(struct.unpack_from('<HI', data, parsed['header_end']), (65535, len(parsed['entities'])))
        definitions = [s for s in parsed['spans'] if s['class_name'] == 'CDataList']
        self.assertEqual(len(definitions), 3)
        for span in definitions:
            self.assertEqual(struct.unpack_from('<HI', data, definition_count_offset(data, span)), (65535, 2))
        self.assertEqual(len(data), len(self.canonical.read_bytes()) + 4 * (2 + 3))

    def test_opens_cross_checks_and_saves_unedited_byte_identical(self):
        document = CadDocument.open(self.dword)
        self.assertEqual(len(document.block_definitions), 3)
        self.assertEqual(document._source_records['count_forms'], ALL)
        target = self.folder / 'dword_saved.jww'
        document.save(target)
        self.assertEqual(target.read_bytes(), self.dword.read_bytes())
        self.assertEqual(CadDocument.open(self.canonical).entities, document.entities)

    def test_plain_drawings_are_unchanged(self):
        parsed = read_records_bytes(self.canonical.read_bytes())
        self.assertNotIn('count_forms', parsed)
        document = CadDocument.open(self.canonical)
        target = self.folder / 'canonical_saved.jww'
        document.save(target)
        self.assertEqual(target.read_bytes(), self.canonical.read_bytes())
        document.add_line((0, 0), (9, 9))
        edited = self.folder / 'canonical_edited.jww'
        document.save(edited)
        data = edited.read_bytes()
        parsed = read_records_bytes(data)
        self.assertEqual(struct.unpack_from('<H', data, parsed['header_end'])[0], len(parsed['entities']))
        self.assertEqual(len(parsed['entities']), len(read_records_bytes(self.canonical.read_bytes())['entities']) + 1)

    def test_edited_save_keeps_the_form_and_new_definitions_follow_it(self):
        document = CadDocument.open(self.dword)
        document.add_line((0, 0), (9, 9))
        document.add_block_definition('NEW', [Line((0, 0), (2, 2))])
        target = self.folder / 'dword_edited.jww'
        document.save(target)
        data = target.read_bytes()
        parsed = read_records_bytes(data)
        # All definitions, the new one included, use the form; otherwise the read stops with the mix message.
        self.assertEqual(parsed['count_forms'], ALL)
        self.assertEqual(struct.unpack_from('<HI', data, parsed['header_end']), (65535, len(parsed['entities'])))
        new = [s for s in parsed['spans'] if s['class_name'] == 'CDataList'][-1]
        self.assertEqual(struct.unpack_from('<HI', data, definition_count_offset(data, new)), (65535, 1))
        self.assertEqual(len(CadDocument.open(target).block_definitions), 4)

    def test_each_list_keeps_its_own_form(self):
        # Observed in one real drawing: the top-level list plain, the definition lists in the DWORD form.
        forms = dict(entities=False, block_defs=True, definition_entities=True)
        source = with_forms(self.canonical, forms, self.folder / 'partly.jww')
        document = CadDocument.open(source)
        self.assertEqual(document._source_records['count_forms'], forms)
        same = self.folder / 'partly_saved.jww'
        document.save(same)
        self.assertEqual(same.read_bytes(), source.read_bytes())
        document.add_line((0, 0), (9, 9))
        edited = self.folder / 'partly_edited.jww'
        document.save(edited)
        data = edited.read_bytes()
        parsed = read_records_bytes(data)
        self.assertEqual(parsed['count_forms'], forms)
        self.assertEqual(struct.unpack_from('<H', data, parsed['header_end'])[0], len(parsed['entities']))

    def test_no_definitions_then_new_definitions_are_written_plainly(self):
        document = JwwDocument()
        document.add_line((0, 0), (1, 1))
        plain = self.folder / 'nodefs.jww'
        document.save(plain)
        forms = dict(entities=True, block_defs=True, definition_entities=None)
        source = with_forms(plain, forms, self.folder / 'nodefs_dword.jww')
        opened = CadDocument.open(source)
        self.assertEqual(opened._source_records['count_forms'], forms)
        opened.add_block_definition('NEW', [Line((0, 0), (2, 2))])
        target = self.folder / 'nodefs_edited.jww'
        opened.save(target)
        data = target.read_bytes()
        parsed = read_records_bytes(data)
        self.assertEqual(parsed['count_forms'], dict(entities=True, block_defs=True, definition_entities=False))
        new = [s for s in parsed['spans'] if s['class_name'] == 'CDataList'][0]
        self.assertEqual(struct.unpack_from('<H', data, definition_count_offset(data, new))[0], 1)

    def test_mixed_forms_inside_definitions_are_rejected(self):
        data = bytearray(self.dword.read_bytes())
        span = [s for s in read_records_bytes(bytes(data))['spans'] if s['class_name'] == 'CDataList'][0]
        offset = definition_count_offset(bytes(data), span)
        self.assertEqual(struct.unpack_from('<HI', data, offset), (65535, 2))
        data[offset:offset + 6] = struct.pack('<H', 2)
        with self.assertRaises(RecordError) as caught:
            read_records_bytes(bytes(data))
        self.assertIn('Unobserved mix of noncanonical and plain sequence count forms', str(caught.exception))
        with self.assertRaises(RecordError):
            CadDocument.open(self.write('mixed.jww', bytes(data)))

    def test_all_ones_dword_is_still_rejected(self):
        data = bytearray(self.canonical.read_bytes())
        end = read_records_bytes(bytes(data))['header_end']
        data[end:end + 2] = struct.pack('<HI', 65535, 0xffffffff)
        with self.assertRaises(RecordError) as caught:
            read_records_bytes(bytes(data))
        self.assertIn(NONCANONICAL, str(caught.exception))

    def test_unobserved_class_schemas_stop_before_the_form(self):
        # v700 whose classes use schema 600 (an unobserved pair): the declarations are refused first.
        data = bytearray(self.dword.read_bytes())
        for declaration in read_records_bytes(bytes(data))['class_declarations']:
            struct.pack_into('<H', data, declaration['offset'] + 2, 600)
        with self.assertRaises(RecordError) as caught:
            read_records_bytes(bytes(data))
        self.assertIn('Unsupported class schema', str(caught.exception))

    def test_rebro_schema0_with_the_form_is_rejected(self):
        # A v700 drawing that rebro_schema0 reads (schema 0 lines and texts, no definitions), with the form.
        document = JwwDocument()
        document.add_line((0, 0), (1, 1))
        plain = self.folder / 'schema0_plain.jww'
        document.save(plain)
        data = bytearray(with_forms(plain, dict(entities=True, block_defs=True, definition_entities=None),
                                    self.folder / 'schema0_dword_700.jww').read_bytes())
        for declaration in read_records_bytes(bytes(data))['class_declarations']:
            struct.pack_into('<H', data, declaration['offset'] + 2, 0)
        plain_zero = bytearray(plain.read_bytes())
        for declaration in read_records_bytes(bytes(plain_zero))['class_declarations']:
            struct.pack_into('<H', plain_zero, declaration['offset'] + 2, 0)
        # The same drawing with plain counts is read by the profile, so only the form is refused.
        read_records_bytes(bytes(plain_zero), schema_profile='rebro_schema0')
        with self.assertRaises(RecordError) as caught:
            read_records_bytes(bytes(data), schema_profile='rebro_schema0')
        self.assertIn(NONCANONICAL, str(caught.exception))

    def test_old_versions_and_v600_with_the_form_are_rejected(self):
        fixtures = Path(__file__).resolve().parent / 'fixtures' / 'jwcad_saved'
        for version in (230, 420, 600):
            with self.subTest(version=version):
                data = (fixtures / f'jwcad10036_save_v{version}.jww').read_bytes()
                parsed = read_records_bytes(data)
                end = parsed['header_end']
                count, = struct.unpack_from('<H', data, end)
                self.assertEqual(count, len(parsed['entities']))
                with self.assertRaises(RecordError) as caught:
                    read_records_bytes(data[:end] + struct.pack('<HI', 65535, count) + data[end + 2:])
                self.assertIn(NONCANONICAL, str(caught.exception))
        # The writer keeps the form only for v700.
        raw, parsed = capture_source(self.canonical)
        with self.assertRaises(ValueError):
            serialize_body(parsed['entities'], parsed['block_defs'], 600, encoding='cp932', count_forms=ALL)

    def test_drawing_without_class_declarations_is_not_taken_as_schema_700(self):
        data = self.canonical.read_bytes()
        parsed = read_records_bytes(data)
        empty = data[:parsed['header_end']] + struct.pack('<HIHI', 65535, 0, 65535, 0) + parsed['raw_trailer']
        read_records_bytes(data[:parsed['header_end']] + struct.pack('<HH', 0, 0) + parsed['raw_trailer'])
        with self.assertRaises(RecordError) as caught:
            read_records_bytes(empty)
        self.assertIn(NONCANONICAL, str(caught.exception))

    def test_normalization_inspection_sees_an_accepted_drawing_as_standard(self):
        from jwwkit.normalization import inspect_schema_normalization
        self.assertEqual(inspect_schema_normalization(self.dword)['status'],
                         inspect_schema_normalization(self.canonical)['status'])

    def test_save_stops_when_the_forms_would_not_be_kept(self):
        from unittest import mock
        from jwwkit.writer import preserved
        document = CadDocument.open(self.dword)
        document.add_line((0, 0), (9, 9))
        target = self.folder / 'forms_check.jww'
        with mock.patch.object(preserved, 'expected_count_forms', return_value=None):
            with self.assertRaises(ValueError) as caught:
                document.save(target)
        self.assertIn('個数の書き方', str(caught.exception))
        self.assertFalse(target.exists())

    def test_emptied_drawing_is_written_plainly(self):
        # Without any element there is no class declaration to show the schema, so the counts are written plainly.
        raw, parsed = capture_source(self.canonical)
        header = raw[:parsed['header_end']]
        body = serialize_body([Line((0, 0), (1, 1)).record()], [], 700, encoding=parsed['body_encoding'],
                              raw_trailer=parsed['raw_trailer'], count_forms=dict(ALL, definition_entities=None))
        source = self.write('one_line_dword.jww', header + body)
        document = CadDocument.open(source)
        self.assertEqual(document._source_records['count_forms']['entities'], True)
        document.delete_entities(list(range(len(document.entities))))
        target = self.folder / 'emptied.jww'
        document.save(target)
        data = target.read_bytes()
        parsed_saved = read_records_bytes(data)
        self.assertNotIn('count_forms', parsed_saved)
        self.assertEqual(data[parsed_saved['header_end']:parsed_saved['header_end'] + 4], struct.pack('<HH', 0, 0))

    def test_lists_of_65535_or_more_tell_nothing_about_the_form(self):
        # Top level: 65534 lines in the DWORD form; one definition holds 65535 lines (marker + DWORD in either
        # form) and the other two lines in the DWORD form.
        raw, parsed = capture_source(self.canonical)
        header = raw[:parsed['header_end']]
        line = Line((0, 0), (1, 1)).record()
        big = dict(type='BLOCK_DEF', base=dict(line['base']), number=1, is_referenced=False, timestamp=0,
                   name='BIG', entities=[dict(line, base=dict(line['base'])) for _ in range(65535)])
        small = dict(big, number=2, name='SMALL', entities=[dict(line, base=dict(line['base'])) for _ in range(2)])
        top = [dict(line, base=dict(line['base'])) for _ in range(65534)]
        body = serialize_body(top, [big, small], 700, encoding=parsed['body_encoding'],
                              raw_trailer=parsed['raw_trailer'], count_forms=ALL)
        source = self.write('large_dword.jww', header + body)
        document = CadDocument.open(source)
        self.assertEqual(document._source_records['count_forms'], ALL)
        same = self.folder / 'large_dword_saved.jww'
        document.save(same)
        self.assertEqual(same.read_bytes(), source.read_bytes())
        # One more top-level element makes 65535: the saved list cannot show the form, and the save goes on.
        document.add_line((0, 0), (9, 9))
        edited = self.folder / 'large_dword_edited.jww'
        document.save(edited)
        saved = read_records_bytes(edited.read_bytes())
        self.assertEqual(len(saved['entities']), 65535)
        self.assertEqual(saved['count_forms'], dict(ALL, entities=False))

    def test_check_folder_names_the_mix_as_the_count_form(self):
        from jwwkit._commands.check_folder import reason_of
        self.assertEqual(reason_of('Unobserved mix of noncanonical and plain sequence count forms inside block '
                                   'definitions (…)'), '要素の個数が普通と違う書き方')


if __name__ == '__main__':
    unittest.main()
