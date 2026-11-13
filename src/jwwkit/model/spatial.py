"""確認済み幾何の矩形検索。字体・記号・ブロックの外形は推測しない。"""
import math

TAU = 2 * math.pi


def inside(point, rect):
    return rect[0] <= point[0] <= rect[2] and rect[1] <= point[1] <= rect[3]


def segment_intersects(start, end, rect):
    """線分を閉矩形でクリップする。点・接触・矩形内線分も含める。"""
    low, high = 0.0, 1.0
    for a, b, minimum, maximum in zip(start, end, rect[:2], rect[2:]):
        delta = b - a
        if delta == 0:
            if not minimum <= a <= maximum:
                return False
            continue
        first, last = sorted(((minimum - a) / delta, (maximum - a) / delta))
        low, high = max(low, first), min(high, last)
        if low > high:
            return False
    return True


def ellipse_matches(geometry, rect, mode):
    """E057確認済み楕円式の端点・極値・矩形辺との交点を解析的に判定。"""
    cx, cy = geometry['center_x'], geometry['center_y']
    radius, flatness, tilt = geometry['radius'], geometry['flatness'], geometry['tilt_angle']
    if radius <= 0 or flatness <= 0:
        raise ValueError('退化した円・楕円の形状検索は保留・要相談です')
    full = geometry.get('is_full_circle', False)
    start = geometry['start_angle']
    sweep = TAU if full else geometry['arc_angle']
    # E074実務図面の真円負角11件は、DXFの始終角入替と一致。
    if sweep < 0 and flatness == 1:
        start += sweep
        sweep = -sweep
    if not 0 < sweep <= TAU:
        raise ValueError('負角楕円弧等の未対応円弧角の形状矩形検索は拒否します')
    a, b = radius * math.cos(tilt), -radius * flatness * math.sin(tilt)
    c, d = radius * math.sin(tilt), radius * flatness * math.cos(tilt)

    def on_arc(angle):
        return full or (angle - start) % TAU <= sweep + 1e-12

    def point(angle):
        co, si = math.cos(angle), math.sin(angle)
        return cx + a * co + b * si, cy + c * co + d * si

    endpoints = (point(start), point(start + sweep))
    if mode == 'contained':
        angles = [start, start + sweep]
        for u, v in ((a, b), (c, d)):
            extremum = math.atan2(v, u)
            angles.extend(t for t in (extremum, extremum + math.pi) if on_arc(t))
        return all(inside(point(t), rect) for t in angles)
    if any(inside(p, rect) for p in endpoints):
        return True
    # x(t)またはy(t)を矩形辺と等置し、残りの座標が辺上かを検証する。
    for center, u, v, boundaries, axis in (
        (cx, a, b, (rect[0], rect[2]), 0),
        (cy, c, d, (rect[1], rect[3]), 1),
    ):
        amplitude = math.hypot(u, v)
        phase = math.atan2(v, u)
        for boundary in boundaries:
            ratio = (boundary - center) / amplitude
            if not -1 <= ratio <= 1:
                continue
            offset = math.acos(ratio)
            for angle in (phase - offset, phase + offset):
                if not on_arc(angle):
                    continue
                other = point(angle)[1 - axis]
                if rect[1 - axis] <= other <= rect[3 - axis]:
                    return True
    return False


def matches(entity, rect, mode):
    """円は輪郭、点はコードなしの位置。非対応は漏れなく明示して拒否する。"""
    kind, geometry = entity.entity_type, entity.geometry
    # 文字とブロックは全モードで挿入点のみ判定する（ユーザー確定仕様）。
    if kind in ('TEXT', 'BLOCK'):
        keys = ('start_x', 'start_y') if kind == 'TEXT' else ('ref_x', 'ref_y')
        return inside(tuple(geometry[key] for key in keys), rect)
    if kind == 'LINE':
        start = (geometry['start_x'], geometry['start_y'])
        end = (geometry['end_x'], geometry['end_y'])
        if mode == 'contained':
            return inside(start, rect) and inside(end, rect)
        return segment_intersects(start, end, rect)
    if kind == 'POINT' and geometry['code'] == 0:
        return inside((geometry['x'], geometry['y']), rect)
    if kind in ('CIRCLE', 'ARC'):
        return ellipse_matches(geometry, rect, mode)
    raise ValueError(f'未対応の形状矩形検索は拒否します: type={kind}, source_index={entity.source_index}')
