from dataclasses import dataclass
import math
from .base import entity_base


@dataclass
class Point:
    position: tuple[float, float]
    is_temporary: bool = False
    code: int = 0
    angle: float = 0.0
    scale: float = 0.0
    color: int = 2
    width: int = 0
    layer: int = 0
    layer_group: int = 0
    group: int = 0
    flag: int = 0

    def record(self):
        """確認済み属性から要素レコードを作る。未知の構造は対応しない。"""
        values = (*self.position, self.angle, self.scale)
        if len(self.position) != 2 or not all(math.isfinite(x) for x in values):
            raise ValueError('Finite point parameters required')
        if not isinstance(self.is_temporary, bool) or self.code < 0:
            raise ValueError('Point flag must be bool and code must be non-negative')
        if not 0 <= self.layer < 16 or not 0 <= self.layer_group < 16:
            raise ValueError('Layer/group must be 0..15')
        # CDataTen stores ordinary points with pen style 1 and marker points
        # with pen style 100, followed by code/angle/scale.
        pen_style = 100 if self.code else 1
        return {
            'type': 'POINT',
            'base': entity_base(self, pen_style),
            'x': self.position[0],
            'y': self.position[1],
            'is_temporary': self.is_temporary,
            'code': self.code,
            'angle': self.angle,
            'scale': self.scale,
        }
