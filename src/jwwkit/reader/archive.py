"""Bounded record supplement for observed v230/v300/v351/v420/v600/v700 layouts.

Native ezjww remains the header/metadata reader. This supplement retains
CP932 strings and embedded dimension attributes that its public model loses.
It rejects unknown classes, object references and unbounded/noncanonical counts.
Observed gzip/BMP image trailers are validated and retained as raw bytes.
"""
from pathlib import Path
import struct
from jwwkit._ezjww_adapter import read_native_document
from .images import read_image_trailer

BASE_KEYS = ('group', 'pen_style', 'pen_color', 'pen_width', 'layer', 'layer_group', 'flag')
XY_KEYS = ('start_x', 'start_y', 'end_x', 'end_y')
TEXT_KEYS = (*XY_KEYS, 'text_type', 'size_x', 'size_y', 'spacing', 'angle')
SOLID_KEYS = tuple(f'point{i}_{axis}' for i in (1,4,2,3) for axis in ('x','y'))
# rebro_schema0: classes whose schema-0 declarations are accepted, and the element kinds they may hold.
# v700 adds points and solids (#36): observed in 37 real drawings, where jwwkit and ezjww agreed and the
# unedited save was byte-identical. Not checked against a published description or sample.
REBRO_SCHEMA0_CLASSES = {600: ('CDataSen', 'CDataEnko', 'CDataMoji'),
                         700: ('CDataSen', 'CDataEnko', 'CDataMoji', 'CDataTen', 'CDataSolid')}
REBRO_SCHEMA0_TYPES = {600: ('LINE', 'CIRCLE', 'ARC', 'TEXT'),
                       700: ('LINE', 'CIRCLE', 'ARC', 'TEXT', 'POINT', 'SOLID', 'CIRCLE_SOLID')}
REBRO_SCHEMA0_HINT = ('; schema=0: explicit schema_profile="rebro_schema0" permits only observed '
                      'v600 CDataSen/CDataEnko/CDataMoji and v700 CDataSen/CDataEnko/CDataMoji/CDataTen/CDataSolid '
                      '(read-only)')
# Observed with ezjww 0.2.13 and 0.7.13: above this many block definitions,
# ezjww returns an empty block_defs list. read_document rejects such drawings.
EZJWW_BLOCK_DEFINITION_LIMIT = 10000
# (file version, class schema) pairs accepted besides schema == version.
# (600, 700): Jw_cad 10.03.6 saving in the v6 format writes every class
# declaration with schema 700; the record layout still follows version 600.
# Accepted only when all declarations use it; edits may not add new class
# declarations (see preserved.py).
# Old file versions (#17) are read-only. Accepted only in the observed pairs:
# schema == version for 230/300/351 (real drawings, #8), and schema 700 for
# 230/300/351/420 (Jw_cad 10.03.6 saving in the old formats; 420 from one sample only).
# (420, 0/1/230/310), (300, 1), (351, 1), (230, 65535) (#41): real drawings only (#40), where
# jwwkit and ezjww agreed and the body re-serialised losslessly. Jw_cad 10.03.6 re-saves differed
# only by its own re-save changes, most of them also seen in controls (VERIFICATION.md 5 and 6).
# The body is still read by the file version; only these exact schema values are accepted.
OBSERVED_CLASS_SCHEMA_PAIRS = frozenset({
    (600, 700), (230, 700), (300, 700), (351, 700), (420, 700),
    (420, 0), (420, 1), (420, 230), (420, 310), (300, 1), (351, 1), (230, 65535),
})
JWW_VERSIONS = (230, 300, 351, 420, 600, 700)
SAME_CLASS_SCHEMA_VERSIONS = frozenset({230, 300, 351, 600, 700})
# Canonical extended counts (65535 marker + DWORD >= 65535) in old versions were
# observed only in (230, 700) and (420, 0) drawings (#41). Large (420, 230) drawings stay
# rejected: they also write class references in a form jwwkit cannot write back (#40).
OLD_EXTENDED_COUNT_PAIRS = frozenset({(230, 700), (420, 0)})
# Old JWS versions have their own observed class lists; only the JWS reader applies them.
JWS_OBSERVED_OLD_CLASSES = {
    230: frozenset({'CDataSen', 'CDataEnko', 'CDataMoji'}),
    351: frozenset({'CDataSen', 'CDataEnko', 'CDataMoji', 'CDataSolid', 'CDataList'}),
    420: frozenset({'CDataSen', 'CDataEnko'}),
}
NONCANONICAL_COUNT_MESSAGE = ('Unsupported noncanonical/64-bit sequence count (a count below 65535 written in the '
                              'DWORD form; ezjww returns no elements for it, so it cannot be cross-checked)')


