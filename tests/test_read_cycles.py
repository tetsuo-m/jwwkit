"""Issue #29: reading, opening and saving leave no reference cycles behind.

The records a read creates must be freed as soon as the caller drops them, without waiting for
Python's cyclic collector. Each check runs once to warm up (imports and caches), then again with
the collector disabled, drops the result and counts what the collector still finds.
"""
import gc
import tempfile
import unittest
from pathlib import Path

from jwwkit import CadDocument, JwwDocument, Line, Text
from jwwkit.reader.archive import Cursor, RecordError, read_records_bytes
from jwwkit.writer.preserved import capture_source

from test_open_isolation import public_samples


def leftover(function):
    """Number of objects the cyclic collector finds after function() and dropping its result."""
    gc.collect()
    enabled = gc.isenabled()
    gc.disable()
    try:
        result = function()
        del result
        return gc.collect()
    finally:
        if enabled:
            gc.enable()


def is_read_object(item):
    """A record, a span or a cursor made by the reader."""
    if isinstance(item, Cursor):
        return True
    return isinstance(item, dict) and (('type' in item and 'base' in item)
                                       or ('class_name' in item and 'base_offset' in item))


def read_objects_left_after_rejection(function):
    """Reader objects still waiting for the collector after a rejected read.

    The exception's traceback and frames can form cycles of their own, and their number varies
    between Python versions, so only objects the reader made are counted.
    """
    gc.collect()
    enabled = gc.isenabled()
    gc.disable()
    gc.set_debug(gc.DEBUG_SAVEALL)
    try:
        try:
            function()
        except (RecordError, ValueError):
            pass
        else:
            raise AssertionError('the read was expected to be rejected')
        gc.collect()
        return sum(1 for item in gc.garbage if is_read_object(item))
    finally:
        gc.set_debug(0)
        gc.garbage.clear()
        if enabled:
            gc.enable()


class ReadCycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls._tmp.name)
        # Synthetic drawing with nested records: dimension (line + text), block definition and reference.
        new = JwwDocument()
        for i in range(30):
            new.add_line((i, 0), (i + 5, 3))
        new.add_text((0, -10), content='synthetic')
        new.add_circle((0, -20), 2)
        new.add_dimension(Line((0, 10), (20, 10)), Text((9, 11), (11, 11), '20'))
        definition = new.add_block_definition('CYCLE', [Line((0, 0), (1, 1))])
        new.add_block(definition.number, (5, 5))
        cls.synthetic = cls.folder / 'synthetic.jww'
        new.save(cls.synthetic)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def samples(self):
        return [Path(p) for p in public_samples()] + [self.synthetic]

    def assert_nothing_left(self, function):
        function()  # warm up: imports and caches are not garbage
        self.assertEqual(leftover(function), 0)

    def test_reading_leaves_no_cycles(self):
        for path in self.samples():
            with self.subTest(path=path.name):
                data = path.read_bytes()
                self.assert_nothing_left(lambda: read_records_bytes(data))
                self.assert_nothing_left(lambda: capture_source(path))

    def test_opening_leaves_no_cycles(self):
        for path in self.samples():
            with self.subTest(path=path.name):
                self.assert_nothing_left(lambda: CadDocument.open(path))

    def test_saving_leaves_no_cycles(self):
        target = self.folder / 'saved.jww'
        for path in self.samples():
            with self.subTest(path=path.name):
                document = CadDocument.open(path)

                def save():
                    target.unlink(missing_ok=True)
                    document.save(target)
                self.assert_nothing_left(save)
                target.unlink()

    def test_a_rejected_read_leaves_no_reader_objects(self):
        data = self.synthetic.read_bytes()
        broken = self.folder / 'truncated.jww'
        broken.write_bytes(data[:len(data) - 40])  # cut inside the element records
        cases = {
            'truncated bytes': lambda: read_records_bytes(data[:len(data) - 40]),
            'truncated file (capture)': lambda: capture_source(broken),
            'truncated file (open)': lambda: CadDocument.open(broken),
        }
        for name, function in cases.items():
            with self.subTest(case=name):
                self.assertRaises((RecordError, ValueError), function)  # warm up, and it is rejected
                self.assertEqual(read_objects_left_after_rejection(function), 0)


if __name__ == '__main__':
    unittest.main()
