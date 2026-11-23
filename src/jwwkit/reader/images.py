"""v700の同梱画像の区間を検証する（保持専用。追加・変更・再圧縮はしない）。

The container (count, name, size field, exactly one gzip member, no leftovers) is checked strictly.
Jw_cad 10.03.6 embeds the original image file unchanged (#19), so the inner file is checked against
its format's published specification (BMP: Microsoft bitmap structures; JPEG: ITU-T T.81; PNG: W3C
PNG specification; GIF: GIF89a specification; TIFF: TIFF 6.0). Pixels are never decoded; only
structure is walked. ``verified`` marks shapes seen in Jw_cad output (samples or real drawings).

An image is rejected only when its format cannot be read from start to end. Bytes after the end of the
format (JPEG EOI, PNG IEND, GIF trailer, BMP pixel data) are common in real files (for example the extra
images of a JPEG MPF file), so they are accepted: the count goes to ``trailing_bytes`` and a short reason
to ``notes``. So do a BMP file size field that differs from the file, a BMP run-length image size field
that differs from the data, and a TIFF directory at an odd offset. An image with notes is not verified.
"""
import hashlib
import struct
import zlib

MAX_IMAGE_BYTES = 128_000_000      # inflated size of one image
MAX_TOTAL_IMAGE_BYTES = 512_000_000  # inflated size of all images in one drawing
MAX_IMAGE_COUNT = 256
INVALID = 'Invalid embedded image: '
UNVERIFIED = 'Embedded image unverified: '
UNVERIFIED_HINT = ' (a Jw_cad sample of this kind would let jwwkit support it; please report it in an Issue)'
EXTENSIONS = {'bmp': 'BMP', 'jpg': 'JPEG', 'jpeg': 'JPEG', 'jpe': 'JPEG', 'png': 'PNG', 'gif': 'GIF',
              'tif': 'TIFF', 'tiff': 'TIFF'}
# Shapes seen in Jw_cad 10.03.6 output (#19 samples) or real drawings.
VERIFIED_SHAPES = {
    'BMP': {(40, 1, 0, False), (40, 4, 0, False), (40, 8, 0, False), (40, 16, 0, False), (40, 24, 0, False),
            (40, 24, 0, True), (40, 32, 0, False), (40, 8, 1, False), (40, 4, 2, False), (108, 24, 0, False),
            (124, 24, 0, False)},
    'JPEG': {('SOF0', 8, 1), ('SOF0', 8, 3), ('SOF0', 8, 4), ('SOF2', 8, 3)},
    'PNG': {(2, 8), (3, 8), (6, 8)},
    'GIF': {('GIF87a', 1), ('GIF89a', 1)},
    'TIFF': {('II', 1, 3), ('II', 5, 4)},
}


def invalid(reason):
    return ValueError(INVALID + reason)


def unverified(reason):
    return ValueError(UNVERIFIED + reason + UNVERIFIED_HINT)


def read_image_trailer(cursor):
    """DWORD個数・CString名前・DWORD圧縮長・gzip（元の画像ファイル）を読む。"""
    count, = cursor.unpack('<I')
    if count > MAX_IMAGE_COUNT:
        raise invalid(f'image count {count} exceeds the limit {MAX_IMAGE_COUNT}')
    if count > (len(cursor.data) - cursor.pos) // 25:
        raise invalid('image count exceeds the remaining bytes')
    images, total = [], 0
    for index in range(count):
        cursor.context = f'trailer.images[{index}]'
        identifier = cursor.string()
        size_offset = cursor.pos
        compressed_size, = cursor.unpack('<I')
        gzip_offset = cursor.pos
        compressed = cursor.take(compressed_size)
        lower = identifier.lower()
        if not lower.endswith('.gz'):
            raise unverified('an image stored without gzip compression')
        extension = lower[:-3].rsplit('.', 1)[-1] if '.' in lower[:-3] else ''
        if not compressed.startswith(b'\x1f\x8b\x08'):
            raise invalid('the data is not a gzip stream')
        limit = min(MAX_IMAGE_BYTES, MAX_TOTAL_IMAGE_BYTES - total)
        inflater = zlib.decompressobj(31)
        try:
            raw = inflater.decompress(compressed, limit + 1)
        except zlib.error as exc:
            raise invalid('broken gzip stream') from exc
        if len(raw) > limit or inflater.unconsumed_tail:
            raise invalid('inflated size exceeds the limit '
                          f'({MAX_IMAGE_BYTES} bytes per image, {MAX_TOTAL_IMAGE_BYTES} bytes per drawing)')
        if not inflater.eof:
            raise invalid('gzip stream is truncated')
        if inflater.unused_data:
            raise invalid('data after the gzip stream (more than one member or leftover bytes)')
        if struct.unpack_from('<I', compressed, len(compressed) - 4)[0] != len(raw) & 0xffffffff:
            raise invalid('gzip size field does not match the inflated size')
        total += len(raw)
        kind, shape, notes = check_image_content(raw, extension)
        images.append(dict(identifier=identifier, size_offset=size_offset, gzip_offset=gzip_offset,
                           compressed_size=compressed_size, format=kind, width=shape['width'],
                           height=shape['height'], bits=shape.get('bits'), raw_size=len(raw),
                           sha256=hashlib.sha256(raw).hexdigest(), shape=shape['key'],
                           trailing_bytes=shape.get('trailing', 0), notes=tuple(notes),
                           verified=shape['key'] in VERIFIED_SHAPES[kind] and not notes))
    return images


