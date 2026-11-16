"""Issue #25: opening keeps every returned value independent of the source snapshot.

CadDocument.open keeps the original records (the source snapshot used by the unedited-save
checks) and builds the public model from a separate read of the same bytes. These tests hold
for 0.3.0 too; they guard the speed-up that stops deep-copying freshly read records.
"""
import copy
import tempfile
import unittest
from pathlib import Path

from jwwkit import CadDocument, JwwDocument, Line, Text, template_path
from jwwkit.reader.archive import Record, read_records_bytes

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
MUTABLE = (dict, list, set, bytearray)


def public_samples():
    paths = sorted((FIXTURES / 'jwcad_saved').glob('*.jww')) + sorted((FIXTURES / 'jwcad_images').glob('*.jww'))
    return [template_path()] + paths


def shape(value):
    """Comparable form that keeps container types and Record.source_strings."""
    if isinstance(value, dict):
        strings = shape(value.source_strings) if isinstance(value, Record) else None
        return (type(value).__name__, tuple((k, shape(v)) for k, v in value.items()), strings)
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, tuple(shape(v) for v in value))
    return (type(value).__name__, value)


def containers(value, found):
    """ids of every mutable container reachable from value (Record.source_strings included)."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, MUTABLE):
            if id(item) in found:
                continue
            found[id(item)] = item
            stack.extend(item.values() if isinstance(item, dict) else item)
        elif isinstance(item, tuple):
            stack.extend(item)
        if isinstance(item, Record) and item.source_strings is not None:
            stack.append(item.source_strings)
    return found


def all_entities(document):
    return tuple(document.entities) + tuple(e for d in document.block_definitions for e in d.entities)


class OpenIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        folder = Path(cls._tmp.name)
        # Synthetic drawing with nested records: dimension (line + text), block definition and reference.
        new = JwwDocument()
        for i in range(30):
            new.add_line((i, 0), (i + 5, 3))
        new.add_text((0, -10), content='synthetic')
        new.add_circle((0, -20), 2)
        new.add_dimension(Line((0, 10), (20, 10)), Text((9, 11), (11, 11), '20'))
        definition = new.add_block_definition('ISO', [Line((0, 0), (1, 1))])
        new.add_block(definition.number, (5, 5))
        cls.synthetic = folder / 'synthetic.jww'
        new.save(cls.synthetic)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def samples(self):
        return public_samples() + [self.synthetic]

    def test_reading_the_same_bytes_twice_gives_equal_records(self):
        # The safety checks run on one read; the model is built from another read of the same bytes.
        for path in self.samples():
            with self.subTest(path=path.name):
                data = Path(path).read_bytes()
                first, second = read_records_bytes(data), read_records_bytes(data)
                self.assertEqual(shape(first), shape(second))
                self.assertFalse(set(containers(first, {})) & set(containers(second, {})))

    def test_opened_values_share_no_containers(self):
        for path in self.samples():
            with self.subTest(path=path.name):
                document = CadDocument.open(path)
                source = set(containers(document._source_records, {}))
                owner = {}
                for index, entity in enumerate(all_entities(document)):
                    raw = set(containers(entity.raw, {}))
                    views = set(containers(entity.geometry, {})) | set(containers(entity.attributes, {}))
                    self.assertFalse(raw & views, 'raw shares a container with geometry/attributes')
                    self.assertFalse((raw | views) & source, 'entity shares a container with the source snapshot')
                    for oid in raw | views:
                        self.assertNotIn(oid, owner, 'two entities share a container')
                        owner[oid] = index

    def test_changing_returned_values_does_not_change_the_snapshot_or_the_unedited_save(self):
        for path in [FIXTURES / 'jwcad_saved' / 'jwcad10036_save_v700.jww', self.synthetic]:
            with self.subTest(path=path.name), tempfile.TemporaryDirectory() as folder:
                reference = CadDocument.open(path)
                document = CadDocument.open(path)
                snapshot = copy.deepcopy(document._source_records)
                for entity in all_entities(document):
                    entity.raw['base']['layer'] = 15
                    entity.raw['unexpected'] = [1]
                    for value in entity.raw.values():
                        if isinstance(value, dict) and 'base' in value:  # dimension line/text records
                            value['base']['layer'] = 15
                self.assertEqual(shape(document._source_records), shape(snapshot))
                self.assertEqual([shape(dict(e.geometry)) for e in all_entities(document)],
                                 [shape(dict(e.geometry)) for e in all_entities(reference)])
                self.assertEqual([shape(dict(e.attributes)) for e in all_entities(document)],
                                 [shape(dict(e.attributes)) for e in all_entities(reference)])
                target = Path(folder) / 'unedited.jww'
                document.save(target)
                self.assertEqual(target.read_bytes(), Path(path).read_bytes())

    def test_changing_a_view_does_not_change_its_raw_record_or_other_entities(self):
        path = FIXTURES / 'jwcad_saved' / 'jwcad10036_save_v700.jww'
        reference = CadDocument.open(path)
        document = CadDocument.open(path)
        nested = next(i for i, e in enumerate(document.entities)
                      if any(isinstance(v, dict) for v in e.geometry.values()))
        for value in document.entities[nested].geometry.values():
            if isinstance(value, dict):
                value['changed'] = True
        document.entities[nested].attributes['layer'] = 15
        self.assertEqual(shape(document.entities[nested].raw), shape(reference.entities[nested].raw))
        others = [i for i in range(len(document.entities)) if i != nested]
        self.assertEqual([shape(dict(document.entities[i].geometry)) for i in others],
                         [shape(dict(reference.entities[i].geometry)) for i in others])
        self.assertEqual(shape(document._source_records), shape(reference._source_records))
        # A fresh open still saves byte-identically.
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'fresh.jww'
            CadDocument.open(path).save(target)
            self.assertEqual(target.read_bytes(), path.read_bytes())


if __name__ == '__main__':
    unittest.main()
