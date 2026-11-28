"""既存要素の編集。未確認の形状・符号の意味を推測して編集しない。"""
from dataclasses import replace
import math

from .common_entities import model_entity
from jwwkit.writer.preserved import entity_record

SUPPORTED = {'LINE', 'CIRCLE', 'ARC', 'POINT', 'TEXT', 'BLOCK', 'SOLID', 'CIRCLE_SOLID', 'DIMENSION'}


def element(document, index):
    """公開要素番号を検証する。負番号・boolによる意図しない選択は拒否。"""
    if type(index) is not int or not 0 <= index < len(document.entities):
        raise IndexError('要素番号が範囲外です')
    return document.entities[index]


def commit(document, index, original, record):
    """原レコードと関連付けを残し、編集後の属性・幾何だけ更新する。"""
    document._validate_addition(record)
    updated = model_entity(record)
    result = replace(original, attributes=updated.attributes, geometry=updated.geometry)
    entities = list(document.entities)
    entities[index] = result
    document.entities = tuple(entities)
    return result


def delete_entity(document, index):
    original = element(document, index)
    document.entities = document.entities[:index] + document.entities[index + 1:]
    return original



def selection(document, indices):
    """編集前の公開番号を検証する。重複指定は二重移動を避けるため拒否する。"""
    indices = tuple(indices)
    for index in indices:
        element(document, index)
    if len(set(indices)) != len(indices):
        raise ValueError('要素番号の重複は指定できません')
    return indices


def delete_entities(document, indices):
    """選択した要素を一括削除する。原定義と対象外ペイロードを保持する。"""
    indices = selection(document, indices)
    removed = tuple(document.entities[index] for index in indices)
    selected = set(indices)
    document.entities = tuple(entity for index, entity in enumerate(document.entities)
                              if index not in selected)
    return removed


def move_entities(document, indices, delta, *, units='paper'):
    """明示選択を原子的に移動。別レコードの寸法引出線を推測で選択しない。"""
    indices = selection(document, indices)
    # 元の文書へ確定するのは全要素の検証・変換が成功した後だけ。
    staged = replace(document)
    moved = tuple(move_entity(staged, index, delta, units=units) for index in indices)
    document.entities = staged.entities
    return moved


def children(record):
    return [record['line'], record['text'], *record['aux_lines'], *record['aux_points']]


AUX_COORDINATE_MESSAGE = ('補助線・補助点に座標がある寸法図形は、この形の変更に対応していません'
                          '（Jw_cadでの動きを確かめていないため）。Jw_cadで操作してください')
AUX_KEYS = ('start_x', 'start_y', 'end_x', 'end_y')


def aux_coordinates(record):
    """#73: for an SXF-mode-0 dimension, 'none' when every auxiliary line/point is all 0 (the Jw_cad samples),
    'all' when every one has a coordinate that is not 0 (the Archicad export resaved by Jw_cad, #69), else 'mixed'.
    None for other records."""
    if record['type'] != 'DIMENSION' or record['sxf_mode'] != 0:
        return None
    flags = ([any(a[k] != 0 for k in AUX_KEYS) for a in record['aux_lines']]
             + [p['x'] != 0 or p['y'] != 0 for p in record['aux_points']])
    return 'none' if not any(flags) else 'all' if all(flags) else 'mixed'


def refuse_aux_coordinate_dimension(record):
    """#73: refuse a geometry change of a dimension whose auxiliaries carry coordinates, before anything changes."""
    if aux_coordinates(record) in ('all', 'mixed'):
        raise ValueError(AUX_COORDINATE_MESSAGE)


def translate_aux(record, delta):
    """#73: Jw_cad 10.03.6 moves the auxiliary lines/points of such a dimension with its line in a move/copy
    (tests/fixtures/archicad_dimensions, ac2_move and ac2_copy). Only the 'all' shape was seen; 'mixed' is refused."""
    shape = aux_coordinates(record)
    if shape == 'mixed':
        raise ValueError(AUX_COORDINATE_MESSAGE)
    if shape == 'all':
        for a in record['aux_lines']:
            a['start_x'] += delta[0]; a['start_y'] += delta[1]; a['end_x'] += delta[0]; a['end_y'] += delta[1]
        for p in record['aux_points']:
            p['x'] += delta[0]; p['y'] += delta[1]


