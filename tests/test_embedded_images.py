"""Issue #19: embedded images (several images; BMP, JPEG, PNG, GIF and TIFF).

The container is checked strictly; the inner file is checked against its format's
specification. Jw_cad 10.03.6 embeds the original image files unchanged (samples in
tests/fixtures/jwcad_images). ``verified`` marks shapes seen in Jw_cad output.
"""
import gzip
import struct
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from jwwkit import CadDocument
from jwwkit.reader import images as image_module
from jwwkit.reader.archive import RecordError, read_records_bytes

from test_v600_schema700 import TempDirTestCase, synthetic

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'jwcad_images'
EXPECTED = {
    'a1': [('BMP', (40, 24, 0, False))], 'a2': [('BMP', (40, 24, 0, False))] * 2,
    'a3': [('JPEG', ('SOF0', 8, 3))], 'a4': [('JPEG', ('SOF0', 8, 3))] * 2,
    'a5': [('JPEG', ('SOF0', 8, 3)), ('BMP', (40, 24, 0, False))], 'a6': [],
    'a7': [('BMP', (40, 24, 0, False))], 'a8': [('BMP', (40, 24, 0, False))], 'a9': [('BMP', (40, 24, 0, False))],
    's_bmp_mono': [('BMP', (40, 1, 0, False))], 's_bmp_16': [('BMP', (40, 4, 0, False))],
    's_bmp_256': [('BMP', (40, 8, 0, False))], 's_bmp_16bit': [('BMP', (40, 16, 0, False))],
    's_bmp_32bit': [('BMP', (40, 32, 0, False))], 's_bmp_rle8': [('BMP', (40, 8, 1, False))],
    's_bmp_rle4': [('BMP', (40, 4, 2, False))], 's_bmp_topdown': [('BMP', (40, 24, 0, True))],
    's_bmp_v4header': [('BMP', (108, 24, 0, False))], 's_bmp_v5header': [('BMP', (124, 24, 0, False))],
    's_jpg_progressive': [('JPEG', ('SOF2', 8, 3))], 's_jpg_gray': [('JPEG', ('SOF0', 8, 1))],
    's_jpg_cmyk': [('JPEG', ('SOF0', 8, 4))], 's_png_a': [('PNG', (6, 8))], 's_gif_a': [('GIF', ('GIF89a', 1))],
    's_tif_a': [('TIFF', ('II', 5, 4))],
    's_png_palette': [('PNG', (3, 8))], 's_png_rgb': [('PNG', (2, 8))], 's_gif87a': [('GIF', ('GIF87a', 1))],
    's_tif_none': [('TIFF', ('II', 1, 3))],
}


def fixture(name):
    return FIXTURES / f'{name}.jww'


def raw_image(name, index=0):
    """The original image file embedded in a fixture (inflated in memory)."""
    data = fixture(name).read_bytes()
    image = read_records_bytes(data)['images'][index]
    blob = data[image['gzip_offset']:image['gzip_offset'] + image['compressed_size']]
    return zlib.decompressobj(31).decompress(blob)


def cstring(text):
    raw = text.encode('cp932')
    return bytes([len(raw)]) + raw


def trailer(entries, count=None):
    out = struct.pack('<I', len(entries) if count is None else count)
    for name, blob in entries:
        out += cstring(name) + struct.pack('<I', len(blob)) + blob
    return out


def gz(raw):
    return gzip.compress(raw, mtime=0)


def drawing(entries, count=None, extra=b''):
    """Synthetic v700 drawing whose image text points to 'synthetic_image.jpg'."""
    return synthetic(700, 700, trailer=trailer(entries, count) + extra)


