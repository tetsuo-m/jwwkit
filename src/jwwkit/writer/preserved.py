"""既存v600/v700図面の生ヘッダーを保持する保存処理（古い版は無編集の別名保存だけ）。

未対応のレコードを保存しない。無編集時も本文の再直列化を検証する。
ヘッダー設定は確認済みの16グループ縮尺とレイヤ／グループ名称を編集できる。
"""
from __future__ import annotations

import copy
import math
from pathlib import Path

from jwwkit.writer.mfc import records_bytes
from jwwkit.reader.archive import OLD_EXTENDED_COUNT_PAIRS, RecordError, is_read_only_version, read_records_bytes

OLD_VERSION_HINT = ('. Old JWW versions are read-only (unedited save-as only); to edit, re-save the drawing in '
                    'Jw_cad in the Ver.7.00 (v7) format and open that file instead.')


def serialize_body(entities, definitions, version, *, encoding=None, raw_trailer=None, class_declarations=None,
                   class_schema=None, old_extended_counts=False, count_forms=None):
    """既知の本文を共通MFCレジストリで直列化する。class_schemaは新しく書く宣言の版（既定はファイルの版）。
    count_formsは、元の図面の個数の書き方（並びの種類ごと。#46）。"""
    registry = {"classes": {}, "next_index": 1}
    if old_extended_counts:
        registry['old_extended_counts'] = True
    if count_forms:
        registry['count_forms'] = count_forms
    if class_schema is not None:
        registry['class_schema'] = class_schema
    if class_declarations is not None:
        registry.update(class_declarations=class_declarations, declaration_position=0)
    encoding = encoding or ("cp932" if version == 600 else "utf-16le")
    body = records_bytes(entities, registry, version=version, encoding=encoding)
    body += records_bytes(definitions, registry, version=version, encoding=encoding, sequence='block_defs')
    if class_declarations is not None and registry['declaration_position'] != len(class_declarations):
        raise ValueError('Original class declarations not fully consumed')
    if version == 700:
        body += bytes(4) if raw_trailer is None else raw_trailer
    return body


NEW_CLASS_DECLARATION_MESSAGE = (
    'This edit needs a new class declaration (a kind of element the drawing does not have yet) in a Jw_cad '
    'v6-format file whose classes use schema 700; that is unverified in Jw_cad and is rejected. '
    'To make this edit, re-save the drawing in Jw_cad in the Ver.7.00 (v7) format and open that file instead.')


IMAGE_REFERENCE_MESSAGE = (
    'This edit makes an image text (^@BM%temp%...) point to an image that is not embedded in the drawing; '
    'Jw_cad could not show it, so the save is rejected')


def dangling_image_references(parsed):
    """v700の^@BM%temp%文字のうち、同梱の画像を指さないものの名前（小文字）を数える。"""
    from collections import Counter
    embedded = {image['identifier'].lower()[:-3] for image in parsed.get('images', ())}
    found = Counter()

    def walk(records):
        for record in records:
            if record['type'] == 'TEXT':
                content = record['content']
            elif record['type'] == 'DIMENSION':
                content = record['text']['content']
            else:
                if record['type'] == 'BLOCK_DEF':
                    walk(record['entities'])
                continue
            if content[:10].lower() == '^@bm%temp%':
                name = content[10:].split(',', 1)[0].lower()
                if name not in embedded:
                    found[name] += 1
    walk(parsed['entities'])
    walk(parsed['block_defs'])
    del walk  # walk calls itself: drop the closure cycle (#29)
    return found


def keeps_class_declarations(parsed):
    """無編集の書き戻しで原宣言をそのまま使う図面か（rebro_schema0、観測済みのクラスの版の組、古い版）。"""
    return (parsed.get('schema_profile') == 'rebro_schema0' or is_read_only_version(parsed['version'])
            or parsed.get('class_schema', parsed['version']) != parsed['version'])


