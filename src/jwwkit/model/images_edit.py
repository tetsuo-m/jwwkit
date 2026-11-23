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
from jwwkit.writer.images import (TEXT_FONT, TEXT_SIZE, check_new_image, embedded_name, image_text,
                                  parse_image_text)


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
    review['shared_with'] = None
    return review, raw, None


def _text_entity(document, name, start, width, height, angle, color, layer_group, layer):
    content = image_text(name, width, height, angle, color)
    # ASCII only (names are checked): every character takes half the text width (E080).
    advance = TEXT_SIZE * 0.5 * len(content)
    radians = math.radians(angle)
    end = (start[0] + advance * math.cos(radians), start[1] + advance * math.sin(radians))
    record = Text(tuple(start), end, content, size_x=TEXT_SIZE, size_y=TEXT_SIZE, spacing=0.0, angle=float(angle),
                  font_name=TEXT_FONT, alignment=1, color=1, layer=layer, layer_group=layer_group).record()
    document._validate_addition(record)
    return model_entity(record)


def add_image(document, path, position, width, *, height=None, angle=0, transparent_color=(255, 255, 255),
              name=None, layer_group=0, layer=0, units='paper'):
    _require_image_document(document)
    width = _number_check(width, 'width', positive=True)
    angle = _number_check(angle, 'angle')
    if not 0 <= angle < 360:
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
    fields = parse_image_text(entity.geometry.get('content', '')) if entity.entity_type == 'TEXT' else None
    if fields is None:
        raise ValueError('The element is not an image text (^@BM%temp%...) of an embedded image')
    names = {i['identifier'].lower()[:-3] for i in embedded_images(document)}
    if fields['name'].lower() not in names:
        raise ValueError('The image text points to an image that is not embedded')
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
    new = _text_entity(document, review['name'], start, fields['width'], height, fields['angle'],
                       fields['color'], attributes['layer_group'], attributes['layer'])
    delete_image(document, index)
    if shared is None:
        _edits(document)['added'].append(dict(identifier=review['identifier'], raw=raw, sha256=review['sha256']))
    document.entities += (new,)
    return new


__all__ = ['add_image', 'delete_image', 'replace_image', 'prepare_image', 'embedded_name']
