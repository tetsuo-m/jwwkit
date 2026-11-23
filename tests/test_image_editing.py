"""Issue #57: insert, delete and replace embedded images in v700 drawings.

Jw_cad 10.03.6 samples (tests/fixtures/jwcad_images): p1_ireru (an image inserted with the relative-path
option), p2_kesu (a2 with the second image deleted), p3_irekae (a2 with the second image replaced by
irekae.bmp), p4_jpg_png (a JPEG and a PNG inserted). jwwkit cannot reproduce Jw_cad's deflate bytes, so
the comparison is the text fields, the trailer names and order, the gzip header values and the inflated
content; deleting needs no new gzip and is compared byte for byte.
"""
import gzip
import hashlib
import struct
import unittest
import zlib
from pathlib import Path

from jwwkit import CadDocument
from jwwkit.reader.archive import read_records_bytes
from jwwkit.writer.images import check_new_image, embedded_name, gzip_member

from test_embedded_images import fixture, raw_image
from test_v600_schema700 import TempDirTestCase

SAVED = Path(__file__).resolve().parent / 'fixtures' / 'jwcad_saved'
TEXT_KEYS = ('start_x', 'start_y', 'size_x', 'size_y', 'spacing', 'angle', 'font_name', 'text_type', 'content', 'base')


def image_indices(document):
    return [i for i, e in enumerate(document.entities)
            if e.entity_type == 'TEXT' and e.geometry['content'].startswith('^@BM')]


def trailer_view(path):
    """(name, gzip header, sha256 of the inflated image) per embedded image, in trailer order."""
    data = Path(path).read_bytes()
    out = []
    for image in read_records_bytes(data)['images']:
        member = data[image['gzip_offset']:image['gzip_offset'] + image['compressed_size']]
        out.append((image['identifier'], member[:10], hashlib.sha256(gzip.decompress(member)).hexdigest()))
    return out


def image_texts(path):
    records = read_records_bytes(Path(path).read_bytes())['entities']
    return [{k: r[k] for k in TEXT_KEYS} for r in records if r['type'] == 'TEXT' and r['content'].startswith('^@BM')]


def png(color_type=2, bits=8, extra=b''):
    """A 1x1 PNG built here (no third-party data)."""
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    channels = {0: 1, 2: 3, 6: 4}[color_type]
    pixels = zlib.compress(b'\x00' + b'\x80' * channels)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, bits, color_type, 0, 0, 0))
            + chunk(b'IDAT', pixels) + chunk(b'IEND', b'') + extra)


def with_exif(jpeg, *, orientation=None, gps=False):
    """Insert an APP1 Exif block after SOI. GPS gets a pointer tag only (value 0, no real place)."""
    entries = []
    if orientation is not None:
        entries.append(struct.pack('<HHIHH', 0x0112, 3, 1, orientation, 0))
    if gps:
        entries.append(struct.pack('<HHII', 0x8825, 4, 1, 0))
    ifd = struct.pack('<H', len(entries)) + b''.join(entries) + struct.pack('<I', 0)
    tiff = b'II*\x00' + struct.pack('<I', 8) + ifd
    payload = b'Exif\x00\x00' + tiff
    return jpeg[:2] + b'\xff\xe1' + struct.pack('>H', len(payload) + 2) + payload + jpeg[2:]


class ImageEditingTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.bmp = self.write('irekae.bmp', raw_image('p3_irekae', 1))
        self.jpg = self.write('shashin.jpg', raw_image('p4_jpg_png', 0))
        self.png = self.write('zukei.png', raw_image('p4_jpg_png', 1))

    def saved(self, document, name):
        path = self.folder / name
        document.save(path)
        return path

    # --- Jw_cad samples ---
    def test_delete_image_matches_jwcad_byte_for_byte(self):
        document = CadDocument.open(fixture('a2'))
        document.delete_image(image_indices(document)[1])
        mine = self.saved(document, 'p2.jww').read_bytes()
        jwcad = fixture('p2_kesu').read_bytes()
        end = read_records_bytes(jwcad)['header_end']
        self.assertEqual(read_records_bytes(mine)['header_end'], end)
        self.assertEqual(mine[end:], jwcad[end:])

    def test_replace_image_matches_jwcad(self):
        document = CadDocument.open(fixture('a2'))
        document.replace_image(image_indices(document)[1], self.bmp)
        path = self.saved(document, 'p3.jww')
        self.assertEqual(trailer_view(path), trailer_view(fixture('p3_irekae')))
        self.assertEqual(image_texts(path), image_texts(fixture('p3_irekae')))
        source = fixture('a2').read_bytes()
        first = read_records_bytes(source)['images'][0]
        kept = source[first['gzip_offset']:first['gzip_offset'] + first['compressed_size']]
        self.assertIn(kept, path.read_bytes())

    def test_add_image_matches_jwcad(self):
        sample = CadDocument.open(fixture('p1_ireru'))
        index = image_indices(sample)[0]
        position = (sample.entities[index].geometry['start_x'], sample.entities[index].geometry['start_y'])
        sample.delete_image(index)
        empty = self.saved(sample, 'empty.jww')
        self.assertEqual(read_records_bytes(empty.read_bytes())['images'], [])
        document = CadDocument.open(empty)
        document.add_image(self.bmp, position, 100)
        path = self.saved(document, 'p1.jww')
        self.assertEqual(trailer_view(path), trailer_view(fixture('p1_ireru')))
        self.assertEqual(image_texts(path), image_texts(fixture('p1_ireru')))

    def test_jpeg_and_png_names_match_jwcad(self):
        document = CadDocument.open(fixture('a1'))
        document.delete_image(image_indices(document)[0])
        jwcad = image_texts(fixture('p4_jpg_png'))
        for path, text in zip((self.jpg, self.png), jwcad):
            document.add_image(path, (text['start_x'], text['start_y']), 100)
        path = self.saved(document, 'p4.jww')
        self.assertEqual(trailer_view(path), trailer_view(fixture('p4_jpg_png')))
        self.assertEqual(image_texts(path), jwcad)

    # --- trailer and text forms ---
    def test_added_image_text_gzip_and_kept_bytes(self):
        document = CadDocument.open(fixture('a1'))
        text = document.add_image(self.png, (10, 20), 150, angle=30, transparent_color=(0, 162, 232),
                                  layer_group=1, layer=2)
        self.assertEqual(text.geometry['content'], '^@BM%temp%zukei.png,150,72.093,0,0,1,30,0,162,232')
        self.assertEqual((text.attributes['layer_group'], text.attributes['layer'], text.attributes['flag']), (1, 2, 0))
        path = self.saved(document, 'added.jww')
        data = path.read_bytes()
        source = fixture('a1').read_bytes()
        parsed = read_records_bytes(data)
        self.assertEqual([i['identifier'] for i in parsed['images']], ['C__jwwkit_sample_bmp_a_bmp.bmp.gz', 'zukei.png.gz'])
        added = parsed['images'][1]
        self.assertEqual(data[added['gzip_offset']:added['gzip_offset'] + 10], bytes.fromhex('1f8b080000000000000a'))
        self.assertEqual(gzip.decompress(data[added['gzip_offset']:added['gzip_offset'] + added['compressed_size']]),
                         self.png.read_bytes())
        original = read_records_bytes(source)
        self.assertTrue(parsed['raw_trailer'].startswith(b'\x02\x00\x00\x00' + original['raw_trailer'][4:]))
        reopened = CadDocument.open(path)
        self.assertEqual([i['verified'] for i in reopened.embedded_images], [True, True])
        again = self.saved(reopened, 'again.jww')
        self.assertEqual(again.read_bytes(), data)

    def test_gzip_member_header(self):
        member = gzip_member(b'abc')
        self.assertEqual(member[:10], bytes.fromhex('1f8b080000000000000a'))
        self.assertEqual(gzip.decompress(member), b'abc')

    def test_japanese_names_match_jwcad(self):
        document = CadDocument.open(fixture('a1'))
        document.delete_image(image_indices(document)[0])
        jwcad = image_texts(fixture('p5b_nihongo'))
        photo = self.write('写真.jpg', self.jpg.read_bytes())
        picture = self.write('画像 1.bmp', self.bmp.read_bytes())
        for path, text in zip((photo, picture), jwcad):
            document.add_image(path, (text['start_x'], text['start_y']), 100)
        path = self.saved(document, 'p5b.jww')
        self.assertEqual(trailer_view(path), trailer_view(fixture('p5b_nihongo')))
        # In this sample Jw_cad wrote flag 2 on the BMP text (meaning unknown, see VERIFICATION.md 16);
        # jwwkit always writes 0, so the flag is left out of this comparison.
        self.assertEqual([t['base'].pop('flag') for t in jwcad], [0, 2])
        mine = image_texts(path)
        self.assertEqual([t['base'].pop('flag') for t in mine], [0, 0])
        self.assertEqual(mine, jwcad)
        jwcad_ends = [(r['end_x'], r['end_y']) for r in read_records_bytes(fixture('p5b_nihongo').read_bytes())['entities']
                      if r['type'] == 'TEXT' and r['content'].startswith('^@BM')]
        mine_ends = [(r['end_x'], r['end_y']) for r in read_records_bytes(path.read_bytes())['entities']
                     if r['type'] == 'TEXT' and r['content'].startswith('^@BM')]
        for mine, theirs in zip(mine_ends, jwcad_ends):
            self.assertAlmostEqual(mine[0], theirs[0], places=9)
            self.assertAlmostEqual(mine[1], theirs[1], places=9)

    def test_names(self):
        self.assertEqual(embedded_name('a-b_1.bmp'), 'a-b_1_bmp.bmp')
        self.assertEqual(embedded_name('x.jpg'), 'x.jpg')
        self.assertEqual(embedded_name('画像 1.bmp'), '画像 1_bmp.bmp')
        self.assertEqual(embedded_name('案内図（１）.png'), '案内図（１）.png')
        self.assertEqual(embedded_name('ｶﾀｶﾅ　写真。.jpg'), 'ｶﾀｶﾅ　写真。.jpg')
        for bad in ('a.b.png', 'a.jpeg', 'a.JPG', 'a.tiff', 'noextension', 'a\\b.bmp', 'a/b.bmp', 'a:b.bmp',
                    'a*b.png', 'a?b.png', 'a"b.png', 'a<b.png', 'a>b.png', 'a|b.png', 'a,b.png', 'a^b.png',
                    ' a.png', 'a .png', '　a.png', 'a　.png', '.png', 'a\tb.png', 'a\x7fb.png',
                    '\U0001F600.png', '☃.png'):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'name'):
                embedded_name(bad)
        with self.assertRaisesRegex(ValueError, 'CP932 cannot'):
            embedded_name('\U0001F600.png')
        document = CadDocument.open(fixture('a1'))
        spaced = self.write('a,b.png', self.png.read_bytes())
        with self.assertRaisesRegex(ValueError, 'name='):
            document.add_image(spaced, (0, 0), 100)
        text = document.add_image(spaced, (0, 0), 100, name='photo_1.png')
        self.assertTrue(text.geometry['content'].startswith('^@BM%temp%photo_1.png,'))

    def test_name_clash_ignores_case(self):
        document = CadDocument.open(fixture('a1'))
        document.add_image(self.png, (0, 0), 100, name='Zukei.png')
        with self.assertRaisesRegex(ValueError, 'give another name'):
            document.add_image(self.write('other.png', png(6)), (0, 0), 100, name='zukei.png')

    # --- sharing and name clashes ---
    def test_same_content_is_shared(self):
        document = CadDocument.open(fixture('a1'))
        copy = self.write('other_name.bmp', raw_image('a1'))
        text = document.add_image(copy, (0, 0), 100)
        self.assertIn('%temp%C__jwwkit_sample_bmp_a_bmp.bmp,', text.geometry['content'])
        document.add_image(self.png, (0, 0), 100)
        document.add_image(self.png, (50, 0), 100)
        path = self.saved(document, 'shared.jww')
        self.assertEqual([i[0] for i in trailer_view(path)], ['C__jwwkit_sample_bmp_a_bmp.bmp.gz', 'zukei.png.gz'])

    def test_same_name_other_content_is_refused(self):
        document = CadDocument.open(fixture('a1'))
        document.add_image(self.png, (0, 0), 100)
        other = self.folder / 'sub'
        other.mkdir()
        clash = other / 'zukei.png'
        clash.write_bytes(png(6))
        with self.assertRaisesRegex(ValueError, 'give another name'):
            document.add_image(clash, (0, 0), 100)
        document.add_image(clash, (0, 0), 100, name='zukei2.png')

    # --- image checks and warnings ---
    def test_unverified_shape_is_refused_with_hint(self):
        path = self.write('gray.png', png(0))
        with self.assertRaisesRegex(ValueError, '24-bit BMP'):
            CadDocument.open(fixture('a1')).add_image(path, (0, 0), 100)

    def test_notes_only_image_is_accepted_with_warning(self):
        jpeg = raw_image('a3') + b'extra'
        review = check_new_image(jpeg, 'x.jpg')
        self.assertEqual(review['trailing_bytes'], 5)
        self.assertTrue(any('after the JPEG' in w for w in review['warnings']))
        path = self.write('x.jpg', jpeg)
        document = CadDocument.open(fixture('a1'))
        document.add_image(path, (0, 0), 100)
        saved = self.saved(document, 'notes.jww')
        self.assertEqual(CadDocument.open(saved).embedded_images[1]['trailing_bytes'], 5)

    def test_exif_orientation_and_location_warnings(self):
        plain = check_new_image(raw_image('a3'), 'x.jpg')
        self.assertEqual(plain['warnings'], [])
        self.assertFalse(plain['exif_location'])
        tagged = check_new_image(with_exif(raw_image('a3'), orientation=6, gps=True), 'x.jpg')
        self.assertTrue(tagged['exif_orientation_not_1'] and tagged['exif_location'])
        self.assertTrue(any('orientation' in w for w in tagged['warnings']))
        self.assertTrue(any('location information' in w for w in tagged['warnings']))
        upright = check_new_image(with_exif(raw_image('a3'), orientation=1), 'x.jpg')
        self.assertEqual(upright['warnings'], [])
        broken = check_new_image(raw_image('a3')[:2] + b'\xff\xe1\x00\x10Exif\x00\x00XX\x00\x00\x00\x00\x00\x00'
                                 + raw_image('a3')[2:], 'x.jpg')
        self.assertTrue(any('could not be read' in w for w in broken['warnings']))

    # --- delete semantics ---
    def test_delete_entity_keeps_the_image(self):
        document = CadDocument.open(fixture('a2'))
        document.delete_entity(image_indices(document)[1])
        path = self.saved(document, 'kept.jww')
        self.assertEqual(len(trailer_view(path)), 2)

    def test_shared_image_is_dropped_only_when_no_text_points_to_it(self):
        for order in ('image_first', 'entity_first'):
            with self.subTest(order=order):
                document = CadDocument.open(fixture('a7'))
                first, second = image_indices(document)
                if order == 'image_first':
                    document.delete_image(first)
                    self.assertEqual(len(trailer_view(self.saved(document, f'{order}_1.jww'))), 1)
                    document.delete_entity(image_indices(document)[0])
                else:
                    document.delete_entity(first)
                    document.delete_image(image_indices(document)[0])
                self.assertEqual(trailer_view(self.saved(document, f'{order}_2.jww')), [])

    def test_image_in_block_definition_keeps_the_image(self):
        document = CadDocument.open(fixture('a9'))
        self.assertEqual(image_indices(document), [])
        with self.assertRaisesRegex(ValueError, 'not an image text'):
            document.delete_image(0)

    def test_delete_image_refuses_other_elements(self):
        document = CadDocument.open(fixture('a1'))
        other = next(i for i, e in enumerate(document.entities) if e.entity_type != 'TEXT')
        with self.assertRaisesRegex(ValueError, 'not an image text'):
            document.delete_image(other)

    # --- the older 6-field image texts (real drawings; no transparent colour) ---
    def legacy_drawing(self):
        """a2 with both image texts rewritten in the 6-field form seen in real drawings."""
        document = CadDocument.open(fixture('a2'))
        for index in image_indices(document):
            content = document.entities[index].geometry['content']
            document.set_text(index, content.rsplit(',', 3)[0])
        path = self.saved(document, 'legacy.jww')
        self.assertTrue(all(t['content'].endswith(',100,48.062,0,0,1,0') for t in image_texts(path)))
        return path

    def test_delete_image_accepts_the_6_field_form(self):
        document = CadDocument.open(self.legacy_drawing())
        document.delete_image(image_indices(document)[1])
        path = self.saved(document, 'legacy_deleted.jww')
        self.assertEqual([i[0] for i in trailer_view(path)], ['C__jwwkit_sample_bmp_a_bmp.bmp.gz'])
        self.assertTrue(image_texts(path)[0]['content'].endswith(',100,48.062,0,0,1,0'))

    def test_add_and_replace_refuse_drawings_with_the_6_field_form(self):
        document = CadDocument.open(self.legacy_drawing())
        before = document.entities
        with self.assertRaisesRegex(ValueError, 'without the transparent-colour fields'):
            document.add_image(self.png, (0, 0), 100)
        with self.assertRaisesRegex(ValueError, '透過色の欄がない形'):
            document.replace_image(image_indices(document)[1], self.bmp)
        self.assertEqual(document.entities, before)
        self.assertEqual(document._image_edits, {})
        # One 6-field text is enough, also after the other image text was deleted.
        document = CadDocument.open(fixture('a2'))
        first, second = image_indices(document)
        document.set_text(first, document.entities[first].geometry['content'].rsplit(',', 3)[0])
        document.delete_image(second)
        with self.assertRaisesRegex(ValueError, 'without the transparent-colour fields'):
            document.add_image(self.png, (0, 0), 100)

    def test_plan_refuses_add_image_on_the_6_field_form(self):
        from jwwkit.safe_edit import write_plan
        source = self.legacy_drawing()
        document = CadDocument.open(source)
        with self.assertRaisesRegex(ValueError, 'without the transparent-colour fields'):
            write_plan(document, [], [dict(op='add_image', kwargs=dict(path=str(self.png), position=[0, 0], width=50))],
                       self.folder / 'out.jww', self.folder / 'plan.json')
        self.assertFalse((self.folder / 'plan.json').exists())

    def test_other_field_counts_are_refused(self):
        document = CadDocument.open(fixture('a1'))
        index = image_indices(document)[0]
        document.set_text(index, '^@BM%temp%C__jwwkit_sample_bmp_a_bmp.bmp,100,48.062,0,0')
        with self.assertRaisesRegex(ValueError, 'unobserved field count'):
            document.delete_image(index)

    # --- refusals ---
    def test_replace_refuses_trimmed_and_flagged_images(self):
        document = CadDocument.open(fixture('a8'))
        with self.assertRaisesRegex(ValueError, 'flag 2'):
            document.replace_image(image_indices(document)[0], self.bmp)
        document = CadDocument.open(fixture('a1'))
        index = image_indices(document)[0]
        document.set_text(index, '^@BM%temp%C__jwwkit_sample_bmp_a_bmp.bmp,84.1815,32.7898,0.102779,0.0752415,'
                                 '0.841815,0,255,255,255')
        with self.assertRaisesRegex(ValueError, 'trimmed'):
            document.replace_image(index, self.bmp)

    def test_refuses_other_versions(self):
        for name in ('jwcad10036_save_v600.jww', 'jwcad10036_save_v420.jww'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                CadDocument.open(SAVED / name).add_image(self.bmp, (0, 0), 100)

    def test_bad_arguments_change_nothing(self):
        document = CadDocument.open(fixture('a1'))
        before = document.entities
        for kwargs in (dict(width=0), dict(width=float('nan')), dict(width=1e30), dict(width=100, angle=360),
                       dict(width=100, transparent_color=(0, 0, 256)), dict(width=100, layer=16)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                document.add_image(self.bmp, (0, 0), **kwargs)
        self.assertEqual(document.entities, before)
        self.assertEqual(document._image_edits, {})

    def test_import_group_is_refused_after_image_edits(self):
        document = CadDocument.open(fixture('a1'))
        document.add_image(self.png, (0, 0), 100)
        with self.assertRaisesRegex(ValueError, 'import_group'):
            document.import_group(fixture('a1'), 0, 1)

    # --- plan, approval and execution ---
    def test_plan_reviews_and_executes_image_actions(self):
        from jwwkit.safe_edit import execute_plan, write_plan
        source = self.write('source.jww', fixture('a2').read_bytes())
        document = CadDocument.open(source)
        first, second = image_indices(document)
        actions = [dict(op='replace_image', indices=[second], kwargs=dict(path=str(self.bmp))),
                   dict(op='add_image', kwargs=dict(path=str(self.png), position=[0, 0], width=50), **{'as': 'new'})]
        receipt = write_plan(document, [second], actions, self.folder / 'out.jww', self.folder / 'plan.json')
        self.assertEqual(document._image_edits, {})
        self.assertEqual(len(document.entities), len(CadDocument.open(source).entities))
        rows = receipt['plan']['resource_targets']
        self.assertEqual([r['kind'] for r in rows], ['replace_image', 'add_image'])
        self.assertEqual(rows[0]['image']['name'], 'irekae_bmp.bmp')
        self.assertEqual(rows[1]['image']['exif_location'], False)
        self.assertEqual(sorted(d['path'] for d in receipt['plan']['dependencies']),
                         sorted(str(p.resolve()) for p in (self.bmp, self.png)))
        report = execute_plan(receipt['path'], approved_sha256=receipt['sha256'])
        self.assertEqual([i['identifier'] for i in report['embedded_images_after']],
                         ['C__jwwkit_sample_bmp_a_bmp.bmp.gz', 'irekae_bmp.bmp.gz', 'zukei.png.gz'])
        self.assertEqual(report['deleted_count'], 1)
        self.assertEqual(report['added_count'], 2)

    def test_plan_refuses_a_changed_image_file(self):
        from jwwkit.safe_edit import execute_plan, write_plan
        source = self.write('source.jww', fixture('a1').read_bytes())
        document = CadDocument.open(source)
        receipt = write_plan(document, [], [dict(op='add_image', kwargs=dict(path=str(self.png), position=[0, 0], width=50))],
                             self.folder / 'out.jww', self.folder / 'plan.json')
        self.png.write_bytes(png(6))
        with self.assertRaisesRegex(ValueError, 'changed'):
            execute_plan(receipt['path'], approved_sha256=receipt['sha256'])
        self.assertFalse((self.folder / 'out.jww').exists())

    def test_embedded_images_shows_the_opened_drawing(self):
        document = CadDocument.open(fixture('a1'))
        before = document.embedded_images
        document.add_image(self.png, (0, 0), 100)
        self.assertEqual(document.embedded_images, before)

    def test_saves_without_image_edits_keep_the_trailer(self):
        document = CadDocument.open(fixture('a2'))
        document.add_line((0, 0), (1, 1))
        path = self.saved(document, 'line.jww')
        self.assertEqual(read_records_bytes(path.read_bytes())['raw_trailer'],
                         read_records_bytes(fixture('a2').read_bytes())['raw_trailer'])


if __name__ == '__main__':
    unittest.main()
