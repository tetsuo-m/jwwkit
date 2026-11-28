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
    'd5.jww': '5d4042d53f9e24c16cadf6ff80c2c8a91a6452bea39decf373bfb77f3472b1da',
    'd6.jww': 'd1d2886e20c3831fddc65f542b05fbe7a812834659393f268852b3cd03d3ef89',
    'd7j.jww': '0a1fbb6f420deaccf743f0867b949663de005ec4a1b2bf9b511e664c73cd690b',
    'd7.jww': 'd93f828ff014a2fa0a844aded371bb94a7565269de90bc3ca3d6286ce1c61c56',
    'd8.jww': '7648415a3b82526cb86efea949c0e3775277afec2bff9e6688e8e0c16e5995bd',
    'd9.jww': '072de0e8a82c0a81df14f9723933d00a293b9fa53d5bb4be9d80955823a28a78',
    'd10.jww': '0d2f17741ef975771b54c96a71fcf7a445a304ca145a88acfbcdbd72ec9b1c6d',
    'd11.jww': '0121665eb99017473c3c04072b78a6f015b399a4207c7793a9b767eb9df4e0f2',
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
                                       ('d8.jww', 'd9.jww', dict(layer_group=1, layer=2)),
                                       # Moved once by Jw_cad (outer flag 8194, form B): again, and back.
                                       ('d2.jww', 'd5.jww', dict(layer_group=2, layer=3)),
                                       ('d2.jww', 'd6.jww', dict(layer_group=0, layer=0)),
                                       # From the d6 shape (outer flag 8194, inner parts in the same place):
                                       # no Jw_cad sample moves it further; d2 has the same records.
                                       ('d6.jww', 'd2.jww', dict(layer_group=1, layer=2))):
            with self.subTest(target=target):
                src = (FIXTURES / source).read_bytes(); want = (FIXTURES / target).read_bytes()
                got = self.move_all(source, f'moved_{source}_{target}', **kwargs)
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
                self.assertEqual(len(dims), 2 if source == 'd8.jww' else 10)
                for mine, jw, orig in dims:
                    self.assertEqual((mine['base']['layer_group'], mine['base']['layer']),
                                     (jw['base']['layer_group'], jw['base']['layer']))
                    self.assertEqual(members(mine), members(orig))
                    self.assertEqual(members(mine), members(jw))

    def test_jwwkit_move_is_d7j_and_jwcad_moves_it_like_its_own(self):
        """d7j: d1 moved to group 1, layer 2 by jwwkit. d7: d7j moved again by Jw_cad (to group 2, layer 3)."""
        # jwwkit changes no per-save value, so the same API move gives d7j byte for byte.
        got = self.move_all('d1.jww', 'moved_d1_d7j', layer_group=1, layer=2)
        self.assertEqual(got, (FIXTURES / 'd7j.jww').read_bytes())
        # Jw_cad then moved jwwkit's dimensions as it moves its own: every record of d7 equals d5's
        # (d1 -> d2 -> d5 in Jw_cad only); only the header differs.
        d5 = (FIXTURES / 'd5.jww').read_bytes(); d7 = (FIXTURES / 'd7.jww').read_bytes()
        self.assertEqual(len(d7), len(d5))
        rec5, rec7 = read_records_bytes(d5), read_records_bytes(d7)
        self.assertEqual(rec7['header_end'], rec5['header_end'])
        end = rec7['header_end']
        self.assertEqual(d7[end:], d5[end:])
        self.assertEqual(rec7['entities'], rec5['entities'])
        _, records = tops(d7)
        dims = [r for _, r in records if r['type'] == 'DIMENSION']
        self.assertEqual(len(dims), 10)
        for r in dims:
            self.assertEqual((r['base']['layer_group'], r['base']['layer'], r['base']['flag']), (2, 3, 8194))
            self.assertEqual({(m['base']['layer_group'], m['base']['layer']) for m in members(r)}, {(0, 0)})
        # The header differs in 4 bytes of Jw_cad's per-save values and in 3 bytes kept from the header of the
        # drawing each move started from (d1's in d7j, Jw_cad's d2 for d5).
        d1, d2 = (FIXTURES / 'd1.jww').read_bytes(), (FIXTURES / 'd2.jww').read_bytes()
        self.assertEqual({i for i in range(end) if d7[i] != d5[i]}, {32, 48, 56, 2396, 2397, 2472, 4680})
        for i in (32, 48, 56):
            self.assertEqual((d7[i], d5[i]), (d1[i], d2[i]))

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

    def changed(self, edit, source='d1.jww', text_type=3):
        """The source document with one dimension's stored record changed by edit (in memory only)."""
        doc, index = self.dimension(source, text_type)
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
        def aux_flag(r): r['aux_points'][1]['base']['flag'] = 1
        def aux_point(r): r['aux_points'][2]['y'] = -1.0
        def sxf(r): r['sxf_mode'] = 1
        cases = dict(aux=aux, text_flag=text_flag, line_flag=line_flag, mixed=mixed, outer_flag=outer_flag,
                     aux_flag=aux_flag, aux_point=aux_point, sxf=sxf)
        for name, edit in cases.items():
            for kwargs in (dict(layer=2), dict(layer_group=1), dict(layer_group=1, layer=2)):
                with self.subTest(shape=name, **kwargs):
                    doc, index = self.changed(edit)
                    before = entity_record(doc.entities[index])
                    with self.assertRaisesRegex(ValueError, '文字種付き寸法'):
                        doc.set_entity_attributes(index, **kwargs)
                    self.assertEqual(entity_record(doc.entities[index]), before)
        # Outer flags other than 8192 and 8194 (8194 = moved once by Jw_cad) stay refused.
        for flag in (8196, 8195):
            def other(r): r['base']['flag'] = flag
            with self.subTest(outer_flag=flag):
                doc, index = self.changed(other)
                before = entity_record(doc.entities[index])
                with self.assertRaisesRegex(ValueError, '文字種付き寸法'):
                    doc.set_entity_attributes(index, layer=2)
                self.assertEqual(entity_record(doc.entities[index]), before)

    def test_text_type_0_still_moves_its_inner_parts_unlike_jwcad(self):
        """Text type 0 keeps its behaviour (#62 decision): the inner parts move too, where Jw_cad leaves them
        (d10 -> d11). d10 is an input with edited text fields that Jw_cad opened and saved (see the README)."""
        got = self.move_all('d10.jww', 'moved_d11.jww', layer_group=1, layer=2)
        _, mine = tops(got)
        _, theirs = tops((FIXTURES / 'd11.jww').read_bytes())
        dims = [(a, b) for (_, a), (_, b) in zip(mine, theirs) if a['type'] == 'DIMENSION']
        self.assertEqual(len(dims), 2)
        for a, b in dims:
            self.assertEqual(a['text']['text_type'], 0)
            self.assertEqual((a['base']['layer_group'], a['base']['layer']), (b['base']['layer_group'], b['base']['layer']))
            self.assertEqual({(m['base']['layer_group'], m['base']['layer']) for m in members(a)}, {(1, 2)})
            self.assertEqual({(m['base']['layer_group'], m['base']['layer']) for m in members(b)}, {(0, 0)})

    def test_only_v700_drawings(self):
        """The same Jw_cad dimensions (text type 2) saved as v700 and as v600: only the v700 ones move."""
        saved = FIXTURES.parent / 'jwcad_saved'
        for version, accepted in ((700, True), (600, False)):
            doc = CadDocument.open(saved / f'jwcad10036_save_v{version}.jww')
            dims = [i for i, e in enumerate(doc.entities) if e.entity_type == 'DIMENSION']
            self.assertEqual(len(dims), 3)
            for i in dims:
                with self.subTest(version=version, index=i):
                    before = entity_record(doc.entities[i])
                    self.assertEqual(before['text']['text_type'], 2)
                    if accepted:
                        doc.set_entity_attributes(i, layer=3)
                        after = entity_record(doc.entities[i])
                        self.assertEqual(after['base']['layer'], 3)
                        self.assertEqual(members(after), members(before))
                    else:
                        with self.assertRaisesRegex(ValueError, '文字種付き寸法の層変更'):
                            doc.set_entity_attributes(i, layer=3)

    def test_building_replacement_archives_only_the_outer_record(self):
        """plan_building_replacement names the archive group: a Jw_cad dimension moves by its outer record."""
        from jwwkit.line_document import JwwDocument, Line, Text
        from jwwkit.model.point import Point
        from jwwkit.replacement_workflow import plan_building_replacement, replacement_reference_points
        from jwwkit.safe_edit import execute_plan
        paths = {}
        for name in ('source', 'incoming'):
            built = JwwDocument()
            for group in (1, 2, 3):
                built.set_group_scale(group, 100)
            built.set_group_scale(8, 50)
            if name == 'source':
                built.add_dimension(Line((0, 10), (4, 10), flag=8192, layer_group=1),
                                    Text((1, 11), (2, 11), '400', text_type=3, flag=16400, layer_group=1),
                                    aux_lines=[Line((0, 0), (0, 0), layer_group=1) for _ in range(2)],
                                    aux_points=[Point((0, 0), layer_group=1) for _ in range(4)], layer_group=1)
            built.save(self.folder / f'base_{name}.jww')
            doc = CadDocument.open(self.folder / f'base_{name}.jww')
            doc.add_line((0, 0), (1000, 100 if name == 'incoming' else 0), layer_group=1, units='real')
            doc.add_line((50, 50), (60, 60), layer_group=2, units='real')
            for point in ((0, 0), (1000, 0)):
                doc.add_point(point, layer_group=3, layer=0, units='real', is_temporary=True)
            paths[name] = self.folder / f'{name}.jww'
            doc.save(paths[name])
        result = plan_building_replacement(
            paths['source'], paths['incoming'], self.folder / 'replaced.jww', self.folder / 'replaced.plan.json',
            work_dir=self.folder, building_group=1, settings_policy='destination', archive_group=8,
            source_reference_indices=[r['index'] for r in replacement_reference_points(paths['incoming'])],
            target_reference_indices=[r['index'] for r in replacement_reference_points(paths['source'])],
            distance_tolerance=0, angle_tolerance=0)
        report = execute_plan(result['path'], approved_sha256=result['sha256'])
        self.assertTrue(report['workflow_audit']['passed'])
        before = next(e for e in CadDocument.open(paths['source']).entities if e.entity_type == 'DIMENSION')
        after = [e for e in CadDocument.open(self.folder / 'replaced.jww').entities if e.entity_type == 'DIMENSION']
        self.assertEqual(len(after), 1)
        self.assertEqual((after[0].attributes['layer_group'], after[0].attributes['layer']), (8, 0))
        self.assertEqual(after[0].geometry, before.geometry)   # the inner parts stay in group 1

    def test_e111_shape_keeps_group_only_and_refuses_a_layer_change(self):
        """Text type 1 with outer flag 0: the group alone changes, on the outer record only (as before #62);
        a layer change is refused (before #62 a layer-only change was accepted and written on the inner parts)."""
        for flag in (0, 2):
            def e111(r): r['base']['flag'] = flag
            doc, index = self.changed(e111, text_type=1)
            before = entity_record(doc.entities[index])
            for kwargs in (dict(layer=2), dict(layer_group=1, layer=2)):
                with self.subTest(flag=flag, **kwargs):
                    with self.assertRaisesRegex(ValueError, '文字種付き寸法'):
                        doc.set_entity_attributes(index, **kwargs)
                    self.assertEqual(entity_record(doc.entities[index]), before)
            doc.set_entity_attributes(index, layer_group=1)
            after = entity_record(doc.entities[index])
            self.assertEqual((after['base']['layer_group'], after['base']['layer'], after['base']['flag']), (1, 0, flag))
            self.assertEqual(members(after), members(before))

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


