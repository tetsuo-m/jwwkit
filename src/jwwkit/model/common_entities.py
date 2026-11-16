"""共通CAD要素の属性・幾何と原レコードを保持する。原レコードは編集後も元資料として残す。"""
from __future__ import annotations
from dataclasses import dataclass, field
import copy
from typing import Any, Mapping


@dataclass(frozen=True)
class CadEntity:
    entity_type: str
    attributes: Mapping[str, Any]
    geometry: Mapping[str, Any]
    raw: Mapping[str, Any]
    source_index: int | None = field(default=None, repr=False, compare=False)


def model_entity(raw, *, source_index=None):
    """既知レコードを共通モデルに変換する。未知属性の意味は補完しない。"""
    return CadEntity(raw['type'],dict(raw.get('base',{})),
        {k:v for k,v in raw.items() if k not in ('type','base')},copy.deepcopy(raw),source_index)


_IMMUTABLE = (int, float, str, bool, bytes, type(None))


def _own(value):
    return value if type(value) in _IMMUTABLE else copy.deepcopy(value)


def _owned_entity(raw, *, source_index=None):
    """model_entity for a record that the caller owns and nobody else references (#25).

    Used only by CadDocument.open for freshly read records. The record itself becomes the
    entity's raw record; attributes and geometry get their own copies of every container, so
    raw, attributes and geometry never share a mutable object (the same as model_entity).
    """
    return CadEntity(raw['type'], {k: _own(v) for k, v in raw.get('base', {}).items()},
        {k: _own(v) for k, v in raw.items() if k not in ('type', 'base')}, raw, source_index)


@dataclass(frozen=True)
class CadBlockDefinition:
    number: int
    name: str
    attributes: Mapping[str, Any]
    entities: tuple[CadEntity, ...]

    @property
    def name_info(self):
        """Read-only name interpretation; .name remains the exact stored name."""
        from .block_names import block_name_info
        return block_name_info(self.name)
