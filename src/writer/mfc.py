"""MFC要素列の保存。ヘッダー編集・新規図面管理とは独立。"""
import struct
from model.base import BASE_KEYS
from .strings import cstring


def records_bytes(records, registry=None, *, version=700, encoding="utf-16le"):
    """確認済みJWW600/700・JWS230/351/420/600/700のMFC要素列を保存する。"""
    if version not in (230,351,420,600,700):
        raise ValueError("Unsupported archive schema")
    count=len(records)
    if count >= 65535 and version not in (600,700):
        raise ValueError('Extended sequence counts unobserved for this old schema')
    if count >= 0xffffffff:
        raise ValueError('64-bit sequence counts are not supported')
    data = bytearray(struct.pack('<H', count) if count < 65535 else struct.pack('<HI',65535,count))
    registry = registry if registry is not None else dict(classes={}, next_index=1)
    classes = registry['classes']
    for record in records:
        kind = record['type']
        name = {'LINE': b'CDataSen', 'CIRCLE': b'CDataEnko', 'ARC': b'CDataEnko',
                'POINT': b'CDataTen', 'TEXT': b'CDataMoji',
                'BLOCK': b'CDataBlock', 'BLOCK_DEF': b'CDataList',
                'DIMENSION': b'CDataSunpou', 'SOLID': b'CDataSolid',
                'CIRCLE_SOLID': b'CDataSolid'}[kind]
        if name not in classes:
            schema = version
            if 'class_declarations' in registry:
                declarations = registry['class_declarations']
                position = registry['declaration_position']
                if position >= len(declarations):
                    raise ValueError('Unexpected new class declaration in read-only archive')
                expected = declarations[position]
                if expected['name'] != name.decode('ascii') or expected['class_index'] != registry['next_index']:
                    raise ValueError('Original class declaration order/index cannot be preserved')
                schema = expected['schema']
                registry['declaration_position'] += 1
            classes[name] = registry['next_index']
            registry['next_index'] += 1
            data += struct.pack('<HHH', 65535, schema, len(name)) + name
        elif classes[name] >= 32767:
            # WORD予約値0x7fffに続くDWORDクラス参照。既知の大規模図面と一致。
            data += struct.pack('<HI', 32767, 0x80000000 | classes[name])
        else:
            data += struct.pack('<H', 32768 | classes[name])
        registry['next_index'] += 1
        if registry['next_index'] >= 0x7fffffff:
            raise ValueError('Prototype archive reference-table limit')
        data += payload_bytes(record, registry, version=version, encoding=encoding)
    return bytes(data)


def field_string(record, key, encoding):
    """無変更CStringは符号位置も含め保持する。変更文字は指定符号化で書く。"""
    original = (getattr(record, 'source_strings', None) or {}).get(key)
    if original is not None and original[0] == record[key]:
        return original[1]
    return cstring(record[key], encoding)


def payload_bytes(record, registry=None, *, version=700, encoding="utf-16le"):
    """既知の値メンバーを書き出す。未知構造は対応しない。"""
    kind = record['type']
    if version == 230:
        if record['base']['pen_width'] != 0:
            raise ValueError('JWS230 has no stored pen_width field')
        data=bytearray(struct.pack('<IBHHHH',*(record['base'][k] for k in BASE_KEYS if k!='pen_width')))
    else:
        data = bytearray(struct.pack('<IBHHHHH', *(record['base'][k] for k in BASE_KEYS)))
    if kind == 'LINE':
        data += struct.pack('<dddd', *(record[k] for k in ('start_x','start_y','end_x','end_y')))
    elif kind == 'CIRCLE':
        data += struct.pack('<dddddddI', *(record[k] for k in (
            'center_x', 'center_y', 'radius', 'start_angle', 'arc_angle',
            'tilt_angle', 'flatness')), int(record['is_full_circle']))
    elif kind == 'ARC':
        data += struct.pack('<dddddddI', *(record[k] for k in (
            'center_x', 'center_y', 'radius', 'start_angle', 'arc_angle',
            'tilt_angle', 'flatness')), int(record['is_full_circle']))
    elif kind == 'POINT':
        data += struct.pack('<ddI', record['x'], record['y'], int(record['is_temporary']))
        if record['base']['pen_style'] == 100:
            data += struct.pack('<Idd', record['code'], record['angle'], record['scale'])
    elif kind == 'TEXT':
        data += struct.pack('<dddd', *(record[k] for k in ('start_x','start_y','end_x','end_y')))
    elif kind == 'BLOCK':
        data += struct.pack('<dddddI', *(record[k] for k in ('ref_x','ref_y','scale_x','scale_y','rotation','def_number')))
    elif kind == 'BLOCK_DEF':
        data += struct.pack('<III',record['number'],int(record['is_referenced']),record['timestamp'])
        data += field_string(record, 'name', encoding)
        data += records_bytes(record['entities'], registry, version=version, encoding=encoding)
    elif kind == 'DIMENSION':
        data += payload_bytes(record['line'], version=version, encoding=encoding) + payload_bytes(record['text'], version=version, encoding=encoding)
        data += struct.pack('<H',record['sxf_mode'])
        for child in record['aux_lines'] + record['aux_points']:
            data += payload_bytes(child, version=version, encoding=encoding)
    elif kind == 'SOLID':
        data += struct.pack('<8d', *(record[f'point{i}_{axis}'] for i in (1,4,2,3) for axis in ('x','y')))
        if record['base']['pen_color'] == 10:
            data += struct.pack('<I', record['color'])
    elif kind == 'CIRCLE_SOLID':
        data += struct.pack('<8d', *(record[k] for k in (
            'center_x','center_y','radius','flatness','tilt_angle',
            'start_angle','arc_angle','solid_mode')))
        if record['base']['pen_color'] == 10:
            data += struct.pack('<I', record['color'])
    if kind == 'TEXT':
        data += struct.pack('<Idddd', *(record[k] for k in ('text_type','size_x','size_y','spacing','angle')))
        data += field_string(record, 'font_name', encoding) + field_string(record, 'content', encoding)
    return bytes(data)