def old_extended_counts(parsed):
    """古い版で拡張個数を書いてよいか（観測した組だけ）。"""
    return (parsed['version'], parsed.get('class_schema', parsed['version'])) in OLD_EXTENDED_COUNT_PAIRS


def count_forms(parsed):
    """元の図面の個数の書き方（#46）。v700・クラスの版700で、65535未満をDWORDで書く並びがある図面だけ。

    編集した後の保存も同じ書き方にする（案A）。前からある並びはその並びの書き方、新しいブロック定義の中の並びは
    元の定義の中の並びと同じ書き方（元に定義がなければ普通の書き方）。それ以外の図面ではNone。"""
    return parsed.get('count_forms')


def save_count_forms(original, entities, definitions):
    """編集した保存で使う書き方。要素も定義もない本文は、宣言がなくクラスの版を示せないので普通の書き方にする。"""
    return count_forms(original) if (entities or definitions) else None


def expected_count_forms(original, entities, definitions):
    """保存した本文を読み直したときに出るはずのcount_forms（案A）。

    - 元に定義がなく、定義を足したときは普通の書き方。
    - 65535個以上の並びは、どちらの書き方でも印+DWORDなので、読み直しでは書き方が分からない（数えない）。"""
    forms = save_count_forms(original, entities, definitions)
    if forms is None:
        return None
    small = [d for d in definitions if len(d['entities']) < 65535]
    inside = forms['definition_entities']
    if inside is None and small:
        inside = False
    elif not small:
        inside = None
    top = forms['entities'] and len(entities) < 65535
    listed = forms['block_defs'] and len(definitions) < 65535
    if not (top or listed or inside):
        return None
    return dict(entities=top, block_defs=listed, definition_entities=inside)


def capture_source(path, *, schema_profile='strict'):
    """開く時点の原データを捕捉し、本文再直列化の全バイト一致を確認する。"""
    raw, parsed = _capture_source(path, schema_profile=schema_profile)
    return raw, copy.deepcopy(parsed)


def _capture_source(path, *, schema_profile='strict'):
    """capture_source without the final deep copy: the caller owns the returned records (#25).

    The records are a fresh read that nothing else references; CadDocument.open keeps them as
    the source snapshot and never hands them to the public model.
    """
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
                class_declarations=parsed['class_declarations'] if keeps_class_declarations(parsed) else None,
                old_extended_counts=old_extended_counts(parsed), count_forms=count_forms(parsed))
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
            del collect_strings  # it calls itself: drop the closure cycle (#29)
            observed = {('utf-16le' if value.startswith(b'\xff\xfe\xff') else 'cp932') for value in string_bytes}
            parsed["body_encoding"] = next(iter(observed)) if len(observed) == 1 else encoding
            return raw, parsed
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
    return raw, parsed


def entity_record(entity):
    """公開モデルからレコードを作る。属性をgeometryで上書きさせない。"""
    if "type" in entity.geometry or "base" in entity.geometry:
        raise ValueError("Geometry may not override entity type or attributes")
    result = copy.deepcopy(dict(entity.geometry))
    source_strings = getattr(entity.raw, 'source_strings', None)
    if source_strings is not None:
        from jwwkit.reader.archive import Record
        result = Record(result)
        result.source_strings = copy.deepcopy(source_strings)
    result["type"] = entity.entity_type
    result["base"] = copy.deepcopy(dict(entity.attributes))
    return result


def _entity_record_for_save(entity):
    """entity_record without deep copies, for records that only live inside one save (#27).

    The save only reads these records (checks, serialization, read-back comparison) and returns
    bytes, so the record may share the entity's nested values: a new top-level record, the
    entity's own source_strings, and its attributes dict as base when that is exactly a dict
    (any other mapping is copied into a dict, as entity_record does).
    """
    if "type" in entity.geometry or "base" in entity.geometry:
        raise ValueError("Geometry may not override entity type or attributes")
    result = dict(entity.geometry)
    source_strings = getattr(entity.raw, 'source_strings', None)
    if source_strings is not None:
        from jwwkit.reader.archive import Record
        result = Record(result)
        result.source_strings = source_strings
    result["type"] = entity.entity_type
    attributes = entity.attributes
    result["base"] = attributes if type(attributes) is dict else dict(attributes)
    return result


