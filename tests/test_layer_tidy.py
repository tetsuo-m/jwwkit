"""Issue #56: tidy a target drawing's groups/layers after a sample drawing (synthetic drawings only)."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import jwwkit
from jwwkit import CadDocument, layer_tidy
from jwwkit.safe_edit import execute_plan

from test_v600_schema700 import TempDirTestCase

ARCH = 'architecture'


def slot(entity):
    return (entity.attributes['layer_group'], entity.attributes['layer'])


class LayerTidyTests(TempDirTestCase):
    def build_sample(self):
        """Architecture only, sorted into group 0 layers 1..4."""
        doc = CadDocument.open(jwwkit.template_path())
        doc.add_line((0, 0), (100, 0), layer_group=0, layer=1)          # wall, split in the target
        doc.add_line((0, 0), (0, 80), layer_group=0, layer=1)
        doc.add_line((0, 80), (100, 80), layer_group=0, layer=1)
        doc.add_circle((50, 40), 5, layer_group=0, layer=2)
        doc.add_arc((20, 20), 4, 0.0, 1.5, layer_group=0, layer=2)
        doc.add_point((10, 10), layer_group=0, layer=3)
        doc.add_text((30, 30), None, ARCH, layer_group=0, layer=3)
        doc.add_solid(((60, 60), (70, 60), (70, 70), (60, 70)), layer_group=0, layer=4)
        doc.add_line((0, 100), (40, 100), layer_group=0, layer=4)       # only in the sample
        path = self.folder / 'sample.jww'
        doc.save(path)
        return path

    def build_target(self, sample, *, edit=None, name='target.jww'):
        """The sample's elements scattered over other groups/layers, plus symbols that are not in the sample."""
        doc = CadDocument.open(sample)
        moves = {0: (3, 5), 1: (4, 0), 2: (0, 1), 3: (5, 7), 4: (5, 7), 5: (6, 2), 6: (7, 3), 7: (2, 9)}
        for index, (g, l) in moves.items():
            doc.set_entity_attributes(index, layer_group=g, layer=l)
        doc.delete_entity(8)                                             # the sample-only line
        doc.add_circle((80, 20), 3, layer_group=0, layer=1)              # electrical symbol
        doc.add_text((82, 20), None, 'E', layer_group=4, layer=0)
        if edit is not None:
            edit(doc)
        path = self.folder / name
        doc.save(path)
        return path

    def run_plan(self, sample, target, **options):
        receipt = layer_tidy.write_plan(sample, target, self.folder / 'out.jww', self.folder / 'plan.json', **options)
        execute_plan(receipt['plan']['path'], approved_sha256=receipt['plan']['sha256'])
        return receipt, CadDocument.open(self.folder / 'out.jww')

    def test_matched_elements_take_the_sample_slots(self):
        sample = self.build_sample()
        target = self.build_target(sample)
        before = target.read_bytes()
        receipt, out = self.run_plan(sample, target)
        self.assertEqual(target.read_bytes(), before)
        s = CadDocument.open(sample)
        expected = [slot(e) for e in s.entities[:8]]
        self.assertEqual([slot(e) for e in out.entities[:8]], expected)
        self.assertEqual([slot(e) for e in out.entities[8:]], [(0, 1), (4, 0)])  # symbols stay
        counts = receipt['review']['counts']
        self.assertEqual(counts['move'], 7)            # index 2 was already in place
        self.assertEqual(counts['already_in_place'], 1)
        self.assertEqual(counts['unmatched'], 2)
        self.assertEqual(counts['sample_only'], 1)
        self.assertEqual(counts['sample_only_by_type'], {'LINE': 1})
        self.assertTrue(Path(receipt['review_path']).exists())
        # Only groups and layers changed.
        t = CadDocument.open(target)
        for a, b in zip(t.entities, out.entities):
            self.assertEqual(a.geometry, b.geometry)
            self.assertEqual({k: v for k, v in a.attributes.items() if k not in ('layer_group', 'layer')},
                             {k: v for k, v in b.attributes.items() if k not in ('layer_group', 'layer')})

    def test_hidden_layers_are_matched_too(self):
        sample = self.build_sample()
        target = self.build_target(sample, edit=lambda d: (d.set_layer_state(3, 5, 'hidden'),
                                                            d.set_layer_state(6, 2, 'display_only')))
        receipt, out = self.run_plan(sample, target)
        self.assertEqual(slot(out.entities[0]), (0, 1))
        self.assertEqual(slot(out.entities[5]), (0, 3))

    def test_split_lines(self):
        sample = self.build_sample()

        def split(d):
            d.delete_entity(0)                                   # replace the wall by two pieces
            d.add_line((0, 0), (60, 0), layer_group=9, layer=9)
            d.add_line((60, 0), (100, 0), layer_group=9, layer=9)
            d.add_line((10, 80), (30, 80), layer_group=9, layer=8)   # wholly inside a sample line
            d.add_line((90, 80), (120, 80), layer_group=9, layer=8)  # sticks out: partial
        target = self.build_target(sample, edit=split)
        result = layer_tidy.analyze(sample, target)
        t = CadDocument.open(target)
        found = {tuple(sorted(((e.geometry['start_x'], e.geometry['end_x'])))): result['moves'].get(i)
                 for i, e in enumerate(t.entities) if e.entity_type == 'LINE' and slot(e)[0] == 9}
        self.assertEqual(found[(0.0, 60.0)], (0, 1))
        self.assertEqual(found[(60.0, 100.0)], (0, 1))
        self.assertEqual(found[(10.0, 30.0)], (0, 1))
        self.assertIsNone(found[(90.0, 120.0)])
        self.assertIn('line_cover', result['review']['counts']['move_by_match'])

    def test_overlapping_and_ambiguous(self):
        sample = self.build_sample()
        doc = CadDocument.open(sample)
        doc.add_line((0, 200), (50, 200), layer_group=0, layer=1)
        doc.add_line((0, 200), (50, 200), layer_group=0, layer=2)    # same shape, other layer
        doc.save(self.folder / 'sample2.jww')
        sample2 = self.folder / 'sample2.jww'

        def extra(d):
            d.add_line((0, 0), (0, 80), layer_group=8, layer=8)      # duplicate of a wall
            d.add_line((0, 200), (50, 200), layer_group=8, layer=1)
            d.add_line((0, 200), (50, 200), layer_group=8, layer=2)
        target = self.build_target(sample2, edit=extra)
        result = layer_tidy.analyze(sample2, target)
        kinds = {x['kind'] for x in result['review']['left_alone']}
        self.assertIn('ambiguous', kinds)
        self.assertEqual(result['review']['counts']['left_alone']['ambiguous'], 2)
        t = CadDocument.open(target)
        dup = [i for i, e in enumerate(t.entities) if slot(e) == (8, 8)][0]
        self.assertEqual(result['moves'][dup], (0, 1))

    def test_attribute_tiebreak_only_when_shape_leaves_it_open(self):
        sample = self.build_sample()
        doc = CadDocument.open(sample)
        doc.add_line((0, 300), (50, 300), layer_group=0, layer=1)                 # solid line, layer 1
        doc.add_line((0, 300), (50, 300), layer_group=0, layer=2, linetype=2)     # dashed, same place, layer 2
        doc.save(self.folder / 'sample3.jww')
        sample3 = self.folder / 'sample3.jww'

        def extra(d):
            d.add_line((0, 300), (50, 300), layer_group=8, layer=5, linetype=2)
            d.add_line((0, 300), (50, 300), layer_group=8, layer=6)
        target = self.build_target(sample3, edit=extra)
        result = layer_tidy.analyze(sample3, target)
        t = CadDocument.open(target)
        dashed = [i for i, e in enumerate(t.entities) if slot(e) == (8, 5)][0]
        solid = [i for i, e in enumerate(t.entities) if slot(e) == (8, 6)][0]
        self.assertEqual(result['moves'][dashed], (0, 2))
        self.assertEqual(result['moves'][solid], (0, 1))
        self.assertEqual(result['review']['counts']['move_by_match'].get('attribute_tiebreak'), 2)
        self.assertNotIn('ambiguous', result['review']['counts']['left_alone'])
        # Elements decided by shape never use the attributes: a wall with another colour still matches.
        recoloured = self.build_target(sample3, edit=lambda d: (extra(d), d.set_entity_attributes(1, color=5)),
                                       name='recoloured.jww')
        self.assertEqual(layer_tidy.analyze(sample3, recoloured)['moves'][1], (0, 1))

    def test_groups_of_other_scales_are_refused(self):
        sample = self.build_sample()
        def rescale(d):
            d.delete_entity(0)
            end = d.convert_point((100, 0), layer_group=0, from_units='paper', to_units='real')
            d.set_group_scale(3, 2 * d.get_group_scale(0) if d.get_group_scale(0) != 50 else 25)
            d.add_line((0, 0), end, layer_group=3, layer=5, units='real')   # same real place, other scale
        target = self.build_target(sample, edit=rescale)
        result = layer_tidy.analyze(sample, target)
        self.assertEqual(result['review']['counts']['refused_for_scale'], 1)
        self.assertEqual(result['review']['counts']['unmatched'], 2)

    def test_unmatched_elements_can_move_to_an_empty_layer(self):
        sample = self.build_sample()
        target = self.build_target(sample)
        receipt, out = self.run_plan(sample, target, unmatched=('move', 10, 15))
        self.assertEqual([slot(e) for e in out.entities[8:]], [(10, 15), (10, 15)])
        for used in ((0, 1), (0, 4)):
            with self.subTest(used=used), self.assertRaisesRegex(ValueError, 'used in the sample'):
                layer_tidy.analyze(sample, target, unmatched=('move', *used))

    def test_unmatched_layer_need_not_be_empty_before(self):
        sample = self.build_sample()
        # (3, 5) holds a scattered wall line (it leaves for the sample layer) and gets the symbols.
        target = self.build_target(sample, edit=lambda d: d.add_circle((90, 90), 2, layer_group=3, layer=5))
        receipt, out = self.run_plan(sample, target, unmatched=('move', 3, 5))
        t = CadDocument.open(target)
        in_slot = [i for i, e in enumerate(out.entities) if slot(e) == (3, 5)]
        self.assertEqual(sorted(in_slot), sorted(i for i, e in enumerate(t.entities) if i >= 8))
        self.assertEqual(slot(out.entities[0]), (0, 1))                     # the wall left (3, 5)
        self.assertEqual(receipt['review']['unmatched_layer'], dict(refused=False, would_stay={}))

    def test_unmatched_layer_refused_if_other_elements_would_stay(self):
        sample = self.build_sample()
        target = self.build_target(sample, edit=lambda d: d.add_text((30, 30), None, 'other', layer_group=3, layer=5))
        with self.assertRaisesRegex(ValueError, r"would still hold.*content_differs': 1"):
            layer_tidy.analyze(sample, target, unmatched=('move', 3, 5))
        with self.assertRaises(layer_tidy.TidyRefused):
            layer_tidy.write_plan(sample, target, self.folder / 'out.jww', self.folder / 'plan.json',
                                  unmatched=('move', 3, 5))
        review = json.loads((self.folder / 'plan.review.json').read_text(encoding='utf-8'))
        self.assertEqual(review['unmatched_layer'], dict(refused=True, would_stay={'content_differs': 1}))
        self.assertFalse((self.folder / 'plan.json').exists())

    def test_layer_and_group_settings(self):
        sample = self.build_sample()
        doc = CadDocument.open(sample)
        doc.set_layer_name(0, 1, 'wall')
        doc.set_group_name(0, 'arch')
        doc.set_layer_state(0, 2, 'display_only')
        doc.save(self.folder / 'named.jww')
        named = self.folder / 'named.jww'
        target = self.build_target(named, edit=lambda d: (d.set_layer_name(0, 1, 'x'), d.set_group_name(0, 'y'),
                                                           d.set_layer_state(0, 2, 'editable')))
        keep = layer_tidy.analyze(named, target)
        self.assertEqual(keep['settings_actions'], [])
        rows = keep['review']['settings']['differences']
        self.assertTrue(any(r['kind'] == 'layer' and r['layer'] == 1 and r['name_differs'] for r in rows))
        self.assertNotIn('wall', json.dumps(keep['review']))
        receipt, out = self.run_plan(named, target, layer_settings='sample', group_settings='sample')
        self.assertEqual(out.get_layer_name(0, 1), 'wall')
        self.assertEqual(out.get_group_name(0), 'arch')
        self.assertEqual(out.get_layer_state(0, 2)['state'], 'display_only')

    def test_tolerance(self):
        sample = self.build_sample()

        def shift(d):
            d.delete_entity(3)
            d.add_circle((50 + 0.000002, 40), 5, layer_group=11, layer=11)   # 0.0002 real mm at 1/100
        target = self.build_target(sample, edit=shift)
        strict_zero = layer_tidy.analyze(sample, target)
        self.assertEqual(strict_zero['review']['counts']['unmatched'], 3)
        loose = layer_tidy.analyze(sample, target, position_tolerance=0.001)
        self.assertEqual(loose['review']['counts']['unmatched'], 2)

    def test_edit_refusals_are_listed_or_stop(self):
        sample = self.build_sample()
        target = self.build_target(sample)
        original = CadDocument.set_entity_attributes

        def refuse_first(self_, index, **kwargs):
            if index == 0:
                raise ValueError('refused for the test')
            return original(self_, index, **kwargs)
        with patch.object(CadDocument, 'set_entity_attributes', refuse_first):
            result = layer_tidy.analyze(sample, target)
            self.assertNotIn(0, result['moves'])
            self.assertEqual(result['review']['counts']['left_alone']['edit_refused'], 1)
            with self.assertRaisesRegex(ValueError, 'strict=True'):
                layer_tidy.analyze(sample, target, strict=True)

    def test_bad_options(self):
        sample = self.build_sample()
        target = self.build_target(sample)
        for kwargs in (dict(layer_settings='x'), dict(group_settings=1), dict(strict='yes'),
                       dict(unmatched=('move', 16, 0)), dict(position_tolerance=-1)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                layer_tidy.analyze(sample, target, **kwargs)

    def test_review_has_no_drawing_text(self):
        sample = self.build_sample()
        target = self.build_target(sample)
        receipt = layer_tidy.write_plan(sample, target, self.folder / 'out.jww', self.folder / 'plan.json')
        text = Path(receipt['review_path']).read_text(encoding='utf-8')
        self.assertNotIn(ARCH, text)
        self.assertNotIn('target.jww', text)
        self.assertNotIn('sample.jww', text)
        self.assertEqual(json.loads(text)['plan_sha256'], receipt['plan']['sha256'])

    # --- review follow-ups ---
    def test_different_text_or_point_kind_is_not_a_match(self):
        sample = self.build_sample()

        def change(d):
            d.set_text(6, 'other text')                                # same place, other content
            d.delete_entity(5)
            d.add_point((10, 10), layer_group=6, layer=2, is_temporary=True)
        target = self.build_target(sample, edit=change)
        result = layer_tidy.analyze(sample, target)
        self.assertEqual(result['review']['counts']['left_alone']['content_differs'], 2)
        t = CadDocument.open(target)
        text = [i for i, e in enumerate(t.entities) if e.entity_type == 'TEXT' and e.geometry['content'] == 'other text'][0]
        self.assertNotIn(text, result['moves'])

    def test_repeats_of_an_already_paired_sample_element(self):
        sample = self.build_sample()

        def extra(d):
            d.add_circle((50, 40), 5, layer_group=10, layer=3)        # second copy of the sample circle
            d.add_line((90, 80), (130, 80), layer_group=10, layer=4)  # partly over a paired wall line
        target = self.build_target(sample, edit=extra)
        result = layer_tidy.analyze(sample, target)
        t = CadDocument.open(target)
        copy_index = [i for i, e in enumerate(t.entities) if slot(e) == (10, 3)][0]
        partial_index = [i for i, e in enumerate(t.entities) if slot(e) == (10, 4)][0]
        self.assertEqual(result['moves'][copy_index], (0, 2))
        self.assertEqual(result['review']['counts']['move_by_match'].get('overlap'), 2)   # the circle and its copy
        self.assertNotIn(partial_index, result['moves'])
        self.assertIn(partial_index, [x['index'] for x in result['review']['left_alone'] if x['kind'] == 'partial_line'])
        self.assertEqual(result['review']['counts']['unmatched'], 2)

    def test_line_partition_is_counted_as_such(self):
        sample = self.build_sample()

        def split(d):
            d.delete_entity(0)
            d.add_line((0, 0), (60, 0), layer_group=9, layer=9)
            d.add_line((60, 0), (100, 0), layer_group=9, layer=9)
        result = layer_tidy.analyze(sample, self.build_target(sample, edit=split))
        self.assertEqual(result['review']['counts']['move_by_match'].get('line_partition'), 2)

    def test_nothing_to_move_writes_the_review_and_says_why(self):
        sample = self.build_sample()

        def rescale(d):
            for g in range(16):
                d.set_group_scale(g, 2 * d.get_group_scale(g))
        target = self.build_target(sample, edit=rescale)
        review_path = self.folder / 'plan.review.json'
        with self.assertRaisesRegex(ValueError, 'Nothing to change.*not in the sample'):
            layer_tidy.write_plan(sample, target, self.folder / 'out.jww', self.folder / 'plan.json')
        self.assertTrue(review_path.exists())
        self.assertFalse((self.folder / 'plan.json').exists())

    def test_an_existing_review_stops_before_the_plan(self):
        sample = self.build_sample()
        target = self.build_target(sample)
        (self.folder / 'plan.review.json').write_text('{}', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            layer_tidy.write_plan(sample, target, self.folder / 'out.jww', self.folder / 'plan.json')
        self.assertFalse((self.folder / 'plan.json').exists())

    def test_settings_are_not_applied_to_the_unmatched_layer(self):
        sample = self.build_sample()
        target = self.build_target(sample, edit=lambda d: d.set_layer_name(10, 15, 'symbols'))
        result = layer_tidy.analyze(sample, target, unmatched=('move', 10, 15), layer_settings='sample')
        self.assertFalse(any(a['kwargs'].get('layer_group') == 10 for a in result['settings_actions']))

    def test_content_is_checked_for_every_candidate(self):
        sample = self.build_sample()

        def extra(d):
            d.add_text((30, 30), None, ARCH, layer_group=12, layer=1)         # same text, other layer
            d.add_text((30, 30), None, 'other', layer_group=12, layer=2)      # same place, other text
            d.add_point((10, 10), layer_group=12, layer=3, is_temporary=True)
        target = self.build_target(sample, edit=extra)
        result = layer_tidy.analyze(sample, target)
        t = CadDocument.open(target)
        by_slot = {slot(e): i for i, e in enumerate(t.entities)}
        self.assertEqual(result['moves'][by_slot[(12, 1)]], (0, 3))
        self.assertNotIn(by_slot[(12, 2)], result['moves'])
        self.assertNotIn(by_slot[(12, 3)], result['moves'])
        self.assertEqual(result['review']['counts']['left_alone']['content_differs'], 2)

    def test_many_unmatched_symbols_do_not_hit_the_limit(self):
        sample = self.build_sample()

        def symbols(d):
            for k in range(1500):
                d.add_circle((1000 + k * 3, 1000), 1, layer_group=13, layer=1)
        target = self.build_target(sample, edit=symbols)
        result = layer_tidy.analyze(sample, target)
        self.assertEqual(result['review']['counts']['unmatched'], 1502)

    def test_tiebreak_must_be_one_to_one(self):
        sample = self.build_sample()
        doc = CadDocument.open(sample)
        doc.add_line((0, 400), (50, 400), layer_group=0, layer=1)
        doc.add_line((0, 400), (50, 400), layer_group=0, layer=2, linetype=2)
        doc.save(self.folder / 'sample4.jww')
        sample4 = self.folder / 'sample4.jww'

        def extra(d):
            d.add_line((0, 400), (50, 400), layer_group=14, layer=1)                 # a second solid copy
            d.add_line((0, 400), (50, 400), layer_group=14, layer=2)                 # and a third
        target = self.build_target(sample4, edit=extra)
        result = layer_tidy.analyze(sample4, target)
        t = CadDocument.open(target)
        copies = [i for i, e in enumerate(t.entities) if slot(e)[0] == 14]
        self.assertTrue(all(i not in result['moves'] for i in copies))
        self.assertEqual(result['review']['counts']['left_alone']['ambiguous'], 2)

    def test_partial_overlap_far_from_the_start_and_reversed(self):
        sample = self.build_sample()
        doc = CadDocument.open(sample)
        doc.add_line((900, 500), (2000, 500), layer_group=0, layer=1)            # a long wall
        doc.save(self.folder / 'sample5.jww')
        sample5 = self.folder / 'sample5.jww'

        def extra(d):
            d.add_line((0, 500), (1200, 500), layer_group=15, layer=1)           # overlaps far from its start
            d.add_line((1200, 501), (0, 501), layer_group=15, layer=2)           # not on the wall
        target = self.build_target(sample5, edit=extra)
        reverse = self.build_target(sample5, edit=lambda d: d.add_line((1200, 500), (0, 500), layer_group=15, layer=1),
                                    name='reverse.jww')
        for path in (target, reverse):
            result = layer_tidy.analyze(sample5, path, unmatched=('move', 10, 15))
            t = CadDocument.open(path)
            far = [i for i, e in enumerate(t.entities) if slot(e) == (15, 1)][0]
            with self.subTest(path=path.name):
                self.assertIn(far, [x['index'] for x in result['review']['left_alone'] if x['kind'] == 'partial_line'])
                self.assertNotIn(far, result['moves'])

    def test_a_very_long_line_stays_fast(self):
        import time
        sample = self.build_sample()
        doc = CadDocument.open(sample)
        doc.add_line((-200000, -100000), (200000, 100000), layer_group=0, layer=5)  # tens of km in real mm
        doc.save(self.folder / 'sample6.jww')
        target = self.build_target(self.folder / 'sample6.jww',
                                   edit=lambda d: d.add_line((0, 0), (10, 5), layer_group=15, layer=3))
        start = time.time()
        layer_tidy.analyze(self.folder / 'sample6.jww', target)
        self.assertLess(time.time() - start, 30)

    def test_many_lines_with_wiring_do_not_hit_the_limit(self):
        import random
        rng = random.Random(56)
        doc = CadDocument.open(jwwkit.template_path())
        for _ in range(4000):                                   # architecture in 30 m x 20 m (real mm)
            x, y = rng.uniform(0, 30000), rng.uniform(0, 20000)
            doc.add_line((x, y), (x + rng.uniform(-3000, 3000), y + rng.uniform(-3000, 3000)),
                         layer_group=0, layer=rng.randrange(1, 5), units='real')
        doc.save(self.folder / 'dense.jww')
        target = CadDocument.open(self.folder / 'dense.jww')
        for _ in range(1500):                                   # wiring that is not in the sample
            x, y = rng.uniform(0, 30000), rng.uniform(0, 20000)
            target.add_line((x, y), (x + rng.uniform(-2000, 2000), y + rng.uniform(-2000, 2000)),
                            layer_group=0, layer=9, units='real')
        target.save(self.folder / 'dense_target.jww')
        result = layer_tidy.analyze(self.folder / 'dense.jww', self.folder / 'dense_target.jww')
        self.assertEqual(result['review']['counts']['already_in_place'], 4000)
        self.assertEqual(result['review']['counts']['unmatched'], 1500)

    def test_covered_pieces_do_not_use_the_tiebreak(self):
        sample = self.build_sample()
        doc = CadDocument.open(sample)
        doc.add_line((0, 600), (50, 600), layer_group=0, layer=1)
        doc.add_line((0, 600), (50, 600), layer_group=0, layer=2, linetype=2)
        doc.save(self.folder / 'sample7.jww')
        target = self.build_target(self.folder / 'sample7.jww',
                                   edit=lambda d: d.add_line((10, 600), (20, 600), layer_group=15, layer=4, linetype=2))
        result = layer_tidy.analyze(self.folder / 'sample7.jww', target)
        self.assertEqual(result['review']['counts']['left_alone'].get('ambiguous'), 1)

    def test_strict_stops_only_for_editing_refusals(self):
        sample = self.build_sample()
        target = self.build_target(sample, edit=lambda d: d.set_text(6, 'other text'))
        result = layer_tidy.analyze(sample, target, strict=True)
        self.assertEqual(result['review']['counts']['left_alone']['content_differs'], 1)


if __name__ == '__main__':
    unittest.main()
