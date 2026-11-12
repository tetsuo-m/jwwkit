"""Bounded record supplement for observed v600/v700 layouts.

Native ezjww remains the header/metadata reader. This supplement retains
CP932 strings and embedded dimension attributes that its public model loses.
It rejects unknown classes, object references and unbounded/noncanonical counts.
Observed gzip/BMP image trailers are validated and retained as raw bytes.
"""
from pathlib import Path
import struct
from _ezjww_adapter import read_native_document
from .images import read_image_trailer

BASE_KEYS = ('group', 'pen_style', 'pen_color', 'pen_width', 'layer', 'layer_group', 'flag')
XY_KEYS = ('start_x', 'start_y', 'end_x', 'end_y')
TEXT_KEYS = (*XY_KEYS, 'text_type', 'size_x', 'size_y', 'spacing', 'angle')
SOLID_KEYS = tuple(f'point{i}_{axis}' for i in (1,4,2,3) for axis in ('x','y'))


class RecordError(ValueError):
    pass


class Record(dict):
    """公開辞書の値を変えず、無変更CStringの原バイトを内部保持する。"""
    source_strings = None


class Cursor:
    def __init__(self, data):
        self.data, self.pos = data, 0
        self.context = 'header'

    def take(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise RecordError(f'Truncated record at {self.pos}')
        b = self.data[self.pos:self.pos+n]
        self.pos += n
        return b

    def unpack(self, fmt):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))

    def string(self, *, preserve_header_bytes=False):
        unicode = False
        length, = self.unpack('<B')
        if length == 255:
            length, = self.unpack('<H')
            if length == 65534:
                unicode = True
                length, = self.unpack('<B')
                if length == 255:
                    length, = self.unpack('<H')
            if length == 65535:
                length, = self.unpack('<I')
        raw = self.take(length*(2 if unicode else 1))
        encoding = 'utf-16le' if unicode else 'cp932'
        # ヘッダーは生バイトを保持するため、不完全な旧CP932名も可逆に表現する。
        # 要素本文では復号エラーを引き続き拒否する。
        errors = 'surrogateescape' if preserve_header_bytes and not unicode else 'strict'
        return raw.decode(encoding, errors=errors)


def read_records(path, *, schema_profile='strict'):
    """v600/v700本文を読む。strict既定、rebro_schema0は観測済み3クラス限定。"""
    return read_records_bytes(Path(path).read_bytes(), schema_profile=schema_profile)


def read_records_bytes(data, *, schema_profile='strict'):
    """原バイト列の本文を読む。strict既定、限定schema0は明示指定し、位置付きで拒否する。"""
    if schema_profile not in ('strict', 'rebro_schema0'):
        raise ValueError('Unknown schema_profile; use strict or rebro_schema0')
    c = Cursor(data)
    c.schema_profile = schema_profile
    c.class_declarations = []
    try:
        return _read_records(c)
    except (ValueError, UnicodeError, struct.error) as exc:
        raise RecordError(f'{exc}; element={c.context}; offset={c.pos}') from exc


def _read_records(c):
    """観測済み本文と入れ子メンバーを読む。v600/v700拡張個数を有限読取り。非正規個数・未知クラス・未確認末尾は拒否する。"""
    if c.take(8) != b'JwwData.':
        raise RecordError('Invalid JWW signature')
    version, = c.unpack('<I')
    if version not in (600,700):
        raise RecordError('Only observed v600/v700 layouts are supported')
    memo = c.string(preserve_header_bytes=True)
    # v600/v700 numeric header fields before the 256+16 layer names.
    c.take(2532)
    layer_names = [c.string(preserve_header_bytes=True) for _ in range(272)]
    # Shadow/zoom/pen/pattern/drawing fields, then SXF display colors.
    # Reference: LibreCAD jwwdoc.cpp ReadHeader; all 15 bundled v600
    # originals and our v700 samples independently agree on these spans.
    c.take(1140 + 257*8)
    color_names = []
    for _ in range(257):
        color_names.append(c.string(preserve_header_bytes=True))
        c.take(16)
    c.take(33*16)
    line_type_names = []
    for _ in range(33):
        line_type_names.append(c.string(preserve_header_bytes=True))
        c.take(84)
    c.take(380)
    header_end = c.pos
    entities, definitions, spans = read_entity_sequences(c, version)
    if c.schema_profile == 'rebro_schema0':
        if definitions or any(r['type'] not in ('LINE','CIRCLE','ARC','TEXT') for r in entities):
            raise RecordError('Unobserved structure for rebro_schema0')
        if not c.class_declarations or any(d['schema'] != 0 for d in c.class_declarations):
            raise RecordError('rebro_schema0 requires exclusively schema-0 declarations')
    c.context = 'trailer'
    tail_offset = c.pos
    images = read_image_trailer(c) if version == 700 else []
    if c.schema_profile == 'rebro_schema0' and images:
        raise RecordError('Images unobserved for rebro_schema0')
    raw_trailer = c.data[tail_offset:c.pos]
    if c.pos != len(c.data):
        raise RecordError('Unsupported trailer/layout')
    return dict(entities=entities, block_defs=definitions, header_end=header_end,
                tail_offset=tail_offset, raw_trailer=raw_trailer, images=images,
                spans=spans, version=version, memo=memo,
                schema_profile=c.schema_profile, class_declarations=c.class_declarations,
                layer_names=layer_names, color_names=color_names, line_type_names=line_type_names)



