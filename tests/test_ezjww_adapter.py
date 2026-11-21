"""ezjww との窓口の試験（Issue #46）。公開の見本の図面だけを使う。

窓口は ezjww 0.7.13 で増えた 7 つの欄だけを取り除き、0.2.13 と同じ形の結果を返す。
- 入っている ezjww の版が、依存の範囲（>=0.7.13,<0.8）の中であること。
- 公開の見本のすべての図面で、窓口の結果の欄の名前（入れ子の道筋）が、0.2.13 の結果と同じであること。
  ezjww の新しい版で欄が増えたり減ったりしたら、ここが落ちる。そのときは窓口と約束の文書を見直す。
- 取り除くのは決めた欄だけで、戻す dict は ezjww が返したものと同じであること。
"""
import unittest
from importlib.metadata import version
from pathlib import Path
from unittest import mock

import ezjww

from jwwkit import _ezjww_adapter
from jwwkit._ezjww_adapter import read_native_document

FIXTURES = Path(__file__).resolve().parent / 'fixtures'

# ezjww 0.2.13 の結果の欄の道筋（公開の見本の全図面の和）。[種類] は要素の種類、[] はそれ以外の並び。
KEY_PATHS_0213 = frozenset('''
.block_def_names
.block_def_names.0
.block_defs
.block_defs[].base
.block_defs[].base.flag
.block_defs[].base.group
.block_defs[].base.layer
.block_defs[].base.layer_group
.block_defs[].base.pen_color
.block_defs[].base.pen_style
.block_defs[].base.pen_width
.block_defs[].entities
.block_defs[].entities[LINE].base
.block_defs[].entities[LINE].base.flag
.block_defs[].entities[LINE].base.group
.block_defs[].entities[LINE].base.layer
.block_defs[].entities[LINE].base.layer_group
.block_defs[].entities[LINE].base.pen_color
.block_defs[].entities[LINE].base.pen_style
.block_defs[].entities[LINE].base.pen_width
.block_defs[].entities[LINE].end_x
.block_defs[].entities[LINE].end_y
.block_defs[].entities[LINE].start_x
.block_defs[].entities[LINE].start_y
.block_defs[].entities[LINE].type
.block_defs[].entities[TEXT].angle
.block_defs[].entities[TEXT].base
.block_defs[].entities[TEXT].base.flag
.block_defs[].entities[TEXT].base.group
.block_defs[].entities[TEXT].base.layer
.block_defs[].entities[TEXT].base.layer_group
.block_defs[].entities[TEXT].base.pen_color
.block_defs[].entities[TEXT].base.pen_style
.block_defs[].entities[TEXT].base.pen_width
.block_defs[].entities[TEXT].content
.block_defs[].entities[TEXT].end_x
.block_defs[].entities[TEXT].end_y
.block_defs[].entities[TEXT].font_name
.block_defs[].entities[TEXT].size_x
.block_defs[].entities[TEXT].size_y
.block_defs[].entities[TEXT].spacing
.block_defs[].entities[TEXT].start_x
.block_defs[].entities[TEXT].start_y
.block_defs[].entities[TEXT].text_type
.block_defs[].entities[TEXT].type
.block_defs[].is_referenced
.block_defs[].name
.block_defs[].number
.diagnostics
.entities
.entities[ARC].arc_angle
.entities[ARC].base
.entities[ARC].base.flag
.entities[ARC].base.group
.entities[ARC].base.layer
.entities[ARC].base.layer_group
.entities[ARC].base.pen_color
.entities[ARC].base.pen_style
.entities[ARC].base.pen_width
.entities[ARC].center_x
.entities[ARC].center_y
.entities[ARC].flatness
.entities[ARC].is_full_circle
.entities[ARC].radius
.entities[ARC].start_angle
.entities[ARC].tilt_angle
.entities[ARC].type
.entities[BLOCK].base
.entities[BLOCK].base.flag
.entities[BLOCK].base.group
.entities[BLOCK].base.layer
.entities[BLOCK].base.layer_group
.entities[BLOCK].base.pen_color
.entities[BLOCK].base.pen_style
.entities[BLOCK].base.pen_width
.entities[BLOCK].block_name
.entities[BLOCK].def_number
.entities[BLOCK].ref_x
.entities[BLOCK].ref_y
.entities[BLOCK].rotation
.entities[BLOCK].scale_x
.entities[BLOCK].scale_y
.entities[BLOCK].type
.entities[CIRCLE_SOLID].arc_angle
.entities[CIRCLE_SOLID].base
.entities[CIRCLE_SOLID].base.flag
.entities[CIRCLE_SOLID].base.group
.entities[CIRCLE_SOLID].base.layer
.entities[CIRCLE_SOLID].base.layer_group
.entities[CIRCLE_SOLID].base.pen_color
.entities[CIRCLE_SOLID].base.pen_style
.entities[CIRCLE_SOLID].base.pen_width
.entities[CIRCLE_SOLID].center_x
.entities[CIRCLE_SOLID].center_y
.entities[CIRCLE_SOLID].color
.entities[CIRCLE_SOLID].flatness
.entities[CIRCLE_SOLID].radius
.entities[CIRCLE_SOLID].solid_mode
.entities[CIRCLE_SOLID].start_angle
.entities[CIRCLE_SOLID].tilt_angle
.entities[CIRCLE_SOLID].type
.entities[DIMENSION].aux_lines
.entities[DIMENSION].aux_lines[].end_x
.entities[DIMENSION].aux_lines[].end_y
.entities[DIMENSION].aux_lines[].start_x
.entities[DIMENSION].aux_lines[].start_y
.entities[DIMENSION].aux_points
.entities[DIMENSION].aux_points[].angle
.entities[DIMENSION].aux_points[].code
.entities[DIMENSION].aux_points[].is_temporary
.entities[DIMENSION].aux_points[].scale
.entities[DIMENSION].aux_points[].x
.entities[DIMENSION].aux_points[].y
.entities[DIMENSION].base
.entities[DIMENSION].base.flag
.entities[DIMENSION].base.group
.entities[DIMENSION].base.layer
.entities[DIMENSION].base.layer_group
.entities[DIMENSION].base.pen_color
.entities[DIMENSION].base.pen_style
.entities[DIMENSION].base.pen_width
.entities[DIMENSION].line
.entities[DIMENSION].line.end_x
.entities[DIMENSION].line.end_y
.entities[DIMENSION].line.start_x
.entities[DIMENSION].line.start_y
.entities[DIMENSION].sxf_mode
.entities[DIMENSION].text
.entities[DIMENSION].text.angle
.entities[DIMENSION].text.content
.entities[DIMENSION].text.end_x
.entities[DIMENSION].text.end_y
.entities[DIMENSION].text.font_name
.entities[DIMENSION].text.size_x
.entities[DIMENSION].text.size_y
.entities[DIMENSION].text.spacing
.entities[DIMENSION].text.start_x
.entities[DIMENSION].text.start_y
.entities[DIMENSION].text.text_type
.entities[DIMENSION].type
.entities[LINE].base
.entities[LINE].base.flag
.entities[LINE].base.group
.entities[LINE].base.layer
.entities[LINE].base.layer_group
.entities[LINE].base.pen_color
.entities[LINE].base.pen_style
.entities[LINE].base.pen_width
.entities[LINE].end_x
.entities[LINE].end_y
.entities[LINE].start_x
.entities[LINE].start_y
.entities[LINE].type
.entities[POINT].angle
.entities[POINT].base
.entities[POINT].base.flag
.entities[POINT].base.group
.entities[POINT].base.layer
.entities[POINT].base.layer_group
.entities[POINT].base.pen_color
.entities[POINT].base.pen_style
.entities[POINT].base.pen_width
.entities[POINT].code
.entities[POINT].is_temporary
.entities[POINT].scale
.entities[POINT].type
.entities[POINT].x
.entities[POINT].y
.entities[TEXT].angle
.entities[TEXT].base
.entities[TEXT].base.flag
.entities[TEXT].base.group
.entities[TEXT].base.layer
.entities[TEXT].base.layer_group
.entities[TEXT].base.pen_color
.entities[TEXT].base.pen_style
.entities[TEXT].base.pen_width
.entities[TEXT].content
.entities[TEXT].end_x
.entities[TEXT].end_y
.entities[TEXT].font_name
.entities[TEXT].size_x
.entities[TEXT].size_y
.entities[TEXT].spacing
.entities[TEXT].start_x
.entities[TEXT].start_y
.entities[TEXT].text_type
.entities[TEXT].type
.entity_counts
.entity_counts.ARC
.entity_counts.BLOCK
.entity_counts.CIRCLE_SOLID
.entity_counts.DIMENSION
.entity_counts.LINE
.entity_counts.POINT
.entity_counts.TEXT
.header
.header.layer_groups
.header.layer_groups[].layers
.header.layer_groups[].layers[].name
.header.layer_groups[].layers[].protect
.header.layer_groups[].layers[].state
.header.layer_groups[].name
.header.layer_groups[].protect
.header.layer_groups[].scale
.header.layer_groups[].state
.header.layer_groups[].write_layer
.header.memo
.header.palette
.header.palette.extended_colors
.header.palette.pen_colors
.header.paper_size
.header.version
.header.write_layer_group
.metadata_settings
.metadata_settings[].entity_index
.metadata_settings[].key
.metadata_settings[].raw
.metadata_settings[].value
.validation
.validation.has_unresolved
.validation.resolved_references
.validation.total_references
.validation.unresolved_def_numbers
'''.split())


