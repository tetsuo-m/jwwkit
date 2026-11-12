"""既存v600/v700図面の生ヘッダーを保持する保存処理。

未対応のレコードを保存しない。無編集時も本文の再直列化を検証する。
ヘッダー設定は確認済みの16グループ縮尺とレイヤ／グループ名称を編集できる。
"""
from __future__ import annotations

import copy
import math
from pathlib import Path

from writer.mfc import records_bytes
from reader.archive import RecordError, read_records_bytes


def serialize_body(entities, definitions, version, *, encoding=None, raw_trailer=None, class_declarations=None):
    """既知の本文を共通MFCレジストリで直列化する。"""
    registry = {"classes": {}, "next_index": 1}
    if class_declarations is not None:
        registry.update(class_declarations=class_declarations, declaration_position=0)
    encoding = encoding or ("cp932" if version == 600 else "utf-16le")
    body = records_bytes(entities, registry, version=version, encoding=encoding)
    body += records_bytes(definitions, registry, version=version, encoding=encoding)
    if class_declarations is not None and registry['declaration_position'] != len(class_declarations):
        raise ValueError('Original class declarations not fully consumed')
    if version == 700:
        body += bytes(4) if raw_trailer is None else raw_trailer
    return body


def capture_source(path, *, schema_profile='strict'):
    """開く時点の原データを捕捉し、本文再直列化の全バイト一致を確認する。"""
    source = Path(path)
    raw = source.read_bytes()
    parsed = read_records_bytes(raw, schema_profile=schema_profile)
    original = raw[parsed["header_end"]:]
    encodings = ["cp932"] if parsed["version"] == 600 else ["utf-16le", "cp932"]
    body = b''
    serialization_errors = []
    for encoding in encodings:
        try:
            body = serialize_body(parsed["entities"], parsed["block_defs"], parsed["version"], encoding=encoding, raw_trailer=parsed["raw_trailer"],
                class_declarations=parsed['class_declarations'] if schema_profile == 'rebro_schema0' else None)
        except (UnicodeError, ValueError) as exc:
            serialization_errors.append(f'{encoding}: {exc}')
            continue
        if body == original:
            string_bytes = []
            def collect_strings(records):
                for record in records:
                    string_bytes.extend(item[1] for item in (getattr(record, 'source_strings', None) or {}).values())
                    if record['type'] == 'BLOCK_DEF':
                        collect_strings(record['entities'])
                    elif record['type'] == 'DIMENSION':
                        collect_strings([record['text']])
            collect_strings(parsed['entities'] + parsed['block_defs'])
            observed = {('utf-16le' if value.startswith(b'\xff\xfe\xff') else 'cp932') for value in string_bytes}
            parsed["body_encoding"] = next(iter(observed)) if len(observed) == 1 else encoding
            return raw, copy.deepcopy(parsed)
    # 同じ版でも旧CP932本文と現行UTF-16本文がある。全バイト一致で判定し、
    # 混在など一致しない表現は推測で正規化せず拒否する。
    if body != original:
        difference = next(
            (i for i, (a, b) in enumerate(zip(body, original)) if a != b),
            min(len(body), len(original)),
        )
        offset = parsed["header_end"] + difference
        raise RecordError(
            f"本文を損失なく再直列化できません: offset={offset}, "
            f"source_bytes={len(original)}, serialized_bytes={len(body)}, "
            f"details={serialization_errors}"
        )
    return raw, copy.deepcopy(parsed)


def entity_record(entity):
    """公開モデルからレコードを作る。属性をgeometryで上書きさせない。"""
    if "type" in entity.geometry or "base" in entity.geometry:
        raise ValueError("Geometry may not override entity type or attributes")
    result = copy.deepcopy(dict(entity.geometry))
    source_strings = getattr(entity.raw, 'source_strings', None)
    if source_strings is not None:
        from reader.archive import Record
        result = Record(result)
        result.source_strings = copy.deepcopy(source_strings)
    result["type"] = entity.entity_type
    result["base"] = copy.deepcopy(dict(entity.attributes))
    return result


