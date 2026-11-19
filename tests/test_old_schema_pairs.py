"""Issue #41: old file versions with class schemas 0/1/230/310/65535 (observed in real drawings, #40).

Read-only, like the other old versions (#17). The body is read by the file version only. Only the
observed values are accepted; other values, mixes, point styles 2/5, (420, 230) extended counts, the
(420, 230) long class-reference form that jwwkit cannot write back, and invalid CP932 text stay rejected.
"""
import struct
import unittest

from jwwkit import CadDocument
from jwwkit.line_document import Line
from jwwkit.normalization import inspect_schema_normalization
from jwwkit.reader.archive import RecordError, read_records, read_records_bytes
from jwwkit.writer.preserved import capture_source, serialize_body

from test_old_versions import PUBLIC_TYPES, patch_schemas
from test_v600_schema700 import EDIT_OPERATIONS, TempDirTestCase, fixture

ADDED = ((420, 0), (420, 1), (420, 230), (420, 310), (300, 1), (351, 1), (230, 65535))
NOT_ADDED = ((420, 420), (420, 2), (420, 699), (300, 0), (300, 230), (351, 0), (351, 230),
             (230, 0), (230, 1), (420, 65535))


def lines(n):
    return [Line((i, 0), (i, 1)).record() for i in range(n)]


class AddedPairsTests(TempDirTestCase):
    def test_added_pairs_open_save_and_stay_read_only(self):
        for version, schema in ADDED:
            with self.subTest(version=version, schema=schema):
                path = self.write(f'v{version}_{schema}.jww', patch_schemas(fixture(version).read_bytes(), schema))
                document = CadDocument.open(path)
                self.assertEqual(document.version, version)
                self.assertEqual(document._source_records['class_schema'], schema)
                self.assertEqual({d['schema'] for d in document._source_records['class_declarations']}, {schema})
                self.assertEqual(document.entity_counts, PUBLIC_TYPES)
                target = self.folder / f'v{version}_{schema}_copy.jww'
                document.save(target)
                self.assertEqual(target.read_bytes(), path.read_bytes())
                for name, operation in EDIT_OPERATIONS.items():
                    with self.assertRaises(ValueError):
                        operation(CadDocument.open(path))
                converted = CadDocument.open(path)
                converted.version = 700
                with self.assertRaises(ValueError) as caught:
                    converted.save(self.folder / f'v{version}_{schema}_700.jww')
                self.assertIn('read-only', str(caught.exception))

    def test_added_pairs_read_the_same_records_as_the_fixture(self):
        # The body is read by the file version: only the declaration schema words differ.
        for version, schema in ADDED:
            with self.subTest(version=version, schema=schema):
                original = read_records(fixture(version))
                patched = read_records_bytes(patch_schemas(fixture(version).read_bytes(), schema))
                self.assertEqual(patched['entities'], original['entities'])
                self.assertEqual(patched['block_defs'], original['block_defs'])

    def test_normalization_inspection_says_not_needed(self):
        for version, schema in ADDED:
            with self.subTest(version=version, schema=schema):
                path = self.write(f'n{version}_{schema}.jww', patch_schemas(fixture(version).read_bytes(), schema))
                info = inspect_schema_normalization(path)
                self.assertEqual((info['status'], info['reason']), ('not_needed', 'already_standard'))


