"""確認済みの要素共通属性順。未知属性の追加は行わない。"""
BASE_KEYS = ('group', 'pen_style', 'pen_color', 'pen_width', 'layer', 'layer_group', 'flag')


def entity_base(entity, pen_style):
    """確認済みの共通属性を保存順で並べる。要素固有の検証・未知属性の補完は行わない。"""
    return {
        'group': entity.group,
        'pen_style': pen_style,
        'pen_color': entity.color,
        'pen_width': entity.width,
        'layer': entity.layer,
        'layer_group': entity.layer_group,
        'flag': entity.flag,
    }
