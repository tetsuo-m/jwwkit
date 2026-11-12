"""新規図面の作成と限定的なテンプレート読込み。原ヘッダー保持保存とは別経路。"""
from pathlib import Path
import hashlib
import copy
import struct
from _ezjww_adapter import read_native_document
from reader.archive import read_document
from reader.template_names import template_layout_names
from writer.strings import cstring
from writer.mfc import records_bytes
from writer.template_constants import TEMPLATE, HEADER_END, NAME_TABLE_START, NAME_TABLE_END
from model.line import Line
from model.circle import Circle
from model.point import Point
from model.text import Text
from model.solid import Solid
from model.dimension import Dimension
from model.block_reference import BlockReference
from model.block_definition import BlockDefinition


class JwwDocument:
    """確認済みテンプレートから新規図面を作る。任意の既存図面編集はCadDocumentを使う。"""
    def __init__(self):
        """固定テンプレートを検証して新規図面を用意する。任意のヘッダーを新規テンプレートとして受け入れない。"""
        raw = TEMPLATE.read_bytes()
        manifest = __import__('json').loads((TEMPLATE.parent/'header.json').read_text(encoding='utf-8'))
        if hashlib.sha256(raw).hexdigest() != manifest['sha256']:
            raise ValueError('Template checksum mismatch')
        source = read_native_document(TEMPLATE)
        if source['diagnostics'] or len(source['metadata_settings']) != 6 or source['entity_counts'] != {'TEXT': 6}:
            raise ValueError('Unexpected template contents')
        self._metadata = source['entities']
        body = records_bytes(self._metadata)
        if raw[HEADER_END:HEADER_END+len(body)] != body:
            raise ValueError('Template entity serialization mismatch')
        self._header = raw[:HEADER_END]
        if self._header[NAME_TABLE_START:NAME_TABLE_END] != cstring('') * 272:
            raise ValueError('Unexpected template layer-name table')
        self._layer_names = [[''] * 16 for _ in range(16)]
        self._group_names = [''] * 16
        self._tail = raw[HEADER_END+len(body):]
        if self._tail != b'\x00'*6:
            raise ValueError('Unexpected template trailer')
        self.entities = []
        self.block_definitions = []
        self._layer_groups = source['header']['layer_groups']
        self._template_header = copy.deepcopy(source['header'])
        self._default_layer_names = [[layer['name'] for layer in group['layers']] for group in self._layer_groups]
        self._default_group_names = [group['name'] for group in self._layer_groups]

    @property
    def layer_groups(self):
        """Read-only snapshot; use the explicit setters to edit names."""
        return copy.deepcopy(self._layer_groups)

    def set_layer_name(self, layer_group, layer, name):
        """新規図面のレイヤ名だけ変更する。状態や保護属性の編集は未対応。"""
        if type(layer_group) is not int or type(layer) is not int or not 0 <= layer_group < 16 or not 0 <= layer < 16:
            raise ValueError('Layer/group must be integers 0..15')
        if not isinstance(name, str):
            raise ValueError('Layer name must be a string')
        cstring(name)
        self._layer_names[layer_group][layer] = name
        self._layer_groups[layer_group]['layers'][layer]['name'] = name or self._default_layer_names[layer_group][layer]

    def set_group_name(self, layer_group, name):
        """新規図面のグループ名だけ変更する。未知のヘッダー設定は編集しない。"""
        if type(layer_group) is not int or not 0 <= layer_group < 16:
            raise ValueError('Layer group must be an integer 0..15')
        if not isinstance(name, str):
            raise ValueError('Group name must be a string')
        cstring(name)
        self._group_names[layer_group] = name
        self._layer_groups[layer_group]['name'] = name or self._default_group_names[layer_group]

    def get_group_scale(self, layer_group):
        """全16グループの縮尺分母を読む。ゼロや不正値を補正しない。"""
        from writer.header import group_index, scale_value
        index = group_index(layer_group)
        return scale_value(self._layer_groups[index]['scale'])

    def set_group_scale(self, layer_group, scale):
        """確認済み16グループの縮尺だけ変更する。紙面位置・実寸を自動保持する処理は行わない。"""
        from writer.header import group_index, scale_value, patch_scales
        index = group_index(layer_group)
        value = scale_value(scale)
        header = patch_scales(self._header, self._layer_groups, {index: value})
        self._header = header
        self._layer_groups[index]['scale'] = value

    def add_line(self, start, end, **attributes):
        from model.preflight import attributes as resolve,normalize_model
        attributes=resolve(self,attributes,'LINE')
        line = Line(tuple(start), tuple(end), **attributes)
        line=normalize_model(self,line)
        self.entities.append(line)
        return line

    def add_rectangle_hatch(self, bounds, **parameters):
        """Add explicit clipped LINEs; boundary/association are caller-owned."""
        from hatch_geometry import rectangle_hatch_lines
        from model.preflight import attributes as resolve
        parameters=resolve(self,parameters,'LINE')
        lines = rectangle_hatch_lines(bounds, **parameters)
        from model.preflight import normalize_model
        lines=[normalize_model(self,line) for line in lines]
        self.entities.extend(lines)
        return lines

    def add_circle(self, center, radius, **attributes):
        from model.preflight import attributes as resolve,normalize_model
        attributes=resolve(self,attributes,'CIRCLE')
        circle = Circle(tuple(center), float(radius), **attributes)
        circle=normalize_model(self,circle)
        self.entities.append(circle)
        return circle

    def add_arc(self, center, radius, start_angle, arc_angle, **attributes):
        """Write an ARC using Jw_cad's shared CDataEnko record."""
        attributes.update(start_angle=float(start_angle), arc_angle=float(arc_angle),
                          is_full_circle=False)
        return self.add_circle(center, radius, **attributes)

    def add_point(self, position, **attributes):
        from model.preflight import attributes as resolve,normalize_model
        attributes=resolve(self,attributes,'POINT')
        point = Point(tuple(position), **attributes)
        point=normalize_model(self,point)
        self.entities.append(point)
        return point

    def add_text(self, start, end=None, content=None, **attributes):
        from model.preflight import attributes as resolve,normalize_model
        attributes=resolve(self,attributes,'TEXT')
        if end is None:
            from model.text_metrics import record_endpoint
            prototype = Text(tuple(start), tuple(start), content, **attributes).record()
            end = record_endpoint(prototype, prototype['base'])
        text = Text(tuple(start), tuple(end), content, **attributes)
        text=normalize_model(self,text)
        self.entities.append(text)
        return text

    def add_dimension(self, line, text, **attributes):
        from model.preflight import attributes as resolve,normalize_model
        attributes=resolve(self,attributes,'DIMENSION')
        dimension = Dimension(copy.deepcopy(line),copy.deepcopy(text),**copy.deepcopy(attributes))
        dimension=normalize_model(self,dimension)
        self.entities.append(dimension)
        return dimension

    def add_solid(self, points, **attributes):
        from model.preflight import attributes as resolve,normalize_model
        attributes=resolve(self,attributes,'SOLID')
        solid = Solid(tuple(tuple(p) for p in points),**attributes)
        solid=normalize_model(self,solid)
        self.entities.append(solid)
        return solid

    def add_block_definition(self, name, entities, *, number=None, timestamp=0, compound_kind=4):
        from model.block_names import definition_name
        name = definition_name(name, compound_kind)
        number = max((d.number for d in self.block_definitions), default=-1)+1 if number is None else number
        definition = BlockDefinition(number,name,copy.deepcopy(list(entities)),timestamp)
        from model.preflight import normalize_model,check
        definition.entities=[normalize_model(self,e) for e in definition.entities]
        check(self,definition.record(False),defined_numbers=set())
        if any(d.number == number for d in self.block_definitions):
            raise ValueError('Duplicate block definition number')
        self.block_definitions.append(definition)
        return definition

    def add_block(self, def_number, position, **attributes):
        if type(def_number) is not int or not any(d.number==def_number for d in self.block_definitions):
            raise ValueError('Unresolved block definition reference')
        from model.preflight import attributes as resolve,normalize_model
        attributes=resolve(self,attributes,'BLOCK')
        block = BlockReference(tuple(position),def_number,**attributes)
        block=normalize_model(self,block)
        self.entities.append(block)
        return block

    def save(self, path):
        """新規図面を別名保存する。未解決ブロック参照と既存ファイルの上書きは拒否する。"""
        records = [line.record() for line in self.entities] + self._metadata
        numbers = [d.number for d in self.block_definitions]
        if len(set(numbers)) != len(numbers):
            raise ValueError('Duplicate block definition number')
        refs = {r['def_number'] for r in records if r['type'] == 'BLOCK'}
        if refs - set(numbers):
            raise ValueError('Unresolved block definition reference')
        definitions = [d.record(d.number in refs) for d in self.block_definitions]
        from model.preflight import check
        for record in records+definitions:check(self,record,defined_numbers=set(numbers))
        names = b''.join(cstring(name) for group in self._layer_names for name in group)
        names += b''.join(cstring(name) for name in self._group_names)
        header = self._header[:NAME_TABLE_START] + names + self._header[NAME_TABLE_END:]
        registry = dict(classes={},next_index=1)
        data = header + records_bytes(records,registry) + records_bytes(definitions,registry) + self._tail[2:]
        with Path(path).open('xb') as f:
            f.write(data)

    @classmethod
    def from_sample(cls, path):
        """確認済みテンプレート互換図面の要素をコピーする。原ヘッダー保持編集ではなく別経路。"""
        from writer.preserved import capture_source
        original_bytes,stored=capture_source(path)
        if stored['images']:raise ValueError('Template copy cannot preserve embedded image trailer; use CadDocument')
        source = read_document(path)
        if source['header']['version'] != 700 or source['diagnostics'] or source['validation']['has_unresolved']:
            raise ValueError('Unsupported or incomplete source')
        result = cls()
        layers, groups, name_table_end = template_layout_names(path)
        for g in range(16):
            result.set_group_name(g, groups[g])
            for layer in range(16):
                result.set_layer_name(g, layer, layers[g][layer])
        for group in range(16):
            result.set_group_scale(group, source['header']['layer_groups'][group]['scale'])
        expected_header = copy.deepcopy(result._template_header)
        expected_header['layer_groups'] = result.layer_groups
        # E045: standard pen COLORREF entries are interleaved with other
        # settings at 4100 + 8*i in the verified empty-name template.
        # Retain only these decoded colors; arbitrary header retention is
        # still unsupported. Check both byte layouts before accepting them.
        colors = source['header']['palette']['pen_colors']
        template_colors = expected_header['palette']['pen_colors']
        if len(colors) != 10 or len(template_colors) != 10:
            raise ValueError('Unsupported standard pen palette length')
        source_bytes = Path(path).read_bytes()
        header_bytes = bytearray(result._header)
        for index, (old, new) in enumerate(zip(template_colors, colors)):
            offset = 4100 + 8 * index
            source_offset = offset + name_table_end - NAME_TABLE_END
            if (type(new) is not int or not 0 <= new <= 0xffffff
                    or struct.unpack_from('<I', header_bytes, offset)[0] != old
                    or struct.unpack_from('<I', source_bytes, source_offset)[0] != new):
                raise ValueError('Unsupported standard pen palette layout')
            struct.pack_into('<I', header_bytes, offset, new)
        result._header = bytes(header_bytes)
        expected_header['palette']['pen_colors'] = list(colors)
        if source['header'] != expected_header:
            raise ValueError('Source header settings differ from template')
        referenced={e['def_number'] for e in source['entities'] if e['type']=='BLOCK'}
        for raw in source['block_defs']:
            if raw['is_referenced'] != (raw['number'] in referenced):
                raise ValueError('Template copy cannot preserve definition reference-state')
            children = cls()
            for record in raw['entities']:
                if record['type'] == 'BLOCK':
                    raise ValueError('Nested blocks are not yet supported')
                children._add_record(record)
            definition = result.add_block_definition(raw['name'],children.entities,
                number=raw['number'],timestamp=raw['timestamp'],compound_kind=None)
            definition.base = dict(raw['base'])
        metadata = {x['entity_index'] for x in source['metadata_settings']}
        # E049: changing Direct2D creates an off-sheet setting TEXT. Retain
        # this observed 0/1 condition instead of silently replacing it with 1.
        source_metadata = [record for index, record in enumerate(source['entities'])
                           if index in metadata]
        if len(source_metadata) == len(result._metadata):
            candidate = copy.deepcopy(source_metadata)
            normalized = copy.deepcopy(candidate)
            for index, (record, template) in enumerate(zip(normalized, result._metadata)):
                if (template['content'] == 'View_Direct2d = 1'
                        and record['content'] in ('View_Direct2d = 0', 'View_Direct2d = 1')):
                    record['content'] = template['content']
            if normalized == result._metadata:
                result._metadata = candidate
        for index, record in enumerate(source['entities']):
            if index in metadata:
                continue
            result._add_record(record)
        if Path(path).read_bytes()!=original_bytes:raise ValueError('Source changed during template copy')
        return result

    def _add_record(self, record):
        """既知の要素レコードを公開モデルに変換する。未知要素・未対応の寸法メンバーは拒否する。"""
        b = record['base']
        attributes = dict(color=b['pen_color'], linetype=b['pen_style'], width=b['pen_width'],
                          layer=b['layer'], layer_group=b['layer_group'], group=b['group'], flag=b['flag'])
        if record['type'] == 'LINE':
            self.add_line((record['start_x'],record['start_y']), (record['end_x'],record['end_y']), **attributes)
        elif record['type'] in ('CIRCLE', 'ARC'):
            self.add_circle((record['center_x'], record['center_y']), record['radius'],
                              start_angle=record['start_angle'], arc_angle=record['arc_angle'],
                              tilt_angle=record['tilt_angle'], flatness=record['flatness'],
                              is_full_circle=record['is_full_circle'], **attributes)
        elif record['type'] == 'POINT':
            style = attributes.pop('linetype')
            if style != (100 if record['code'] else 1):
                raise ValueError('Unsupported point pen style/code combination')
            self.add_point((record['x'], record['y']),
                             is_temporary=record['is_temporary'], code=record['code'],
                             angle=record['angle'], scale=record['scale'], **attributes)
        elif record['type'] == 'TEXT':
            attributes['alignment'] = attributes.pop('linetype')
            self.add_text((record['start_x'], record['start_y']),
                            (record['end_x'], record['end_y']), record['content'],
                            text_type=record['text_type'], size_x=record['size_x'],
                            size_y=record['size_y'], spacing=record['spacing'],
                            angle=record['angle'], font_name=record['font_name'],
                            **attributes)
        elif record['type'] == 'BLOCK':
            self.add_block(record['def_number'],(record['ref_x'],record['ref_y']),
                           scale_x=record['scale_x'],scale_y=record['scale_y'],
                           rotation=record['rotation'],**attributes)
        elif record['type'] == 'SOLID':
            value = record['color']
            rgb = None
            if b['pen_color'] == 10:
                if type(value) is not int or not 0 <= value <= 0xffffff:
                    raise ValueError('Unsupported solid COLORREF high byte')
                rgb = (value & 255, value >> 8 & 255, value >> 16 & 255)
            elif value is not None:
                raise ValueError('Unexpected palette solid color payload')
            self.add_solid([(record[f'point{i}_x'],record[f'point{i}_y']) for i in range(1,5)],rgb=rgb,**attributes)
        elif record['type'] == 'DIMENSION':
            def member(raw):
                b = raw['base']
                attrs = dict(color=b['pen_color'],width=b['pen_width'],layer=b['layer'],
                             layer_group=b['layer_group'],group=b['group'],flag=b['flag'])
                if raw['type'] == 'LINE':
                    return Line((raw['start_x'],raw['start_y']),(raw['end_x'],raw['end_y']),linetype=b['pen_style'],**attrs)
                if raw['type'] == 'TEXT':
                    return Text((raw['start_x'],raw['start_y']),(raw['end_x'],raw['end_y']),raw['content'],
                                **{k:raw[k] for k in ('text_type','size_x','size_y','spacing','angle','font_name')},
                                alignment=b['pen_style'],**attrs)
                if raw['type'] == 'POINT':
                    if b['pen_style'] != (100 if raw['code'] else 1):
                        raise ValueError('Unsupported dimension point style')
                    return Point((raw['x'],raw['y']),**{k:raw[k] for k in ('is_temporary','code','angle','scale')},**attrs)
                raise ValueError('Unsupported dimension member')
            self.add_dimension(member(record['line']),member(record['text']),
                aux_lines=[member(r) for r in record['aux_lines']],
                aux_points=[member(r) for r in record['aux_points']],sxf_mode=record['sxf_mode'],**attributes)
        else:
            raise ValueError('Unsupported entity for constrained Writer')

    @classmethod
    def from_cad_document(cls, document):
        """テンプレート互換の共通モデルだけをコピーする。任意の既存図面はCadDocument.saveを使う。"""
        if document.diagnostics or document.includes_metadata:
            raise ValueError('Incomplete or metadata-inclusive common model cannot be saved')
        if Path(document.source).read_bytes()!=document._source_bytes:raise ValueError('Source changed since opening')
        source = read_document(document.source)
        if document.version != 700 or document.header != source['header']:
            raise ValueError('Common-model header edits are not supported')
        result = cls.from_sample(document.source)
        result.entities.clear()
        result.block_definitions.clear()
        originals={d['number']:d for d in document._source_records['block_defs']}
        referenced={e.geometry['def_number'] for e in document.entities if e.entity_type=='BLOCK'}
        for definition in document.block_definitions:
            children = cls()
            for entity in definition.entities:
                if entity.entity_type == 'BLOCK':
                    raise ValueError('Nested blocks are not yet supported')
                children._add_record(dict(entity.geometry,type=entity.entity_type,base=dict(entity.attributes)))
            original=originals.get(definition.number,document._new_block_records.get(definition.number))
            if original is None:raise ValueError('Unmanaged definition has no verified storage attributes')
            if definition.number in originals and original['is_referenced']!=(definition.number in referenced):
                raise ValueError('Template copy cannot preserve definition reference-state')
            block = result.add_block_definition(definition.name,children.entities,
                        number=definition.number,timestamp=original['timestamp'],compound_kind=None)
            block.base = dict(definition.attributes)
        for entity in document.entities:
            if 'type' in entity.geometry or 'base' in entity.geometry:
                raise ValueError('Geometry may not override entity type or attributes')
            record = dict(entity.geometry, type=entity.entity_type, base=dict(entity.attributes))
            result._add_record(record)
        if Path(document.source).read_bytes()!=document._source_bytes:raise ValueError('Source changed during template copy')
        return result

    @classmethod
    def open(cls, path):
        """Open a supported basic drawing into the constrained template Writer."""
        return cls.from_sample(path)

    @classmethod
    def from_line_sample(cls, path):
        """Copy a LINE-only sample for compatibility with the original prototype API."""
        result = cls.from_sample(path)
        if any(not isinstance(entity, Line) for entity in result.entities):
            raise ValueError('Only LINE drawings can be copied by this compatibility method')
        return result