def is_read_only_version(version):
    """Old file versions are read-only (unedited save-as only)."""
    return version not in (600, 700)


def header_layout(version):
    """Header spans after the memo, per the official description and the version conditions (#8).

    Steps: ('skip', n) or ('strings', key, count, bytes after each string).
    """
    at_least_300 = version >= 300
    steps = [
        # Drawing size .. grid reference point (write group 4, 16 groups x
        # (20 + 16 layers x 8), dummies, dimension settings, printer/scale fields).
        ('skip', 2532),
        # 256 layer names + 16 layer group names.
        ('strings', 'layer_names', 272, 0),
        ('skip', 28),  # shadow conditions
    ]
    if at_least_300:
        steps.append(('skip', 16))  # sky map conditions (300 and later)
    steps.append(('skip', 52))  # 2.5D unit, saved screen scale/origin, range memory
    steps.append(('skip', 8 * 28 if at_least_300 else 4 * 24))  # mark jumps
    if at_least_300:
        steps.append(('skip', 56))  # text drawing state (300 and later)
    # Parallel lines .. print settings 664, Ver.2.23-2.30 items 100 (present from v230).
    steps.append(('skip', 664 + 100))
    if version >= 420:
        steps += [
            ('skip', 257 * 8),  # SXF extended colors: screen color and width (4 + 4) each
            ('strings', 'color_names', 257, 16),  # name, print color 4, print width 4, point radius 8
            ('skip', 33 * 16),  # SXF extended line types: pattern (4 x 4) each
            ('strings', 'line_type_names', 33, 84),  # name, segment count 4 + pitch 10 x 8
        ]
    # 380: text types 1-10 x (24 + color 4), write text 32, text alignment/offsets 68.
    steps.append(('skip', 380))
    return steps


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
    """v600/v700と観測済みの古い版の本文を読む。strict既定、rebro_schema0はv600の3クラス・v700の5クラスの観測済みの形だけ。"""
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
    """観測済み本文と入れ子メンバーを読む。拡張個数を有限読取り。非正規個数・未知クラス・未確認末尾は拒否する。"""
    if c.take(8) != b'JwwData.':
        raise RecordError('Invalid JWW signature')
    version, = c.unpack('<I')
    if version not in JWW_VERSIONS:
        raise RecordError(f'Unsupported JWW version {version}: only observed v230/v300/v351/v420/v600/v700 layouts are supported')
    if version not in (600, 700) and c.schema_profile != 'strict':
        raise RecordError('rebro_schema0 applies only to v600/v700')
    memo = c.string(preserve_header_bytes=True)
    # Header spans follow the official Jw_cad data format description
    # (https://www.jwcad.net/jwdatafmt.txt, Jw_cad 7.02; see VERIFICATION.md).
    # All 15 v600 originals used in development, our v700 samples and the old-version
    # drawings of #8 independently agree on them.
    names = dict(layer_names=[], color_names=[], line_type_names=[])
    for step in header_layout(version):
        if step[0] == 'skip':
            c.take(step[1])
            continue
        _, key, count, after = step
        for _ in range(count):
            names[key].append(c.string(preserve_header_bytes=True))
            c.take(after)
    layer_names, color_names, line_type_names = names['layer_names'], names['color_names'], names['line_type_names']
    header_end = c.pos
    # Only the JWW path accepts the observed pairs; JWS shares the sequence reader.
    c.accepted_schema_pairs = OBSERVED_CLASS_SCHEMA_PAIRS
    c.same_schema_versions = SAME_CLASS_SCHEMA_VERSIONS
    c.old_extended_counts = 0
    entities, definitions, spans = read_entity_sequences(c, version)
    schemas = {d['schema'] for d in c.class_declarations}
    class_schema = version
    if c.schema_profile == 'strict' and schemas - {version}:
        if len(schemas) != 1:
            raise RecordError(f'Unsupported class schema mix (mixed class schemas are unobserved): {sorted(schemas)}')
        class_schema, = schemas
    if version not in (600, 700):
        if not c.class_declarations:
            raise RecordError(f'Old version {version} without class declarations is unobserved')
        if c.old_extended_counts and (version, class_schema) not in OLD_EXTENDED_COUNT_PAIRS:
            raise RecordError(f'Extended sequence count unobserved for ({version}, {class_schema})')
    if c.schema_profile == 'rebro_schema0':
        if definitions or any(r['type'] not in REBRO_SCHEMA0_TYPES[version] for r in entities):
            raise RecordError('Unobserved structure for rebro_schema0')
        # Points and solids (v700, #36): only the forms observed in real drawings.
        for r in entities:
            if r['type'] == 'POINT' and (r['base']['pen_style'] != 1 or r['is_temporary'] or r['code']):
                raise RecordError('Unobserved point form for rebro_schema0')
            if (r['type'] in ('SOLID', 'CIRCLE_SOLID') and (r['base']['pen_color'] == 10
                    or r['base']['pen_style'] != (1 if r['type'] == 'SOLID' else 101))):
                raise RecordError('Unobserved solid form for rebro_schema0')
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
                class_schema=class_schema,
                layer_names=layer_names, color_names=color_names, line_type_names=line_type_names)



