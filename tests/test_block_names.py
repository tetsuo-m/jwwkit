import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from model.block_names import block_name_info, MARKER
from model.common_entities import CadBlockDefinition


class BlockNameTests(unittest.TestCase):
    def test_observed_kinds_have_display_name_without_rewriting_raw(self):
        for kind in range(1,5):
            raw='FLAG081'+MARKER+str(kind)
            info=block_name_info(raw)
            self.assertEqual((info.raw_name,info.display_name,info.compound_kind,info.marker_status),
                             (raw,'FLAG081',kind,'recognized'))

    def test_unmarked_name_is_unchanged(self):
        info=block_name_info('名前')
        self.assertEqual((info.display_name,info.compound_kind,info.marker_status),('名前',None,'absent'))

    def test_unknown_suffixes_are_not_stripped(self):
        for suffix in ('','0','5','-1','01','4 ','４','4extra','4'+MARKER+'1'):
            raw='名前'+MARKER+suffix
            info=block_name_info(raw)
            self.assertEqual((info.display_name,info.compound_kind,info.marker_status),(raw,None,'unrecognized'))

    def test_model_reading_does_not_modify_stored_name(self):
        raw='FLAG081'+MARKER+'4'
        definition=CadBlockDefinition(0,raw,{},())
        self.assertEqual(definition.name_info.compound_kind,4)
        self.assertEqual(definition.name,raw)

    def test_non_string_rejected(self):
        for value in (None,4,b'FLAG081'):
            with self.assertRaises(TypeError):block_name_info(value)
