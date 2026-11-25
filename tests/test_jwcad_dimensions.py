"""#62: group/layer changes of Jw_cad dimension figures write only the outer record, as Jw_cad does.

The samples in tests/fixtures/jwcad_dimensions were saved by the owner in Jw_cad 10.03.6 (see its README).
"""
import copy
import hashlib
import struct
import unittest
from pathlib import Path

from jwwkit import CadDocument
from jwwkit.model.editing import entity_record
from jwwkit.reader.archive import read_records_bytes
from test_v600_schema700 import TempDirTestCase

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'jwcad_dimensions'
SHA256 = {
    'd0.jww': 'eea7a451a5a3a0eea94936f67fd7e4b0023453ae3a31198a908c95050107493c',
    'd1.jww': '016433e27a652b49eab96c85ac3062626ad7d20d6a2d0e1afbc608efc8d2dec8',
    'd2.jww': '6559e17a8b67be3884a173c9608fe91fc37b3ce8dab8a9e37936e2c3a5c3897d',
    'd3.jww': '96fb14567e2f908f8b2586ea6ed5612de1efa772c82b8d851b36012345eaafd9',
    'd8.jww': '7648415a3b82526cb86efea949c0e3775277afec2bff9e6688e8e0c16e5995bd',
    'd9.jww': '072de0e8a82c0a81df14f9723933d00a293b9fa53d5bb4be9d80955823a28a78',
}


def members(record):
    return [record['line'], record['text'], *record['aux_lines'], *record['aux_points']]


def tops(data):
    """Top-level records (not inside another record) with their base offsets, in file order."""
    rec = read_records_bytes(data)
    spans = sorted(rec['spans'], key=lambda s: s['base_offset'])
    out = []
    for s in spans:
        if not any(t['base_offset'] <= s['base_offset'] < t['end'] for t in out):
            out.append(s)
    assert len(out) == len(rec['entities'])
    return rec, [(s['base_offset'], r) for s, r in zip(out, rec['entities'])]