def key_paths(value, prefix='', out=None):
    out = set() if out is None else out
    if isinstance(value, dict):
        for key, item in value.items():
            path = f'{prefix}.{key}'
            out.add(path)
            key_paths(item, path, out)
    elif isinstance(value, list):
        for item in value:
            kind = item.get('type') if isinstance(item, dict) else None
            key_paths(item, prefix + (f'[{kind}]' if kind else '[]'), out)
    return out


def drawings():
    found = sorted(FIXTURES.rglob('*.jww'))
    if not found:
        raise unittest.SkipTest('public fixtures are missing')
    return found


class EzjwwAdapterTests(unittest.TestCase):
    def test_installed_version_is_in_the_dependency_range(self):
        parts = tuple(int(part) for part in version('ezjww').split('.')[:3])
        self.assertGreaterEqual(parts, (0, 7, 13))
        self.assertLess(parts, (0, 8))

    def test_result_shape_matches_0213_on_public_fixtures(self):
        seen = set()
        for path in drawings():
            key_paths(read_native_document(path), out=seen)
        self.assertEqual(sorted(seen - KEY_PATHS_0213), [], 'fields not in the 0.2.13 result')
        self.assertEqual(sorted(KEY_PATHS_0213 - seen), [], 'fields of the 0.2.13 result are missing')

    def test_only_the_listed_fields_are_removed(self):
        removed = ('.images', '.text_encoding', '.header.pens', '.header.line_types', '.header.text_presets',
                   '[TEXT].image', '[DIMENSION].line.base', '[DIMENSION].text.base',
                   '[DIMENSION].aux_lines[].base', '[DIMENSION].aux_points[].base')
        for path in drawings():
            native = key_paths(ezjww.read_document(str(path)))
            adapted = key_paths(read_native_document(path))
            for extra in native - adapted:
                # the marker must end at the end of the path or at the next part ('.' or '[')
                self.assertTrue(any(marker in extra and (extra.endswith(marker) or
                                                         extra.split(marker, 1)[1][:1] in '.[')
                                    for marker in removed), extra)

    def test_text_image_and_dimension_part_base_only_are_removed(self):
        def text():
            return {'type': 'TEXT', 'base': {'layer': 1}, 'content': 'a', 'image': {'width': 1}}

        def dimension():
            part = lambda: {'base': {'layer': 2}, 'start_x': 0.0}
            return {'type': 'DIMENSION', 'base': {'layer': 3}, 'line': part(), 'text': part(),
                    'aux_lines': [part(), part()], 'aux_points': [part()]}
        line = {'type': 'LINE', 'base': {'layer': 4}, 'image': 'kept on other kinds'}
        result = {'header': {}, 'entities': [text(), dimension(), dict(line)], 'diagnostics': [],
                  'block_defs': [{'number': 1, 'base': {'layer': 5}, 'entities': [text(), dimension()]}]}
        with mock.patch.object(_ezjww_adapter._ezjww, 'read_document', return_value=result):
            read_native_document('x.jww')
        for entities in (result['entities'], result['block_defs'][0]['entities']):
            self.assertEqual(entities[0], {'type': 'TEXT', 'base': {'layer': 1}, 'content': 'a'})
            dim = entities[1]
            self.assertEqual(dim['base'], {'layer': 3})
            for part in [dim['line'], dim['text'], *dim['aux_lines'], *dim['aux_points']]:
                self.assertEqual(part, {'start_x': 0.0})
        self.assertEqual(result['entities'][2], line)
        self.assertEqual(result['block_defs'][0]['base'], {'layer': 5})

    def test_same_object_is_returned_and_exceptions_pass_through(self):
        result = {'header': {'pens': 1, 'version': 700}, 'entities': [], 'block_defs': [], 'images': [],
                  'text_encoding': 'cp932', 'unknown_new_field': 1}
        with mock.patch.object(_ezjww_adapter._ezjww, 'read_document', return_value=result) as called:
            returned = read_native_document(Path('x.jww'))
        called.assert_called_once_with('x.jww')
        self.assertIs(returned, result)
        self.assertEqual(returned, {'header': {'version': 700}, 'entities': [], 'block_defs': [],
                                    'unknown_new_field': 1})
        error = OSError('boom')
        with mock.patch.object(_ezjww_adapter._ezjww, 'read_document', side_effect=error):
            with self.assertRaises(OSError) as caught:
                read_native_document('x.jww')
        self.assertIs(caught.exception, error)


    def test_diagnostics_on_removed_fields_are_removed_and_others_kept(self):
        removed = ['header.line_types', 'header.line_types.sxf[1].name', 'header.pens[0].width', 'header.pens.printer',
                   'header.text_presets[2]', 'images[0].data', 'text_encoding',
                   'entities[3].image.width', 'block_defs[2].entities[0].line.base',
                   'entities[5].aux_points[1].base.layer']
        kept = ['header.pens_extra', 'header.line_typesx.name', 'header.layer_groups[0].layers[2].name',
                'entities[3].content', 'entities[3].text.content', 'entity.text.content', 'block_definition.name',
                'imagesx', 'header.memo']
        diagnostics = [dict(code='CP932_DECODE_REPLACED', details=dict(field=f)) for f in removed + kept]
        # A diagnostic with no field (0.7.13's IMAGE_LIST_TRUNCATED, say) is kept: it does not point to a removed field.
        others = ['Exact text/embedded attributes unverified: x', dict(code='IMAGE_LIST_TRUNCATED', details={}),
                  dict(code='OTHER')]
        result = {'header': {}, 'entities': [], 'block_defs': [], 'diagnostics': diagnostics + others}
        listed = result['diagnostics']
        with mock.patch.object(_ezjww_adapter._ezjww, 'read_document', return_value=result):
            returned = read_native_document('x.jww')
        self.assertIs(returned['diagnostics'], listed)
        fields = [d['details']['field'] for d in returned['diagnostics']
                  if isinstance(d, dict) and d.get('details', {}).get('field')]
        self.assertEqual(fields, kept)
        self.assertEqual(returned['diagnostics'][len(kept):], others)


