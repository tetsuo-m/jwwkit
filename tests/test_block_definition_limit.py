"""ブロック定義が 10,000 個を超える図面の拒否（Issue #6）。合成の図面だけを使う。

ezjww 0.2.13 は定義が 10,000 個を超えると block_defs を空で返す（診断なし）。
jwwkit は照合を弱めずに拒否し、理由だけを専用の文言で示す。
ezjww の版を上げてこの制限が変わったら、test_ezjww_limit_is_unchanged が落ちる。
"""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jwwkit import CadDocument, JwwDocument
from jwwkit._ezjww_adapter import read_native_document
from jwwkit.line_document import Line
from jwwkit.reader import archive
from jwwkit.reader.archive import EZJWW_BLOCK_DEFINITION_LIMIT, RecordError

LIMIT_MESSAGE = 'Block definitions exceed the ezjww limit'
GENERIC_MESSAGE = 'Native/raw record count mismatch'


def build(path: Path, count: int) -> Path:
    doc = JwwDocument()
    for number in range(count):
        doc.add_block_definition(f'B{number}', [Line((0, 0), (1, 0))], number=number)
    doc.save(path)
    return path


class BlockDefinitionLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(tempfile.mkdtemp(prefix='jwwkit-block-limit-'))
        cls.at_limit = build(cls.folder / 'at_limit.jww', EZJWW_BLOCK_DEFINITION_LIMIT)
        cls.over_limit = build(cls.folder / 'over_limit.jww', EZJWW_BLOCK_DEFINITION_LIMIT + 1)
        cls.small = build(cls.folder / 'small.jww', 3)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_limit_value(self):
        self.assertEqual(EZJWW_BLOCK_DEFINITION_LIMIT, 10000)

    def test_ezjww_limit_is_unchanged(self):
        # ezjww の版を上げて制限が変わったら、ここが落ちる。そのときは制限と文言を見直す。
        self.assertEqual(len(read_native_document(self.at_limit)['block_defs']), 10000)
        self.assertEqual(len(read_native_document(self.over_limit)['block_defs']), 0)

    def test_at_limit_reads_and_saves_byte_identical(self):
        document = CadDocument.open(self.at_limit)
        self.assertEqual(len(document.block_definitions), 10000)
        target = self.folder / 'at_limit_saved.jww'
        document.save(target)
        self.assertEqual(target.read_bytes(), self.at_limit.read_bytes())

    def test_over_limit_is_rejected_with_specific_reason(self):
        before = self.over_limit.read_bytes()
        with self.assertRaises(RecordError) as caught:
            CadDocument.open(self.over_limit)
        message = str(caught.exception)
        self.assertIn(LIMIT_MESSAGE, message)
        self.assertIn('jwwkit read 10001 definitions', message)
        self.assertIn('above 10000', message)
        self.assertNotIn(GENERIC_MESSAGE, message)
        self.assertEqual(self.over_limit.read_bytes(), before)

    def test_other_count_mismatch_keeps_generic_reason(self):
        def drop_one(path):
            native = read_native_document(path)
            native['block_defs'] = native['block_defs'][:-1]
            return native

        with patch.object(archive, 'read_native_document', drop_one):
            with self.assertRaises(RecordError) as caught:
                archive.read_document(self.small)
        self.assertIn(GENERIC_MESSAGE, str(caught.exception))
        self.assertNotIn(LIMIT_MESSAGE, str(caught.exception))

    def test_no_native_definitions_within_limit_keeps_generic_reason(self):
        # ezjww の定義が0個でも、jwwkit 側が上限以下なら専用の文言にしない（確認役の指摘で追加）。
        def empty(path):
            native = read_native_document(path)
            native['block_defs'] = []
            return native

        with patch.object(archive, 'read_native_document', empty):
            with self.assertRaises(RecordError) as caught:
                archive.read_document(self.small)
        self.assertIn(GENERIC_MESSAGE, str(caught.exception))
        self.assertNotIn(LIMIT_MESSAGE, str(caught.exception))

    def test_top_level_check_runs_before_limit_check(self):
        # 図面直下の要素の照合が先に行われ、そこで止まれば専用の文言は出ない（確認役の指摘で追加）。
        def drop_entity(path):
            native = read_native_document(path)
            native['entities'] = native['entities'][:-1]
            return native

        self.assertTrue(read_native_document(self.over_limit)['entities'])
        with patch.object(archive, 'read_native_document', drop_entity):
            with self.assertRaises(RecordError) as caught:
                archive.read_document(self.over_limit)
        self.assertIn(GENERIC_MESSAGE, str(caught.exception))
        self.assertNotIn(LIMIT_MESSAGE, str(caught.exception))

    def test_over_limit_with_partial_native_definitions_keeps_generic_reason(self):
        # ezjww が定義を1つでも返したら、専用の文言にはしない（照合は今のまま）。
        one = read_native_document(self.small)['block_defs'][:1]

        def partial(path):
            native = read_native_document(path)
            native['block_defs'] = list(one)
            return native

        with patch.object(archive, 'read_native_document', partial):
            with self.assertRaises(RecordError) as caught:
                archive.read_document(self.over_limit)
        self.assertIn(GENERIC_MESSAGE, str(caught.exception))
        self.assertNotIn(LIMIT_MESSAGE, str(caught.exception))


if __name__ == '__main__':
    unittest.main()