def jwcad_dimension_move(document, record, layer_group=None):
    """Jw_cadの寸法図形で、群・層の変更が外側の記録だけを書き換えると確かめた形か（#62）。

    Jw_cad 10.03.6 の見本（文字種1～10、v700）では、範囲選択の属性変更は寸法の外側の群・層だけを変え、
    寸法線・文字・補助線・補助点の群・層・印は変えなかった。確かめた形は、外側の印8192か8194
    （8194はJw_cadで一度移した寸法。もう一度移しても、元の場所へ戻しても同じ決まりだった）、
    寸法線8192・文字16400・補助0の印、補助線・補助点の座標が全部0、中の部品が全部同じ1つの群・層
    （外側と同じか、移して外側と別になったもの）、関わる群の縮尺が全部同じ、のものに限る。
    Jw_cadが移すときに足す外側の印の2は、jwwkitは書かない（印はそのまま残す）。
    """
    if (document.version != 700 or record['type'] != 'DIMENSION' or record['sxf_mode'] != 0
            or not 1 <= record['text']['text_type'] <= 10 or record['base']['flag'] not in (8192, 8194)):
        return False
    aux = [*record['aux_lines'], *record['aux_points']]
    if (record['line']['base']['flag'] != 8192 or record['text']['base']['flag'] != 16400
            or any(c['base']['flag'] != 0 for c in aux)):
        return False
    if not (all(all(c[k] == 0 for k in ('start_x', 'start_y', 'end_x', 'end_y')) for c in record['aux_lines'])
            and all(c['x'] == c['y'] == 0 for c in record['aux_points'])):
        return False
    slots = {(c['base']['layer_group'], c['base']['layer']) for c in children(record)}
    if len(slots) != 1:
        return False
    groups = {record['base']['layer_group'], next(iter(slots))[0]}
    if layer_group is not None:
        groups.add(layer_group)
    return len({document.get_group_scale(g) for g in groups}) == 1


def transform(record, factor, delta):
    """保存値を一様拡大＋平行移動する。角度・フラグ・文字内容は変えない。"""
    kind = record['type']
    if kind not in SUPPORTED:
        raise ValueError(f'未確認形状は移動・縮尺換算できません: type={kind}')
    if kind == 'CIRCLE_SOLID':
        from .circular_solid import validate_circular_solid
        validate_circular_solid(record)
        record['center_x'] = record['center_x'] * factor + delta[0]
        record['center_y'] = record['center_y'] * factor + delta[1]
        record['radius'] *= factor
        if record['base']['pen_style']==105:record['solid_mode']*=factor
        validate_circular_solid(record)
        return
    if factor != 1 and kind == 'TEXT' and record['text_type'] != 0:
        raise ValueError('文字種付き文字の異縮尺実寸保持は保留・要相談です')
    if kind == 'DIMENSION':
        if factor != 1:
            # Scale conversions (group change keeping real size, group import): unverified in Jw_cad (#73).
            refuse_aux_coordinate_dimension(record)
        elif delta[0] != 0 or delta[1] != 0:
            translate_aux(record, delta)
        members=[record['line'],record['text']] if record['sxf_mode']==0 else children(record)
        for child in members:
            transform(child, factor, delta)
        return
    point_keys = {
        'LINE': [('start_x', 'start_y'), ('end_x', 'end_y')],
        'TEXT': [('start_x', 'start_y'), ('end_x', 'end_y')],
        'CIRCLE': [('center_x', 'center_y')],
        'ARC': [('center_x', 'center_y')],
        'POINT': [('x', 'y')],
        'BLOCK': [('ref_x', 'ref_y')],
        'SOLID': [(f'point{i}_x', f'point{i}_y') for i in (1, 2, 3, 4)],
    }
    for x_key, y_key in point_keys[kind]:
        record[x_key] = record[x_key] * factor + delta[0]
        record[y_key] = record[y_key] * factor + delta[1]
    if kind in ('CIRCLE', 'ARC'):
        record['radius'] *= factor
    elif kind == 'TEXT':
        for key in ('size_x', 'size_y', 'spacing'):
            record[key] *= factor
    elif kind == 'BLOCK':
        record['scale_x'] *= factor
        record['scale_y'] *= factor
    # コード付き点のscaleは記号倍率。意味未確認のため一様換算時は拒否する。
    elif kind == 'POINT' and record['code'] and factor != 1:
        raise ValueError('コード付き点の異縮尺実寸保持は未対応のため拒否します')
    if any(isinstance(v, float) and not math.isfinite(v) for v in record.values()):
        raise ValueError('換算後の値が有限ではありません')


