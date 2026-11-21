"""Internal boundary for the required ezjww 0.7.13 reader (ezjww>=0.7.13,<0.8).

This is a transparent adapter, not a new parser or validation policy.
See docs/ezjww_adapter_contract.md for the consumed result contract.
Keep the import eager: making the dependency optional belongs to a later design.
"""
import re

import ezjww as _ezjww

# Fields that ezjww 0.7.13 returns and 0.2.13 did not (#46). They are removed here, and only these,
# so that every caller (cross-check, read_document's limited read, template copy) receives the
# 0.2.13 result shape and jwwkit's public output does not change. Any other new field is kept.
ADDED_RESULT_FIELDS = ('images', 'text_encoding')
ADDED_HEADER_FIELDS = ('pens', 'line_types', 'text_presets')
ADDED_TEXT_FIELDS = ('image',)
# Inside a DIMENSION: the attributes of its line, text, auxiliary lines and points. 0.2.13 left them
# out and the cross-check treats them as optional; keeping them would change what it compares.
ADDED_DIMENSION_PART_FIELDS = ('base',)
# A diagnostic whose details.field is one of the removed fields, or lies under one (the name is followed
# by the end, '.' or '['), is removed with it (#46: CP932 warnings on header.line_types.sxf[n].name).
# A field that only begins with the same letters (header.pens_extra, say) is kept.
_REMOVED_FIELD = re.compile(
    r'(?:header\.(?:pens|line_types|text_presets)|images|text_encoding'
    r'|(?:block_defs\[\d+\]\.)?entities\[\d+\]\.(?:image|(?:line|text|aux_lines\[\d+\]|aux_points\[\d+\])\.base))'
    r'(?:$|[.\[])')


def _points_to_removed_field(diagnostic):
    if not isinstance(diagnostic, dict):
        return False
    details = diagnostic.get('details')
    field = details.get('field') if isinstance(details, dict) else None
    return isinstance(field, str) and _REMOVED_FIELD.match(field) is not None


def _remove_added_entity_fields(entities):
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        kind = entity.get('type')
        if kind == 'TEXT':
            for key in ADDED_TEXT_FIELDS:
                entity.pop(key, None)
        elif kind == 'DIMENSION':
            parts = [entity.get('line'), entity.get('text'),
                     *(entity.get('aux_lines') or ()), *(entity.get('aux_points') or ())]
            for part in parts:
                if isinstance(part, dict):
                    for key in ADDED_DIMENSION_PART_FIELDS:
                        part.pop(key, None)


def _remove_added_fields(result):
    """Remove, in place, exactly the fields listed above; the same dict object is returned."""
    if not isinstance(result, dict):
        return result
    for key in ADDED_RESULT_FIELDS:
        result.pop(key, None)
    header = result.get('header')
    if isinstance(header, dict):
        for key in ADDED_HEADER_FIELDS:
            header.pop(key, None)
    _remove_added_entity_fields(result.get('entities') or ())
    for definition in result.get('block_defs') or ():
        if isinstance(definition, dict):
            _remove_added_entity_fields(definition.get('entities') or ())
    diagnostics = result.get('diagnostics')
    if isinstance(diagnostics, list):
        # in place: the same list object stays in the result
        diagnostics[:] = [d for d in diagnostics if not _points_to_removed_field(d)]
    return result


def read_native_document(path):
    """Delegate once; return the native result object (with the fields added in 0.7.13 removed) and
    let any exception through unchanged."""
    return _remove_added_fields(_ezjww.read_document(str(path)))
