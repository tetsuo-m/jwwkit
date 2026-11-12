"""Strict reader for observed JWS schemas 230/351/420/600/700.

Header offsets are separately measured in JWS. No fabricated JWW header.
The raw body must round-trip exactly, including strings and class references.
"""
import copy
import hashlib
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

from .archive import Cursor, RecordError, read_entity_sequences
from model.common_entities import model_entity, CadBlockDefinition

# E091: identical in all 116 business JWS700 files. Meaning is unproven;
# retain it verbatim and refuse other patterns rather than interpreting it.
JWS700_RESERVED = struct.pack('<6I6d', *range(1, 7), *range(1, 7))


@dataclass(frozen=True)
class JwsDocument:
    source: Path | None
    version: int
    base_point: tuple
    group_scales: tuple
    bounds: tuple
    reserved: bytes
    entities: tuple
    block_definitions: tuple
    sha256: str
    _bytes: bytes = field(repr=False)
    _records: dict = field(repr=False)

    @property
    def records(self):
        """Independent copy of every stored entity/definition field."""
        return copy.deepcopy(self._records)

    @classmethod
    def open(cls, path):
        source = Path(path)
        return cls.from_bytes(source.read_bytes(), source=source)

    @classmethod
    def from_bytes(cls, data, *, source=None):
        c = Cursor(bytes(data))
        try:
            if c.take(200) != b'JwsData.' + b'.'*192:
                raise RecordError('Invalid or unobserved JWS signature/header')
            version, = c.unpack('<I')
            if version not in (230, 351, 420, 600, 700):
                raise RecordError('Unsupported JWS version')
            origin = c.unpack('<dd')
            scales = c.unpack('<16d')
            reserved = c.take(72)
            if version in (230,700) and reserved != JWS700_RESERVED:
                raise RecordError(f'Unobserved JWS{version} reserved header pattern')
            bounds = c.unpack('<4d')
            if not all(math.isfinite(x) for x in (*origin, *scales, *bounds)):
                raise RecordError('Nonfinite JWS header value')
            if any(x <= 0 for x in scales):
                raise RecordError('JWS scales must be positive')
            if bounds[0] > bounds[2] or bounds[1] > bounds[3]:
                raise RecordError('Inverted JWS bounds')
            entities, definitions, _ = read_entity_sequences(c, version)
            if c.pos != len(data):
                raise RecordError('Unsupported JWS trailer')
            if any(d['type'] != 'BLOCK_DEF' for d in definitions):
                raise RecordError('Non-definition record in JWS definition table')
            if any(e['type'] == 'BLOCK_DEF' for e in entities):
                raise RecordError('Definition record in JWS drawing sequence')
            numbers = [d['number'] for d in definitions]
            if len(numbers) != len(set(numbers)):
                raise RecordError('Duplicate JWS definition number')
            def validate(items):
                for item in items:
                    base = item['base']
                    if not (0 <= base['layer'] < 16 and 0 <= base['layer_group'] < 16):
                        raise RecordError('Invalid JWS layer/group')
                    def finite(value):
                        if isinstance(value, float) and not math.isfinite(value):
                            raise RecordError('Nonfinite JWS payload')
                        if isinstance(value, dict):
                            for v in value.values(): finite(v)
                        elif isinstance(value, list):
                            for v in value: finite(v)
                    finite(item)
                    if item['type'] == 'BLOCK' and item['def_number'] not in numbers:
                        raise RecordError('Unresolved JWS block reference')
                    if item['type'] == 'BLOCK_DEF':
                        if any(e['type'] == 'BLOCK_DEF' for e in item['entities']):
                            raise RecordError('Embedded JWS definition record')
                        validate(item['entities'])
            validate(entities + definitions)
            edges = {d['number']: [e['def_number'] for e in d['entities']
                                  if e['type'] == 'BLOCK'] for d in definitions}
            visiting, visited = set(), {}
            def acyclic(n, depth=0):
                if depth > 128: raise RecordError('JWS reference depth exceeds 128')
                if n in visiting: raise RecordError('Cyclic JWS block reference')
                if n in visited: return visited[n]
                visiting.add(n)
                height=1+max((acyclic(child, depth+1) for child in edges[n]),default=0)
                if height>128:raise RecordError('JWS reference depth exceeds 128')
                visiting.remove(n); visited[n]=height
                return height
            for n in edges: acyclic(n)
            from writer.mfc import records_bytes
            registry = dict(classes={}, next_index=1)
            body = records_bytes(entities, registry, version=version, encoding='cp932')
            body += records_bytes(definitions, registry, version=version, encoding='cp932')
            if body != data[452:]:
                raise RecordError('JWS body cannot be reproduced without loss')
            return cls(source, version, origin, scales, bounds, reserved,
                       tuple(model_entity(e) for e in entities),
                       tuple(CadBlockDefinition(d['number'], d['name'], dict(d['base']),
                                               tuple(model_entity(e) for e in d['entities']))
                             for d in definitions),
                       hashlib.sha256(data).hexdigest(), bytes(data),
                       dict(entities=copy.deepcopy(entities), block_defs=copy.deepcopy(definitions)))
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise RecordError(f'{exc}; JWS offset={c.pos}; element={c.context}') from exc

    def to_bytes(self):
        """Re-serialize every stored record with the original validated header.

        This read-only API does not edit header fields or delete unused definitions.
        Original CString bytes and shared MFC class references are retained.
        """
        from writer.mfc import records_bytes
        registry = dict(classes={}, next_index=1)
        body = records_bytes(self._records['entities'], registry, version=self.version, encoding='cp932')
        body += records_bytes(self._records['block_defs'], registry, version=self.version, encoding='cp932')
        return self._bytes[:452] + body

    def place_as_block(self, document, name, position, *, layer_group=0,
                       units='paper', layer=0, layer_priority=True):
        """Place at stored base point, preserving each source group's real size.

JWS700 nested references are flattened with composed affine transforms.
Unused stored definitions remain available on this reader but are not imported.
Unproven flag-bit2 combinations are refused atomically.
"""
        from dataclasses import replace
        from model.block_operations import inverse_record, number, RecordChild
        if type(layer_priority) is not bool:
            raise TypeError('Layer priority must be bool')
        if not self.entities:
            raise ValueError('Empty JWS figure')
        if type(layer_group) is not int or not 0 <= layer_group < 16:
            raise ValueError('Layer group must be 0..15')
        target_scale = document.get_group_scale(layer_group)
        origin = self.base_point
        if self.version == 700:
            from .jws_placement import flatten
            children = flatten(self, target_scale)
        else:
            children = []
            for record in self._records['entities']:
                ratio = self.group_scales[record['base']['layer_group']] / target_scale
                children.append(inverse_record(record, origin, 0, 1/ratio, 1/ratio))
        position = document.convert_point(position, layer_group=layer_group,
                                          from_units=units, to_units='paper')
        number(position[0], 'x'); number(position[1], 'y')
        staged = replace(document, _new_block_records=copy.deepcopy(document._new_block_records))
        if any(d.name_info.display_name == name for d in staged.block_definitions):
            raise ValueError('JWS import name already exists')
        definition = staged.add_block_definition(name, [RecordChild(x) for x in children], compound_kind=4)
        ref = staged.place_block(definition.number, position, layer_group=layer_group, layer=layer)
        staged.set_block_layer_priority(len(staged.entities)-1, layer_priority)
        document.entities = staged.entities
        document.block_definitions = staged.block_definitions
        document._new_block_records = staged._new_block_records
        return document.entities[-1]