def check_image_content(raw, extension):
    """Check one image file against its name extension and its format; return (format, shape, notes).

    Shared by the trailer reader and by add_image (#57), so both refuse and note exactly the same things.
    """
    kind = detect_format(raw)
    if kind is None:
        raise unverified('an image format other than BMP, JPEG, PNG, GIF and TIFF')
    if extension not in EXTENSIONS:
        raise unverified(f'the image name extension .{extension}' if extension else 'an image name without an extension')
    if EXTENSIONS[extension] != kind:
        raise invalid(f'the name extension .{extension} does not match the {kind} content')
    try:
        notes = []
        shape = CHECKS[kind](raw, notes)
    except (IndexError, KeyError, struct.error) as exc:
        raise invalid(f'{kind} structure is inconsistent') from exc
    return kind, shape, notes


def detect_format(raw):
    if raw[:2] == b'BM':
        return 'BMP'
    if raw[:3] == b'\xff\xd8\xff':
        return 'JPEG'
    if raw[:8] == b'\x89PNG\r\n\x1a\n':
        return 'PNG'
    if raw[:6] in (b'GIF87a', b'GIF89a'):
        return 'GIF'
    if raw[:4] in (b'II*\x00', b'MM\x00*'):
        return 'TIFF'
    return None


def _need(data, end, what):
    if end > len(data):
        raise invalid(f'{what} is truncated')


def _trailing(data, end, what, notes, shape):
    """Bytes after the end of the format: accepted, counted and noted."""
    extra = len(data) - end
    if extra:
        notes.append(f'{extra} bytes after the {what}')
    shape['trailing'] = extra
    return shape