class JwcadDimensionTests(TempDirTestCase):
    def test_fixtures_are_the_reviewed_samples(self):
        for name, digest in SHA256.items():
            self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(), digest, name)

    def move_all(self, source, name, **kwargs):
        doc = CadDocument.open(FIXTURES / source)
        for i in range(len(doc.entities)):
            doc.set_entity_attributes(i, **kwargs)
        path = self.folder / name
        doc.save(path)
        return path.read_bytes()

    def test_moving_like_jwcad_gives_jwcad_bytes_except_its_flag_and_state(self):
        for source, target, kwargs in (('d1.jww', 'd2.jww', dict(layer_group=1, layer=2)),
                                       ('d1.jww', 'd3.jww', dict(layer_group=1)),
                                       ('d8.jww', 'd9.jww', dict(layer_group=1, layer=2))):
            with self.subTest(target=target):
                src = (FIXTURES / source).read_bytes(); want = (FIXTURES / target).read_bytes()
                got = self.move_all(source, f'moved_{target}', **kwargs)
                self.assertEqual(len(got), len(want))
                rec, records = tops(got)
                end = rec['header_end']
                # jwwkit does not touch the header (write group/layer, group/layer states, save values).
                self.assertEqual(got[:end], src[:end])
                # In the records, only Jw_cad's selection flag (bit 2, non-text records) and the group/layer of
                # the six setting texts (not public elements, so not moved by this loop) differ.
                allowed = set()
                for offset, r in records:
                    if r['type'] == 'TEXT':
                        allowed |= {offset + 9, offset + 10, offset + 11, offset + 12}
                    else:
                        allowed |= {offset + 13, offset + 14}
                diff = {i for i in range(end, len(got)) if got[i] != want[i]}
                self.assertTrue(diff)
                self.assertLessEqual(diff, allowed)
                for offset, r in records:
                    if r['type'] != 'TEXT':
                        flag, = struct.unpack_from('<H', got, offset + 13)
                        self.assertEqual(struct.unpack_from('<H', want, offset + 13)[0], flag | 2)
                # Every dimension: outer group/layer as Jw_cad's, inner parts unchanged (as in the source).
                _, theirs = tops(want); _, before = tops(src)
                dims = [(a, b, c) for (_, a), (_, b), (_, c) in zip(records, theirs, before) if a['type'] == 'DIMENSION']
                self.assertEqual(len(dims), 10 if source == 'd1.jww' else 2)
                for mine, jw, orig in dims:
                    self.assertEqual((mine['base']['layer_group'], mine['base']['layer']),
                                     (jw['base']['layer_group'], jw['base']['layer']))
                    self.assertEqual(members(mine), members(orig))
                    self.assertEqual(members(mine), members(jw))

    def test_layer_only_and_a_second_move_write_only_the_outer_record(self):
        doc = CadDocument.open(FIXTURES / 'd1.jww')
        dims = [i for i, e in enumerate(doc.entities) if e.entity_type == 'DIMENSION']
        before = {i: entity_record(doc.entities[i]) for i in dims}
        for i in dims:
            doc.set_entity_attributes(i, layer=5)
        for i in dims:
            after = entity_record(doc.entities[i])
            self.assertEqual((after['base']['layer_group'], after['base']['layer']), (0, 5))
            self.assertEqual(members(after), members(before[i]))
        # Moved by jwwkit, the inner parts are in another place than the outer record (form C); it moves again.
        for i in dims:
            doc.set_entity_attributes(i, layer_group=1, layer=3, preserve='real')
            doc.set_entity_attributes(i, layer_group=0, layer=0)
        path = self.folder / 'back.jww'
        doc.save(path)
        self.assertEqual(path.read_bytes(), (FIXTURES / 'd1.jww').read_bytes())

    def dimension(self, source='d1.jww', text_type=3):
        # Text type 3: text type 1 with outer flag 0/2 is the E111 shape (group-only changes, kept as before).
        doc = CadDocument.open(FIXTURES / source)
        return doc, next(i for i, e in enumerate(doc.entities)
                         if e.entity_type == 'DIMENSION' and e.geometry['text']['text_type'] == text_type)

    def changed(self, edit, source='d1.jww'):
        """The source document with its first dimension's stored record changed by edit (in memory only)."""
        doc, index = self.dimension(source)
        record = entity_record(doc.entities[index])
        edit(record)
        from jwwkit.model.editing import commit
        commit(doc, index, doc.entities[index], record)
        return doc, index

    def test_unobserved_shapes_are_refused(self):
        def aux(r): r['aux_lines'][0]['end_x'] = 1.0
        def text_flag(r): r['text']['base']['flag'] = 16384
        def line_flag(r): r['line']['base']['flag'] = 0
        def mixed(r): r['text']['base']['layer'] = 4
        def outer_flag(r): r['base']['flag'] = 0
        cases = dict(aux=aux, text_flag=text_flag, line_flag=line_flag, mixed=mixed, outer_flag=outer_flag)
        for name, edit in cases.items():
            for kwargs in (dict(layer=2), dict(layer_group=1), dict(layer_group=1, layer=2)):
                with self.subTest(shape=name, **kwargs):
                    doc, index = self.changed(edit)
                    before = entity_record(doc.entities[index])
                    with self.assertRaisesRegex(ValueError, '文字種付き寸法'):
                        doc.set_entity_attributes(index, **kwargs)
                    self.assertEqual(entity_record(doc.entities[index]), before)
        # Moved once by Jw_cad (outer flag 8194, form B): refused until the samples D5/D6 are reviewed.
        doc, index = self.dimension('d2.jww')
        for kwargs in (dict(layer=3), dict(layer_group=2), dict(layer_group=0, layer=0)):
            with self.subTest(shape='form B', **kwargs), self.assertRaisesRegex(ValueError, '文字種付き寸法'):
                doc.set_entity_attributes(index, **kwargs)

    def test_other_scales_and_colors_stay_refused(self):
        doc, index = self.dimension()
        doc.set_group_scale(1, 100)
        with self.assertRaisesRegex(ValueError, '文字種付き寸法の色・グループ変更'):
            doc.set_entity_attributes(index, layer_group=1)
        doc.set_entity_attributes(index, layer_group=2, layer=1)
        # Inner parts in group 0 (1/50), outer in group 2 (1/50): a layer change in group 2 is fine,
        # but group 0 at another scale makes every later move refused.
        doc.set_entity_attributes(index, layer=4)
        doc.set_group_scale(0, 100)
        with self.assertRaisesRegex(ValueError, '文字種付き寸法の層変更'):
            doc.set_entity_attributes(index, layer=5)
        doc, index = self.dimension()
        with self.assertRaisesRegex(ValueError, '文字種付き寸法の色・グループ変更'):
            doc.set_entity_attributes(index, color=3, layer=2)

    def test_linetype_with_a_layer_change_still_reaches_the_inner_parts(self):
        doc, index = self.dimension()
        before = entity_record(doc.entities[index])
        doc.set_entity_attributes(index, layer=2, linetype=2)
        after = entity_record(doc.entities[index])
        self.assertEqual((after['base']['layer'], after['base']['pen_style']), (2, 2))
        expected = copy.deepcopy(before)
        for part in members(expected):
            if part['type'] not in ('TEXT', 'POINT'):
                part['base']['pen_style'] = 2
        self.assertEqual(members(after), members(expected))


if __name__ == '__main__':
    unittest.main()