def move_entity(document, index, delta, *, units='paper'):
    original = element(document, index)
    paper = document.convert_point(delta, layer_group=original.attributes['layer_group'],
                                   from_units=units, to_units='paper')
    record = entity_record(original)
    transform(record, 1, paper)
    return commit(document, index, original, record)


def uint(value, maximum, label):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f'{label}は0～{maximum}の整数で指定してください')
    return value


def set_entity_attributes(document, index, *, color=None, linetype=None,
                          width=None, layer=None, layer_group=None, preserve='paper'):
    original = element(document, index)
    from .preflight import color_code,linetype_code
    if color is not None:color=color_code(document,color,rgb=original.entity_type in ('SOLID','CIRCLE_SOLID'))
    if linetype is not None and original.entity_type not in ('TEXT','POINT','BLOCK','CIRCLE_SOLID'):
        linetype=linetype_code(document,linetype)
    if preserve not in ('paper', 'real'):
        raise ValueError('preserveはpaperまたはrealを指定してください')
    updates = {}
    for key, value, limit in [('pen_color', color, 65535), ('pen_width', width, 65535),
                              ('layer', layer, 15), ('layer_group', layer_group, 15)]:
        if value is not None:
            updates[key] = uint(value, limit, key)
    if linetype is not None:
        updates['pen_style'] = uint(linetype, 255, 'linetype')
    record = entity_record(original)
    if record['type'] not in SUPPORTED:
        raise ValueError('未確認形状の属性編集は保留・要相談です')
    if record['type'] == 'CIRCLE_SOLID':
        from .circular_solid import validate_circular_solid
        validate_circular_solid(record)
        if linetype is not None and linetype != record['base']['pen_style']:
            raise ValueError('Circular solids require their fixed storage style')
    if linetype is not None and record['type'] in ('TEXT', 'POINT', 'BLOCK'):
        raise ValueError('TEXT/POINT/BLOCKの線種変更は未対応のため拒否します')
    # 寸法文字のpen_width=8259等は設定を兼ねる。線幅として上書きしない。
    if width is not None and record['type'] in ('TEXT', 'DIMENSION'):
        raise ValueError('TEXT/DIMENSIONの線幅変更は未対応のため拒否します')
    # E111: native group-only control preserves all 56 preset1 dimensions at
    # equal scales. Only the outer group changes; embedded member attributes
    # remain intact. Do not apply the GUI selection-flag changes to any record.
    preset_group_only = (record['type']=='DIMENSION' and record['text']['text_type']==1
        and document.version==700 and layer_group is not None
        and all(v is None for v in (color,linetype,width,layer))
        and document.get_group_scale(original.attributes['layer_group'])==document.get_group_scale(layer_group)
        and record['base']['flag'] in (0,2)
        and record['sxf_mode']==0
        and all(all(c[k]==0 for k in ('start_x','start_y','end_x','end_y')) for c in record['aux_lines'])
        and all(c['x']==c['y']==0 for c in record['aux_points'])
        and all(record[k]['base']['layer_group']==record['base']['layer_group'] for k in ('line','text')))
    # #62: a Jw_cad dimension figure of the observed shapes moves by its outer group/layer only, as Jw_cad does.
    # Other shapes (aux coordinates, other member flags, other outer flags, unequal scales, ...) stay refused.
    outer_move = (record['type'] == 'DIMENSION' and record['text']['text_type'] != 0 and not preset_group_only
                  and (layer is not None or layer_group is not None)
                  and jwcad_dimension_move(document, record, layer_group))
    # Historical mixed-attribute preset2 -> 0 control is still unresolved.
    # Other presets, unequal scales and combined overrides remain refused.
    if record['type'] == 'DIMENSION' and record['text']['text_type'] != 0 and not preset_group_only:
        if color is not None or (layer_group is not None and not outer_move):
            raise ValueError('文字種付き寸法の色・グループ変更は未対応のため拒否します')
        if layer is not None and not outer_move:
            raise ValueError('文字種付き寸法の層変更は、Jw_cadで確かめた形の寸法図形に限ります')
    if layer_group is not None and preserve == 'real' and not preset_group_only and not outer_move:
        factor = (document.get_group_scale(original.attributes['layer_group'])
                  / document.get_group_scale(layer_group))
        transform(record, factor, (0, 0))
    targets = [record] + (children(record) if record['type'] == 'DIMENSION' and not preset_group_only else [])
    for target in targets:
        for key, value in updates.items():
            if key == 'pen_style' and target['type'] in ('TEXT', 'POINT'):
                continue
            if outer_move and target is not record and key in ('layer', 'layer_group'):
                continue
            if key == 'pen_color' and target['type'] in ('SOLID', 'CIRCLE_SOLID'):
                if (value == 10) != (target.get('color') is not None):
                    raise ValueError('任意色ソリッド形式への切替は保留・要相談です')
            target['base'][key] = value
    if record['type'] == 'CIRCLE_SOLID':validate_circular_solid(record)
    return commit(document, index, original, record)


