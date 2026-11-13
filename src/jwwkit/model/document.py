"""Small common CAD model used by the experimental JWW adapter.

The model deliberately keeps geometry payloads explicit while
leaving unsupported JWW-specific fields in ``raw`` for later investigation.
Existing documents retain their original header bytes when saved separately.
New documents use the separate JwwDocument template writer.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
import copy
import math
from pathlib import Path
from typing import Any, Mapping

from jwwkit.reader.archive import read_document
from jwwkit.model.common_entities import CadEntity, CadBlockDefinition, model_entity








@dataclass
class CadDocument:
    source: Path
    version: int
    header: Mapping[str, Any]
    entities: tuple[CadEntity, ...]
    metadata_settings: tuple[Mapping[str, Any], ...]
    diagnostics: tuple[Any, ...]
    includes_metadata: bool = False
    block_definitions: tuple[CadBlockDefinition, ...] = ()
    _source_bytes: bytes | None = field(default=None, repr=False, compare=False)
    _source_records: Mapping[str, Any] | None = field(default=None, repr=False, compare=False)
    _source_header: Mapping[str, Any] | None = field(default=None, repr=False, compare=False)
    _source_metadata_indices: tuple[int, ...] = field(default=(), repr=False, compare=False)
    _group_scale_edits: dict[int, float] = field(default_factory=dict, repr=False, compare=False)
    _state_edits: dict[tuple[int, int | None], int] = field(default_factory=dict, repr=False, compare=False)

    _name_edits: dict[int, str] = field(default_factory=dict, repr=False, compare=False)
    _new_block_records: dict[int, Mapping[str, Any]] = field(default_factory=dict, repr=False, compare=False)
    _readonly_state: Mapping[str, Any] | None = field(default=None, repr=False, compare=False)

    @classmethod
    def open(cls, path: str | Path, *, include_metadata: bool = False, schema_profile: str = 'strict') -> "CadDocument":
        """strict既定で原ヘッダー・本文を保持する。rebro_schema0は読取り/無編集別名保存のみ。"""
        source = Path(path)
        from jwwkit.writer.preserved import capture_source
        source_bytes, source_records = capture_source(source, schema_profile=schema_profile)
        parsed = read_document(source, schema_profile=schema_profile)
        if source.read_bytes() != source_bytes:
            raise ValueError('読込み中に原ファイルが変更されました。再度開いてください')
        metadata_indices = {item['entity_index'] for item in parsed['metadata_settings']}
        entities: list[CadEntity] = []
        for index, raw in enumerate(parsed['entities']):
            if not include_metadata and index in metadata_indices:
                continue
            entities.append(model_entity(raw, source_index=index))
        blocks = tuple(CadBlockDefinition(d['number'],d['name'],dict(d['base']),
                       tuple(model_entity(e) for e in d['entities'])) for d in parsed['block_defs'])
        return cls(source=source, version=parsed['header']['version'],
                   header=parsed['header'], entities=tuple(entities),
                   metadata_settings=tuple(parsed['metadata_settings']),
                   diagnostics=tuple(parsed['diagnostics']), includes_metadata=include_metadata,
                   block_definitions=blocks, _source_bytes=source_bytes,
                   _source_records=source_records, _source_header=copy.deepcopy(parsed['header']),
                   _source_metadata_indices=tuple(sorted(metadata_indices)),
                   _readonly_state=copy.deepcopy(dict(header=parsed['header'],
                       metadata_settings=tuple(parsed['metadata_settings']), diagnostics=tuple(parsed['diagnostics']),
                       includes_metadata=include_metadata, _source_metadata_indices=tuple(sorted(metadata_indices))))
                       if schema_profile == 'rebro_schema0' else None)

    def save(self, path: str | Path) -> None:
        """既知v600/v700図面を別名保存する。ヘッダー編集は縮尺・名称・確認済み表示状態APIに対応。"""
        from jwwkit.writer.preserved import save_document
        save_document(self, path)

    def _require_editable(self):
        if self._source_records and self._source_records.get('schema_profile') == 'rebro_schema0':
            raise ValueError('rebro_schema0 is read-only; editing is not yet supported')

    def get_sxf_colors(self, *, include_unnamed=False):
        """SXF色の名前・番号・表示/印刷RGB・生幅・点半径を独立コピーで読む。"""
        if type(include_unnamed) is not bool:raise TypeError('include_unnamed must be bool')
        from jwwkit.reader.sxf import read_sxf_tables
        colors,_=read_sxf_tables(self._source_bytes,self._source_records['header_end'])
        return colors if include_unnamed else [r for r in colors if r['name'] and not r['reserved']]

    def get_sxf_linetypes(self, *, include_unnamed=False):
        """SXF線種の名前・番号・保存パターン・区間数と長さを読む。"""
        if type(include_unnamed) is not bool:raise TypeError('include_unnamed must be bool')
        from jwwkit.reader.sxf import read_sxf_tables
        _,styles=read_sxf_tables(self._source_bytes,self._source_records['header_end'])
        return styles if include_unnamed else [r for r in styles if r['name'] and not r['reserved']]

    def get_sxf_color(self, value):
        """SXF色を数値コード/一致する名前で読む。欠落・同名複数は拒否。"""
        from jwwkit.reader.sxf import select_definition
        return select_definition(self.get_sxf_colors(include_unnamed=True),value)

    def get_sxf_linetype(self, value):
        """SXF線種を数値コード/一致する名前で読む。編集許可の判定ではない。"""
        from jwwkit.reader.sxf import select_definition
        return select_definition(self.get_sxf_linetypes(include_unnamed=True),value)

    def delete_entity(self, index):
        """指定した公開要素だけ削除する。ブロック定義は自動削除しない。"""
        self._require_editable()
        from jwwkit.model.editing import delete_entity
        return delete_entity(self, index)

    def delete_entities(self, indices):
        """編集前の公開番号で一括削除する。番号不正・重複時は何も変更しない。"""
        self._require_editable()
        from jwwkit.model.editing import delete_entities
        return delete_entities(self, indices)

    def move_entities(self, indices, delta, *, units='paper'):
        """明示選択した関連要素を一体移動する。自動関連付けは行わない。"""
        self._require_editable()
        from jwwkit.model.editing import move_entities
        return move_entities(self, indices, delta, units=units)

    def move_entity(self, index, delta, *, units='paper'):
        """既知9種類を平行移動する。寸法の値メンバーは一括で移動する。"""
        self._require_editable()
        from jwwkit.model.editing import move_entity
        return move_entity(self, index, delta, units=units)

    def transform_entities(self, indices, **options):
        """原子的な複写／回転／反転／倍率変換。属性・非対象・定義は保持する。"""
        self._require_editable()
        from jwwkit.model.transformations import transform_entities
        return transform_entities(self, indices, **options)

    def copy_entities(self, indices, delta=(0,0), *, units='paper'):
        self._require_editable()
        from jwwkit.model.transformations import copy_entities
        return copy_entities(self, indices, delta, units=units)

    def align_two_points(self, indices, source_points, target_points, *, distance_tolerance,
                         angle_tolerance, angle_units='rad', allow_scale=False):
        """実寸2点対で位置合わせする。許容超過は無変更、表現不能は原子的に拒否。"""
        self._require_editable()
        from jwwkit.alignment import solve_two_point_alignment
        result = solve_two_point_alignment(source_points, target_points,
            distance_tolerance=distance_tolerance, angle_tolerance=angle_tolerance,
            angle_units=angle_units, allow_scale=allow_scale)
        if result['passed']:
            self.transform_entities(indices, **result['transform'])
        return result

    def rotate_entities(self, indices, angle, **options):
        self._require_editable()
        from jwwkit.model.transformations import rotate_entities
        return rotate_entities(self, indices, angle, **options)

    def reflect_entities(self, indices, **options):
        self._require_editable()
        from jwwkit.model.transformations import reflect_entities
        return reflect_entities(self, indices, **options)

    def scale_entities(self, indices, scale_x, scale_y=None, **options):
        self._require_editable()
        from jwwkit.model.transformations import scale_entities
        return scale_entities(self, indices, scale_x, scale_y, **options)

    def set_entity_attributes(self, index, *, color=None, linetype=None,
                              width=None, layer=None, layer_group=None, preserve='paper'):
        """共通属性を変更する。異縮尺グループ変更は実寸/紙面保持を選択する。"""
        self._require_editable()
        from jwwkit.model.editing import set_entity_attributes
        return set_entity_attributes(self, index, color=color, linetype=linetype,
                                     width=width, layer=layer, layer_group=layer_group,
                                     preserve=preserve)

    def find_entities(self, *, layer=None, layer_group=None, entity_type=None,
                      block_name=None, text=None, rect=None, units='paper', rect_mode='anchor',
                      color=None, linetype=None, query=None):
        """属性・種類・保存されたブロック名・文字部分一致で公開要素番号を返す。"""
        from jwwkit.model.query import find
        return find(self, layer=layer, layer_group=layer_group,
                             entity_type=entity_type, block_name=block_name, text=text, rect=rect, units=units,
                             rect_mode=rect_mode,color=color,linetype=linetype,query=query)

    def search_entities(self, query, *, scope='drawing', limits=None):
        """JSON条件で読み取り検索し、対象識別子・実効条件・完全性を返す。"""
        from jwwkit.model.query import search
        return search(self,query,scope=scope,limits=limits)

    def set_text(self, index: int, content: str, *, recalculate_end: bool = False) -> None:
        """本文を変更する。recalculate_end=Trueで確認済み通常文字の終点も原子的に再計算。"""
        self._require_editable()
        if not isinstance(content, str):
            raise TypeError('文字列を指定してください')
        from jwwkit.model.editing import element
        entity = element(self,index)
        if entity.entity_type != 'TEXT':
            raise ValueError(f'文字要素ではありません: index={index}')
        geometry = dict(entity.geometry, content=content)
        if recalculate_end:
            from jwwkit.model.text_metrics import record_endpoint
            geometry['end_x'], geometry['end_y'] = record_endpoint(geometry, entity.attributes)
        self._validate_addition(dict(geometry,type='TEXT',base=dict(entity.attributes)))
        entities = list(self.entities)
        entities[index] = replace(entity, geometry=geometry)
        self.entities = tuple(entities)

    def recalculate_text_endpoint(self, index: int) -> None:
        """本文・属性・始点を保ち、確認済み通常文字の終点だけを再計算する。"""
        self._require_editable()
        from jwwkit.model.editing import element
        entity = element(self,index)
        if entity.entity_type != 'TEXT':
            raise ValueError(f'文字要素ではありません: index={index}')
        self.set_text(index, entity.geometry['content'], recalculate_end=True)

    def get_group_scale(self, layer_group: int) -> float:
        """全16グループの縮尺分母を読む。不正な縮尺は補正せず拒否する。"""
        from jwwkit.writer.header import group_index, scale_value
        return scale_value(self.header['layer_groups'][group_index(layer_group)]['scale'])

    def set_group_scale(self, layer_group: int, scale: float) -> None:
        """縮尺分母を設定する。既存要素の紙面位置は変えず、実寸は変わる。"""
        self._require_editable()
        from jwwkit.writer.header import group_index, scale_value, scale_offsets
        index = group_index(layer_group)
        value = scale_value(scale)
        scale_offsets(self._source_bytes, self._source_header['layer_groups'])
        self.header['layer_groups'][index]['scale'] = value
        self._group_scale_edits[index] = value

    def convert_point(self, point, *, layer_group=0, from_units='paper', to_units='real'):
        """図面中心原点を保ち紙面mmと実寸mmを換算する。DXF原点移動は含めない。"""
        if from_units not in ('paper', 'real') or to_units not in ('paper', 'real'):
            raise ValueError('unitsはpaperまたはrealを指定してください')
        values = tuple(point)
        if len(values) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError('座標は有限の数2個を指定してください')
        scale = self.get_group_scale(layer_group)
        factor = 1 if from_units == to_units else (scale if from_units == 'paper' else 1 / scale)
        result = tuple(v * factor for v in values)
        if not all(math.isfinite(v) for v in result):
            raise ValueError('換算後の座標が有限ではありません')
        return result

    def line_points(self, index, *, units='paper'):
        """線の両端を紙面mmまたは実寸mmで返す。他の要素型は未対応。"""
        entity = self.entities[index]
        if entity.entity_type != 'LINE':
            raise ValueError(f'線要素ではありません: index={index}')
        geometry = entity.geometry
        return tuple(self.convert_point((geometry[f'{side}_x'], geometry[f'{side}_y']),
                     layer_group=entity.attributes['layer_group'], to_units=units)
                     for side in ('start', 'end'))

    def add_line(self, start, end, *, layer_group=0, units='paper', **attributes) -> CadEntity:
        """線を紙面mmまたは実寸mmで追加する。保存値は紙面mm。"""
        self._require_editable()
        from jwwkit.model.line import Line
        from jwwkit.model.preflight import attributes as resolve
        attributes=resolve(self,attributes,'LINE')
        start = self.convert_point(start, layer_group=layer_group, from_units=units, to_units='paper')
        end = self.convert_point(end, layer_group=layer_group, from_units=units, to_units='paper')
        record = Line(start, end, layer_group=layer_group, **attributes).record()
        self._validate_addition(record)
        entity = model_entity(record)
        self.entities += (entity,)
        return entity

    def add_text(self, start, end=None, content=None, *, layer_group=0, units='paper', **attributes) -> CadEntity:
        """文字を追加。end省略で自動計算。unitsは位置だけ、幅・高さ・間隔は紙面mm。"""
        self._require_editable()
        from jwwkit.model.text import Text
        from jwwkit.model.preflight import attributes as resolve
        attributes=resolve(self,attributes,'TEXT')
        start = self.convert_point(start, layer_group=layer_group, from_units=units, to_units='paper')
        if end is None:
            from jwwkit.model.text_metrics import record_endpoint
            prototype = Text(start, start, content, layer_group=layer_group, **attributes).record()
            end = record_endpoint(prototype, prototype['base'])
        else:
            end = self.convert_point(end, layer_group=layer_group, from_units=units, to_units='paper')
        entity = model_entity(Text(start, end, content, layer_group=layer_group, **attributes).record())
        self._validate_addition(entity.raw)
        self.entities += (entity,)
        return entity

    def get_text_preset(self, text_type: int) -> dict[str, Any]:
        """原図面の文字種1〜10の幅・高さ・間隔・色を読む。フォント設定は含まない。"""
        from jwwkit.reader.text_presets import read_text_presets
        if type(text_type) is not int or not 1 <= text_type <= 10:
            raise ValueError('文字種は1〜10を指定してください')
        presets = read_text_presets(self._source_bytes, self._source_records['header_end'], self.version)
        return presets[text_type - 1]

    def add_circle(self, center, radius, *, layer_group=0, units='paper',
                   flatness=1.0, tilt_angle=0.0, **attributes) -> CadEntity:
        """真円・楕円を追加する。中心と半径は指定単位、扁平率は正、傾きはラジアン。"""
        self._require_editable()
        from jwwkit.model.circle import Circle
        from jwwkit.model.preflight import attributes as resolve
        attributes=resolve(self,attributes,'CIRCLE')
        if {'start_angle', 'arc_angle', 'is_full_circle'} & attributes.keys():
            raise ValueError('add_circleは全周円専用です。円弧にはadd_arcを使用してください')
        if type(flatness) not in (int, float) or not math.isfinite(flatness) or flatness <= 0:
            raise ValueError('扁平率は有限の正の数を指定してください')
        center = self.convert_point(center, layer_group=layer_group, from_units=units, to_units='paper')
        radius = self.convert_point((radius, 0), layer_group=layer_group,
                                    from_units=units, to_units='paper')[0]
        entity = model_entity(Circle(center, radius, flatness=flatness, tilt_angle=tilt_angle,
                                     layer_group=layer_group, **attributes).record())
        self._validate_addition(entity.raw)
        self.entities += (entity,)
        return entity

    def add_point(self, position, *, layer_group=0, units='paper', **attributes) -> CadEntity:
        """点を追加する。unitsは位置に適用し、コード記号の角度・倍率は保存値で指定する。"""
        self._require_editable()
        from jwwkit.model.point import Point
        from jwwkit.model.preflight import attributes as resolve
        attributes=resolve(self,attributes,'POINT')
        position = self.convert_point(position, layer_group=layer_group, from_units=units, to_units='paper')
        entity = model_entity(Point(position, layer_group=layer_group, **attributes).record())
        self._validate_addition(entity.raw)
        self.entities += (entity,)
        return entity

    def add_solid(self, points, *, rgb=None, layer_group=0, units='paper', **attributes) -> CadEntity:
        """4保存頂点を追加（周回順1,3,2,4）。実寸換算・観測済みSXF色に対応。"""
        self._require_editable()
        from jwwkit.model.solid import Solid
        from jwwkit.model.preflight import attributes as resolve
        attributes=resolve(self,attributes,'SOLID')
        # Native-created E104 SXF polygons use 31; native resave uses 1.
        if attributes.get('color',2)>=100:attributes.setdefault('linetype',31)
        points=tuple(self.convert_point(p,layer_group=layer_group,from_units=units,to_units='paper') for p in points)
        entity=model_entity(Solid(points,rgb=rgb,layer_group=layer_group,**attributes).record())
        self._validate_addition(entity.raw);self.entities+=(entity,);return entity

    def add_circle_solid(self, center, radius, *, solid_mode=100., flatness=1.,
                         tilt_angle=0., start_angle=0., arc_angle=2*math.pi,
                         rgb=None, inner_radius=None, layer_group=0, units='paper', **attributes) -> CadEntity:
        """全円/弓形と、inner_radius指定の観測済み真円全周円環105を追加。角度rad、半径は指定単位。"""
        self._require_editable()
        from jwwkit.model.line import Line
        from jwwkit.model.circular_solid import validate_circular_solid
        from jwwkit.model.preflight import attributes as resolve
        attributes=resolve(self,attributes,'CIRCLE_SOLID')
        if 'linetype' in attributes:raise ValueError('Circular solids require fixed pen_style 101')
        center=self.convert_point(center,layer_group=layer_group,from_units=units,to_units='paper')
        radius=self.convert_point((radius,0),layer_group=layer_group,from_units=units,to_units='paper')[0]
        style=101
        if inner_radius is not None:
            if solid_mode!=100. or rgb is not None:raise ValueError('Ring radius and fill mode/RGB cannot be combined')
            solid_mode=self.convert_point((inner_radius,0),layer_group=layer_group,from_units=units,to_units='paper')[0]
            style=105
        base=Line(center,center,linetype=style,layer_group=layer_group,**attributes).record()['base']
        record=dict(type='CIRCLE_SOLID',base=base,center_x=center[0],center_y=center[1],radius=radius,
                    flatness=flatness,tilt_angle=tilt_angle,start_angle=start_angle,arc_angle=arc_angle,
                    solid_mode=solid_mode,color=rgb)
        validate_circular_solid(record);self._validate_addition(record)
        entity=model_entity(record);self.entities+=(entity,);return entity

    def _validate_addition(self, record):
        """新規要素の保存形式・数値範囲・文字符号化を追加前に検証する。"""
        from jwwkit.model.preflight import check
        check(self,record)

    def get_layer_name(self, layer_group, layer):
        """保存名（未保存の名称編集を含む）。表示用仮名は返さない。"""
        from jwwkit.model.summary import get_layer_name
        return get_layer_name(self, layer_group, layer)

    def get_group_name(self, layer_group):
        from jwwkit.model.summary import get_group_name
        return get_group_name(self, layer_group)

    def get_group_state(self, layer_group):
        """群の保存状態0非表示/1表示のみ/2編集可/3書込み選択を独立辞書で返す。"""
        from jwwkit.model.display_state import get_state
        return get_state(self,layer_group)

    def snapshot_group(self, layer_group):
        """群の全保存値・名前/状態/縮尺/保護・要素順序・参照定義閉包をSHA付きで捕捉する。"""
        from jwwkit.model.group_audit import snapshot_group
        return snapshot_group(self,layer_group)

    def audit_group_unchanged(self, layer_group, before):
        """事前スナップショットと厳密照合し、差分全欄を返す。差があればpassed=False。"""
        from jwwkit.model.group_audit import audit_group
        return audit_group(self,layer_group,before)

    def get_layer_state(self, layer_group, layer):
        """層の保存状態と、親群の表示/編集状態を合成した有効状態を読む。"""
        from jwwkit.model.display_state import get_state
        return get_state(self,layer_group,layer)

    def set_group_state(self, layer_group, state):
        """非書込み群をhidden/display_only/editableへ変更。書込み選択と保護欄は変更しない。"""
        self._require_editable()
        from jwwkit.model.display_state import set_state
        return set_state(self,layer_group,state)

    def set_layer_state(self, layer_group, layer, state):
        """非書込み層の表示状態だけ変更。親群の状態・書込み選択・保護欄は保持する。"""
        self._require_editable()
        from jwwkit.model.display_state import set_state
        return set_state(self,layer_group,state,layer)

    def summary(self):
        from jwwkit.model.summary import summarize
        return summarize(self)

    def write_summary(self, path):
        from jwwkit.model.summary import write_summary
        return write_summary(self, path)

    def set_layer_name(self, layer_group, layer, name):
        """確認済み272名称の指定レイヤだけ変更する。原CStringの符号化を保持する。"""
        self._require_editable()
        from jwwkit.writer.header import group_index, validate_name_edit
        group = group_index(layer_group)
        index = group_index(layer)
        slot = group * 16 + index
        validate_name_edit(self._source_bytes, self._source_records['layer_names'], slot, name)
        self.header['layer_groups'][group]['layers'][index]['name'] = name
        self._name_edits[slot] = name

    def set_group_name(self, layer_group, name):
        """確認済み272名称の指定グループ名だけ変更する。未変更名称は生バイト保持。"""
        self._require_editable()
        from jwwkit.writer.header import group_index, validate_name_edit
        group = group_index(layer_group)
        slot = 256 + group
        validate_name_edit(self._source_bytes, self._source_records['layer_names'], slot, name)
        self.header['layer_groups'][group]['name'] = name
        self._name_edits[slot] = name

    def add_block_definition(self, name, entities, *, timestamp=0, compound_kind=None):
        """入れ子なしの新規定義を追加する。子要素はLine/Circle等のモデル、座標は紙面mm。"""
        self._require_editable()
        from jwwkit.model.block_definition import BlockDefinition
        from jwwkit.model.block_names import definition_name
        name = definition_name(name, compound_kind)
        children = list(entities)
        if not children:
            raise ValueError('新規ブロックには1個以上の子要素が必要です')
        number = max((d.number for d in self.block_definitions), default=-1) + 1
        record = BlockDefinition(number, name, children, timestamp=timestamp).record(False)
        from jwwkit.model.preflight import normalize_record,check
        record=normalize_record(self,record)
        check(self,record,defined_numbers=set())
        # 旧版CP932で表現できない名称・不正な子属性は追加前に拒否する。
        from jwwkit.writer.mfc import payload_bytes
        from jwwkit.writer.preserved import validate_records
        validate_records(record['entities'], [], 'new_block.entities', set())
        payload_bytes(record, version=self.version, encoding=self._source_records['body_encoding'])
        definition = CadBlockDefinition(number, name, dict(record['base']),
                                        tuple(model_entity(e) for e in record['entities']))
        # 既存定義の日時・参照フラグは変えず、新規定義の全フィールドだけ保存する。
        self._new_block_records[number] = copy.deepcopy(record)
        self.block_definitions += (definition,)
        return definition

    def add_arc(self, center, radius, start_angle, arc_angle, *, layer_group=0,
                units='paper', **attributes) -> CadEntity:
        """円弧を追加する。中心・半径は指定単位、角度はラジアン。楕円変換は扱わない。"""
        self._require_editable()
        from jwwkit.model.circle import Circle
        from jwwkit.model.preflight import attributes as resolve
        attributes=resolve(self,attributes,'ARC')
        center = self.convert_point(center, layer_group=layer_group, from_units=units, to_units='paper')
        radius = self.convert_point((radius, 0), layer_group=layer_group,
                                    from_units=units, to_units='paper')[0]
        record = Circle(center, radius, start_angle=start_angle, arc_angle=arc_angle,
                        is_full_circle=False, layer_group=layer_group, **attributes).record()
        record['type'] = 'ARC'
        self._validate_addition(record)
        entity = model_entity(record)
        self.entities += (entity,)
        return entity

    def set_dimension_text(self, index: int, content: str) -> None:
        """既存寸法の表示文字だけ変更する。測定値・寸法位置の自動再計算はしない。"""
        self._require_editable()
        if not isinstance(content, str):
            raise TypeError('文字列を指定してください')
        from jwwkit.model.editing import element
        entity = element(self,index)
        if entity.entity_type != 'DIMENSION':
            raise ValueError(f'寸法要素ではありません: index={index}')
        geometry = dict(entity.geometry)
        geometry['text'] = dict(geometry['text'], content=content)
        self._validate_addition(dict(geometry,type='DIMENSION',base=dict(entity.attributes)))
        entities = list(self.entities)
        entities[index] = replace(entity, geometry=geometry)
        self.entities = tuple(entities)

    def place_block(self, def_number, position, *, layer_group=0, units='paper',
                    **attributes) -> CadEntity:
        """既存定義を配置する。位置は指定単位、倍率は無次元、回転はラジアン。入れ子の新規定義は未対応。"""
        self._require_editable()
        from jwwkit.model.block_reference import BlockReference
        from jwwkit.model.preflight import attributes as resolve
        attributes=resolve(self,attributes,'BLOCK')
        if type(def_number) is not int or not any(d.number == def_number for d in self.block_definitions):
            raise ValueError(f'既存ブロック定義がありません: number={def_number}')
        position = self.convert_point(position, layer_group=layer_group, from_units=units, to_units='paper')
        entity = model_entity(BlockReference(position, def_number, layer_group=layer_group,
                                            **attributes).record())
        self._validate_addition(entity.raw)
        self.entities += (entity,)
        return entity

    def block_reference_counts(self):
        """表示名別に図面直下の参照を集計する。定義内の参照は集計しない。"""
        from jwwkit.model.block_operations import block_reference_counts
        return block_reference_counts(self)

    def replace_entities_with_block(self, indices, name, **options):
        """選択要素を位置・定義内属性を保つ名前付きブロックへ原子的に置換する。"""
        self._require_editable()
        from jwwkit.model.block_operations import replace_entities_with_block
        return replace_entities_with_block(self, indices, name, **options)

    def get_block_layer_priority(self, index: int) -> bool:
        """Read the experimentally verified ordinary-reference layer priority."""
        from jwwkit.model.editing import element
        entity = element(self,index)
        if entity.entity_type != 'BLOCK':
            raise ValueError('Block reference required')
        at = entity.attributes
        if type(at['pen_style']) is not int or at['pen_style'] not in (0, 1, 2, 3, 64, 65, 66, 67) or at['pen_width'] != 0 or at['flag'] != 0:
            raise ValueError('Unverified block reference attributes; refusing interpretation')
        return bool(at['pen_style'] & 0x40)

    def set_block_layer_priority(self, index: int, enabled: bool) -> None:
        """Set verified ordinary-reference priority; definition and raw name stay intact."""
        self._require_editable()
        if type(enabled) is not bool:
            raise TypeError('enabled must be bool')
        self.get_block_layer_priority(index)
        entity = self.entities[index]
        style = (entity.attributes['pen_style'] & ~0x40) | (0x40 if enabled else 0)
        attributes = dict(entity.attributes, pen_style=style)
        record = dict(entity.geometry, type='BLOCK', base=attributes)
        self._validate_addition(record)
        entities = list(self.entities)
        entities[index] = replace(entity, attributes=attributes)
        self.entities = tuple(entities)

    @property
    def entity_counts(self) -> dict[str, int]:
        return dict(Counter(entity.entity_type for entity in self.entities))

    def import_group(self, path, source_group, target_group, *, sync_scale=False,
                     sync_group_name=True, sync_layer_names=True, block_renames=None,
                     settings_policy='strict'):
        """別JWWの指定群を全検証後に取込む。保持不能・衝突は全体を変更前拒否。"""
        self._require_editable()
        from jwwkit.model.group_import import prepare,global_settings_bytes
        from jwwkit.writer.preserved import _document_bytes
        candidate,receipt=prepare(self,path,source_group,target_group,sync_scale=sync_scale,
            sync_group_name=sync_group_name,sync_layer_names=sync_layer_names,block_renames=block_renames,
            settings_policy=settings_policy)
        serialized=_document_bytes(candidate)
        import hashlib
        original_globals=global_settings_bytes(self)
        candidate_globals=global_settings_bytes(candidate,serialized)
        if original_globals!=candidate_globals:
            raise ValueError('Import would change destination global settings bytes')
        receipt.update(destination_global_settings_preserved=True,
            destination_global_settings_sha256=hashlib.sha256(candidate_globals).hexdigest())
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=receipt['source_sha256']:
            raise ValueError('Import source changed before commit')
        if self.source.read_bytes()!=self._source_bytes:
            raise ValueError('Destination source changed before commit')
        for field in ('header','entities','block_definitions','_new_block_records','_name_edits','_group_scale_edits'):
            setattr(self,field,getattr(candidate,field))
        return receipt
