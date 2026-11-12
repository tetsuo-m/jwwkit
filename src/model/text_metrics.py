"""E080: stored JWW text endpoints, not a font glyph/ink bounding box.

Jw_cad 10.03.6 counts UTF-16 code units. ASCII and halfwidth katakana
consume half a cell; other units consume one. Inter-character spacing is
weighted by the PRECEDING character, and no spacing follows the last unit.
Only the explicitly verified ordinary-text domain is accepted.
"""
import math

VERIFIED_FONTS = frozenset(('ＭＳ ゴシック', 'ＭＳ 明朝', 'ＭＳ Ｐゴシック', 'Arial'))


def _finite(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    return value


def text_advance(content, *, size_x=2.5, spacing=0.0):
    """Return the ordinary-text baseline advance in paper mm.

    This does not interpret JWW control strings, distribution markers or
    newlines. Reject those rather than silently using a glyph-width guess.
    """
    if not isinstance(content, str) or not content:
        raise ValueError('Automatic endpoint requires nonempty text')
    if '^' in content or content.endswith(('・', '･')):
        raise ValueError('JWW text controls/distribution markers require an explicit endpoint')
    if any(ord(c) < 32 or 0x7f <= ord(c) < 0xa0 for c in content):
        raise ValueError('Control characters are not supported by automatic endpoints')
    width = _finite(size_x, 'size_x')
    gap = _finite(spacing, 'spacing')
    if width <= 0 or width+gap <= 0:
        raise ValueError('Text width and width+spacing must be positive')
    try:
        encoded = content.encode('utf-16le', errors='strict')
    except UnicodeEncodeError as exc:
        raise ValueError('Unpaired UTF-16 surrogate is not supported') from exc
    units = [encoded[i] | encoded[i+1] << 8 for i in range(0, len(encoded), 2)]
    cells = [0.5 if u < 0x80 or 0xff61 <= u <= 0xff9f else 1.0 for u in units]
    advance = width*sum(cells) + gap*sum(cells[:-1])
    if not math.isfinite(advance) or advance <= 0:
        raise ValueError('Computed text advance is not finite and positive')
    return advance


def text_endpoint(start, content, *, size_x=2.5, size_y=2.5, spacing=0.0,
                  angle=0.0, font_name='ＭＳ ゴシック', alignment=1):
    """Calculate an ordinary TEXT endpoint; angle is degrees, coordinates paper mm.

    Alignment does not relocate the stored start point. This calculation is
    neither a text bounding box nor a measurement of the rendered font.
    """
    if not isinstance(font_name, str) or font_name not in VERIFIED_FONTS:
        raise ValueError('Font not verified for automatic endpoints; use an explicit endpoint')
    if type(alignment) is not int or not 1 <= alignment <= 9:
        raise ValueError('Automatic endpoint alignment must be 1..9')
    point = tuple(start)
    if len(point) != 2:
        raise ValueError('Text start requires two coordinates')
    x, y = (_finite(v, 'start') for v in point)
    if _finite(size_y, 'size_y') <= 0:
        raise ValueError('size_y must be positive')
    radians = math.radians(_finite(angle, 'angle'))
    advance = text_advance(content, size_x=size_x, spacing=spacing)
    result = (x+advance*math.cos(radians), y+advance*math.sin(radians))
    if not all(math.isfinite(v) for v in result):
        raise ValueError('Computed text endpoint is not finite')
    return result


def record_endpoint(geometry, attributes):
    """Guard dimension/style-bearing text before opt-in recalculation."""
    if attributes.get('pen_width', 0) != 0 or attributes.get('flag', 0) != 0:
        raise ValueError('Flagged/dimension text requires an explicit endpoint')
    return text_endpoint((geometry['start_x'], geometry['start_y']), geometry['content'],
                         **{k: geometry[k] for k in ('size_x','size_y','spacing','angle','font_name')},
                         alignment=attributes['pen_style'])