ARCHICAD = FIXTURES.parent / 'archicad_dimensions'
ARCHICAD_SHA256 = {
    'ac2_resave.jww': 'ff0be0a0d62ef26fc459bce1d5b1edb730ef941537e528e8986bbcac424c8403',
    'ac2_gun1_sou2.jww': '051e36935e595104fc258790d56c0dcb60e85c6f5e5081ea3da18b65d6ac55db',
    'ac2_sou3.jww': '6bd23ed504a7d986d8f8fdd7e6a60a7e6a312d92b47d1838bba0fdcc49ff7c51',
    'ac2_gun2.jww': 'b336998f151d66816000239f6b2cf2cd0f85e1d3db3882ac44cdd5b2bf53accd',
    'ac2_modoshi.jww': 'd7b8919d475f455bf3588411e40b66cb2c90767d00a6262478ef3738f2c581ec',
}


class ArchicadDimensionTests(TempDirTestCase):
    """#69: the Archicad export resaved by Jw_cad 10.03.6 (tests/fixtures/archicad_dimensions, README). Jw_cad moves
    its dimension figures by the outer record only, like its own (#62), and keeps their outer linetype 0."""

    def test_fixtures_are_the_reviewed_samples(self):
        for name, digest in ARCHICAD_SHA256.items():
            self.assertEqual(hashlib.sha256((ARCHICAD / name).read_bytes()).hexdigest(), digest, name)

    def move_all(self, source, name, **kwargs):
        doc = CadDocument.open(ARCHICAD / source)
        for i in range(len(doc.entities)):
            doc.set_entity_attributes(i, **kwargs)
        path = self.folder / name
        doc.save(path)
        return path.read_bytes()

    def test_moving_like_jwcad_gives_jwcad_bytes_except_its_flag_and_state(self):
        for source, target, kwargs in (('ac2_resave.jww', 'ac2_gun1_sou2.jww', dict(layer_group=1, layer=2)),
                                       ('ac2_resave.jww', 'ac2_sou3.jww', dict(layer=3)),
                                       ('ac2_resave.jww', 'ac2_gun2.jww', dict(layer_group=2)),
                                       # Moved once by Jw_cad (outer flag 8194, inner parts elsewhere): back.
                                       ('ac2_gun1_sou2.jww', 'ac2_modoshi.jww', dict(layer_group=0, layer=0))):
            with self.subTest(target=target):
                src = (ARCHICAD / source).read_bytes(); want = (ARCHICAD / target).read_bytes()
                got = self.move_all(source, f'moved_{target}', **kwargs)
                self.assertEqual(len(got), len(want))
                rec, records = tops(got)
                end = rec['header_end']
                # jwwkit does not touch the header (Jw_cad's screen state and per-save values).
                self.assertEqual(got[:end], src[:end])
                # In the records, only Jw_cad's selection flag (bit 2; also on the one ordinary text) and the
                # group/layer of the six setting texts (not public elements, so not moved by this loop) differ.
                allowed = set()
                for offset, r in records:
                    if r['type'] == 'TEXT' and r['text_type'] == 1:
                        allowed |= {offset + 9, offset + 10, offset + 11, offset + 12}
                    else:
                        allowed |= {offset + 13, offset + 14}
                diff = {i for i in range(end, len(got)) if got[i] != want[i]}
                self.assertLessEqual(diff, allowed)
                for offset, r in records:
                    if not (r['type'] == 'TEXT' and r['text_type'] == 1):
                        flag, = struct.unpack_from('<H', got, offset + 13)
                        self.assertEqual(struct.unpack_from('<H', want, offset + 13)[0], flag | 2)
                _, theirs = tops(want); _, before = tops(src)
                dims = [(a, b, c) for (_, a), (_, b), (_, c) in zip(records, theirs, before) if a['type'] == 'DIMENSION']
                self.assertEqual(len(dims), 8)
                for mine, jw, orig in dims:
                    self.assertEqual((mine['base']['layer_group'], mine['base']['layer']),
                                     (jw['base']['layer_group'], jw['base']['layer']))
                    self.assertEqual(mine['base']['pen_style'], 0)   # kept, as Jw_cad keeps it
                    self.assertEqual(members(mine), members(orig))
                    self.assertEqual(members(mine), members(jw))

    def dimensions(self, source='ac2_resave.jww'):
        doc = CadDocument.open(ARCHICAD / source)
        return doc, [i for i, e in enumerate(doc.entities) if e.entity_type == 'DIMENSION']

    def test_other_changes_with_the_outer_linetype_0_stay_refused(self):
        """Only a group/layer change keeps the outer linetype 0 out of the check; color, linetype or width with it,
        and any change of coordinates (#73: move, copy), are refused as before."""
        cases = dict(color=(lambda d, i: d.set_entity_attributes(i, layer=2, color=3), '文字種付き寸法の色'),
                     linetype=(lambda d, i: d.set_entity_attributes(i, layer=2, linetype=1), '群・層だけの変更に限ります'),
                     width=(lambda d, i: d.set_entity_attributes(i, layer=2, width=1), '線幅変更'),
                     move=(lambda d, i: d.move_entities([i], (10, 5)), 'Linetype is not defined'),
                     copy=(lambda d, i: d.copy_entities([i], (10, 5)), 'Linetype is not defined'),
                     move_one=(lambda d, i: d.move_entity(i, (10, 5)), 'Linetype is not defined'))
        for name, (operation, message) in cases.items():
            with self.subTest(operation=name):
                doc, dims = self.dimensions()
                before = [entity_record(e) for e in doc.entities]
                with self.assertRaisesRegex(ValueError, message):
                    operation(doc, dims[0])
                self.assertEqual([entity_record(e) for e in doc.entities], before)

    def inject(self, doc, index, record):
        """Put a changed stored record in memory without the edit check (to build unobserved shapes)."""
        from dataclasses import replace
        from jwwkit.model.common_entities import model_entity
        updated = model_entity(record)
        entities = list(doc.entities)
        entities[index] = replace(entities[index], attributes=updated.attributes, geometry=updated.geometry)
        doc.entities = tuple(entities)

    def test_unobserved_shapes_are_refused(self):
        def text_type(r): r['text']['text_type'] = 10001
        def text_flag(r): r['text']['base']['flag'] = 16384
        def line_flag(r): r['line']['base']['flag'] = 0
        def line_style(r): r['line']['base']['pen_style'] = 2
        def aux_line(r): r['aux_lines'][1]['end_x'] += 1.0
        def aux_line_flag(r): r['aux_lines'][0]['base']['flag'] = 0
        def aux_point(r): r['aux_points'][2]['y'] += 1.0
        def aux_point_style(r): r['aux_points'][0]['base']['pen_style'] = 0   # the export before resaving
        def aux_point_flag(r): r['aux_points'][3]['base']['flag'] = 8192
        def mixed(r): r['text']['base']['layer'] = 4
        def outer_flag(r): r['base']['flag'] = 8196
        def sxf(r): r['sxf_mode'] = 1
        cases = dict(text_type=text_type, text_flag=text_flag, line_flag=line_flag, line_style=line_style,
                     aux_line=aux_line, aux_line_flag=aux_line_flag, aux_point=aux_point,
                     aux_point_style=aux_point_style, aux_point_flag=aux_point_flag, mixed=mixed,
                     outer_flag=outer_flag, sxf=sxf)
        for name, edit in cases.items():
            for kwargs in (dict(layer=2), dict(layer_group=1), dict(layer_group=1, layer=2)):
                with self.subTest(shape=name, **kwargs):
                    doc, dims = self.dimensions()
                    record = entity_record(doc.entities[dims[0]])
                    edit(record)
                    self.inject(doc, dims[0], record)
                    with self.assertRaisesRegex(ValueError, '文字種付き寸法'):
                        doc.set_entity_attributes(dims[0], **kwargs)
                    self.assertEqual(entity_record(doc.entities[dims[0]]), record)

    def test_no_op_changes_with_the_outer_linetype_0_stay_refused(self):
        """Only a real change of the outer group/layer keeps the outer linetype 0 out of the check."""
        for name, operation in (('zero move', lambda d, i: d.move_entities([i], (0, 0))),
                                ('zero move one', lambda d, i: d.move_entity(i, (0, 0))),
                                ('same layer', lambda d, i: d.set_entity_attributes(i, layer_group=0, layer=0))):
            with self.subTest(operation=name):
                doc, dims = self.dimensions()
                with self.assertRaisesRegex(ValueError, 'Linetype is not defined'):
                    operation(doc, dims[0])

    def test_a_changed_outer_linetype_is_not_this_shape(self):
        """The samples all have the outer linetype 0. After a linetype-only change (kept from 0.5.1), the group/layer
        change is refused (no Jw_cad sample), in either order."""
        doc, dims = self.dimensions()
        doc.set_entity_attributes(dims[0], linetype=1)
        with self.assertRaisesRegex(ValueError, '文字種付き寸法'):
            doc.set_entity_attributes(dims[0], layer=2)
        doc, dims = self.dimensions()
        doc.set_entity_attributes(dims[0], layer=2)
        doc.set_entity_attributes(dims[0], linetype=1)
        with self.assertRaisesRegex(ValueError, '文字種付き寸法'):
            doc.set_entity_attributes(dims[0], layer=3)

    def test_other_scales_stay_refused(self):
        doc, dims = self.dimensions()
        doc.set_group_scale(1, 50)
        with self.assertRaisesRegex(ValueError, '文字種付き寸法の色・グループ変更'):
            doc.set_entity_attributes(dims[0], layer_group=1)

    def test_the_save_checks_the_same_way(self):
        """A stored record changed beside the edit API: at the save, only an outer group/layer change of this shape
        keeps the outer linetype 0 out of the check."""
        doc, dims = self.dimensions()
        record = entity_record(doc.entities[dims[0]])
        record['base']['layer_group'], record['base']['layer'] = 3, 4
        self.inject(doc, dims[0], record)
        doc.save(self.folder / 'outer_only.jww')
        saved = entity_record(CadDocument.open(self.folder / 'outer_only.jww').entities[dims[0]])
        self.assertEqual(saved, record)
        for name, edit in (('color', lambda r: r['base'].update(pen_color=3)),
                           ('member', lambda r: r['line']['base'].update(layer=4)),
                           ('coordinate', lambda r: r['line'].update(start_x=r['line']['start_x'] + 1))):
            with self.subTest(change=name):
                doc, dims = self.dimensions()
                record = entity_record(doc.entities[dims[0]])
                record['base']['layer'] = 4
                edit(record)
                self.inject(doc, dims[0], record)
                with self.assertRaisesRegex(ValueError, 'Linetype is not defined'):
                    doc.save(self.folder / f'refused_{name}.jww')
                self.assertFalse((self.folder / f'refused_{name}.jww').exists())

    def test_only_v700_drawings(self):
        from jwwkit.model.editing import archicad_dimension_shape
        doc, dims = self.dimensions()
        record = entity_record(doc.entities[dims[0]])
        self.assertTrue(archicad_dimension_shape(doc, record))

        class V600:
            version = 600
        self.assertFalse(archicad_dimension_shape(V600(), record))


if __name__ == '__main__':
    unittest.main()
