from dataclasses import dataclass
import math
from .base import entity_base


@dataclass
class Circle:
    center: tuple[float, float]
    radius: float
    start_angle: float = 0.0
    arc_angle: float = 2 * math.pi
    tilt_angle: float = 0.0
    flatness: float = 1.0
    is_full_circle: bool = True
    color: int = 2
    linetype: int = 1
    width: int = 0
    layer: int = 0
    layer_group: int = 0
    group: int = 0
    flag: int = 0

    def record(self):
        """確認済み属性から要素レコードを作る。未知の構造は対応しない。"""
        values = (*self.center, self.radius, self.start_angle, self.arc_angle,
                  self.tilt_angle, self.flatness)
        if len(self.center) != 2 or not all(math.isfinite(x) for x in values):
            raise ValueError('Finite circle parameters required')
        if self.radius < 0 or not 0 <= self.layer < 16 or not 0 <= self.layer_group < 16:
            raise ValueError('Radius must be non-negative and layer/group must be 0..15')
        if not isinstance(self.is_full_circle, bool):
            raise ValueError('is_full_circle must be bool')
        return {
            'type': 'CIRCLE' if self.is_full_circle else 'ARC',
            'base': entity_base(self, self.linetype),
            'center_x': self.center[0],
            'center_y': self.center[1],
            'radius': self.radius,
            'start_angle': self.start_angle,
            'arc_angle': self.arc_angle,
            'tilt_angle': self.tilt_angle,
            'flatness': self.flatness,
            'is_full_circle': self.is_full_circle,
        }
