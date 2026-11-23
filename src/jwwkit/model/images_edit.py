"""Insert, delete and replace embedded images in v700 drawings (#57).

The edits are kept on the document (``_image_edits``) until saving:
``added`` lists the images to append to the trailer (in order) and ``drop`` holds the names that
``delete_image`` asked to remove. On saving, a name in ``drop`` leaves the trailer only if no image text
(drawing, block definitions or dimension text) points to it any more. ``delete_entity`` never removes
images (unchanged behaviour); only ``delete_image`` does.
"""
import math
from pathlib import Path

from jwwkit.model.common_entities import model_entity
from jwwkit.model.text import Text
from jwwkit.reader.images import MAX_IMAGE_COUNT, MAX_TOTAL_IMAGE_BYTES
from jwwkit.writer.images import (SIX_FIELD_FORM_MESSAGE, number, TEXT_FONT, TEXT_SIZE, check_new_image, embedded_name,
                                  image_text, parse_image_text, split_image_text)


def _require_image_document(document):
    document._require_editable()
    records = document._source_records
    if records is None or document._source_bytes is None:
        raise ValueError('Image edits need a drawing opened with CadDocument.open')
    if document.version != 700 or records['version'] != 700:
        raise ValueError('Embedded image edits are supported only for v700 drawings (Ver.7.00 format); '
                         'other versions are refused')
    if document.includes_metadata:
        raise ValueError('Image edits need a drawing opened with include_metadata=False')
    if document._imported_group:
        raise ValueError('add_image/delete_image/replace_image cannot be combined with import_group')
    return records


def _edits(document):
    if not document._image_edits:
        document._image_edits = dict(added=[], drop=set())
    return document._image_edits


def embedded_images(document):
    """Source images plus pending added ones (identifier, sha256), before dropping."""
    images = [dict(identifier=i['identifier'], sha256=i['sha256'], raw_size=i['raw_size'], source=True)
              for i in document._source_records.get('images', ())]
    images += [dict(identifier=i['identifier'], sha256=i['sha256'], raw_size=len(i['raw']), source=False)
               for i in (document._image_edits or {}).get('added', ())]
    return images


def _embedded_names(document):
    return {i['identifier'].lower()[:-3] for i in embedded_images(document)}


def _texts(entities):
    for entity in entities:
        if entity.entity_type == 'TEXT':
            yield entity.geometry.get('content', '')
        elif entity.entity_type == 'DIMENSION':
            yield (entity.geometry.get('text') or {}).get('content', '')


def has_six_field_image_texts(document):
    """True if an embedded image text does not have Jw_cad 10.03.6's 9 fields (6 in some real drawings)."""
    names = _embedded_names(document)
    contents = list(_texts(document.entities))
    for definition in document.block_definitions:
        contents += list(_texts(definition.entities))
    for content in contents:
        split = split_image_text(content, names)
        if split is not None and len(split[1]) != 9:
            return True
    return False


def _refuse_six_field_form(document):
    if has_six_field_image_texts(document):
        raise ValueError(SIX_FIELD_FORM_MESSAGE)


def _number_check(value, what, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'Image {what} must be a finite number')
    if positive and value <= 0:
        raise ValueError(f'Image {what} must be positive')
    return float(value)


def _color(value):
    if (not isinstance(value, (tuple, list)) or len(value) != 3
            or any(type(c) is not int or not 0 <= c <= 255 for c in value)):
        raise ValueError('transparent_color must be three integers 0..255 (red, green, blue)')
    return tuple(value)


def prepare_image(document, path, *, name=None):
    """Read and check an image file; return (review, raw, existing identifier or None). No changes."""
    _require_image_document(document)
    file_path = Path(path)
    raw = file_path.read_bytes()
    review = check_new_image(raw, file_path.name if name is None else name)
    images = embedded_images(document)
    same = [i for i in images if i['sha256'] == review['sha256']]
    if same:
        # Same content: share the embedded image (as Jw_cad does for one file pasted twice).
        review.update(shared_with=same[0]['identifier'], name=same[0]['identifier'][:-3],
                      identifier=same[0]['identifier'])
        return review, raw, same[0]['identifier']
    clash = [i for i in images if i['identifier'].lower() == review['identifier'].lower()]
    if clash:
        raise ValueError(f'An embedded image named {review["name"]!r} with different content already exists; '
                         'give another name with name=...')
    if len(images) + 1 > MAX_IMAGE_COUNT:
        raise ValueError(f'More than {MAX_IMAGE_COUNT} embedded images')
    if sum(i['raw_size'] for i in images) + len(raw) > MAX_TOTAL_IMAGE_BYTES:
        raise ValueError(f'Embedded images would exceed {MAX_TOTAL_IMAGE_BYTES} bytes in one drawing')
    review['shared_with'] = None
    return review, raw, None