def read_entity_sequences(c, version):
    """Shared bounded MFC sequences; caller verifies container/version/trailer."""
    classes, spans, next_index = {}, [], 1

    def base():
        if version == 230:
            keys=tuple(k for k in BASE_KEYS if k!='pen_width')
            return dict(zip(keys,c.unpack('<IBHHHH')),pen_width=0)
        return dict(zip(BASE_KEYS, c.unpack('<IBHHHHH')))

    def string_fields(record, keys):
        # CP932の同一文字に複数ある符号位置も、無変更フィールドは原バイト保持。
        original_strings = {}
        for key in keys:
            start = c.pos
            value = c.string()
            record[key] = value
            original_strings[key] = (value, c.data[start:c.pos])
        record.source_strings = original_strings

    def payload(name):
        start = c.pos
        observed_old_classes = {
            230: {'CDataSen', 'CDataEnko', 'CDataMoji'},
            351: {'CDataSen', 'CDataEnko', 'CDataMoji', 'CDataSolid', 'CDataList'},
            420: {'CDataSen', 'CDataEnko'},
        }
        if version in observed_old_classes and name not in observed_old_classes[version]:
            raise RecordError(f'Unobserved old JWS class/schema: {name}/{version}')
        if name not in {'CDataSen','CDataTen','CDataMoji','CDataEnko','CDataBlock','CDataList','CDataSunpou','CDataSolid'}:
            raise RecordError(f'Unsupported class {name} at payload offset={start}')
        b = base()
        if name == 'CDataSen':
            r = dict(type='LINE', base=b, **dict(zip(XY_KEYS, c.unpack('<dddd'))))
        elif name == 'CDataTen':
            x, y, temp = c.unpack('<ddI')
            r = dict(type='POINT', base=b, x=x, y=y, is_temporary=bool(temp), code=0, angle=0.0, scale=0.0)
            if b['pen_style'] == 100:
                r.update(zip(('code','angle','scale'), c.unpack('<Idd')))
            elif b['pen_style'] != 1:
                raise RecordError('Unsupported point style')
        elif name == 'CDataMoji':
            r = Record(type='TEXT', base=b, **dict(zip(TEXT_KEYS, c.unpack('<ddddIdddd'))))
            string_fields(r, ('font_name', 'content'))
        elif name == 'CDataEnko':
            r = dict(base=b, **dict(zip(('center_x','center_y','radius','start_angle','arc_angle','tilt_angle','flatness'), c.unpack('<ddddddd'))))
            full, = c.unpack('<I')
            r.update(type='CIRCLE' if full else 'ARC', is_full_circle=bool(full))
        elif name == 'CDataBlock':
            r = dict(type='BLOCK', base=b, **dict(zip(('ref_x','ref_y','scale_x','scale_y','rotation','def_number'), c.unpack('<dddddI'))))
        elif name == 'CDataList':
            number, referenced, timestamp = c.unpack('<III')
            r = Record(type='BLOCK_DEF', base=b, number=number, is_referenced=bool(referenced), timestamp=timestamp, name='', entities=[])
            string_fields(r, ('name',))
            r['entities'] = sequence(c.context+'.entities')
        elif name == 'CDataSunpou':
            line, text = payload('CDataSen'), payload('CDataMoji')
            mode, = c.unpack('<H')
            r = dict(type='DIMENSION', base=b, line=line, text=text, sxf_mode=mode,
                     aux_lines=[payload('CDataSen') for _ in range(2)],
                     aux_points=[payload('CDataTen') for _ in range(4)])
        elif name == 'CDataSolid':
            values = c.unpack('<8d')
            if b['pen_style'] >= 101:
                # 公開形式はstyle>=101を円系8数値として保存する。
                # E104見本の105もezjwwと全欄一致。読取り/原表現保持と、
                # 編集許可(style101の既確認範囲)は分離する。
                keys = ('center_x','center_y','radius','flatness','tilt_angle','start_angle','arc_angle','solid_mode')
                r = dict(type='CIRCLE_SOLID', base=b, **dict(zip(keys, values)), color=None)
            else:
                r = dict(type='SOLID', base=b, **dict(zip(SOLID_KEYS, values)), color=None)
            if b['pen_color'] == 10:
                r['color'], = c.unpack('<I')
        else:
            raise RecordError(f'Unsupported class {name}')
        spans.append(dict(class_name=name, base_offset=start, end=c.pos, base=b))
        return r

    def sequence(label):
        nonlocal next_index
        n, = c.unpack('<H')
        if n == 65535:
            if version not in (600,700):
                raise RecordError('Extended sequence count unobserved for this old schema')
            n, = c.unpack('<I')
            if n < 65535 or n == 0xffffffff:
                raise RecordError('Unsupported noncanonical/64-bit sequence count')
        if n > (len(c.data)-c.pos)//2:
            raise RecordError('Sequence count exceeds remaining record-tag capacity')
        records = []
        for index in range(n):
            c.context = f'{label}[{index}]'
            tag, = c.unpack('<H')
            if tag == 65535:
                declaration_offset = c.pos - 2
                schema, length = c.unpack('<HH')
                name_bytes = c.take(length)
                observer=getattr(c,'_class_declaration_observer',None)
                if observer is not None:observer(name_bytes,schema,declaration_offset,next_index)
                name = name_bytes.decode('ascii')
                profile = getattr(c, 'schema_profile', 'strict')
                if schema != version:
                    accepted = (profile == 'rebro_schema0' and version in (600,700)
                                and schema == 0 and name in ('CDataSen','CDataEnko','CDataMoji'))
                    if not accepted:
                        hint = ('; schema=0: explicit schema_profile="rebro_schema0" permits only '
                                'observed v600/v700 CDataSen/CDataEnko/CDataMoji (read-only)'
                                if schema == 0 and version in (600,700) else '')
                        raise RecordError(f'Unsupported class schema: {schema}, class={name}{hint}')
                if hasattr(c, 'class_declarations'):
                    c.class_declarations.append(dict(name=name, schema=schema,
                        class_index=next_index, offset=declaration_offset))
                classes[next_index] = name
                next_index += 1
            elif tag == 32767:
                # 大規模図面で確認したMFCのDWORDクラス参照。オブジェクト参照は拒否。
                extended, = c.unpack('<I')
                class_index = extended & 0x7fffffff
                if not extended & 0x80000000 or class_index not in classes:
                    raise RecordError('Unsupported extended object/class reference')
                name = classes[class_index]
            elif tag & 32768 and (tag & 32767) in classes:
                name = classes[tag & 32767]
            else:
                raise RecordError('Unsupported object/class reference')
            next_index += 1
            if next_index >= 0x7fffffff:
                raise RecordError('Reference table limit')
            records.append(payload(name))
        return records

    entities, definitions = sequence('entities'), sequence('block_defs')
    return entities, definitions, spans