class StillRejectedTests(TempDirTestCase):
    def test_values_not_added_are_rejected(self):
        for version, schema in NOT_ADDED:
            with self.subTest(version=version, schema=schema):
                with self.assertRaises(RecordError) as caught:
                    read_records_bytes(patch_schemas(fixture(version).read_bytes(), schema))
                self.assertIn('Unsupported class schema', str(caught.exception))

    def test_mixes_with_the_file_version_or_700_are_rejected(self):
        for version, schema in ADDED:
            for other in (version, 700):
                if other == schema:
                    continue
                with self.subTest(version=version, schema=schema, other=other):
                    data = patch_schemas(patch_schemas(fixture(version).read_bytes(), schema), other, index=0)
                    with self.assertRaises(RecordError) as caught:
                        read_records_bytes(data)
                    self.assertIn('Unsupported class schema', str(caught.exception))

    def test_point_styles_2_and_5_are_rejected(self):
        for version in (300, 351):
            data = patch_schemas(fixture(version).read_bytes(), 1)
            point = next(s for s in read_records_bytes(data)['spans'] if s['class_name'] == 'CDataTen')
            for style in (2, 5):
                with self.subTest(version=version, style=style):
                    changed = bytearray(data)
                    changed[point['base_offset'] + 4] = style
                    with self.assertRaises(RecordError) as caught:
                        read_records_bytes(bytes(changed))
                    self.assertIn('Unsupported point style', str(caught.exception))

    def test_extended_counts_only_for_420_0(self):
        data = fixture(420).read_bytes()
        end = read_records_bytes(data)['header_end']
        records = lines(65535)
        for schema, accepted in ((0, True), (230, False), (1, False), (310, False)):
            with self.subTest(schema=schema):
                body = serialize_body(records, [], 420, encoding='utf-16le', old_extended_counts=True,
                                      class_schema=schema)
                raw = data[:end] + body
                self.assertEqual(struct.unpack_from('<HI', raw, end), (65535, 65535))
                path = self.write(f'extended{schema}.jww', raw)
                if accepted:
                    source, parsed = capture_source(path)
                    self.assertEqual((len(parsed['entities']), parsed['class_schema']), (65535, 0))
                    document = CadDocument.open(path)
                    target = self.folder / 'extended0_copy.jww'
                    document.save(target)
                    self.assertEqual(target.read_bytes(), raw)
                else:
                    with self.assertRaises(RecordError) as caught:
                        read_records_bytes(raw)
                    self.assertIn(f'Extended sequence count unobserved for (420, {schema})', str(caught.exception))

    def test_420_230_long_class_references_cannot_be_written_back(self):
        # Real (420, 230) drawings write every reference from the 32767th element on in the
        # 0x7fff + DWORD form; jwwkit writes that form only for class indexes of 32767 or more.
        data = fixture(420).read_bytes()
        end = read_records_bytes(data)['header_end']
        count = 40000
        body = serialize_body(lines(count), [], 420, encoding='utf-16le', class_schema=230)
        raw = data[:end] + body
        spans = read_records_bytes(raw)['spans']
        out = bytearray(raw[:spans[32767]['base_offset'] - 2])
        for k in range(32767, count):
            start = spans[k]['base_offset']
            self.assertEqual(raw[start - 2:start], struct.pack('<H', 0x8001))
            stop = spans[k + 1]['base_offset'] - 2 if k + 1 < count else len(raw)
            out += struct.pack('<HI', 0x7fff, 0x80000001) + raw[start:stop]
        long_form = bytes(out)
        parsed = read_records_bytes(long_form)
        self.assertEqual((len(parsed['entities']), parsed['class_schema']), (count, 230))
        path = self.write('long_form.jww', long_form)
        with self.assertRaises(RecordError) as caught:
            CadDocument.open(path)
        self.assertIn('本文を損失なく再直列化できません', str(caught.exception))
        # The same drawing with the short form (what jwwkit writes) opens.
        self.assertEqual(CadDocument.open(self.write('short_form.jww', raw)).entity_counts, {'LINE': count})

    def test_invalid_cp932_text_is_rejected(self):
        data = fixture(300).read_bytes()
        parsed = read_records(fixture(300))
        text = dict(next(r for r in parsed['entities'] if r['type'] == 'TEXT'), content='ZQZQ')
        body = serialize_body([text], [], 300, encoding='cp932', class_schema=1)
        self.assertIn(b'ZQZQ', body)
        raw = data[:parsed['header_end']] + body.replace(b'ZQZQ', b'\x81\x20ZQ', 1)
        with self.assertRaises(RecordError) as caught:
            read_records_bytes(raw)
        self.assertIn("codec can't decode", str(caught.exception))
        # Valid CP932 text in the same drawing is read.
        self.assertEqual(read_records_bytes(data[:parsed['header_end']] + body)['entities'][0]['content'], 'ZQZQ')


if __name__ == '__main__':
    unittest.main()
