"""確認済みv600/v700数値ヘッダーの縮尺だけを書き換える。"""
import math
import struct

from jwwkit.reader.archive import Cursor


def scale_value(value):
    """有限の正の縮尺分母だけ受け付ける。ゼロ縮尺の推測補正はしない。"""
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('縮尺分母は有限の正の数を指定してください')
    return float(value)


def group_index(index):
    if type(index) is not int or not 0 <= index < 16:
        raise ValueError('レイヤグループは0～15を指定してください')
    return index


def scale_offsets(raw, groups):
    """CStringを越えて全16グループの数値構造を照合し、縮尺位置を返す。"""
    cursor = Cursor(raw)
    if cursor.take(8) != b'JwwData.' or cursor.unpack('<I')[0] not in (600, 700):
        raise ValueError('未対応のヘッダー形式です')
    cursor.string(preserve_header_bytes=True)
    cursor.take(8)
    if len(groups) != 16:
        raise ValueError('16グループのヘッダーが必要です')
    offsets = []
    for index, group in enumerate(groups):
        start = cursor.pos
        fields = cursor.unpack('<IIdI')
        expected = (group['state'], group['write_layer'], group['scale'], group['protect'])
        if fields != expected:
            raise ValueError(f'ヘッダー構造が一致しません: element=layer_groups[{index}], offset={start}')
        offsets.append(start + 8)
        for layer in group['layers']:
            if cursor.unpack('<II') != (layer['state'], layer['protect']):
                raise ValueError(f'レイヤ構造が一致しません: element=layer_groups[{index}], offset={cursor.pos - 8}')
    return offsets


def patch_scales(raw, groups, edits):
    """縮尺8バイト以外を保持する。グループ状態・名前等の編集は未対応。"""
    offsets = scale_offsets(raw, groups)
    result = bytearray(raw)
    for index, value in edits.items():
        struct.pack_into('<d', result, offsets[group_index(index)], scale_value(value))
    return bytes(result)

def patch_states(raw,groups,edits):
    """検証済み元ヘッダーの状態DWORDだけ変更。書込み指定と保護値は保持。"""
    offsets=scale_offsets(raw,groups);result=bytearray(raw)
    for (group,layer),value in edits.items():
        group=group_index(group)
        if type(value) is not int or value not in (0,1,2):raise ValueError('Unverified display state edit')
        offset=offsets[group]-8
        if layer is not None:offset+=20+8*group_index(layer)
        struct.pack_into('<I',result,offset,value)
    return bytes(result)


def name_spans(raw, names):
    """既知ヘッダーの272 CStringを値と照合する。未知配置・不一致は拒否する。"""
    cursor = Cursor(raw)
    if cursor.take(8) != b'JwwData.' or cursor.unpack('<I')[0] not in (600, 700):
        raise ValueError('未対応のヘッダー形式です')
    cursor.string(preserve_header_bytes=True)
    cursor.take(2532)
    if len(names) != 272:
        raise ValueError('272個のレイヤ・グループ名が必要です')
    spans = []
    for index, expected in enumerate(names):
        start = cursor.pos
        if cursor.string(preserve_header_bytes=True) != expected:
            raise ValueError(f'名称構造が一致しません: element=layer_names[{index}], offset={start}')
        spans.append((start, cursor.pos))
    return spans


def validate_name_edit(raw, names, index, name):
    """原フィールドのUTF-16/CP932で符号化する。表現不能な名前は事前拒否する。"""
    from jwwkit.writer.strings import cstring
    if type(index) is not int or not 0 <= index < 272 or not isinstance(name, str):
        raise ValueError('名称番号と文字列が不正です')
    start, end = name_spans(raw, names)[index]
    encoding = 'utf-16le' if raw[start:end].startswith(b'\xff\xfe\xff') else 'cp932'
    return cstring(name, encoding)


def patch_names(raw, names, edits):
    """変更されたCStringだけ差し替える。長さが変わっても他のヘッダー値は保持する。"""
    spans = name_spans(raw, names)
    result = bytearray()
    position = 0
    for index in sorted(edits):
        start, end = spans[index]
        result += raw[position:start]
        # 元と同じ値へ戻した場合は別符号位置を含め原バイトを維持する。
        result += raw[start:end] if edits[index] == names[index] else validate_name_edit(raw, names, index, edits[index])
        position = end
    result += raw[position:]
    return bytes(result)