def read_document(path, *, schema_profile='strict'):
    """既知本文を標準Readerと照合して文字・寸法属性を補う。未照合文字は診断を残し安全な編集保存を保証しない。"""
    native = read_native_document(path)
    try:
        raw = read_records(path, schema_profile=schema_profile)
    except (RecordError, UnicodeError, struct.error) as exc:
        if schema_profile != 'strict' or 'Unsupported class schema' in str(exc):
            raise
        # Basic/native read compatibility is retained; copying lossy text is
        # blocked by the existing save diagnostic check.
        def has_text(items):
            return any(e['type'] in ('TEXT','DIMENSION') for e in items)
        if has_text(native['entities']) or any(has_text(d['entities']) for d in native['block_defs']):
            native['diagnostics'].append(f'Exact text/embedded attributes unverified: {exc}')
        return native

    def check(a, b):
        if isinstance(a, dict):
            for k, v in a.items():
                if k in ('font_name','content','timestamp'):
                    continue
                if k in b:
                    check(v, b[k])
                elif k not in ('base','type'):
                    raise RecordError(f'Native field missing: {k}')
        elif isinstance(a, list):
            if len(a) != len(b):
                raise RecordError('Native/raw record count mismatch')
            for x, y in zip(a, b):
                check(x, y)
        elif a != b:
            raise RecordError('Native/raw numeric or attribute mismatch')
    check(raw['entities'], native['entities'])
    check(raw['block_defs'], native['block_defs'])
    native['entities'] = raw['entities']
    native['block_defs'] = raw['block_defs']
    return native
