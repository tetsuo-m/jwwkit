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
    # Historical mixed-attribute preset2 -> 0 control is still unresolved.
    # Other presets, unequal scales and combined overrides remain refused.
    if (record['type'] == 'DIMENSION' and record['text']['text_type'] != 0
            and (color is not None or layer_group is not None) and not preset_group_only):
        raise ValueError('文字種付き寸法の色・グループ変更は未対応のため拒否します')
    if layer_group is not None and preserve == 'real' and not preset_group_only:
        factor = (document.get_group_scale(original.attributes['layer_group'])
                  / document.get_group_scale(layer_group))
        transform(record, factor, (0, 0))
    targets = [record] + (children(record) if record['type'] == 'DIMENSION' and not preset_group_only else [])
    for target in targets:
        for key, value in updates.items():
            if key == 'pen_style' and target['type'] in ('TEXT', 'POINT'):
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
