"""確認済みv700画像末尾を検証する。既存gzip/BMPの保持専用で追加・変更は不可。"""
import hashlib
import struct
import zlib

MAX_IMAGE_BYTES = 50_000_000


def read_image_trailer(cursor):
    """DWORD個数・CString識別子・DWORD圧縮長・gzip/BMPを読む。未知形式は拒否。"""
    count, = cursor.unpack('<I')
    if count > 1:
        raise ValueError('Multiple embedded images are unverified')
    if count > (len(cursor.data) - cursor.pos) // 25:
        raise ValueError('Invalid image trailer count')
    images = []
    for index in range(count):
        cursor.context = f'trailer.images[{index}]'
        identifier = cursor.string()
        size_offset = cursor.pos
        compressed_size, = cursor.unpack('<I')
        gzip_offset = cursor.pos
        compressed = cursor.take(compressed_size)
        if not compressed.startswith(b'\x1f\x8b\x08'):
            raise ValueError('Unsupported embedded image compression')
        inflater = zlib.decompressobj(31)
        try:
            bitmap = inflater.decompress(compressed, MAX_IMAGE_BYTES + 1)
        except zlib.error as exc:
            raise ValueError('Invalid gzip image stream') from exc
        if (len(bitmap) > MAX_IMAGE_BYTES or not inflater.eof
                or inflater.unused_data or inflater.unconsumed_tail):
            raise ValueError('Unsupported gzip image stream length or members')
        if len(bitmap) < 54 or bitmap[:2] != b'BM':
            raise ValueError('Unsupported embedded image format')
        file_size, reserved, pixel_offset = struct.unpack_from('<III', bitmap, 2)
        dib_size, width, height, planes, bits, compression = struct.unpack_from('<IiiHHI', bitmap, 14)
        # 実ファイルで確認した40-byte DIB・24-bit BI_RGBだけを受け付ける。
        if (file_size != len(bitmap) or reserved != 0 or pixel_offset != 54
                or dib_size != 40 or width <= 0 or height <= 0
                or planes != 1 or bits != 24 or compression != 0
                or 54 + ((width * 3 + 3) // 4) * 4 * height != len(bitmap)):
            raise ValueError('Unsupported BMP layout')
        images.append(dict(identifier=identifier, size_offset=size_offset,
                           gzip_offset=gzip_offset, compressed_size=compressed_size,
                           format='BMP', width=width, height=height, bits=bits,
                           raw_size=len(bitmap), sha256=hashlib.sha256(bitmap).hexdigest()))
    return images