def _text_entity(document, name, start, width, height, angle, color, layer_group, layer, pen_color=1, group=0):
    content = image_text(name, width, height, angle, color)
    # E080 rule, as in Jw_cad's image texts (#57, also with Japanese names): per UTF-16 unit, ASCII and
    # half-width katakana take half the text width, others the full width (CP932 names have no surrogates).
    advance = TEXT_SIZE * sum(0.5 if ord(c) < 0x80 or 0xff61 <= ord(c) <= 0xff9f else 1.0 for c in content)
    radians = math.radians(angle)
    end = (start[0] + advance * math.cos(radians), start[1] + advance * math.sin(radians))
    record = Text(tuple(start), end, content, size_x=TEXT_SIZE, size_y=TEXT_SIZE, spacing=0.0, angle=float(angle),
                  font_name=TEXT_FONT, alignment=1, color=pen_color, layer=layer, layer_group=layer_group,
                  group=group).record()
    try:
        document._validate_addition(record)
    except ValueError as exc:
        if 'short' in str(exc):
            raise ValueError('Image name is too long for an image text; give a shorter name with name=...') from exc
        raise
    return model_entity(record)


def add_image(document, path, position, width, *, height=None, angle=0, transparent_color=(255, 255, 255),
              name=None, layer_group=0, layer=0, units='paper'):
    _require_image_document(document)
    _refuse_six_field_form(document)
    width = _number_check(width, 'width', positive=True)
    angle = _number_check(angle, 'angle')
    if not 0 <= angle < 360 or float(number(angle, 'angle')) >= 360:
        raise ValueError('Image angle must be 0 or more and less than 360 degrees')
    color = _color(transparent_color)
    for value, what in ((layer_group, 'layer_group'), (layer, 'layer')):
        if type(value) is not int or not 0 <= value < 16:
            raise ValueError(f'{what} must be 0..15')
    review, raw, shared = prepare_image(document, path, name=name)
    if height is None:
        height = width * review['height'] / review['width']
    height = _number_check(height, 'height', positive=True)
    start = document.convert_point(position, layer_group=layer_group, from_units=units, to_units='paper')
    entity = _text_entity(document, review['name'], start, width, height, angle, color, layer_group, layer)
    edits = _edits(document)
    if shared is None:
        edits['added'].append(dict(identifier=review['identifier'], raw=raw, sha256=review['sha256']))
    document.entities += (entity,)
    return entity


def image_text_at(document, index):
    if type(index) is not int or not 0 <= index < len(document.entities):
        raise ValueError('Image text index out of range')
    entity = document.entities[index]
    content = entity.geometry.get('content', '') if entity.entity_type == 'TEXT' else ''
    fields = parse_image_text(content, _embedded_names(document))
    if fields is None:
        raise ValueError('The element is not an image text (^@BM%temp%...) of an embedded image')
    return entity, fields


def delete_image(document, index):
    _require_image_document(document)
    entity, fields = image_text_at(document, index)
    from jwwkit.model.editing import delete_entity
    delete_entity(document, index)
    _edits(document)['drop'].add(fields['name'].lower() + '.gz')


def replace_image(document, index, path, *, name=None, keep_height=False):
    _require_image_document(document)
    if type(keep_height) is not bool:
        raise ValueError('keep_height must be True or False')
    _refuse_six_field_form(document)
    entity, fields = image_text_at(document, index)
    if fields['trimming'] != (0.0, 0.0, 1.0):
        raise ValueError('Replacing a trimmed image is not supported (the trimming rules are not known)')
    if entity.attributes.get('flag', 0) != 0:
        raise ValueError('Replacing an image text with flag 2 is not supported (its meaning is not known)')
    if not 0 <= fields['angle'] < 360:
        raise ValueError('Replacing an image with an angle outside 0..360 degrees is not supported')
    start = (entity.geometry['start_x'], entity.geometry['start_y'])
    attributes = entity.attributes
    # Check everything before changing the document.
    review, raw, shared = prepare_image(document, path, name=name)
    height = fields['height'] if keep_height else fields['width'] * review['height'] / review['width']
    # Kept from the old text: position, width, angle, transparent colour, layer group, layer, pen colour and
    # group. Pen style, text size and font are the values Jw_cad writes for image texts.
    new = _text_entity(document, review['name'], start, fields['width'], height, fields['angle'],
                       fields['color'], attributes['layer_group'], attributes['layer'],
                       pen_color=attributes['pen_color'], group=attributes['group'])
    delete_image(document, index)
    if shared is None:
        _edits(document)['added'].append(dict(identifier=review['identifier'], raw=raw, sha256=review['sha256']))
    document.entities += (new,)
    return new


__all__ = ['add_image', 'delete_image', 'replace_image', 'prepare_image', 'embedded_name']