def bmp(width=4, height=2, bits=24, compression=0, header=40, pixels=None, colors=None, top_down=False):
    palette_entries = (1 << bits) if bits <= 8 and colors is None else (colors or 0)
    entry = 3 if header == 12 else 4
    masks = 12 if compression == 3 and header == 40 else 0
    stride = ((width * bits + 31) // 32) * 4
    if pixels is None:
        pixels = bytes(stride * height)
    offset = 14 + header + masks + palette_entries * entry
    if header == 12:
        info = struct.pack('<IHHHH', 12, width, height, 1, bits)
    else:
        info = struct.pack('<IiiHHIIiiII', header, width, -height if top_down else height, 1, bits, compression,
                           len(pixels), 0, 0, 0, 0).ljust(header, b'\0')
    body = info + (struct.pack('<III', 0xf800, 0x07e0, 0x001f) if masks else b'') + bytes(palette_entries * entry) + pixels
    return b'BM' + struct.pack('<IHHI', 14 + len(body), 0, 0, offset) + body


def png(color_type=2, depth=8, extra_chunks=()):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    row = b'\0' + bytes((2 * channels * depth + 7) // 8)
    chunks = [chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 1, depth, color_type, 0, 0, 0))]
    if color_type == 3:
        chunks.append(chunk(b'PLTE', bytes(6)))
    chunks += [chunk(k, d) for k, d in extra_chunks]
    chunks += [chunk(b'IDAT', zlib.compress(row)), chunk(b'IEND', b'')]
    return b'\x89PNG\r\n\x1a\n' + b''.join(chunks)


def tiff_big_endian():
    entries = [(256, 3, 1, 2), (257, 3, 1, 1), (259, 3, 1, 1), (273, 4, 1, 8 + 2 + 12 * 4 + 4), (279, 4, 1, 2)]
    entries.append((277, 3, 1, 1))
    entries.sort()
    ifd = struct.pack('>H', len(entries))
    data_offset = 8 + 2 + 12 * len(entries) + 4
    for tag, kind, n, value in entries:
        if tag == 273:
            value = data_offset
        ifd += struct.pack('>HHI', tag, kind, n) + (struct.pack('>HH', value, 0) if kind == 3 else struct.pack('>I', value))
    return b'MM\x00*' + struct.pack('>I', 8) + ifd + struct.pack('>I', 0) + b'\x00\xff'