class SyntheticDecodeWarningTests(unittest.TestCase):
    """公開の v700 の見本を書き換え、レイヤ名（残す）と SXF の線種の名前（取り除く）を、正しくない CP932 にした図面。"""

    @classmethod
    def setUpClass(cls):
        import tempfile
        from jwwkit import CadDocument
        source = FIXTURES / 'jwcad_saved' / 'jwcad10036_save_v700.jww'
        if not source.exists():
            raise unittest.SkipTest('public fixture is missing')
        cls.folder = Path(tempfile.mkdtemp(prefix='jwwkit-adapter-'))
        named = cls.folder / 'named.jww'
        document = CadDocument.open(source)
        document.set_layer_name(0, 2, 'QZXQ')
        document.save(named)
        data = named.read_bytes()
        # Jw_cad 10 writes these names as Unicode CStrings (ff fe ff + length + UTF-16). Write each as an
        # ANSI CString of the same length whose first two bytes are not a CP932 pair.
        layer = b'\xff\xfe\xff\x04' + 'QZXQ'.encode('utf-16-le')
        sxf = b'\xff\xfe\xff\x0a' + 'continuous'.encode('utf-16-le')
        assert data.count(layer) == 1 and data.count(sxf) == 1
        data = data.replace(layer, b'\x04\x81\x20ZX').replace(sxf, b'\x0a\x81\x20ntinuous')
        cls.drawing = cls.folder / 'decode_warnings.jww'
        cls.drawing.write_bytes(data)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.folder, ignore_errors=True)

    @staticmethod
    def fields(diagnostics):
        return [d['details']['field'] for d in diagnostics if isinstance(d, dict)]

    def test_ezjww_reports_both_warnings(self):
        self.assertEqual(self.fields(ezjww.read_document(str(self.drawing))['diagnostics']),
                         ['header.layer_groups[0].layers[2].name', 'header.line_types.sxf[1].name'])

    def test_adapter_and_document_keep_only_the_layer_name_warning(self):
        from jwwkit import CadDocument
        self.assertEqual(self.fields(read_native_document(self.drawing)['diagnostics']),
                         ['header.layer_groups[0].layers[2].name'])
        document = CadDocument.open(self.drawing)
        self.assertEqual(self.fields(document.diagnostics), ['header.layer_groups[0].layers[2].name'])
        target = self.folder / 'saved.jww'
        document.save(target)
        self.assertEqual(target.read_bytes(), self.drawing.read_bytes())


if __name__ == '__main__':
    unittest.main()
