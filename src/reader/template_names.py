"""空テンプレート系図面の名前表。既存図面保存の汎用ヘッダー解析とは別経路。"""
from pathlib import Path
import struct
from writer.strings import cstring
from writer.template_constants import NAME_TABLE_START


def template_layout_names(path):
    """確認済みv700空メモの名前表だけを読む。任意の旧版・別配置は拒否する。"""
    raw = Path(path).read_bytes()
    if raw[:16] != b'JwwData.' + struct.pack('<I', 700) + cstring(''):
        raise ValueError('Only the verified v700 empty-memo name-table layout is supported')
    pos, names = NAME_TABLE_START, []
    for _ in range(272):
        if raw[pos:pos+3] != b'\xff\xfe\xff' or pos+4 > len(raw):
            raise ValueError('Unsupported layer-name string encoding')
        length = raw[pos+3]
        if length == 255 or pos+4+length*2 > len(raw):
            raise ValueError('Unsupported or truncated layer-name string')
        names.append(raw[pos+4:pos+4+length*2].decode('utf-16le'))
        pos += 4 + length*2
    return [names[i:i+16] for i in range(0,256,16)], names[256:], pos
