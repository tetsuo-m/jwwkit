from dataclasses import dataclass
import math
from .base import entity_base


@dataclass
class Line:
    start: tuple[float, float]
    end: tuple[float, float]
    color: int = 2
    linetype: int = 1
    width: int = 0
    layer: int = 0
    layer_group: int = 0
    group: int = 0
    flag: int = 0

    def record(self):
        """確認済み属性から要素レコードを作る。未知の構造は対応しない。"""
        if len(self.start) != 2 or len(self.end) != 2 or not all(math.isfinite(x) for x in (*self.start, *self.end)):
            raise ValueError('Finite 2D coordinates required')
        if not 0 <= self.layer < 16 or not 0 <= self.layer_group < 16:
            raise ValueError('Layer/group must be 0..15')
        return {
            'type': 'LINE',
            'base': entity_base(self, self.linetype),
            'start_x': self.start[0],
            'start_y': self.start[1],
            'end_x': self.end[0],
            'end_y': self.end[1],
        }
