# 共通編集結果の対応表

CadDocumentの31メソッド。ソースの許可表/実際の関数引数から生成し、各メソッドを計画→保存/読戻しと旧APIの全バイト一致で試験する。従来の戻り値と例外は変えない。詳細はedit_results.md。

|メソッド|実際の引数|計画の対象指定|
|---|---|---|
|CadDocument.delete_entity|`(self, index)`|indicesに対象1件|
|CadDocument.delete_entities|`(self, indices)`|indicesに対象一覧|
|CadDocument.move_entities|`(self, indices, delta, *, units='paper')`|indicesに対象一覧|
|CadDocument.move_entity|`(self, index, delta, *, units='paper')`|indicesに対象1件|
|CadDocument.transform_entities|`(self, indices, **options)`|indicesに対象一覧|
|CadDocument.copy_entities|`(self, indices, delta=(0, 0), *, units='paper')`|indicesに対象一覧|
|CadDocument.align_two_points|`(self, indices, source_points, target_points, *, distance_tolerance, angle_tolerance, angle_units='rad', allow_scale=False)`|indicesに対象一覧|
|CadDocument.rotate_entities|`(self, indices, angle, **options)`|indicesに対象一覧|
|CadDocument.reflect_entities|`(self, indices, **options)`|indicesに対象一覧|
|CadDocument.scale_entities|`(self, indices, scale_x, scale_y=None, **options)`|indicesに対象一覧|
|CadDocument.set_entity_attributes|`(self, index, *, color=None, linetype=None, width=None, layer=None, layer_group=None, preserve='paper')`|indicesに対象1件|
|CadDocument.set_text|`(self, index: 'int', content: 'str', *, recalculate_end: 'bool' = False) -> 'None'`|indicesに対象1件|
|CadDocument.recalculate_text_endpoint|`(self, index: 'int') -> 'None'`|indicesに対象1件|
|CadDocument.set_group_scale|`(self, layer_group: 'int', scale: 'float') -> 'None'`|kwargs（要素indicesなし）|
|CadDocument.add_line|`(self, start, end, *, layer_group=0, units='paper', **attributes) -> 'CadEntity'`|kwargs（要素indicesなし）|
|CadDocument.add_text|`(self, start, end=None, content=None, *, layer_group=0, units='paper', **attributes) -> 'CadEntity'`|kwargs（要素indicesなし）|
|CadDocument.add_circle|`(self, center, radius, *, layer_group=0, units='paper', flatness=1.0, tilt_angle=0.0, **attributes) -> 'CadEntity'`|kwargs（要素indicesなし）|
|CadDocument.add_point|`(self, position, *, layer_group=0, units='paper', **attributes) -> 'CadEntity'`|kwargs（要素indicesなし）|
|CadDocument.add_solid|`(self, points, *, rgb=None, layer_group=0, units='paper', **attributes) -> 'CadEntity'`|kwargs（要素indicesなし）|
|CadDocument.add_circle_solid|`(self, center, radius, *, solid_mode=100.0, flatness=1.0, tilt_angle=0.0, start_angle=0.0, arc_angle=6.283185307179586, rgb=None, inner_radius=None, layer_group=0, units='paper', **attributes) -> 'CadEntity'`|kwargs（要素indicesなし）|
|CadDocument.set_group_state|`(self, layer_group, state)`|kwargs（要素indicesなし）|
|CadDocument.set_layer_state|`(self, layer_group, layer, state)`|kwargs（要素indicesなし）|
|CadDocument.set_layer_name|`(self, layer_group, layer, name)`|kwargs（要素indicesなし）|
|CadDocument.set_group_name|`(self, layer_group, name)`|kwargs（要素indicesなし）|
|CadDocument.add_block_definition|`(self, name, entities, *, timestamp=0, compound_kind=None)`|kwargs（定義は選択indicesまたは宣言entities）|
|CadDocument.add_arc|`(self, center, radius, start_angle, arc_angle, *, layer_group=0, units='paper', **attributes) -> 'CadEntity'`|kwargs（要素indicesなし）|
|CadDocument.set_dimension_text|`(self, index: 'int', content: 'str') -> 'None'`|indicesに対象1件|
|CadDocument.place_block|`(self, def_number, position, *, layer_group=0, units='paper', **attributes) -> 'CadEntity'`|kwargs（要素indicesなし）|
|CadDocument.replace_entities_with_block|`(self, indices, name, **options)`|indicesに対象一覧|
|CadDocument.set_block_layer_priority|`(self, index: 'int', enabled: 'bool') -> 'None'`|indicesに対象1件|
|CadDocument.import_group|`(self, path, source_group, target_group, *, sync_scale=False, sync_group_name=True, sync_layer_names=True, block_renames=None, settings_policy='strict')`|kwargs（要素indicesなし）|

JwwDocument13/LegacyDocument1は対象外。名前の推測で別のメソッドへ回避しない。保存/factory/読取りは31件に含めない。
既存計画の28編集操作は従来の許可表のまま。追加4名はschema5だけで許可し、編集権限の黙示拡大を防ぐ。
