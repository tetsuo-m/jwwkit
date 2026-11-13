from dataclasses import dataclass
from .base import BASE_KEYS
from jwwkit.writer.strings import cstring


@dataclass
class BlockDefinition:
    number: int
    name: str
    entities: list
    timestamp: int = 0
    base: dict = None

    def record(self, referenced):
        """既知のブロック定義をレコード化する。入れ子参照は拒否する。"""
        if type(self.number) is not int or not 0 <= self.number <= 0xffffffff:
            raise ValueError('Definition number must be uint32')
        if type(self.timestamp) is not int or not 0 <= self.timestamp <= 0xffffffff:
            raise ValueError('Definition timestamp must be uint32')
        cstring(self.name)
        children = [e.record() for e in self.entities]
        if any(e['type'] == 'BLOCK' for e in children):
            raise ValueError('Nested block definitions are not yet supported')
        return dict(
            type='BLOCK_DEF',
            base=self.base or dict(zip(BASE_KEYS, (0, 1, 2, 0, 0, 0, 0))),
            number=self.number,
            is_referenced=referenced,
            timestamp=self.timestamp,
            name=self.name,
            entities=children,
        )
