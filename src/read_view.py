"""Immutable inspection of current CadDocument values and SHA-bound source paths.

No geometry, editing, normalization, cursor or cross-drawing identity is added.
The private byte tuples are immutable; every public result is detached JSON data.
"""
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import uuid

from cad_model import CadDocument
from writer.preserved import entity_record

__all__ = ['create_read_view', 'resolve_file_reference']

_KINDS = {'LINE': 'line', 'CIRCLE': 'circle', 'ARC': 'arc', 'POINT': 'point',
          'TEXT': 'text', 'DIMENSION': 'dimension', 'BLOCK': 'block_reference',
          'SOLID': 'solid', 'CIRCLE_SOLID': 'circle_solid'}


def _pack(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def _unpack(value):
    return json.loads(value)


def _integer(value, upper, label):
    if type(value) is not int or not 0 <= value < upper:
        raise ValueError('Invalid ' + label)
    return value


def _path(value):
    if type(value) is not list or len(value) > 128:
        raise ValueError('child_path must be a list of at most 128 tokens')
    if any(type(x) not in (str, int) for x in value):
        raise ValueError('child_path accepts only typed field names and integer positions')
    return list(value)


def _follow(record, path, definitions):
    """Explicit grammar, no eval/getattr, rooted in a stored/current root record."""
    path = _path(path); trace = []; seen = set(); pos = 0
    while pos < len(path):
        kind = record['type']; field = path[pos]
        if kind == 'DIMENSION' and field in ('line', 'text'):
            record = record[field]; trace.append({'field': field}); pos += 1
        elif kind == 'DIMENSION' and field in ('aux_lines', 'aux_points'):
            if pos + 1 >= len(path): raise ValueError('Missing dimension child position')
            index = _integer(path[pos + 1], len(record[field]), 'dimension child position')
            record = record[field][index]; trace.append({'field': field, 'index': index}); pos += 2
        elif kind == 'BLOCK' and field == 'definition':
            if pos + 1 >= len(path): raise ValueError('Missing definition child position')
            number = record['def_number']
            if number in seen or len(seen) >= 64: raise ValueError('Cyclic or overdeep definition path')
            if number not in definitions: raise ValueError('Missing block definition for child_path')
            seen.add(number); definition = definitions[number]
            index = _integer(path[pos + 1], len(definition['entities']), 'definition child position')
            trace.append(dict(field='definition', definition_number=number, index=index,
                              saved_placement={k: record[k] for k in ('ref_x', 'ref_y', 'scale_x', 'scale_y', 'rotation')}))
            record = definition['entities'][index]; pos += 2
        else:
            raise ValueError('Unsupported child_path for ' + str(kind))
    return record, trace


def _definition_map(records):
    result = {}
    for record in records:
        _integer(record['number'], 1 << 32, 'definition number')
        if record['number'] in result: raise ValueError('Duplicate definition number')
        result[record['number']] = record
    return result


def _values(record):
    """Unformatted stored-unit fields, not world geometry or inferred attributes."""
    fields = {k: v for k, v in record.items() if k not in ('type', 'base')}
    result = dict(attributes=record.get('base', {}), fields=fields)
    for name in ('start', 'end', 'center', 'ref'):
        if name + '_x' in record and name + '_y' in record:
            result['position' if name == 'ref' else name] = [record[name + '_x'], record[name + '_y']]
    for name in ('radius', 'text_type', 'size_x', 'size_y', 'spacing', 'angle'):
        if name in record: result[name] = record[name]
    if record['type'] == 'TEXT': result['text'] = record['content']
    if record['type'] == 'DIMENSION': result['text'] = record.get('text', {}).get('content')
    return result


def _item(record, persisted, reference, header, root_group, trace, origin_relation):
    kind = _KINDS.get(record['type'], 'unknown')
    text = record.get('content') if record['type'] == 'TEXT' else record.get('text', {}).get('content') if record['type'] == 'DIMENSION' else None
    base = record.get('base', {}); values = _values(record)
    properties = [dict(key='kind', label='種類', value=kind)]
    for name, label in (('layer_group', '群番号'), ('layer', 'レイヤ番号'), ('pen_color', '保存線色番号'),
                        ('pen_style', '保存線種番号'), ('pen_width', '保存線幅値'), ('flag', '保存フラグ')):
        if name in base: properties.append(dict(key=name, label=label, value=str(base[name])))
    if text is not None: properties.append(dict(key='text', label='文字', value=text))
    scale = None
    if type(root_group) is int and 0 <= root_group < 16:
        scale = header['layer_groups'][root_group]['scale']
    placement = dict(coordinate_space='definition_local_paper_mm' if any(t['field'] == 'definition' for t in trace) else 'paper_mm',
                     root_layer_group=root_group, scale_denominator=scale, path=trace, geometry_transform_applied=False)
    pending = record if persisted is None or _pack(persisted) != _pack(record) else None
    return dict(ref=reference, kind=kind,
                bbox=dict(status='not_requested', value=None, reason='Geometry is implemented in U2, not U1'),
                text=text, properties=properties, values=values, values_basis='current_stored_units',
                placement=placement,
                storage=dict(state='not_saved' if persisted is None else 'modified' if pending is not None else 'persisted',
                             persisted_record=persisted, pending_record=pending, origin_relation=origin_relation),
                semantic=dict(kind=kind, placement=placement, geometry_status='not_requested'),
                display=dict(properties=properties), geometry_implemented=False)


@dataclass(frozen=True, slots=True)
class ReadView:
    """Factory-returned immutable snapshot. Indices identify this snapshot only."""
    view_id: str
    source_sha256: str
    model_sha256: str
    includes_metadata: bool
    version: int
    _source_path: str
    _profile: str
    _records: tuple
    _persisted: tuple
    _indices: tuple
    _definitions: tuple
    _origin_definitions: tuple
    _header: bytes
    _origin_header: bytes
    _metadata: bytes
    _diagnostics: bytes
    _kinds: tuple
    _layers: tuple
    _text_presets: bytes
    _source_header_bytes: bytes

    @property
    def entity_count(self):
        return len(self._records)

    def entity(self, element_index, *, child_path=None):
        """Return a detached item; child paths remain local and do not flatten shapes."""
        index = _integer(element_index, len(self._records), 'view element index')
        path = _path([] if child_path is None else child_path)
        root = _unpack(self._records[index]); persisted = _unpack(self._persisted[index]) if self._persisted[index] is not None else None
        record, trace = _follow(root, path, _definition_map(_unpack(x) for x in self._definitions)) if path else (root, [])
        if path and persisted is not None:
            try: persisted, _ = _follow(persisted, path, _definition_map(_unpack(x) for x in self._origin_definitions))
            except ValueError: persisted = None
        reference = dict(reference_schema=1, scope='view', view_id=self.view_id, element_index=index, child_path=path)
        return _item(record, persisted, reference, _unpack(self._header), root.get('base', {}).get('layer_group'), trace,
                     'same_source_path_not_identity' if path else 'source_record' if self._indices[index] is not None else 'new_record')

    def resolve(self, reference):
        """Resolve only an exact local-view reference; never reinterpret a file reference."""
        keys = {'reference_schema', 'scope', 'view_id', 'element_index', 'child_path'}
        if type(reference) is not dict or set(reference) != keys or type(reference['reference_schema']) is not int or reference['reference_schema'] != 1:
            raise ValueError('Invalid view reference')
        if reference['scope'] != 'view' or reference['view_id'] != self.view_id: raise ValueError('Reference belongs to a different view')
        return self.entity(reference['element_index'], child_path=reference['child_path'])

    def summary(self):
        """Count all snapshot roots, independently of the detail limit."""
        return dict(entity_count=len(self._records), kinds=dict(sorted(Counter(self._kinds).items())),
                    layers=[dict(layer_group=g, layer=l, count=n) for (g, l), n in sorted(Counter(self._layers).items())],
                    definitions=len(self._definitions), metadata_settings=len(_unpack(self._metadata)),
                    includes_metadata=self.includes_metadata)

    def entities(self, *, limit=100, mode='details'):
        """Bound returned root detail; count/summary avoid generating any item payload."""
        if type(limit) is not int or not 0 <= limit <= 1000: raise ValueError('limit must be an integer in 0..1000')
        if mode not in ('details', 'count', 'summary'): raise ValueError('Unknown read-view result mode')
        total = len(self._records); returned = min(limit, total) if mode == 'details' else 0
        return dict(schema_version=1, view_id=self.view_id, source_sha256=self.source_sha256,
                    model_sha256=self.model_sha256, mode=mode, total=total, returned=returned, limit=limit,
                    truncated=mode == 'details' and returned < total, details_omitted=mode != 'details',
                    items=[self.entity(i) for i in range(returned)],
                    summary=self.summary() if mode == 'summary' else None,
                    evaluation_complete=True, geometry_evaluated=False, continuation_implemented=False)

    def file_reference(self, element_index, *, child_path=None):
        """Issue a stateless reference only after comparing with the unchanged file model."""
        index = _integer(element_index, len(self._records), 'view element index')
        self.entity(index, child_path=child_path)  # validate the path before returning a reference
        if hashlib.sha256(Path(self._source_path).read_bytes()).hexdigest() != self.source_sha256:
            raise ValueError('Source SHA256 changed; file reference issuance refused')
        actual = create_read_view(CadDocument.open(self._source_path, include_metadata=self.includes_metadata, schema_profile=self._profile))
        if actual.source_sha256 != self.source_sha256 or actual.model_sha256 != self.model_sha256:
            raise ValueError('File references require the unchanged original model; edited views cannot use them')
        number = self._indices[index]
        if number is None: raise ValueError('Unsaved element has no stored record reference')
        return dict(reference_schema=1, scope='file', source_sha256=self.source_sha256,
                    numbering='stored_root_record_0', element_index=number,
                    child_path=_path([] if child_path is None else child_path), schema_profile=self._profile)


def create_read_view(source, *, include_metadata=None, schema_profile=None, max_snapshot_bytes=536870912, max_entities=1000000):
    """Freeze the current CadDocument without writing; no geometry or native-policy change."""
    if include_metadata is not None and type(include_metadata) is not bool: raise ValueError('include_metadata must be bool or None')
    if schema_profile not in (None, 'strict', 'rebro_schema0'): raise ValueError('Unknown schema_profile')
    if type(max_snapshot_bytes) is not int or max_snapshot_bytes < 1 or type(max_entities) is not int or max_entities < 1:
        raise ValueError('Snapshot limits must be positive integers')
    if isinstance(source, CadDocument):
        doc = source
        if include_metadata is not None and doc.includes_metadata != include_metadata:
            raise ValueError('include_metadata differs from the supplied model')
        if schema_profile is not None and doc._source_records.get('schema_profile', 'strict') != schema_profile:
            raise ValueError('schema_profile differs from the supplied model')
    else:
        doc = CadDocument.open(source, include_metadata=False if include_metadata is None else include_metadata,
                               schema_profile='strict' if schema_profile is None else schema_profile)
    if doc._source_bytes is None or doc._source_records is None: raise ValueError('A file-backed CadDocument is required')
    data = doc._source_bytes
    if Path(doc.source).read_bytes() != data: raise ValueError('Source file changed before view creation')
    if len(doc.entities) > max_entities: raise ValueError('Snapshot entity limit exceeded')
    budget = [len(data)]
    def freeze(value):
        blob = _pack(value); budget[0] += len(blob)
        if budget[0] > max_snapshot_bytes: raise ValueError('Snapshot serialized-byte limit exceeded')
        return blob
    header = freeze(doc.header); origin_header = freeze(doc._source_header)
    metadata = freeze(doc.metadata_settings); diagnostics = freeze(doc.diagnostics)
    definitions = []; original_defs = doc._source_records['block_defs']; numbers = set()
    originals = _definition_map(original_defs)
    for definition in doc.block_definitions:
        _integer(definition.number, 1 << 32, 'definition number')
        if definition.number in numbers: raise ValueError('Duplicate definition number')
        numbers.add(definition.number)
        prior = originals.get(definition.number, doc._new_block_records.get(definition.number))
        if prior is None: raise ValueError('Unmanaged definition in current model')
        record = dict(prior, name=definition.name, base=dict(definition.attributes), entities=[entity_record(e) for e in definition.entities])
        definitions.append(freeze(record))
    origin_defs = tuple(freeze(x) for x in original_defs)
    records = []; persisted = []; indices = []; kinds = []; layers = []; seen = set()
    origin_entities = doc._source_records['entities']
    for entity in doc.entities:
        index = entity.source_index
        if index is not None:
            _integer(index, len(origin_entities), 'source record index')
            if index in seen: raise ValueError('Duplicate source record index')
            seen.add(index)
        record = entity_record(entity); current = freeze(record)
        old = _pack(origin_entities[index]) if index is not None else None
        if old == current: old = current
        elif old is not None:
            budget[0] += len(old)
            if budget[0] > max_snapshot_bytes: raise ValueError('Snapshot serialized-byte limit exceeded')
        records.append(current); persisted.append(old); indices.append(index)
        kinds.append(_KINDS.get(record['type'], 'unknown'))
        base = record.get('base', {}); group, layer = base.get('layer_group'), base.get('layer')
        _integer(group, 16, 'layer group'); _integer(layer, 16, 'layer')
        layers.append((group, layer))
    source_sha = hashlib.sha256(data).hexdigest(); digest = hashlib.sha256()
    if type(doc.version) is not int or doc.version not in (600, 700): raise ValueError('Unverified model version')
    for value in [b'read-view-model-1', source_sha.encode('ascii'), _pack(doc.version), header, metadata, diagnostics,
                  _pack(doc.includes_metadata), _pack(len(definitions)), *definitions, _pack(len(records))]:
        digest.update(len(value).to_bytes(8, 'little')); digest.update(value)
    for index, value in zip(indices, records):
        digest.update(_pack(index)); digest.update(len(value).to_bytes(8, 'little')); digest.update(value)
    if Path(doc.source).read_bytes() != data: raise ValueError('Source file changed during view creation')
    from reader.text_presets import read_text_presets
    try:
        presets=dict(status='exact',values=read_text_presets(data,doc._source_records['header_end'],doc._source_records['version']))
    except ValueError as exc:
        presets=dict(status='undetermined',reason=str(exc))
    preset_blob=freeze(presets)
    return ReadView(uuid.uuid4().hex, source_sha, digest.hexdigest(), doc.includes_metadata, doc.version, str(Path(doc.source).resolve()),
                    doc._source_records.get('schema_profile', 'strict'), tuple(records), tuple(persisted), tuple(indices),
                    tuple(definitions), origin_defs, header, origin_header, metadata, diagnostics, tuple(kinds), tuple(layers),preset_blob,
                    data[:doc._source_records['header_end']])


def resolve_file_reference(path, reference, *, schema_profile='strict'):
    """Reopen identical bytes and resolve a stored-root reference, across processes if needed."""
    keys = {'reference_schema', 'scope', 'source_sha256', 'numbering', 'element_index', 'child_path', 'schema_profile'}
    if type(reference) is not dict or set(reference) != keys or type(reference['reference_schema']) is not int or reference['reference_schema'] != 1:
        raise ValueError('Invalid file reference')
    if reference['scope'] != 'file' or reference['numbering'] != 'stored_root_record_0': raise ValueError('Invalid file reference numbering')
    expected = reference['source_sha256']
    if type(expected) is not str or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected): raise ValueError('Invalid reference SHA256')
    if schema_profile not in ('strict', 'rebro_schema0') or reference['schema_profile'] != schema_profile:
        raise ValueError('Explicit matching schema_profile required; no automatic fallback')
    child_path = _path(reference['child_path']); source = Path(path); data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected: raise ValueError('Reference SHA256 differs; refusing before parsing')
    doc = CadDocument.open(source, include_metadata=True, schema_profile=schema_profile)
    if doc._source_bytes != data: raise ValueError('Source changed while resolving reference')
    index = _integer(reference['element_index'], len(doc._source_records['entities']), 'stored record index')
    root = doc._source_records['entities'][index]
    record, trace = _follow(root, child_path, _definition_map(doc._source_records['block_defs']))
    if source.read_bytes() != data: raise ValueError('Source changed during reference resolution')
    return _item(record, record, _unpack(_pack(reference)), doc.header, root.get('base', {}).get('layer_group'), trace,
                 'same_source_path_not_identity' if child_path else 'source_record')
