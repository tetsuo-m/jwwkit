from dataclasses import dataclass, field
import math
from .base import entity_base
from .line import Line
from .text import Text
from .point import Point


@dataclass
class Dimension:
    """Explicit dimension members, not an automatic dimension calculator.

    sxf_mode=0 is observed. Its auxiliary members may be zero placeholders;
    the GUI fixture stores the visible extension lines and points separately.
    """
    line: Line
    text: Text
    aux_lines: list = field(default_factory=lambda: [Line((0,0),(0,0)) for _ in range(2)])
    aux_points: list = field(default_factory=lambda: [Point((0,0)) for _ in range(4)])
    sxf_mode: int = 0
    color: int = 2
    linetype: int = 1
    width: int = 0
    layer: int = 0
    layer_group: int = 0
    group: int = 0
    flag: int = 8192

    def record(self):
        """明示された寸法構成要素を保持する。寸法値の自動計算は行わない。"""
        if type(self.sxf_mode) is not int or self.sxf_mode != 0:
            raise ValueError('Only observed dimension SXF mode 0 is supported')
        if not isinstance(self.line, Line) or not isinstance(self.text, Text):
            raise ValueError('Dimension requires Line and Text members')
        if len(self.aux_lines) != 2 or any(not isinstance(x,Line) for x in self.aux_lines):
            raise ValueError('Dimension requires two auxiliary lines')
        if len(self.aux_points) != 4 or any(not isinstance(x,Point) for x in self.aux_points):
            raise ValueError('Dimension requires four auxiliary points')
        if not 0 <= self.layer < 16 or not 0 <= self.layer_group < 16:
            raise ValueError('Layer/group must be 0..15')
        return dict(
            type='DIMENSION',
            base=entity_base(self, self.linetype),
            line=self.line.record(),
            text=self.text.record(),
            sxf_mode=self.sxf_mode,
            aux_lines=[x.record() for x in self.aux_lines],
            aux_points=[x.record() for x in self.aux_points],
        )
