"""Issue #27: saving reads the document and never changes it.

The save builds its records from the public model (and the source snapshot) without deep copies
where the records only live inside the save. These tests hold for 0.3.0 too; they guard that:
the document is the same after a save (values, container types, Record.source_strings and the
sign of zeros), no new container sharing appears, each entity keeps its own attributes object,
saving twice gives the same bytes, and a rejected save leaves the document reusable.
"""
import dataclasses
import math
import shutil
import tempfile
import types
import unittest
from pathlib import Path

from jwwkit import CadDocument, JwwDocument, Line, Text
from jwwkit.reader.archive import Record, is_read_only_version

from test_open_isolation import all_entities, containers, public_samples

MISSING_IMAGE_TEXT = '^@BM%temp%missing_image.jpg,100,48.062,0,0,1,0,255,255,255'


def shape(value):
    """Comparable form that keeps container types, Record.source_strings and the sign of zeros."""
    if isinstance(value, dict):
        strings = shape(value.source_strings) if isinstance(value, Record) else None
        return (type(value).__name__, tuple((k, shape(v)) for k, v in value.items()), strings)
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, tuple(shape(v) for v in value))
    if isinstance(value, float):
        return ('float', 'nan') if math.isnan(value) else ('float', math.copysign(1.0, value), value)
    return (type(value).__name__, value)


def document_shape(document):
    return (tuple((e.entity_type, shape(dict(e.attributes)), shape(dict(e.geometry)), shape(e.raw), e.source_index)
                  for e in all_entities(document)),
            tuple((d.number, d.name, shape(dict(d.attributes))) for d in document.block_definitions),
            shape(document.header), shape(document._source_records), shape(document._source_header),
            shape(dict(document._new_block_records)), shape(dict(document._name_edits)),
            shape(dict(document._group_scale_edits)), shape(dict(document._state_edits)),
            document._source_bytes)


def shared_containers(document):
    """Containers reachable from more than one owner: each entity's raw, geometry and attributes,
    each block definition's attributes, the source records, the headers and each added block record."""
    owners = []
    for entity in all_entities(document):
        owners += [entity.raw, entity.geometry, entity.attributes]
    owners += [d.attributes for d in document.block_definitions]
    owners += [document._source_records, document._source_header, document.header,
               *document._new_block_records.values()]
    seen, shared = {}, 0
    for number, owner in enumerate(owners):
        for key in containers(owner, {}):
            if seen.setdefault(key, number) != number:
                shared += 1
    return shared


def first(document, kind):
    return next(i for i, e in enumerate(document.entities) if e.entity_type == kind)


EDITS = {
    'unedited': lambda d, other: None,
    'move': lambda d, other: d.move_entities([first(d, 'LINE')], (100, 0), units='real'),
    'delete': lambda d, other: d.delete_entity(first(d, 'LINE')),
    'add_line': lambda d, other: d.add_line((0, 0), (1000, 0), units='real', layer=2),
    'set_text': lambda d, other: d.set_text(first(d, 'TEXT'), '変更', recalculate_end=True),
    'attributes': lambda d, other: d.set_entity_attributes(first(d, 'LINE'), color=3, linetype=2, layer=4),
    'layer_name': lambda d, other: d.set_layer_name(0, 3, 'L3'),
    'place_block': lambda d, other: d.place_block(d.block_definitions[0].number, (20, 30)),
    'new_block': lambda d, other: d.place_block(
        d.add_block_definition('記号A', [Line((0, 0), (10, 0))], compound_kind=4).number, (20, 30)),
    'import_group': lambda d, other: d.import_group(other, 0, 5),
}