def validate_records(records, originals, label, defined_numbers):
    """保存対象の非有限値・未解決参照と未検証の円ソリッド表現を拒否する。"""
    def finite(value, location):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f'非有限の値: element={location}')
        if isinstance(value, dict):
            for key, item in value.items():
                finite(item, f'{location}.{key}')
        elif isinstance(value, list):
            for index, item in enumerate(value):
                finite(item, f'{location}[{index}]')
    for index, record in enumerate(records):
        location = f'{label}[{index}]'
        finite(record, location)
        if record['type'] == 'CIRCLE_SOLID':
            if not any(record == item for item in originals if item['type'] == 'CIRCLE_SOLID'):
                from model.circular_solid import validate_circular_solid
                validate_circular_solid(record)
        if record['type']=='SOLID' and record['base']['pen_style']>=101:
            if not any(record==item for item in originals if item['type']=='SOLID'):
                raise ValueError('Unsupported circular-solid storage style')
        if record['type'] == 'BLOCK' and record['def_number'] not in defined_numbers:
            raise ValueError(f'未解決ブロック参照: element={location}, def_number={record["def_number"]}')


def _document_bytes(document):
    """Validate a complete candidate in memory without creating an output file."""
    if document._source_bytes is None or document._source_records is None:
        raise ValueError("原ファイルの保存用スナップショットがありません")
    blocking = []
    for diagnostic in document.diagnostics:
        header_decode_warning = (
            isinstance(diagnostic, dict)
            and diagnostic.get('code') == 'CP932_DECODE_REPLACED'
            and diagnostic.get('details', {}).get('field', '').startswith('header.')
        )
        if not header_decode_warning:
            blocking.append(diagnostic)
    if blocking:
        raise ValueError(f"未確認の構造があるため保存できません: {document.diagnostics}")
    if document._source_records.get('schema_profile') == 'rebro_schema0':
        return _readonly_schema0_bytes(document)
    if document.includes_metadata:
        raise ValueError("Metadata-inclusive editing is not supported")
    expected_header = copy.deepcopy(document._source_header)
    for index, scale in document._group_scale_edits.items():
        expected_header['layer_groups'][index]['scale'] = scale
    for (group,layer),state in document._state_edits.items():
        target=expected_header['layer_groups'][group]
        if layer is not None:target=target['layers'][layer]
        target['state']=state
    for slot, name in document._name_edits.items():
        if slot < 256:
            expected_header['layer_groups'][slot // 16]['layers'][slot % 16]['name'] = name
        else:
            expected_header['layer_groups'][slot - 256]['name'] = name
    if document.header != expected_header or document.version != document._source_records["version"]:
        raise ValueError("生ヘッダー保持方式ではヘッダーの直接編集に対応しません")
    original = document._source_records
    # 公開番号ではなく原要素番号で再配置する。削除してもメタデータを前後させない。
    metadata = set(document._source_metadata_indices)
    replacements = {}
    appended = []
    for entity in document.entities:
        record = entity_record(entity)
        source_index = entity.source_index
        if source_index is None:
            document._validate_addition(record)
            appended.append(record)
            continue
        if (type(source_index) is not int or source_index < 0
                or source_index >= len(original['entities']) or source_index in metadata
                or source_index in replacements):
            raise ValueError('原要素の関連付けが不正または重複しています')
        if record != original['entities'][source_index]:document._validate_addition(record)
        replacements[source_index] = record
    entities = []
    for index, record in enumerate(original['entities']):
        if index in metadata:
            entities.append(copy.deepcopy(record))
        elif index in replacements:
            entities.append(replacements[index])
    entities.extend(appended)
    definitions = []
    originals = {item["number"]: item for item in original["block_defs"]}
    for definition in document.block_definitions:
        if definition.number in originals:
            record = copy.deepcopy(originals[definition.number])
        elif definition.number in document._new_block_records:
            record = copy.deepcopy(document._new_block_records[definition.number])
            record['is_referenced'] = any(e['type'] == 'BLOCK' and e['def_number'] == definition.number for e in entities)
            if any(e.entity_type == 'BLOCK' for e in definition.entities):
                raise ValueError('新規定義の入れ子参照は未対応です')
        else:
            raise ValueError(f"追加APIで管理されていないブロック定義: number={definition.number}")
        record.update(number=definition.number, name=definition.name,
                      base=copy.deepcopy(dict(definition.attributes)),
                      entities=[entity_record(entity) for entity in definition.entities])
        definitions.append(record)
    numbers = [record['number'] for record in definitions]
    if len(numbers) != len(set(numbers)):
        raise ValueError('ブロック定義番号が重複しています')
    validate_records(entities, original['entities'], 'entities', set(numbers))
    for definition in definitions:
        validate_records(definition['entities'], originals.get(definition['number'], {'entities': []})['entities'],
                         f'block_defs[{definition["number"]}].entities', set(numbers))
    body = serialize_body(entities, definitions, document.version, encoding=original["body_encoding"], raw_trailer=original["raw_trailer"])
    from writer.header import patch_scales
    header = document._source_bytes[:original['header_end']]
    if document._state_edits:
        from writer.header import patch_states
        header=patch_states(header,document._source_header['layer_groups'],document._state_edits)
    if document._group_scale_edits:
        # Verify original state/protection fields before applying independent
        # patches; a state-edited header no longer matches the original groups.
        scaled=patch_scales(document._source_bytes[:original['header_end']],document._source_header['layer_groups'],document._group_scale_edits)
        from writer.header import scale_offsets
        patched=bytearray(header)
        for index in document._group_scale_edits:
            offset=scale_offsets(document._source_bytes[:original['header_end']],document._source_header['layer_groups'])[index]
            patched[offset:offset+8]=scaled[offset:offset+8]
        header=bytes(patched)
    if document._name_edits:
        from writer.header import patch_names
        header = patch_names(header, original['layer_names'], document._name_edits)
    data = header + body
    # 作成前に再読取で確かめる。メモリ読取を使用し中間ファイルを作らない。
    checked = read_records_bytes(data)
    if (checked['entities'] != entities or checked['block_defs'] != definitions
            or checked["raw_trailer"] != original["raw_trailer"]):
        raise ValueError("保存前検証で本文が一致しません")
    return data


def _readonly_schema0_bytes(document):
    """Reparse, compare the full public model, then serialize original declarations."""
    from model.common_entities import model_entity
    original = read_records_bytes(document._source_bytes, schema_profile='rebro_schema0')
    if document._readonly_state is None or any(getattr(document, key) != value
            for key, value in document._readonly_state.items()):
        raise ValueError('rebro_schema0 is read-only; model settings were changed')
    indices = set(document._source_metadata_indices)
    expected = tuple(model_entity(raw, source_index=i) for i, raw in enumerate(original['entities'])
                     if document.includes_metadata or i not in indices)
    if (document.version != original['version'] or document.header != document._source_header
            or document.entities != expected
            or tuple(e.source_index for e in document.entities) != tuple(e.source_index for e in expected)
            or document.block_definitions or document._name_edits or document._group_scale_edits
            or document._state_edits or document._new_block_records):
        raise ValueError('rebro_schema0 is read-only; edited documents cannot be saved')
    # The source records (including CString bytes and declaration metadata) must also stay intact.
    for key in ('entities','block_defs','class_declarations','raw_trailer','version','header_end'):
        if document._source_records[key] != original[key]:
            raise ValueError('rebro_schema0 source snapshot was changed')
    # Rebuild from the current model too: Python numeric equality alone misses signed-zero changes.
    current = list(original['entities'])
    for entity in document.entities:
        current[entity.source_index] = entity_record(entity)
    body = serialize_body(current, original['block_defs'], original['version'],
        encoding=document._source_records['body_encoding'], raw_trailer=original['raw_trailer'],
        class_declarations=original['class_declarations'])
    result = document._source_bytes[:original['header_end']] + body
    if result != document._source_bytes:
        raise ValueError('Read-only schema-0 serialization must be byte-identical')
    return result


def save_document(document, path):
    """原ヘッダーと本文を検証後、別名の新規ファイルだけへ保存する。"""
    target = Path(path)
    if target.resolve() == document.source.resolve():
        raise ValueError("原ファイルを上書きできません。別名を指定してください")
    data = _document_bytes(document)
    with target.open("xb") as stream:
        stream.write(data)