def _finite(value, location):
    """Reject a non-finite float anywhere in a record (module level: no closure cycle, #29)."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f'非有限の値: element={location}')
    if isinstance(value, dict):
        for key, item in value.items():
            _finite(item, f'{location}.{key}')
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _finite(item, f'{location}[{index}]')


def validate_records(records, originals, label, defined_numbers):
    """保存対象の非有限値・未解決参照と未検証の円ソリッド表現を拒否する。"""
    for index, record in enumerate(records):
        location = f'{label}[{index}]'
        _finite(record, location)
        if record['type'] == 'CIRCLE_SOLID':
            if not any(record == item for item in originals if item['type'] == 'CIRCLE_SOLID'):
                from jwwkit.model.circular_solid import validate_circular_solid
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
    if (document._source_records.get('schema_profile') == 'rebro_schema0'
            or is_read_only_version(document._source_records['version'])):
        return _readonly_bytes(document)
    if keeps_class_declarations(document._source_records) and document.includes_metadata:
        # (600, 700) opened with include_metadata=True: unedited save-as only (as in #11).
        return _readonly_bytes(document)
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
    # The records built below share nested values with the document (#27): from here on they are
    # only read, never written into, and none of them is kept after this function returns.
    for entity in document.entities:
        record = _entity_record_for_save(entity)
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
    # Shallow copies (#27): only top-level keys are written below (is_referenced, and number, name,
    # base and entities through update); the nested base and entities are replaced, not changed.
    for definition in document.block_definitions:
        if definition.number in originals:
            record = copy.copy(originals[definition.number])
        elif definition.number in document._new_block_records:
            record = copy.copy(document._new_block_records[definition.number])
            record['is_referenced'] = any(e['type'] == 'BLOCK' and e['def_number'] == definition.number for e in entities)
            if any(e.entity_type == 'BLOCK' for e in definition.entities):
                raise ValueError('新規定義の入れ子参照は未対応です')
        else:
            raise ValueError(f"追加APIで管理されていないブロック定義: number={definition.number}")
        record.update(number=definition.number, name=definition.name,
                      base=dict(definition.attributes),
                      entities=[_entity_record_for_save(entity) for entity in definition.entities])
        definitions.append(record)
    numbers = [record['number'] for record in definitions]
    if len(numbers) != len(set(numbers)):
        raise ValueError('ブロック定義番号が重複しています')
    validate_records(entities, original['entities'], 'entities', set(numbers))
    for definition in definitions:
        validate_records(definition['entities'], originals.get(definition['number'], {'entities': []})['entities'],
                         f'block_defs[{definition["number"]}].entities', set(numbers))
    # (600, 700): Jw_cad 10.03.6 v6 output. Write every declaration with the source class schema.
    class_schema = original.get('class_schema', document.version)
    # Embedded image edits (#57) rebuild the trailer; every other save keeps it byte for byte.
    trailer, expected_images = original['raw_trailer'], None
    if document._image_edits:
        trailer, expected_images = _edited_trailer(document, entities, definitions)
    body = serialize_body(entities, definitions, document.version, encoding=original["body_encoding"], raw_trailer=trailer,
                          class_schema=class_schema if class_schema != document.version else None,
                          count_forms=save_count_forms(original, entities, definitions))
    from jwwkit.writer.header import patch_scales
    header = document._source_bytes[:original['header_end']]
    if document._state_edits:
        from jwwkit.writer.header import patch_states
        header=patch_states(header,document._source_header['layer_groups'],document._state_edits)
    if document._group_scale_edits:
        # Verify original state/protection fields before applying independent
        # patches; a state-edited header no longer matches the original groups.
        scaled=patch_scales(document._source_bytes[:original['header_end']],document._source_header['layer_groups'],document._group_scale_edits)
        from jwwkit.writer.header import scale_offsets
        patched=bytearray(header)
        for index in document._group_scale_edits:
            offset=scale_offsets(document._source_bytes[:original['header_end']],document._source_header['layer_groups'])[index]
            patched[offset:offset+8]=scaled[offset:offset+8]
        header=bytes(patched)
    if document._name_edits:
        from jwwkit.writer.header import patch_names
        header = patch_names(header, original['layer_names'], document._name_edits)
    data = header + body
    # 作成前に再読取で確かめる。メモリ読取を使用し中間ファイルを作らない。
    checked = read_records_bytes(data)
    if class_schema != document.version:
        # Only classes the source already declared may be written (no new declarations).
        declared = {d['name'] for d in original['class_declarations']}
        if any(d['name'] not in declared for d in checked['class_declarations']):
            raise ValueError(NEW_CLASS_DECLARATION_MESSAGE)
        if checked['class_declarations'] and checked['class_schema'] != class_schema:
            raise ValueError('保存前検証でクラスの版が保たれません')
    if (checked['entities'] != entities or checked['block_defs'] != definitions
            or checked["raw_trailer"] != trailer):
        raise ValueError("保存前検証で本文が一致しません")
    if expected_images is not None:
        if [(i['identifier'], i['sha256']) for i in checked['images']] != expected_images:
            raise ValueError('保存前検証で同梱の画像が予定と一致しません')
        # No text of the candidate may still point to an image that was taken out (same name reading).
        all_names = {i['identifier'].lower()[:-3] for i in original['images']} | {
            name.lower()[:-3] for name, _ in expected_images}
        removed = all_names - {name.lower()[:-3] for name, _ in expected_images}
        if removed & image_reference_names(checked['entities'], checked['block_defs'], all_names):
            raise ValueError(IMAGE_REFERENCE_MESSAGE)
    if checked.get('count_forms') != expected_count_forms(original, entities, definitions):
        raise ValueError('保存前検証で個数の書き方が保たれません')
    if document.version == 700:
        # Image texts may only point to embedded images, unless the source already had such a text.
        before = dangling_image_references(original)
        if any(count > before.get(name, 0) for name, count in dangling_image_references(checked).items()):
            raise ValueError(IMAGE_REFERENCE_MESSAGE)
    return data


def image_reference_names(entities, definitions, names):
    """Lower-case embedded names (from ``names``) that ^@BM%temp% texts point to, in the drawing, block
    definitions and dimension texts. Names are matched against the embedded names, longest first, so a
    comma inside a name is read the same way as delete_image reads it (#57)."""
    from jwwkit.writer.images import split_image_text
    found = set()

    def walk(records):
        for record in records:
            if record['type'] == 'TEXT':
                content = record['content']
            elif record['type'] == 'DIMENSION':
                content = record['text']['content']
            else:
                if record['type'] == 'BLOCK_DEF':
                    walk(record['entities'])
                continue
            split = split_image_text(content, names)
            if split is not None:
                found.add(split[0].lower())
    walk(entities)
    walk(definitions)
    del walk  # walk calls itself: drop the closure cycle (#29)
    return found


def _edited_trailer(document, entities, definitions):
    """Trailer after add_image/delete_image/replace_image (#57) and the expected (name, SHA256) list."""
    import hashlib
    from jwwkit.writer.images import compose_trailer
    original = document._source_records
    if document.version != 700 or original['version'] != 700:
        raise ValueError('Embedded image edits are supported only for v700 drawings')
    edits = document._image_edits
    names = {i['identifier'].lower()[:-3] for i in original['images']} | {
        i['identifier'].lower()[:-3] for i in edits['added']}
    referenced = image_reference_names(entities, definitions, names)
    dropped = {name for name in edits['drop'] if name[:-3] not in referenced}
    keep = [i['identifier'] for i in original['images'] if i['identifier'].lower() not in dropped]
    added = [item for item in edits['added'] if item['identifier'].lower() not in dropped]
    for item in added:
        if hashlib.sha256(item['raw']).hexdigest() != item['sha256']:
            raise ValueError('An image to add changed in memory')
    trailer = compose_trailer(document._source_bytes, original, set(keep), added)
    by_name = {i['identifier']: i['sha256'] for i in original['images']}
    expected = [(name, by_name[name]) for name in keep] + [(i['identifier'], i['sha256']) for i in added]
    return trailer, expected


def _readonly_bytes(document):
    """Reparse, compare the full public model, then serialize original declarations.

    Used for rebro_schema0, old file versions (#17), and for (600, 700) documents
    opened with include_metadata=True; all must save unedited and byte-identically.
    """
    from jwwkit.model.common_entities import CadBlockDefinition, model_entity
    profile = document._source_records.get('schema_profile', 'strict')
    if profile == 'rebro_schema0':
        label = profile
    elif is_read_only_version(document._source_records['version']):
        label = f'JWW v{document._source_records["version"]} (old version)'
    else:
        label = 'Jw_cad v6 file with class schema 700 opened with include_metadata=True'
    original = read_records_bytes(document._source_bytes, schema_profile=profile)
    if not keeps_class_declarations(original):
        raise ValueError(f'{label} source snapshot was changed')
    if document._readonly_state is None or any(getattr(document, key) != value
            for key, value in document._readonly_state.items()):
        raise ValueError(f'{label} is read-only; model settings were changed')
    indices = set(document._source_metadata_indices)
    expected = tuple(model_entity(raw, source_index=i) for i, raw in enumerate(original['entities'])
                     if document.includes_metadata or i not in indices)
    expected_blocks = tuple(CadBlockDefinition(d['number'], d['name'], dict(d['base']),
                            tuple(model_entity(e) for e in d['entities'])) for d in original['block_defs'])
    if (document.version != original['version'] or document.header != document._source_header
            or document.entities != expected
            or tuple(e.source_index for e in document.entities) != tuple(e.source_index for e in expected)
            or document.block_definitions != expected_blocks or document._name_edits or document._group_scale_edits
            or document._state_edits or document._new_block_records or document._image_edits):
        raise ValueError(f'{label} is read-only; edited documents cannot be saved'
                         + (OLD_VERSION_HINT if is_read_only_version(original['version']) else ''))
    # The source records (including CString bytes and declaration metadata) must also stay intact.
    for key in ('entities','block_defs','class_declarations','raw_trailer','version','header_end'):
        if document._source_records[key] != original[key]:
            raise ValueError(f'{label} source snapshot was changed')
    # Rebuild from the current model too: Python numeric equality alone misses signed-zero changes.
    current = list(original['entities'])
    for entity in document.entities:
        current[entity.source_index] = entity_record(entity)
    definitions = []
    for definition, source in zip(document.block_definitions, original['block_defs']):
        record = copy.deepcopy(source)
        record.update(number=definition.number, name=definition.name, base=copy.deepcopy(dict(definition.attributes)),
                      entities=[entity_record(entity) for entity in definition.entities])
        definitions.append(record)
    body = serialize_body(current, definitions, original['version'],
        encoding=document._source_records['body_encoding'], raw_trailer=original['raw_trailer'],
        class_declarations=original['class_declarations'], old_extended_counts=old_extended_counts(original),
        count_forms=count_forms(original))
    result = document._source_bytes[:original['header_end']] + body
    if result != document._source_bytes:
        raise ValueError(f'Read-only {label} serialization must be byte-identical')
    # Re-read the candidate: declarations (including their schema) must be unchanged.
    if read_records_bytes(result, schema_profile=profile)['class_declarations'] != original['class_declarations']:
        raise ValueError(f'{label}: class declarations changed on save')
    return result


def save_document(document, path):
    """原ヘッダーと本文を検証後、別名の新規ファイルだけへ保存する。"""
    target = Path(path)
    if target.resolve() == document.source.resolve():
        raise ValueError("原ファイルを上書きできません。別名を指定してください")
    data = _document_bytes(document)
    with target.open("xb") as stream:
        stream.write(data)