def find_entities(document, *, layer=None, layer_group=None, entity_type=None,
                  block_name=None, text=None, rect=None, units='paper', rect_mode='anchor',color=None,linetype=None):
    """返す番号は現在の公開要素列の番号。削除後の古い番号は無効になる。"""
    from .preflight import color_code,linetype_code
    if color is not None:color=color_code(document,color,rgb=True)
    if linetype is not None:linetype=linetype_code(document,linetype)
    for value, label in ((layer, 'layer'), (layer_group, 'layer_group')):
        if value is not None:
            uint(value, 15, label)
    if entity_type is not None and not isinstance(entity_type, str):
        raise TypeError('entity_typeは文字列で指定してください')
    for value in (block_name, text):
        if value is not None and not isinstance(value, str):
            raise TypeError('検索文字は文字列で指定してください')
    if units not in ('paper', 'real'):
        raise ValueError('unitsはpaperまたはrealを指定してください')
    if rect_mode not in ('anchor', 'intersects', 'contained'):
        raise ValueError('rect_modeはanchor、intersects、containedを指定してください')
    if rect is not None:
        rect = tuple(rect)
        if (len(rect) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in rect)
                or rect[0] > rect[2] or rect[1] > rect[3]):
            raise ValueError('rectは有限のxmin,ymin,xmax,ymaxで指定してください')
    names = {definition.number: definition.name for definition in document.block_definitions}
    result = []
    for index, entity in enumerate(document.entities):
        if color is not None and entity.attributes['pen_color']!=color:continue
        if linetype is not None and (entity.entity_type not in ('LINE','CIRCLE','ARC','SOLID','DIMENSION') or entity.attributes['pen_style']!=linetype):continue
        if layer is not None and entity.attributes['layer'] != layer:
            continue
        if layer_group is not None and entity.attributes['layer_group'] != layer_group:
            continue
        if entity_type is not None and entity.entity_type != entity_type.upper():
            continue
        if block_name is not None:
            if entity.entity_type != 'BLOCK' or names.get(entity.geometry['def_number']) != block_name:
                continue
        if text is not None:
            if entity.entity_type == 'TEXT':
                content = entity.geometry['content']
            elif entity.entity_type == 'DIMENSION':
                content = entity.geometry['text']['content']
            else:
                continue
            if text not in content:
                continue
        if rect is not None and rect_mode != 'anchor':
            from .spatial import matches
            scale = document.get_group_scale(entity.attributes['layer_group']) if units == 'real' else 1
            paper_rect = tuple(v / scale for v in rect)
            try:
                match = matches(entity, paper_rect, rect_mode)
            except ValueError as exc:
                raise ValueError(f'{exc}; index={index}; source_index={entity.source_index}') from exc
            if not match:
                continue
        elif rect is not None:
            # 範囲検索は保存された基準点の包含。字体の実外形は推測しない。
            geometry = entity.geometry
            kind = entity.entity_type
            if kind == 'DIMENSION':
                geometry = geometry['line']
                kind = 'LINE'
            keys = {'LINE': ('start_x', 'start_y'), 'TEXT': ('start_x', 'start_y'),
                    'CIRCLE': ('center_x', 'center_y'), 'ARC': ('center_x', 'center_y'),
                    'POINT': ('x', 'y'), 'BLOCK': ('ref_x', 'ref_y'),
                    'SOLID': ('point1_x', 'point1_y')}
            if kind not in keys:
                raise ValueError(f'未確認形状の基準点検索は保留・要相談: type={kind}')
            point = tuple(geometry[k] for k in keys[kind])
            x, y = document.convert_point(point, layer_group=entity.attributes['layer_group'], to_units=units)
            if not (rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]):
                continue
        result.append(index)
    return tuple(result)
