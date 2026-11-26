"""#63: moving the write group / write layer gives the bytes Jw_cad 10.03.6 saves.

The samples in tests/fixtures/jwcad_write were saved by the owner in Jw_cad 10.03.6 (see its README);
d0.jww is the #62 sample they start from.
"""
import hashlib
import struct
import unittest
from pathlib import Path

from jwwkit import CadDocument
from jwwkit.safe_edit import execute_plan, write_plan
from jwwkit.writer.header import scale_offsets
from test_v600_schema700 import TempDirTestCase

HERE = Path(__file__).resolve().parent / 'fixtures'
FIXTURES = HERE / 'jwcad_write'
D0 = HERE / 'jwcad_dimensions' / 'd0.jww'
V600 = HERE / 'jwcad_saved' / 'jwcad10036_save_v600.jww'
SHA256 = {
    'w1.jww': '4cb2e3e74a1dabd05b4be41f5536b4de639fd6cfccf4272ac1db956eed15367c',
    'w2.jww': '11557104cb62f1eab9a96f291f9e892700ba8cd117ec063b171793dc9d41cda5',
    'w3.jww': '9c9d0bc373f60eac0b778d73f3f283b58a5dd8b1404d700e0dcdfa12d8db0621',
    'w4.jww': 'd6a6d58a455e8ea45bdba1854c91b80eac1c37f92e3b4aceeff9a4681e3b07a6',
    'w5.jww': '463126b8416ee886677bdab35f3b5d5bc221be8c90b9bfc442090a1a1b8ef901',
    'w6.jww': 'ebc78e8be92bc639f3dd58efa15ace24b4f553d5418acce3ddc697b6bf3f0587',
    'w7.jww': 'd0445df4798154a2cdabd30b7b15cfdbc8fa42c02aa5e33a755e9a66e6daf133',
}
# Values Jw_cad changes on every save (as in the #62 tests).
PER_SAVE = {2396, 2397, 2472, 2473, 4680, 4681}


def source(name):
    return D0 if name == 'd0' else FIXTURES / f'{name}.jww'


def differing(a, b):
    assert len(a) == len(b)
    return {i for i in range(len(a)) if a[i] != b[i]}