def read_entity_sequences(c, version):
    """Shared bounded MFC sequences; caller verifies container/version/trailer."""
    classes, spans, next_index = {}, [], 1

    def base():
        if version < 351:  # the pen width field exists from 351
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
        observed_old_classes = getattr(c, 'jws_observed_old_classes', {})
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
            if version < 252:
                # No code fields before 252. The description says the style is always 1;
                # real v230 drawings also use 0 (#8). Other values are unobserved.
                if b['pen_style'] not in (0, 1):
                    raise RecordError('Unsupported point style before v252')
            elif b['pen_style'] == 100:
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
            if version < 420:
                # No SXF part before 420; same shape as ezjww returns.
                r = dict(type='DIMENSION', base=b, line=line, text=text, sxf_mode=None, aux_lines=[], aux_points=[])
            else:
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
                # Old JWW: checked against the class schema after reading (OLD_EXTENDED_COUNT_PAIRS).
                if not hasattr(c, 'old_extended_counts'):
                    raise RecordError('Extended sequence count unobserved for this old schema')
                c.old_extended_counts += 1
            n, = c.unpack('<I')
            if n < 65535 or n == 0xffffffff:
                raise RecordError(NONCANONICAL_COUNT_MESSAGE)
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
                same_schema_versions = getattr(c, 'same_schema_versions', None)
                if schema == version and same_schema_versions is not None and version not in same_schema_versions:
                    raise RecordError(f'Unsupported class schema: {schema}, class={name} (unobserved for v{version})')
                if schema != version:
                    accepted = (profile == 'rebro_schema0' and version in REBRO_SCHEMA0_CLASSES
                                and schema == 0 and name in REBRO_SCHEMA0_CLASSES[version])
                    accepted = accepted or (profile == 'strict'
                                and (version, schema) in getattr(c, 'accepted_schema_pairs', ()))
                    if not accepted:
                        hint = (REBRO_SCHEMA0_HINT if schema == 0 and version in (600,700) else '')
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

    try:
        entities, definitions = sequence('entities'), sequence('block_defs')
    finally:
        # payload and sequence call each other (and payload itself), so their closures form a
        # reference cycle that holds the cursor and every span; clear it so that the records are
        # freed as soon as the caller drops them, without waiting for the cyclic collector (#29).
        del payload, sequence
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
    return _cross_check(native, raw)


def _read_document_with(path, raw):
    """read_document for records the caller has already read from the file's bytes (#25).

    CadDocument.open passes the read it made for the re-serialisation check, so the cross-check
    runs on exactly the records it keeps as the source snapshot. ezjww still reads the file.
    """
    return _cross_check(read_native_document(path), raw)


def _cross_check(native, raw):
    """Check jwwkit's records against ezjww's result; return ezjww's result with jwwkit's records."""
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
    # Guard: ezjww returning no elements while jwwkit reads some cannot be cross-checked.
    if raw['entities'] and not native['entities']:
        raise RecordError(f'ezjww returned no elements but jwwkit read {len(raw["entities"])}; '
                          'the drawing cannot be cross-checked')
    check(raw['entities'], native['entities'])
    # ezjww 0.2.13 returns no block definitions (and no diagnostic) when a drawing
    # has more than 10000. Keep rejecting, but say why; never fill in or skip the check.
    if not native['block_defs'] and len(raw['block_defs']) > EZJWW_BLOCK_DEFINITION_LIMIT:
        raise RecordError(
            f'Block definitions exceed the ezjww limit: jwwkit read {len(raw["block_defs"])} '
            f'definitions, but ezjww returns none above {EZJWW_BLOCK_DEFINITION_LIMIT}, '
            'so they cannot be cross-checked')
    check(raw['block_defs'], native['block_defs'])
    del check  # check calls itself: drop the closure cycle (#29)
    native['entities'] = raw['entities']
    native['block_defs'] = raw['block_defs']
    return native