# --- BMP (Microsoft bitmap file and header structures) ---
def check_bmp(b, notes):
    _need(b, 18, 'BMP header')
    file_size, reserved1, reserved2, offset = struct.unpack_from('<IHHI', b, 2)
    dib, = struct.unpack_from('<I', b, 14)
    if file_size != len(b):
        notes.append(f'BMP file size field is {file_size}, the file has {len(b)} bytes')
    if reserved1 or reserved2:
        raise invalid('BMP reserved fields are not zero')
    if dib not in (12, 40, 52, 56, 64, 108, 124):
        raise invalid(f'BMP header size {dib} is not defined')
    _need(b, 14 + dib, 'BMP header')
    if dib == 12:
        width, height, planes, bits = struct.unpack_from('<HHHH', b, 18)
        compression, image_size, used, entry = 0, 0, 0, 3
    else:
        width, height, planes, bits, compression, image_size = struct.unpack_from('<iiHHII', b, 18)
        used = struct.unpack_from('<I', b, 46)[0] if dib >= 40 else 0
        entry = 4
    top_down = height < 0
    rows = abs(height)
    if planes != 1:
        raise invalid('BMP plane count is not 1')
    if width <= 0 or rows == 0:
        raise invalid('BMP width or height is not positive')
    if bits not in (1, 4, 8, 16, 24, 32):
        raise invalid(f'BMP bit count {bits} is not defined')
    allowed = {0: (1, 4, 8, 16, 24, 32), 1: (8,), 2: (4,), 3: (16, 32)}
    if compression in (4, 5, 6):
        raise unverified('a BMP with JPEG, PNG or alpha-bitfield compression')
    if compression not in allowed or bits not in allowed[compression] or (dib == 64 and compression == 3):
        raise invalid(f'BMP compression {compression} with {bits} bits is not defined')
    if top_down and compression in (1, 2):
        raise invalid('a run-length BMP cannot be stored top-down')
    masks = 12 if compression == 3 and dib == 40 else 0
    if bits <= 8:
        colors = used or (1 << bits)
        if colors > (1 << bits):
            raise invalid('BMP color count exceeds the bit count')
    else:
        colors = used
    table_end = 14 + dib + masks + colors * entry
    if offset < table_end:
        raise invalid('BMP pixel offset overlaps the header or color table')
    end, profile_end = len(b), None
    if dib == 124:  # an embedded color profile may follow the pixels
        profile_offset, profile_size = struct.unpack_from('<II', b, 14 + 112)
        if profile_size:
            if struct.unpack_from('<I', b, 14 + 56)[0] not in (0x4D424544, 0x4C494E4B):  # 'MBED', 'LINK'
                raise invalid('BMP profile fields are set for a color space without a profile')
            start = 14 + profile_offset
            if start < offset:
                raise invalid('BMP color profile data overlaps the pixel offset')
            _need(b, start + profile_size, 'BMP color profile data')
            end, profile_end = start, start + profile_size
    if compression in (1, 2):
        stop = _walk_rle(b, offset, end, width, rows, compression == 1)
        if image_size and stop - offset != image_size:
            notes.append(f'BMP image size field is {image_size}, the run-length data has {stop - offset} bytes')
    else:
        stride = ((width * bits + 31) // 32) * 4
        stop = offset + stride * rows
        if stop > end:
            raise invalid('BMP pixel data is truncated' if profile_end is None
                          else 'BMP pixel data overlaps the color profile')
    shape = dict(width=width, height=rows, bits=bits, key=(dib, bits, compression, top_down))
    if profile_end is None:
        return _trailing(b, stop, 'BMP pixel data', notes, shape)
    if stop != end:
        notes.append(f'{end - stop} bytes between the BMP pixel data and the color profile')
    return _trailing(b, profile_end, 'BMP color profile', notes, shape)


def _walk_rle(b, pos, end, width, height, eight):
    """Walk RLE8/RLE4 commands to the end-of-bitmap marker; never leave the image or the data."""
    x = y = 0
    while True:
        if pos + 2 > end:
            raise invalid('BMP run-length data is truncated')
        first, second = b[pos], b[pos + 1]
        pos += 2
        if first or second not in (0, 1):
            if y >= height:
                raise invalid('BMP run-length data exceeds the image')
        if first:
            x += first
        elif second == 0:
            x, y = 0, y + 1
            continue
        elif second == 1:
            return pos
        elif second == 2:
            if pos + 2 > end:
                raise invalid('BMP run-length data is truncated')
            x, y = x + b[pos], y + b[pos + 1]
            pos += 2
            if y > height or (y == height and x):
                raise invalid('BMP run-length delta exceeds the image')
        else:
            x += second
            length = second if eight else (second + 1) // 2
            pos += length + (length & 1)
            if pos > end:
                raise invalid('BMP run-length data is truncated')
        if x > width:
            raise invalid('BMP run-length data exceeds the row')


# --- JPEG (ITU-T T.81) ---
SOF_NAMES = {0xc0: 'SOF0', 0xc1: 'SOF1', 0xc2: 'SOF2', 0xc3: 'SOF3', 0xc5: 'SOF5', 0xc6: 'SOF6', 0xc7: 'SOF7',
             0xc9: 'SOF9', 0xca: 'SOF10', 0xcb: 'SOF11', 0xcd: 'SOF13', 0xce: 'SOF14', 0xcf: 'SOF15'}


def check_jpeg(b, notes):
    pos, frame, scans, n = 2, None, 0, len(b)
    while True:
        _need(b, pos + 2, 'JPEG marker')
        if b[pos] != 0xff:
            raise invalid('JPEG marker expected')
        while b[pos + 1] == 0xff:  # fill bytes
            pos += 1
            _need(b, pos + 2, 'JPEG marker')
        marker = b[pos + 1]
        pos += 2
        if marker == 0xd9:
            if frame is None or not scans:
                raise invalid('JPEG ends without a frame and a scan')
            shape = dict(width=frame[1], height=frame[2], bits=frame[0], key=(frame[3], frame[0], frame[4]))
            if b[pos:pos + 3] == b'\xff\xd8\xff':
                notes.append('another JPEG follows the end marker (as in a multi-picture file)')
            return _trailing(b, pos, 'JPEG end marker', notes, shape)
        if marker in (0x01,) or 0xd0 <= marker <= 0xd7:
            continue  # TEM; RSTn outside a scan carry no data
        if marker < 0xc0 or marker == 0xd8:
            raise invalid(f'JPEG marker 0x{marker:02X} is not allowed here')
        _need(b, pos + 2, 'JPEG segment length')
        length, = struct.unpack_from('>H', b, pos)
        if length < 2:
            raise invalid('JPEG segment length is too short')
        _need(b, pos + length, 'JPEG segment')
        if marker in SOF_NAMES:
            if length < 8:
                raise invalid('JPEG frame header is too short')
            precision, height, width, components = struct.unpack_from('>BHHB', b, pos + 2)
            if length != 8 + 3 * components or components == 0 or width == 0:
                raise invalid('JPEG frame header fields do not match')
            if frame is None:
                frame = (precision, width, height, SOF_NAMES[marker], components)
        pos += length
        if marker == 0xda:  # entropy-coded data until the next marker other than RSTn / stuffing
            if frame is None:
                raise invalid('JPEG scan before the frame header')
            scans += 1
            while True:
                index = b.find(b'\xff', pos)
                if index < 0 or index + 1 >= n:
                    raise invalid('JPEG scan data is truncated')
                following = b[index + 1]
                if following == 0x00 or 0xd0 <= following <= 0xd7:
                    pos = index + 2
                    continue
                if following == 0xff:
                    pos = index + 1
                    continue
                pos = index
                break


# --- PNG (W3C Portable Network Graphics specification) ---
PNG_DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}


