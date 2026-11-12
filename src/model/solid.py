from dataclasses import dataclass
import math
from .base import entity_base


@dataclass
class Solid:
    """Four native vertex slots; perimeter order is 1,3,2,4.

    rgb is an (R,G,B) tuple and requires native pen color 10. Other
    pen colors use the drawing palette and have no appended color value.
    """
    points: tuple
    rgb: tuple | None = None
    color: int = 2
    linetype: int | None = None
    width: int = 0
    layer: int = 0
    layer_group: int = 0
    group: int = 0
    flag: int = 0

    def record(self):
        """確認済み属性から要素レコードを作る。未知の構造は対応しない。"""
        if len(self.points) != 4 or any(len(p) != 2 for p in self.points):
            raise ValueError('Solid requires four native vertex slots')
        if not all(math.isfinite(v) for p in self.points for v in p):
            raise ValueError('Finite solid coordinates required')
        if type(self.color) is not int or not (1 <= self.color <= 10 or self.color in (102,104,110,112)):
            raise ValueError('Unobserved solid pen color')
        style=self.linetype if self.linetype is not None else (31 if self.color>=100 else 1)
        if self.color>=100:
            observed=(self.flag==0 and style in (1,31)) or (self.flag==2 and style==1)
            if not observed:raise ValueError('Unobserved SXF solid style/flag combination')
        if self.color == 10:
            if self.rgb is None or len(self.rgb) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in self.rgb):
                raise ValueError('Arbitrary solid color requires three uint8 RGB components')
            value = self.rgb[0] | self.rgb[1] << 8 | self.rgb[2] << 16
        else:
            if self.rgb is not None:
                raise ValueError('RGB requires native solid pen color 10')
            value = None
        if type(self.layer) is not int or type(self.layer_group) is not int or not 0 <= self.layer < 16 or not 0 <= self.layer_group < 16:
            raise ValueError('Layer/group must be integers 0..15')
        geometry = {f'point{i}_{axis}':p[j] for i,p in enumerate(self.points,1) for j,axis in enumerate(('x','y'))}
        return dict(
            type='SOLID',
            base=entity_base(self, style),
            color=value,
            **geometry,
        )
