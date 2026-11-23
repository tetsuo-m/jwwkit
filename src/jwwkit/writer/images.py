"""v700の同梱画像を入れる・外すための部品（#57）。

What Jw_cad 10.03.6 writes was read from samples made with the "相対パス" (relative path) option, the
image file in the drawing's folder (VERIFICATION.md section 16):

- trailer: DWORD count, then per image a Unicode CString name, a DWORD size and one gzip member holding
  the original image file unchanged. Order: the order the images were inserted; a replaced image goes last.
- name: BMP ``<stem>_bmp.bmp``, others ``<stem>.<ext>`` (seen: jpg, png, gif, tif), plus ``.gz``.
- gzip header: mtime 0, XFL 0, OS 10, no file name. Jw_cad's deflate body could not be reproduced with
  zlib, so jwwkit writes its own (zlib level 9); the inflated content is what is compared.
- image text: ``^@BM%temp%<name>,width,height,0,0,1,angle,R,G,B`` (numbers like C ``%g``), at the lower
  left of the image, text angle = image angle, MS Gothic 2.0 x 2.0, pen style 1, color 1, flag 0.

Anything not seen in those samples (other name characters, other extensions, trimming, flag 2) is refused.
"""
import hashlib
import math
import re
import struct
import zlib

from jwwkit.reader.images import (MAX_IMAGE_BYTES, MAX_IMAGE_COUNT, MAX_TOTAL_IMAGE_BYTES, VERIFIED_SHAPES,
                                  check_image_content)

IMAGE_PREFIX = '^@BM%temp%'
# Extensions seen in Jw_cad output names (#19, #57). .jpeg/.jpe/.tiff and upper case were not seen.
NAME_EXTENSIONS = {'bmp', 'jpg', 'png', 'gif', 'tif'}
STEM = re.compile(r'[A-Za-z0-9_-]+\Z')
GZIP_HEADER = b'\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x0a'
TEXT_SIZE = 2.0
TEXT_FONT = 'ＭＳ ゴシック'
UNVERIFIED_SHAPE_HINT = (' Re-save the image as a 24-bit BMP or a plain (baseline) JPEG and it can be inserted.')
NAME_HINT = (' Only half-width letters, digits, "-" and "_" with the extension .bmp, .jpg, .png, .gif or .tif '
             '(lower case) are accepted; pass another name with name=...')


def embedded_name(file_name):
    """Jw_cad's relative-path name for an image in the drawing's folder, without ``.gz``."""
    if not isinstance(file_name, str) or '.' not in file_name:
        raise ValueError('Image name needs an extension.' + NAME_HINT)
    stem, extension = file_name.rsplit('.', 1)
    if extension not in NAME_EXTENSIONS or not STEM.match(stem):
        raise ValueError(f'Image name {file_name!r} is not in a form seen in Jw_cad output.' + NAME_HINT)
    name = f'{stem}_bmp.bmp' if extension == 'bmp' else f'{stem}.{extension}'
    if len(name) + 3 >= 255:
        raise ValueError('Image name is too long.' + NAME_HINT)
    return name


def number(value, what):
    """Format a field like Jw_cad (C %g: 6 significant digits). Exponent forms were not seen: refused."""
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'Image {what} must be a finite number')
    text = '%g' % value
    if 'e' in text or 'inf' in text or 'nan' in text:
        raise ValueError(f'Image {what} {value!r} is outside the range Jw_cad writes as a plain number')
    return '0' if text == '-0' else text


def image_text(name, width, height, angle, color):
    return (f'{IMAGE_PREFIX}{name},{number(width, "width")},{number(height, "height")},0,0,1,'
            f'{number(angle, "angle")},{color[0]},{color[1]},{color[2]}')


def parse_image_text(content):
    """Split ``^@BM%temp%name,w,h,a,b,c,angle,R,G,B`` (the embedded form). Return None for other texts."""
    if content[:len(IMAGE_PREFIX)].lower() != IMAGE_PREFIX.lower():
        return None
    parts = content[len(IMAGE_PREFIX):].rsplit(',', 9)
    if len(parts) != 10:
        raise ValueError('Image text has an unobserved field count')
    try:
        values = [float(x) for x in parts[1:7]] + [int(x) for x in parts[7:]]
    except ValueError as exc:
        raise ValueError('Image text has an unobserved field value') from exc
    return dict(name=parts[0], width=values[0], height=values[1], trimming=tuple(values[2:5]),
                angle=values[5], color=tuple(values[6:9]))


def gzip_member(raw):
    """One gzip member with Jw_cad's header values; the deflate body is zlib's, not Jw_cad's."""
    deflater = zlib.compressobj(9, zlib.DEFLATED, -15)
    body = deflater.compress(raw) + deflater.flush()
    return GZIP_HEADER + body + struct.pack('<II', zlib.crc32(raw) & 0xffffffff, len(raw) & 0xffffffff)


