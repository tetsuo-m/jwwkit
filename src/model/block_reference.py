from dataclasses import dataclass
import math
from .base import entity_base


@dataclass
class BlockReference:
    position: tuple[float, float]
    def_number: int
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0  # radians
    color: int = 2
    linetype: int = 1
    width: int = 0
    layer: int = 0
    layer_group: int = 0
    group: int = 0
    flag: int = 0

    def record(self):
        """確認済み属性から要素レコードを作る。未知の構造は対応しない。"""
        values = (*self.position, self.scale_x, self.scale_y, self.rotation)
        if len(self.position) != 2 or not all(math.isfinite(x) for x in values):
            raise ValueError('Finite block transform required')
        if type(self.def_number) is not int or not 0 <= self.def_number <= 0xffffffff:
            raise ValueError('Block definition number must be uint32')
        if not 0 <= self.layer < 16 or not 0 <= self.layer_group < 16:
            raise ValueError('Layer/group must be 0..15')
        return dict(
            type='BLOCK',
            base=entity_base(self, self.linetype),
            ref_x=self.position[0],
            ref_y=self.position[1],
            scale_x=self.scale_x,
            scale_y=self.scale_y,
            rotation=self.rotation,
            def_number=self.def_number,
        )
