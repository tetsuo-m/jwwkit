"""Read-only interpretation of the observed block-name suffix; never rewrite it."""
from dataclasses import dataclass

MARKER = '@@SfigorgFlag@@'


def definition_name(name: str, compound_kind: int | None) -> str:
    """Explicit new-definition suffix; None preserves the supplied raw name."""
    if not isinstance(name, str):
        raise TypeError('Block name must be a string')
    if compound_kind is None:
        return name
    if type(compound_kind) is not int or compound_kind not in (1, 2, 3, 4):
        raise ValueError('Verified compound kind must be an integer 1..4 or None')
    if MARKER in name:
        raise ValueError('Explicit compound kind requires a name without an existing marker')
    return name + MARKER + str(compound_kind)


@dataclass(frozen=True)
class BlockNameInfo:
    raw_name: str
    display_name: str
    compound_kind: int | None
    marker_status: str


def block_name_info(name: str) -> BlockNameInfo:
    """Recognize exactly one terminal marker 1..4; retain everything else verbatim.

    The code is a stored kind, not a guarantee of modern GUI behavior. It does
    not describe the separate source-layer-priority property of a reference.
    """
    if not isinstance(name, str):
        raise TypeError('Block name must be a string')
    if MARKER not in name:
        return BlockNameInfo(name, name, None, 'absent')
    head, tail = name.rsplit(MARKER, 1)
    if name.count(MARKER) == 1 and tail in ('1', '2', '3', '4'):
        return BlockNameInfo(name, head, int(tail), 'recognized')
    return BlockNameInfo(name, name, None, 'unrecognized')