def cstring(name):
    """MFC Unicode CString as Jw_cad writes trailer names (FF FE FF, length, UTF-16LE)."""
    encoded = name.encode('utf-16le')
    return b'\xff\xfe\xff' + bytes([len(name)]) + encoded


def check_new_image(raw, file_name):
    """Check an image to insert. Returns a dict for the plan review (no EXIF values)."""
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(f'Image is larger than {MAX_IMAGE_BYTES} bytes')
    name = embedded_name(file_name)
    extension = name.rsplit('.', 1)[1]
    kind, shape, notes = check_image_content(raw, extension)
    if shape['key'] not in VERIFIED_SHAPES[kind]:
        raise ValueError(f'Embedded image unverified: this {kind} form ({shape["key"]}) has not been seen in '
                         'Jw_cad output.' + UNVERIFIED_SHAPE_HINT)
    exif = exif_flags(raw, kind)
    warnings = list(notes)
    if exif['status'] == 'unreadable':
        warnings.append('The EXIF data could not be read, so the orientation and location could not be checked.')
    if exif['orientation'] not in (None, 1):
        warnings.append('Jw_cad does not use the EXIF orientation, so this image will look rotated or mirrored.')
    if exif['gps']:
        warnings.append('This image contains location information (EXIF GPS). jwwkit inserts the image bytes '
                        'unchanged, so the location goes into the drawing too; take care whom you give it to.')
    return dict(name=name, identifier=name + '.gz', format=kind, width=shape['width'], height=shape['height'],
                raw_size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), trailing_bytes=shape.get('trailing', 0),
                notes=list(notes), exif_orientation_not_1=exif['orientation'] not in (None, 1),
                exif_location=exif['gps'], exif_status=exif['status'], warnings=warnings)


def _ifd0_flags(tiff):
    """Orientation value and GPS-pointer presence from IFD0 of a TIFF structure. GPS values are not read."""
    if tiff[:2] not in (b'II', b'MM'):
        raise ValueError('not TIFF')
    endian = '<' if tiff[:2] == b'II' else '>'
    offset, = struct.unpack_from(endian + 'I', tiff, 4)
    count, = struct.unpack_from(endian + 'H', tiff, offset)
    orientation, gps = None, False
    for i in range(count):
        entry = offset + 2 + 12 * i
        tag, kind, items = struct.unpack_from(endian + 'HHI', tiff, entry)
        if tag == 0x0112 and kind == 3 and items == 1:
            orientation, = struct.unpack_from(endian + 'H', tiff, entry + 8)
        elif tag == 0x8825:
            gps = True
    return orientation, gps


def exif_flags(raw, kind):
    """EXIF orientation and whether a GPS block exists (JPEG APP1, PNG eXIf, TIFF IFD0). No other EXIF data."""
    try:
        tiff = None
        if kind == 'JPEG':
            pos = 2
            while pos + 4 <= len(raw) and raw[pos] == 0xFF:
                marker = raw[pos + 1]
                if marker in (0xD9, 0xDA):
                    break
                length, = struct.unpack_from('>H', raw, pos + 2)
                segment = raw[pos + 4:pos + 2 + length]
                if marker == 0xE1 and segment[:6] == b'Exif\0\0':
                    tiff = segment[6:]
                    break
                pos += 2 + length
        elif kind == 'PNG':
            pos = 8
            while pos + 8 <= len(raw):
                length, chunk = struct.unpack_from('>I4s', raw, pos)
                if chunk == b'eXIf':
                    tiff = raw[pos + 8:pos + 8 + length]
                    break
                if chunk == b'IEND':
                    break
                pos += 12 + length
        elif kind == 'TIFF':
            tiff = raw
        if tiff is None:
            return dict(orientation=None, gps=False, status='none')
        orientation, gps = _ifd0_flags(tiff)
        return dict(orientation=orientation, gps=gps, status='ok')
    except (struct.error, ValueError, IndexError):
        return dict(orientation=None, gps=False, status='unreadable')


def compose_trailer(source_bytes, source_records, keep, added):
    """Kept source images byte for byte in their order, then the added ones; return the trailer bytes."""
    images = source_records['images']
    start = source_records['tail_offset'] + 4
    parts = []
    for image in images:
        end = image['gzip_offset'] + image['compressed_size']
        if image['identifier'] in keep:
            parts.append(source_bytes[start:end])
        start = end
    for item in added:
        member = gzip_member(item['raw'])
        parts.append(cstring(item['identifier']) + struct.pack('<I', len(member)) + member)
    count = len(parts)
    if count > MAX_IMAGE_COUNT:
        raise ValueError(f'More than {MAX_IMAGE_COUNT} embedded images')
    total = sum(i['raw_size'] for i in images if i['identifier'] in keep) + sum(len(i['raw']) for i in added)
    if total > MAX_TOTAL_IMAGE_BYTES:
        raise ValueError(f'Embedded images exceed {MAX_TOTAL_IMAGE_BYTES} bytes in one drawing')
    return struct.pack('<I', count) + b''.join(parts)
