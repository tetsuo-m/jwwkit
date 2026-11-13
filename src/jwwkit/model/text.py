from dataclasses import dataclass
import math
from .base import entity_base


@dataclass
class Text:
    start: tuple[float, float]
    end: tuple[float, float]
    content: str
    text_type: int = 0
    size_x: float = 2.5
    size_y: float = 2.5
    spacing: float = 0.0
    angle: float = 0.0
    font_name: str = 'ＭＳ ゴシック'
    alignment: int = 1
    color: int = 2
    width: int = 0
    layer: int = 0
    layer_group: int = 0
    group: int = 0
    flag: int = 0

    def record(self):
        """確認済み属性から要素レコードを作る。未知の構造は対応しない。"""
        values = (*self.start, *self.end, self.size_x, self.size_y, self.spacing, self.angle)
        if len(self.start) != 2 or len(self.end) != 2 or not all(math.isfinite(x) for x in values):
            raise ValueError('Finite text parameters required')
        if not isinstance(self.content, str) or not isinstance(self.font_name, str):
            raise ValueError('Text content and font name must be strings')
        if not 0 <= self.layer < 16 or not 0 <= self.layer_group < 16:
            raise ValueError('Layer/group must be 0..15')
        # The template serializer uses pen_width as the dimension-setting flag.
        return {
            'type': 'TEXT',
            'base': entity_base(self, self.alignment),
            'start_x': self.start[0],
            'start_y': self.start[1],
            'end_x': self.end[0],
            'end_y': self.end[1],
            'text_type': self.text_type,
            'size_x': self.size_x,
            'size_y': self.size_y,
            'spacing': self.spacing,
            'angle': self.angle,
            'font_name': self.font_name,
            'content': self.content,
        }