def check_png(b, notes):
    pos, chunks, header, seen_idat, idat_done, palette = 8, 0, None, False, False, False
    while True:
        _need(b, pos + 12, 'PNG chunk')
        length, kind = struct.unpack_from('>I4s', b, pos)
        if length > 0x7fffffff:
            raise invalid('PNG chunk length is too large')
        _need(b, pos + 12 + length, 'PNG chunk')
        data = b[pos + 8:pos + 8 + length]
        crc, = struct.unpack_from('>I', b, pos + 8 + length)
        if zlib.crc32(kind + data) != crc:
            raise invalid('PNG chunk CRC mismatch')
        if not all(65 <= c <= 90 or 97 <= c <= 122 for c in kind):
            raise invalid('PNG chunk type is not four letters')
        name = kind.decode('ascii')
        if chunks == 0 and name != 'IHDR':
            raise invalid('PNG does not start with IHDR')
        if name == 'IHDR':
            if chunks or length != 13:
                raise invalid('PNG IHDR is misplaced or has the wrong length')
            header = struct.unpack('>IIBBBBB', data)
            width, height, depth, color, compression, filtering, interlace = header
            if not width or not height or color not in PNG_DEPTHS or depth not in PNG_DEPTHS[color]:
                raise invalid('PNG image header values are not defined')
            if compression or filtering or interlace not in (0, 1):
                raise invalid('PNG compression, filter or interlace method is not defined')
        elif name == 'PLTE':
            if header[3] in (0, 4) or length % 3 or not length or seen_idat:
                raise invalid('PNG palette is not allowed here')
            palette = True
        elif name == 'IDAT':
            if idat_done:
                raise invalid('PNG image data chunks are not consecutive')
            seen_idat = True
        elif name == 'IEND':
            if length or not seen_idat:
                raise invalid('PNG IEND is misplaced')
            if header[3] == 3 and not palette:
                raise invalid('PNG palette image without a palette')
            shape = dict(width=header[0], height=header[1], bits=header[2], key=(header[3], header[2]))
            return _trailing(b, pos + 12, 'PNG IEND chunk', notes, shape)
        elif kind[0] < 97:  # an unknown critical chunk (upper-case first letter)
            raise invalid(f'unknown critical PNG chunk {name}')
        if seen_idat and name != 'IDAT':
            idat_done = True
        chunks += 1
        pos += 12 + length