class SaveIsolationTests(unittest.TestCase):
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
        # A copy of the same drawing under another name: its group 0 can be imported into the synthetic one.
        cls.other = folder / 'synthetic_copy.jww'
        shutil.copyfile(cls.synthetic, cls.other)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def samples(self):
        return public_samples() + [self.synthetic]

    def edited_documents(self):
        """(sample, edit, document) for every edit that the sample accepts."""
        for path in self.samples():
            for name, edit in EDITS.items():
                document = CadDocument.open(path)
                try:
                    edit(document, self.other)
                except (ValueError, IndexError, StopIteration):
                    continue  # this sample does not take this edit (read-only, no text, no block ...)
                yield Path(path), name, document

    def test_saving_leaves_the_document_unchanged_and_twice_gives_the_same_bytes(self):
        checked = set()
        for path, name, document in self.edited_documents():
            with self.subTest(path=path.name, edit=name), tempfile.TemporaryDirectory() as folder:
                before, shared = document_shape(document), shared_containers(document)
                attributes = [e.attributes for e in all_entities(document)]
                contents = [shape(dict(a)) for a in attributes]
                first_target, second_target = Path(folder) / 'first.jww', Path(folder) / 'second.jww'
                document.save(first_target)
                self.assertEqual(document_shape(document), before)
                self.assertLessEqual(shared_containers(document), shared)
                # Each entity keeps the same attributes object, with the same contents.
                self.assertEqual(len(all_entities(document)), len(attributes))
                for entity, original, content in zip(all_entities(document), attributes, contents):
                    self.assertIs(entity.attributes, original)
                    self.assertEqual(shape(dict(entity.attributes)), content)
                document.save(second_target)
                self.assertEqual(second_target.read_bytes(), first_target.read_bytes())
                self.assertEqual(document_shape(document), before)
                if name == 'unedited':
                    self.assertEqual(first_target.read_bytes(), path.read_bytes())
                checked.add(name)
        # Every kind of edit reached a save on at least one sample.
        self.assertEqual(checked, set(EDITS))

    def test_attributes_that_are_not_a_plain_dict_are_copied_into_the_record(self):
        # Only an exact dict is shared with the save; any other mapping goes through dict(...).
        saved = 0
        for path in [Path(p) for p in self.samples()]:
            document = CadDocument.open(path)
            if is_read_only_version(document.version) or document._readonly_state is not None or not document.entities:
                continue
            with self.subTest(path=path.name), tempfile.TemporaryDirectory() as folder:
                proxies = tuple(dataclasses.replace(e, attributes=types.MappingProxyType(dict(e.attributes)))
                                for e in document.entities)
                document.entities = proxies
                before = document_shape(document)
                target = Path(folder) / 'proxy.jww'
                document.save(target)
                self.assertEqual(target.read_bytes(), path.read_bytes())
                self.assertEqual(document_shape(document), before)
                self.assertTrue(all(a is b for a, b in zip((e.attributes for e in document.entities),
                                                          (e.attributes for e in proxies))))
                saved += 1
        self.assertGreater(saved, 0)

    def assert_rejected_then_saved(self, document, spoil, restore, expected):
        before = document_shape(document)
        spoil()
        spoiled, shared = document_shape(document), shared_containers(document)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                document.save(Path(folder) / 'rejected.jww')
            self.assertFalse((Path(folder) / 'rejected.jww').exists())
            self.assertEqual(document_shape(document), spoiled)
            self.assertLessEqual(shared_containers(document), shared)
            restore()
            self.assertEqual(document_shape(document), before)
            target = Path(folder) / 'restored.jww'
            document.save(target)
            self.assertEqual(target.read_bytes(), expected)

    def test_a_save_rejected_before_writing_records_leaves_the_document_reusable(self):
        # A non-finite value is rejected by the checks before serialization.
        for path in self.samples():
            document = CadDocument.open(path)
            lines = [i for i, e in enumerate(document.entities) if e.entity_type == 'LINE']
            if not lines or is_read_only_version(document.version):
                continue
            with self.subTest(path=Path(path).name):
                kept, index = document.entities, lines[0]
                spoiled = dataclasses.replace(kept[index], geometry={**kept[index].geometry, 'start_x': float('nan')})

                def spoil():
                    document.entities = kept[:index] + (spoiled,) + kept[index + 1:]

                def restore():
                    document.entities = kept
                self.assert_rejected_then_saved(document, spoil, restore, Path(path).read_bytes())

    def test_a_save_rejected_after_reading_back_leaves_the_document_reusable(self):
        # An image text pointing to an image that is not embedded is rejected after the read-back (v700).
        done = 0
        for path in self.samples():
            document = CadDocument.open(path)
            if document.version != 700:
                continue
            for index in [i for i, e in enumerate(document.entities) if e.entity_type == 'TEXT']:
                original = document.entities[index].geometry['content']
                try:
                    document.set_text(index, MISSING_IMAGE_TEXT)
                except ValueError:
                    continue
                document.set_text(index, original)
                break
            else:
                continue
            with self.subTest(path=Path(path).name), tempfile.TemporaryDirectory() as folder:
                reference = Path(folder) / 'reference.jww'
                document.save(reference)  # the text set back to its content (end point recalculated or not)
                self.assert_rejected_then_saved(document, lambda: document.set_text(index, MISSING_IMAGE_TEXT),
                                                lambda: document.set_text(index, original), reference.read_bytes())
                done += 1
        self.assertGreater(done, 0)

    def test_opened_raw_records_equal_the_source_records_with_the_same_number(self):
        # Issue #25 follow-up: each opened raw equals the source record it came from, including
        # container types and the original string bytes (blocks: the definition's entity records).
        for path in self.samples():
            with self.subTest(path=Path(path).name):
                document = CadDocument.open(path)
                source = document._source_records
                for entity in document.entities:
                    self.assertEqual(shape(entity.raw), shape(source['entities'][entity.source_index]))
                self.assertEqual(len(document.block_definitions), len(source['block_defs']))
                for definition, record in zip(document.block_definitions, source['block_defs']):
                    self.assertEqual(definition.number, record['number'])
                    self.assertEqual([shape(e.raw) for e in definition.entities],
                                     [shape(r) for r in record['entities']])


if __name__ == '__main__':
    unittest.main()