class JwcadImageSampleTests(TempDirTestCase):
    def test_samples_open_with_expected_shapes_and_save_identically(self):
        self.assertEqual(sorted(p.stem for p in FIXTURES.glob('*.jww')), sorted(EXPECTED))
        for name, expected in EXPECTED.items():
            with self.subTest(sample=name):
                document = CadDocument.open(fixture(name))
                images = document._source_records['images']
                self.assertEqual([(i['format'], i['shape']) for i in images], expected)
                self.assertTrue(all(i['verified'] for i in images))
                self.assertEqual([(i['width'], i['height']) for i in images], [(258, 124)] * len(expected))
                self.assertEqual(len(document.embedded_images), len(expected))
                target = self.folder / f'{name}.jww'
                document.save(target)
                self.assertEqual(target.read_bytes(), fixture(name).read_bytes())

    def test_embedded_files_are_the_original_images(self):
        # Inflated content equals the image files of the samples (recorded SHA256).
        self.assertEqual(CadDocument.open(fixture('a3')).embedded_images[0]['sha256'],
                         'af0f06d440f50f838c2303b1a162fb031d4bf4394e485aa7fa08d4ef49ee0f0a')
        self.assertEqual(raw_image('s_png_a')[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(raw_image('s_tif_a')[:4], b'II*\x00')

    def test_edits_keep_the_image_section(self):
        def ref(d):
            return next(i for i, e in enumerate(d.entities)
                        if e.entity_type == 'TEXT' and e.geometry['content'].startswith('^@BM'))
        operations = {
            'add_line': lambda d: d.add_line((0, 0), (10, 0)),
            'move_image_text': lambda d: d.move_entity(ref(d), (5, 5)),
            'delete_image_text': lambda d: d.delete_entity(ref(d)),
            'copy_image_text': lambda d: d.copy_entities([ref(d)], (5, 5)),
        }
        for name in ('a5', 'a7', 's_png_a', 's_tif_a', 's_bmp_rle8'):
            source = read_records_bytes(fixture(name).read_bytes())
            for label, operation in operations.items():
                with self.subTest(sample=name, edit=label):
                    document = CadDocument.open(fixture(name))
                    operation(document)
                    target = self.folder / f'{name}_{label}.jww'
                    document.save(target)
                    saved = read_records_bytes(target.read_bytes())
                    self.assertEqual(saved['raw_trailer'], source['raw_trailer'])
                    self.assertEqual(saved['images'], [dict(i, size_offset=s['size_offset'], gzip_offset=s['gzip_offset'])
                                                       for i, s in zip(source['images'], saved['images'])])
        # The image text inside a block definition is kept by unrelated edits.
        document = CadDocument.open(fixture('a9'))
        document.add_line((0, 0), (1, 0))
        document.save(self.folder / 'a9_edit.jww')

    def test_new_text_pointing_to_a_missing_image_is_rejected(self):
        for name in ('a1', 'a5', 's_tif_a'):
            with self.subTest(sample=name):
                document = CadDocument.open(fixture(name))
                index = next(i for i, e in enumerate(document.entities)
                             if e.entity_type == 'TEXT' and e.geometry['content'].startswith('^@BM'))
                document.set_text(index, '^@BM%temp%not_embedded.bmp,100,48.062,0,0,1,0,255,255,255')
                target = self.folder / f'{name}_dangling.jww'
                with self.assertRaises(ValueError) as caught:
                    document.save(target)
                self.assertIn('not embedded', str(caught.exception))
                self.assertFalse(target.exists())
        # Texts pointing to outside files (a6: not embedded at all) are not checked, as before.
        document = CadDocument.open(fixture('a6'))
        document.add_line((0, 0), (1, 0))
        document.save(self.folder / 'a6_edit.jww')


class ImageContainerTests(TempDirTestCase):
    def reject(self, data, prefix, words):
        with self.assertRaises(RecordError) as caught:
            read_records_bytes(data)
        self.assertIn(prefix, str(caught.exception))
        self.assertIn(words, str(caught.exception))

    def test_container_rules(self):
        jpeg = raw_image('a3')
        good = gz(jpeg)
        parsed = read_records_bytes(drawing([('synthetic_image.jpg.gz', good)]))
        self.assertEqual([(i['format'], i['verified']) for i in parsed['images']], [('JPEG', True)])
        cases = [
            (drawing([('synthetic_image.jpg.gz', good[:-10])]), 'Invalid', 'truncated'),
            (drawing([('synthetic_image.jpg.gz', good + good)]), 'Invalid', 'data after the gzip stream'),
            (drawing([('synthetic_image.jpg.gz', good[:-4] + struct.pack('<I', 1))]), 'Invalid', 'gzip'),
            (drawing([('synthetic_image.jpg.gz', jpeg)]), 'Invalid', 'not a gzip'),
            (drawing([('synthetic_image.jpg', jpeg)]), 'unverified', 'without gzip compression'),
            (drawing([('synthetic_image.webp.gz', good)]), 'unverified', 'extension .webp'),
            (drawing([('synthetic_image.png.gz', good)]), 'Invalid', 'does not match the JPEG'),
            (drawing([('synthetic_image.jpg.gz', gz(b'RIFF0000WEBP'))]), 'unverified', 'other than BMP'),
            (drawing([('synthetic_image.jpg.gz', good)], count=257), 'Invalid', 'exceeds the limit 256'),
            (drawing([('synthetic_image.jpg.gz', good)], count=200), 'Invalid', 'remaining bytes'),
        ]
        for data, prefix, words in cases:
            with self.subTest(words=words):
                self.reject(data, prefix, words)
        with self.assertRaises(RecordError) as caught:
            read_records_bytes(drawing([('synthetic_image.jpg.gz', good)], extra=b'\0'))
        self.assertIn('Unsupported trailer/layout', str(caught.exception))
        for limit_name in ('MAX_IMAGE_BYTES', 'MAX_TOTAL_IMAGE_BYTES'):
            with self.subTest(limit=limit_name), patch.object(image_module, limit_name, len(jpeg) - 1):
                self.reject(drawing([('synthetic_image.jpg.gz', good)]), 'Invalid', 'exceeds the limit')
        two = drawing([('synthetic_image.jpg.gz', good), ('second.bmp.gz', gz(bmp()))])
        self.assertEqual(len(read_records_bytes(two)['images']), 2)
        with patch.object(image_module, 'MAX_TOTAL_IMAGE_BYTES', len(jpeg) + 10):
            self.reject(two, 'Invalid', 'exceeds the limit')

    def test_extension_aliases_and_the_count_limit(self):
        jpeg, tif = gz(raw_image('a3')), gz(raw_image('s_tif_a'))
        for name, blob in (('a.jpeg.gz', jpeg), ('a.JPE.gz', jpeg), ('a.tiff.gz', tif)):
            with self.subTest(name=name):
                self.assertEqual(len(read_records_bytes(drawing([(name, blob)]))['images']), 1)
        tiny = gz(bmp(width=1, height=1))
        many = drawing([(f'i{n}.bmp.gz', tiny) for n in range(256)])
        self.assertEqual(len(read_records_bytes(many)['images']), 256)

    def test_unverified_shapes_are_read_and_flagged(self):
        path = self.write('rgb_png.jww', drawing([('synthetic_image.png.gz', gz(png(0, 8)))]))
        document = CadDocument.open(path)
        self.assertEqual([(i['format'], i['verified']) for i in document.embedded_images], [('PNG', False)])
        self.assertEqual([i['verified'] for i in document.summary()['embedded_images']], [False])
        document.save(self.folder / 'rgb_png_copy.jww')
        self.assertEqual((self.folder / 'rgb_png_copy.jww').read_bytes(), path.read_bytes())
        plain = CadDocument.open(Path(__file__).resolve().parent / 'fixtures' / 'jwcad_saved' / 'jwcad10036_save_v600.jww')
        self.assertEqual(plain.embedded_images, ())
        self.assertEqual(plain.summary()['embedded_images'], [])

    def test_dangling_reference_rules(self):
        # The synthetic text points to 'synthetic_image.jpg', which is not embedded here (already dangling).
        path = self.write('dangling.jww', drawing([('other.bmp.gz', gz(bmp()))]))
        document = CadDocument.open(path)
        index = next(i for i, e in enumerate(document.entities) if e.entity_type == 'TEXT'
                     and e.geometry['content'].startswith('^@BM'))
        document.move_entity(index, (1, 1))
        document.save(self.folder / 'dangling_moved.jww')  # an existing dangling text may be kept
        document = CadDocument.open(path)
        document.copy_entities([index], (1, 1))
        with self.assertRaises(ValueError) as caught:  # copying it makes one more dangling text
            document.save(self.folder / 'dangling_copied.jww')
        self.assertIn('not embedded', str(caught.exception))
        # Inside a block definition (a9): the walk counts those texts too. Image texts cannot be grouped into
        # blocks through the API ('Controlled/image text grouping unsupported'), so check the function directly.
        from jwwkit.writer.preserved import dangling_image_references
        parsed = read_records_bytes(fixture('a9').read_bytes())
        self.assertEqual(dangling_image_references(parsed), {})
        text = next(r for d in parsed['block_defs'] for r in d['entities'] if r['type'] == 'TEXT')
        text['content'] = '^@BM%temp%missing.bmp,100,48.062,0,0,1,0,255,255,255'
        self.assertEqual(dict(dangling_image_references(parsed)), {'missing.bmp': 1})
        document = CadDocument.open(fixture('a1'))
        ref = next(i for i, e in enumerate(document.entities) if e.entity_type == 'TEXT'
                   and e.geometry['content'].startswith('^@BM'))
        with self.assertRaises(ValueError) as caught:
            document.replace_entities_with_block([ref], 'image block', base_point=(0, 0))
        self.assertIn('image text grouping unsupported', str(caught.exception))

    def test_single_bmp_drawings_keep_their_result(self):
        # The shape jwwkit accepted before #19 (40-byte header, 24-bit, bottom-up) stays verified.
        self.reject(drawing([('synthetic_image.jpg.gz', gz(raw_image('a1')))]), 'Invalid', 'does not match the BMP')
        parsed = read_records_bytes(drawing([('synthetic_image.bmp.gz', gz(raw_image('a1')))]))
        self.assertEqual(parsed['images'][0]['shape'], (40, 24, 0, False))
        self.assertTrue(parsed['images'][0]['verified'])


class ImageFormatTests(unittest.TestCase):
    def check(self, kind, raw):
        return image_module.CHECKS[kind](raw)

    def bad(self, kind, raw, words):
        with self.assertRaises(ValueError) as caught:
            self.check(kind, raw)
        self.assertIn(image_module.INVALID, str(caught.exception))
        self.assertIn(words, str(caught.exception))

    def test_bmp(self):
        accepted = {
            'core header': (bmp(header=12, bits=24), (12, 24, 0, False), False),
            '32-bit top-down': (bmp(bits=32, top_down=True), (40, 32, 0, True), False),
            '16-bit bitfields': (bmp(bits=16, compression=3), (40, 16, 3, False), False),
            '52-byte header': (bmp(header=52), (52, 24, 0, False), False),
            '8-bit': (bmp(bits=8), (40, 8, 0, False), True),
        }
        for label, (raw, key, verified) in accepted.items():
            with self.subTest(label):
                shape = self.check('BMP', raw)
                self.assertEqual(shape['key'], key)
                self.assertEqual(key in image_module.VERIFIED_SHAPES['BMP'], verified)
        for name in ('s_bmp_rle8', 's_bmp_rle4', 's_bmp_v5header', 's_bmp_mono'):
            self.check('BMP', raw_image(name))
        good = bmp()
        self.bad('BMP', good[:2] + struct.pack('<I', 1) + good[6:], 'file size field')
        self.bad('BMP', good[:6] + b'\1\0' + good[8:], 'reserved')
        self.bad('BMP', bmp(header=40)[:14] + struct.pack('<I', 20) + good[18:], 'header size 20')
        self.bad('BMP', bmp(bits=24)[:28] + struct.pack('<H', 3) + good[30:], 'bit count 3')
        self.bad('BMP', bmp(bits=24, compression=1), 'compression 1 with 24 bits')
        self.bad('BMP', bmp(pixels=bytes(20)), 'pixel data size')
        rle = raw_image('s_bmp_rle8')
        self.bad('BMP', rle[:-2] + b'\x00\x00', 'truncated')
        long_run = bytearray(rle)
        offset, = struct.unpack_from('<I', rle, 10)
        long_run[offset] = 255
        long_run[offset + 2] = 255
        self.bad('BMP', bytes(long_run), 'exceeds the row')
        flipped = bytearray(rle)
        struct.pack_into('<i', flipped, 22, -124)
        self.bad('BMP', bytes(flipped), 'cannot be stored top-down')

    def test_jpeg(self):
        for name in ('a3', 's_jpg_progressive', 's_jpg_gray', 's_jpg_cmyk'):
            self.check('JPEG', raw_image(name))
        jpeg = raw_image('a3')
        self.bad('JPEG', jpeg + b'\0', 'after the JPEG end marker')
        self.bad('JPEG', jpeg[:-2], 'truncated')
        sof = jpeg.index(b'\xff\xc0')
        extended = jpeg[:sof + 1] + b'\xc1' + jpeg[sof + 2:]
        shape = self.check('JPEG', extended)
        self.assertEqual(shape['key'], ('SOF1', 8, 3))
        self.assertNotIn(shape['key'], image_module.VERIFIED_SHAPES['JPEG'])
        self.bad('JPEG', jpeg[:2] + b'\xff\x02\x00\x02' + jpeg[2:], 'not allowed')
        broken = bytearray(jpeg)
        broken[sof + 9] = 2  # component count disagrees with the length
        self.bad('JPEG', bytes(broken), 'frame header fields')

    def test_png(self):
        self.check('PNG', raw_image('s_png_a'))
        for color, depth in ((0, 1), (0, 16), (2, 8), (2, 16), (3, 4), (4, 8), (6, 16)):
            with self.subTest(color=color, depth=depth):
                shape = self.check('PNG', png(color, depth, extra_chunks=[(b'tEXt', b'k\0v')]))
                self.assertEqual(shape['key'], (color, depth))
        good = png()
        self.bad('PNG', good + b'\0', 'after the PNG IEND')
        self.bad('PNG', good[:20] + bytes([good[20] ^ 1]) + good[21:], 'CRC')
        self.bad('PNG', png(extra_chunks=[(b'ABCD', b'')]), 'unknown critical')
        self.bad('PNG', png(2, 4), 'header values')
        self.bad('PNG', png(0, 8, extra_chunks=[(b'PLTE', bytes(3))]), 'palette is not allowed')

    def test_gif(self):
        gif = raw_image('s_gif_a')
        self.assertEqual(self.check('GIF', gif)['key'], ('GIF89a', 1))
        self.assertEqual(self.check('GIF', b'GIF87a' + gif[6:])['key'], ('GIF87a', 1))
        self.bad('GIF', gif[:-1], 'truncated')
        self.bad('GIF', gif + b'\0', 'after the GIF trailer')

    def test_bmp_v5_with_an_embedded_profile(self):
        base = bytearray(bmp(header=124))
        profile = b'profile-bytes'
        struct.pack_into('<I', base, 14 + 56, 0x4D424544)  # PROFILE_EMBEDDED ('MBED' as a DWORD)
        struct.pack_into('<II', base, 14 + 112, len(base) - 14, len(profile))
        data = bytes(base) + profile
        data = data[:2] + struct.pack('<I', len(data)) + data[6:]
        self.assertEqual(self.check('BMP', data)['key'], (124, 24, 0, False))
        wrong = bytearray(data)
        struct.pack_into('<I', wrong, 14 + 56, 0x73524742)  # LCS_sRGB has no profile
        self.bad('BMP', bytes(wrong), 'without a profile')

    def test_tiff_required_fields_and_unknown_types(self):
        data = bytearray(tiff_big_endian())
        count, = struct.unpack_from('>H', data, 8)
        for i in range(count):
            tag, = struct.unpack_from('>H', data, 10 + 12 * i)
            if tag == 256:
                struct.pack_into('>I', data, 10 + 12 * i + 4, 0)  # ImageWidth with no value
        self.bad('TIFF', bytes(data), 'has no integer value')
        data = bytearray(tiff_big_endian())
        tag_offset = 10 + 12 * (count - 1)  # the last field gets an unknown type: skipped (TIFF 6.0)
        last_tag, = struct.unpack_from('>H', data, tag_offset)
        self.assertEqual(last_tag, 279)
        data2 = bytearray(tiff_big_endian())
        entries = bytes(data2[10:10 + 12 * count])
        extra = struct.pack('>HHI4s', 65000, 99, 1, bytes(4))
        rebuilt = b'MM\x00*' + struct.pack('>I', 8) + struct.pack('>H', count + 1) + entries + extra
        image_offset = len(rebuilt) + 4
        fixed = bytearray(rebuilt + struct.pack('>I', 0) + b'\x00\xff')
        for i in range(count):
            tag, = struct.unpack_from('>H', fixed, 10 + 12 * i)
            if tag == 273:
                struct.pack_into('>I', fixed, 10 + 12 * i + 8, image_offset)
        self.assertEqual(self.check('TIFF', bytes(fixed))['key'], ('MM', 1, 1))

    def test_tiff(self):
        self.check('TIFF', raw_image('s_tif_a'))
        shape = self.check('TIFF', tiff_big_endian())
        self.assertEqual(shape['key'], ('MM', 1, 1))
        self.assertNotIn(shape['key'], image_module.VERIFIED_SHAPES['TIFF'])
        self.bad('TIFF', tiff_big_endian()[:-1], 'image data is truncated')
        looped = bytearray(raw_image('s_tif_a'))
        first, = struct.unpack_from('<I', looped, 4)
        count, = struct.unpack_from('<H', looped, first)
        struct.pack_into('<I', looped, first + 2 + 12 * count, first)
        self.bad('TIFF', bytes(looped), 'loop')


if __name__ == '__main__':
    unittest.main()