# --- GIF (GIF89a specification; GIF87a is its subset) ---
def check_gif(b, notes):
    _need(b, 13, 'GIF screen descriptor')
    width, height, flags = struct.unpack_from('<HHB', b, 6)
    pos = 13 + (3 * (2 << (flags & 7)) if flags & 0x80 else 0)
    images = 0
    while True:
        _need(b, pos + 1, 'GIF block')
        block = b[pos]
        if block == 0x3b:
            if not images:
                raise invalid('GIF has no image')
            shape = dict(width=width, height=height, bits=None, key=(b[:6].decode('ascii'), images))
            return _trailing(b, pos + 1, 'GIF trailer', notes, shape)
        if block == 0x21:
            _need(b, pos + 2, 'GIF extension')
            pos = _gif_sub_blocks(b, pos + 2)
        elif block == 0x2c:
            _need(b, pos + 10, 'GIF image descriptor')
            local = b[pos + 9]
            pos += 10 + (3 * (2 << (local & 7)) if local & 0x80 else 0)
            _need(b, pos + 1, 'GIF image data')
            if not 1 <= b[pos] <= 11:
                raise invalid('GIF LZW code size is not defined')
            pos = _gif_sub_blocks(b, pos + 1)
            images += 1
        else:
            raise invalid(f'GIF block 0x{block:02X} is not defined')


def _gif_sub_blocks(b, pos):
    while True:
        _need(b, pos + 1, 'GIF data sub-block')
        size = b[pos]
        pos += 1 + size
        if size == 0:
            return pos
        _need(b, pos, 'GIF data sub-block')


# --- TIFF (TIFF 6.0) ---
TIFF_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}


def check_tiff(b, notes):
    order = '<' if b[:2] == b'II' else '>'
    _need(b, 8, 'TIFF header')
    offset, = struct.unpack_from(order + 'I', b, 4)
    seen, first = set(), None
    while offset:
        if offset in seen or len(seen) >= 1024:
            raise invalid('TIFF image directories loop')
        seen.add(offset)
        if offset < 8:
            raise invalid('TIFF directory offset is not valid')
        if offset % 2:
            notes.append(f'TIFF directory at the odd offset {offset}')
        _need(b, offset + 2, 'TIFF directory')
        count, = struct.unpack_from(order + 'H', b, offset)
        _need(b, offset + 2 + 12 * count + 4, 'TIFF directory')
        fields = {}
        for i in range(count):
            tag, kind, n, value = struct.unpack_from(order + 'HHI4s', b, offset + 2 + 12 * i)
            if kind not in TIFF_TYPE_SIZES:
                continue  # TIFF 6.0: readers skip fields of an unknown type
            size = TIFF_TYPE_SIZES[kind] * n
            if size > 4:
                start, = struct.unpack(order + 'I', value)
                _need(b, start + size, 'TIFF field value')
                where = (b, start)
            else:
                where = (value, 0)
            if tag in (256, 257, 259, 273, 277, 279, 324, 325):
                if kind not in (3, 4) or n == 0:
                    raise invalid(f'TIFF field {tag} has no integer value')
                fields[tag] = (order + ('H' if kind == 3 else 'I'), n, where)
        for offsets, counts in ((273, 279), (324, 325)):
            if offsets in fields or counts in fields:
                if offsets not in fields or counts not in fields or fields[offsets][1] != fields[counts][1]:
                    raise invalid('TIFF data offsets and byte counts do not match')
                for start, size in zip(_tiff_values(fields[offsets]), _tiff_values(fields[counts])):
                    _need(b, start + size, 'TIFF image data')
        if 273 not in fields and 324 not in fields:
            raise invalid('TIFF directory has no image data')
        if 256 not in fields or 257 not in fields:
            raise invalid('TIFF directory has no image size')
        if first is None:
            first = fields
        offset, = struct.unpack_from(order + 'I', b, offset + 2 + 12 * count)
    if first is None:
        raise invalid('TIFF has no image directory')
    one = lambda tag, default: next(_tiff_values(first[tag])) if tag in first else default
    return dict(width=one(256, 0), height=one(257, 0), bits=None,
                key=('II' if order == '<' else 'MM', one(259, 1), one(277, 1)))


def _tiff_values(field):
    """Yield the integer values of a field one by one (no large tuples for big strip tables)."""
    fmt, n, (source, start) = field
    size = struct.calcsize(fmt)
    for index in range(n):
        yield struct.unpack_from(fmt, source, start + index * size)[0]


CHECKS = {'BMP': check_bmp, 'JPEG': check_jpeg, 'PNG': check_png, 'GIF': check_gif, 'TIFF': check_tiff}