class JwcadWriteTargetTests(TempDirTestCase):
    def saved(self, document, name='out.jww'):
        path = self.folder / name
        document.save(path)
        return path.read_bytes()

    def test_fixtures_are_the_reviewed_samples(self):
        for name, digest in SHA256.items():
            self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(), digest, name)

    def test_moves_give_the_jwcad_bytes(self):
        # (start, sample, group, layer): W1 layer only, W2 group only, W3 layer in the new group,
        # W5 to a display-only layer, W6 to a hidden layer.
        for start, sample, group, layer in [('d0', 'w1', 0, 2), ('d0', 'w2', 1, 0), ('w2', 'w3', 1, 2),
                                            ('w4', 'w5', 0, 1), ('w4', 'w6', 0, 2)]:
            with self.subTest(sample=sample):
                document = CadDocument.open(source(start))
                document.set_write_target(group, layer)
                data = self.saved(document, f'{sample}.jww')
                jwcad = (FIXTURES / f'{sample}.jww').read_bytes()
                self.assertEqual(differing(data, jwcad) - PER_SAVE, set())
                self.assertEqual(data[:2396], jwcad[:2396])

    def test_display_only_group_becomes_writing_like_w7(self):
        # W7: group 1 display-only and group 2 hidden were set before the switch, in the same Jw_cad session.
        document = CadDocument.open(D0)
        document.set_group_state(1, 'display_only')
        document.set_group_state(2, 'hidden')
        first = self.folder / 'states.jww'
        document.save(first)
        document = CadDocument.open(first)
        document.set_write_target(1, 0)
        data = self.saved(document)
        self.assertEqual(differing(data, (FIXTURES / 'w7.jww').read_bytes()) - PER_SAVE, set())
        reloaded = CadDocument.open(self.folder / 'out.jww')
        self.assertEqual(reloaded.get_group_state(1)['state'], 'writing')
        self.assertEqual(reloaded.get_group_state(0)['state'], 'editable')
        self.assertEqual(reloaded.get_group_state(2)['state'], 'hidden')

    def test_old_write_target_can_then_change_its_state(self):
        document = CadDocument.open(D0)
        with self.assertRaises(ValueError):
            document.set_group_state(0, 'display_only')
        document.set_write_target(1, 2)
        document.set_group_state(0, 'display_only')
        document.set_layer_state(1, 0, 'hidden')
        self.saved(document)
        reloaded = CadDocument.open(self.folder / 'out.jww')
        self.assertEqual(reloaded.header['write_layer_group'], 1)
        self.assertEqual(reloaded.get_group_state(0)['state'], 'display_only')
        self.assertEqual(reloaded.get_layer_state(1, 0)['state'], 'hidden')
        self.assertEqual(reloaded.get_layer_state(1, 2)['state'], 'writing')
        # The settings texts follow the write target; the elements stay where they were.
        self.assertTrue(all((s['base']['layer_group'], s['base']['layer']) == (1, 2)
                            for s in [reloaded._source_records['entities'][i]
                                      for i in reloaded._source_metadata_indices]))
        self.assertEqual(len(reloaded._source_metadata_indices), 6)
        self.assertEqual([e.attributes['layer_group'] for e in reloaded.entities],
                         [e.attributes['layer_group'] for e in CadDocument.open(D0).entities])

    def test_two_moves_are_replayed_in_order(self):
        # d0 -> group 1 layer 2 -> group 2 layer 3: group 1 keeps layer 2 as its write layer (editable now).
        document = CadDocument.open(D0)
        document.set_write_target(1, 2)
        document.set_write_target(2, 3)
        self.saved(document)
        reloaded = CadDocument.open(self.folder / 'out.jww')
        groups = reloaded.header['layer_groups']
        self.assertEqual(reloaded.header['write_layer_group'], 2)
        self.assertEqual([g['state'] for g in groups[:3]], [2, 2, 3])
        self.assertEqual(groups[1]['write_layer'], 2)
        self.assertEqual(groups[1]['layers'][2]['state'], 3)
        self.assertEqual(groups[2]['write_layer'], 3)
        self.assertEqual([l['state'] for l in groups[2]['layers'][:4]], [2, 2, 2, 3])

    def test_same_target_changes_nothing(self):
        document = CadDocument.open(D0)
        document.set_write_target(0, 0)
        self.assertEqual(self.saved(document), D0.read_bytes())

    def patched(self, edit):
        data = bytearray(D0.read_bytes())
        offsets = scale_offsets(bytes(data), CadDocument.open(D0)._source_header['layer_groups'])
        edit(data, [o - 8 for o in offsets])
        return self.write('patched.jww', bytes(data))

    def test_unobserved_layouts_are_refused(self):
        cases = {
            'two writing groups': lambda d, s: struct.pack_into('<I', d, s[1], 3),
            'write layer not writing': lambda d, s: struct.pack_into('<I', d, s[0] + 20, 2),
            'protected target group': lambda d, s: struct.pack_into('<I', d, s[1] + 16, 1),
            'protected target layer': lambda d, s: struct.pack_into('<I', d, s[1] + 20 + 8 * 2 + 4, 1),
        }
        for label, edit in cases.items():
            with self.subTest(label):
                path = self.patched(edit)
                document = CadDocument.open(path)
                with self.assertRaises(ValueError):
                    document.set_write_target(1, 2)
                self.assertEqual(document.header, document._source_header)
                path.unlink()

    def test_state_change_first_is_refused(self):
        document = CadDocument.open(D0)
        document.set_group_state(1, 'hidden')
        with self.assertRaisesRegex(ValueError, 'move the write group/layer first'):
            document.set_write_target(1, 0)

    def test_only_v700(self):
        document = CadDocument.open(V600)
        with self.assertRaisesRegex(ValueError, 'Ver.7.00'):
            document.set_write_target(1, 0)

    def test_bad_numbers_are_refused(self):
        document = CadDocument.open(D0)
        for args in [(16, 0), (0, 16), (-1, 0), (True, 0), ('1', 0)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                document.set_write_target(*args)

    def test_plan_approval_run(self):
        path = self.write('d0.jww', D0.read_bytes())
        document = CadDocument.open(path)
        actions = [dict(op='set_write_target', kwargs=dict(layer_group=1, layer=2)),
                   dict(op='set_group_state', kwargs=dict(layer_group=0, state='hidden'))]
        receipt = write_plan(document, [], actions, self.folder / 'edited.jww', self.folder / 'plan.json')
        rows = [r for r in receipt['plan']['resource_targets'] if r['kind'] == 'set_write_target']
        self.assertEqual(rows[0]['write_target_before'], dict(layer_group=0, layer=0))
        self.assertFalse((self.folder / 'edited.jww').exists())
        execute_plan(receipt['path'], approved_sha256=receipt['sha256'])
        saved = CadDocument.open(self.folder / 'edited.jww')
        self.assertEqual(saved.header['write_layer_group'], 1)
        self.assertEqual(saved.get_group_state(0)['state'], 'hidden')
        self.assertEqual(saved.get_layer_state(1, 2)['state'], 'writing')
        self.assertEqual(path.read_bytes(), D0.read_bytes())


if __name__ == '__main__':
    unittest.main()
