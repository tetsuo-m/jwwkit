# 計画から呼べる公開編集API

ソースのクラスメソッドとsafe_editの許可表を照合した。公開API一覧全体はapi_list.md。計画の実行対象はCadDocument。

CadDocumentの編集APIは27件が直接対応。4件は直接名が未登録で、既存の宣言操作による代替を示す。

| API | 対応 | 範囲・代替 |
| --- | --- | --- |
| CadDocument.delete_entity | 直接名は計画外 | delete_entitiesのindicesを1件にして同等操作が可能。単体名は未登録。 |
| CadDocument.delete_entities | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.move_entities | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.move_entity | 直接名は計画外 | move_entitiesのindicesを1件にして同等操作が可能。単体名は未登録。 |
| CadDocument.transform_entities | 直接名は計画外 | 汎用合成オプションは未登録。copy/rotate/reflect/scaleの宣言操作を順序と単位を明示して使う。 |
| CadDocument.copy_entities | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.align_two_points | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.rotate_entities | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.reflect_entities | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.scale_entities | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.set_entity_attributes | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.set_text | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.recalculate_text_endpoint | 直接名は計画外 | set_textに現在のcontentとrecalculate_end=Trueを指定して同等操作が可能。直接名は未登録。 |
| CadDocument.set_group_scale | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.add_line | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.add_text | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.add_circle | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.add_point | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.add_solid | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.add_circle_solid | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.set_group_state | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.set_layer_state | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.set_layer_name | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.set_group_name | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.add_block_definition | 直接計画対応 | CadDocumentの同名APIを呼ぶ。子は7種の宣言コンストラクタ、または承認済み既存要素。定義内flag2は既知の正規化。 |
| CadDocument.add_arc | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.set_dimension_text | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.place_block | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.replace_entities_with_block | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.set_block_layer_priority | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| CadDocument.import_group | 直接計画対応 | CadDocumentの同名APIを呼ぶ。 |
| JwwDocument.set_layer_name | 別の保存経路：計画外 | 計画は既存CadDocumentを編集する。新規テンプレート/限定旧版のオブジェクトを直接操作しない。CadDocumentの同名操作は計画対応。 |
| JwwDocument.set_group_name | 別の保存経路：計画外 | 計画は既存CadDocumentを編集する。新規テンプレート/限定旧版のオブジェクトを直接操作しない。CadDocumentの同名操作は計画対応。 |
| JwwDocument.set_group_scale | 別の保存経路：計画外 | 計画は既存CadDocumentを編集する。新規テンプレート/限定旧版のオブジェクトを直接操作しない。CadDocumentの同名操作は計画対応。 |
| JwwDocument.add_line | 別の保存経路：計画外 | 計画は既存CadDocumentを編集する。新規テンプレート/限定旧版のオブジェクトを直接操作しない。CadDocumentの同名操作は計画対応。 |
| JwwDocument.add_rectangle_hatch | 別の保存経路：計画外 | 計画は既存CadDocumentを編集する。新規テンプレート/限定旧版のオブジェクトを直接操作しない。 |
| JwwDocument.add_circle | 別の保存経路：計画外 | 計画は既存CadDocumentを編集する。新規テンプレート/限定旧版のオブジェクトを直接操作しない。CadDocumentの同名操作は計画対応。 |
| JwwDocument.add_arc | 別の保存経路：計画外 | 計画は既存CadDocumentを編集する。新規テンプレート/限定旧版のオブジェクトを直接操作しない。CadDocumentの同名操作は計画対応。 |
| JwwDocument.add_point | 別の保存経路：計画外 | 計画は既存CadDocumentを編集する。新規テンプレート/限定旧版のオブジェクトを直接操作しない。CadDocumentの同名操作は計画対応。 |
| JwwDocument.add_text | 別の保存経路：計画外 | 計画は既存CadDocumentを編集する。新規テンプレート/限定旧版のオブジェクトを直接操作しない。CadDocumentの同名操作は計画対応。 |
| JwwDocument.add_dimension | 別の保存経路：計画外 | 計画は既存CadDocumentを編集する。新規テンプレート/限定旧版のオブジェクトを直接操作しない。 |
| JwwDocument.add_solid | 別の保存経路：計画外 | 計画は既存CadDocumentを編集する。新規テンプレート/限定旧版のオブジェクトを直接操作しない。CadDocumentの同名操作は計画対応。 |
| JwwDocument.add_block_definition | 別の保存経路：計画外 | 計画は既存CadDocumentを編集する。新規テンプレート/限定旧版のオブジェクトを直接操作しない。CadDocumentの同名操作は計画対応。 |
| JwwDocument.add_block | 別の保存経路：計画外 | 計画は既存CadDocumentを編集する。新規テンプレート/限定旧版のオブジェクトを直接操作しない。 |
| LegacyDocument.set_text | 別の保存経路：計画外 | 計画は既存CadDocumentを編集する。新規テンプレート/限定旧版のオブジェクトを直接操作しない。 |
| JwsDocument.place_as_block | place_jwsで計画対応 | JWSを依存ハッシュと全要素/定義のレビュー対象として配置する。 |

saveは宣言操作ではなくexecute_plan/save_checkedの最後に指定済み出力へ実行する。

open/from_*、検索/読取り/要約、Line等のモデル構築、rectangle_hatch_lines等の生成補助は既存図面の編集APIではない。

計画の編集操作28種＋GUI専用タグ1種。未知のAPI名を推測で追加しない。グループ/レイヤ/定義はschema2のresource_targetsに変更前の内容とSHA256を載せる。
追加要素のasと、定義のasは別の型。place_block.def_numberには既存整数番号または先に宣言した定義別名を使う。既存定義の名称は番号・全内容とともにレビューする。
add_block_definitionの子指定はkwargs.entitiesの宣言構造かindicesの承認済み要素の片方。宣言のunitsは座標をローカル紙面mmへ換算する指定。既存要素からの定義作成は現在の紙面座標をコピーし、元要素を消さない。世界位置を保って置換する場合はreplace_entities_with_blockを使う。
新しい計画はschema2。schema1の既存計画は従来の10編集操作/GUIタグだけ受け付け、新操作を追加してレビュー情報を省略することは拒否する。


取り込み時の設定方針。import_groupのsettings_policyはstrictが既定、明示destinationだけ先の全体設定生バイトを保持して元の属性番号を取り込む。明示指定のschema2計画ではresource_targets.settingsに方針/両設定ハッシュ/比較列の差/見え方の説明を含める。未定義番号等の拒否は解除しない。旧計画のうち新引数を含まないものは従来のレビュー形式を維持する。


## 検索条件付き計画

write_plan(..., selection=query, selection_limits=None)はschema3。indices=Noneで検索結果を確定し、明示indicesは完全一致が必要。元JSON/実効JSON/規則版/制限/解決値/対象とSHAを保持し、実行前に再検索・完全一致検証を行う。編集操作の許可表は変更しない。旧schema1/2も維持する。定義内の検索結果と不完全な結果は編集対象へ渡せない。詳細はsearch_queries.md。
## 共通編集結果を使う計画

edit_result.write_edit_planは新しいschema5でCadDocument31メソッドに対応する。従来の直接未登録4名（delete_entity/move_entity/transform_entities/recalculate_text_endpoint）も、この契約内だけで許可する。既定のsafe_edit.write_planの許可表は広げず、旧計画1～4の意味を維持する。schema5の実行はexecute_plan_resultだけ。JwwDocument/LegacyDocument/JWS配置/GUIをこの追加の権限へ含めない。詳しくはdocs/edit_results.md。

