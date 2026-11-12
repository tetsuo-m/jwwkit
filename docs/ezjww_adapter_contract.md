# ezjww窓口の内部契約

対象はezjww **0.2.13**。唯一の実行用窓口は `src/_ezjww_adapter.py` の `read_native_document(path)`。利用者向け公開APIではない。`src/reader/archive.py` と `src/writer/template_document.py` はこの窓口を使う。モデルの不要な直接importを除き、src内のezjww import/呼出しをこの1モジュールへ集約した。テストと開発監査の直接呼出しは独立した比較相手として維持する。

## 呼出し契約

- `ezjww.read_document(str(path))` を1回だけ呼ぶ。Pathでも文字列でも従来と同じstr変換を行う。
- 戻った**同一の辞書オブジェクト**を返す。浅い/深いコピー、型変換、キーの追加/削除、文字復号、診断の正規化はしない。呼出し側は従来どおり辞書を更新できる。
- 例外を捕捉・再包装せず、その例外オブジェクトをそのまま伝播する。別Readerへの切替、再試行、部分成功の完全成功への変更はしない。
- importは従来どおり即時に行い、ezjwwを必須依存のままにする。
- 版固定はrequirements.txtで行う。契約テストも導入版0.2.13を確認するが、窓口に新たな版判定/型検証による実行時拒否は追加しない。契約違反をテストで検出する方式にして、既存の受理・拒否を変えない。

## 戻り値の契約

0.2.13のJWW辞書は次の8キー。以下の型/意味はこの版の使用契約であり、新しい版へ一般化しない。未知の追加キーが返った場合も窓口は勝手に捨てない。

|キー|型|意味と利用|
|---|---|---|
|header|dict|版・メモ・用紙・書込み群・パレット・群/層の復号結果。モデルの原状態として保持し、群操作/不変監査/テンプレート比較に使う|
|entities|list[dict]|設定TEXTを含む図面直下の保存順の要素。定義内要素はここに混ぜない|
|block_defs|list[dict]|定義番号・名称・属性・参照状態・定義内要素。参照と定義の区別を維持|
|metadata_settings|list[dict]|設定TEXTの分類。entity_indexはentitiesの0始まり添字であり、通常図形を除外した後の公開番号ではない|
|block_def_names|dict[int,str]|定義番号から名前への表。低レベル結果として保持、現行モデルはこの表を直接利用しない|
|entity_counts|dict[str,int]|entities直下の種類別件数。設定TEXTを含み、定義内を足さない|
|validation|dict|ブロック参照の解決結果。モデル/テンプレートで未解決参照の拒否に使う|
|diagnostics|list[dict]|復号・切断等のnative診断。空であることと、部分読取りに診断があることを区別する|

### header

|項目|型|意味|
|---|---|---|
|version|int|保存版。ライブラリの通常JWW入口は観測済み600/700に限定|
|memo|str|メモの復号結果。原CStringの保持は別の独自Readerで行う|
|paper_size|int|用紙コード。ここで用紙サイズの単位換算をしない|
|write_layer_group|int|書込み群番号|
|palette|dictまたはNone|pen_colors（list[int]、10個の標準色COLORREF）、extended_colors（list[int]、257個またはNone）。個々の値を別の色番号へ変換しない|
|layer_groups|list[dict]、16個|各群はstate:int、write_layer:int、scale:float、protect:int、name:str、layers:list[dict]。scaleは縮尺分母。各16層はstate:int、protect:int、name:str|

nameはnativeの復号/表示用代替名を含むことがある。原保存名の空欄・不完全CP932・原バイトは独自の名称表で保持し、この辞書だけを原バイトの証明にしない。stateやprotectの意味をこの窓口で再解釈せず、既存の表示状態API/拒否規則へ渡す。

### 要素・定義

共通baseはgroup/pen_style/pen_color/pen_width/layer/layer_group/flag（全てint）。groupは曲線属性番号で、layer_groupと別。flagの意味を異なる種類へ一般化しない。保存座標は紙面mm、TEXTのangleは度、円弧の角度・BLOCK.rotationはrad。値・順序・表現はnativeのまま返す。POINT.angleをTEXT.angleと同じ規則へ変換しない。

|種類|使用する欄|
|---|---|
|LINE|start_x/start_y/end_x/end_y：float|
|CIRCLE/ARC|center_x/center_y/radius/start_angle/arc_angle/tilt_angle/flatness：float、is_full_circle：bool|
|POINT|x/y/angle/scale：float、is_temporary：bool、code：int|
|TEXT|始終点/size_x/size_y/spacing/angle：float、text_type：int、font_name/content：str|
|SOLID|point1～4のx/y：float、color：intまたはNone。頂点の保存順を入れ替えない|
|CIRCLE_SOLID|center_x/center_y/radius/flatness/tilt_angle/start_angle/arc_angle/solid_mode：float、color：intまたはNone。solid_modeの意味を塗り種別へ固定しない（円環では内半径）|
|BLOCK|ref_x/ref_y/scale_x/scale_y/rotation：float、def_number：int、block_name：strまたはNone（native追加欄）。scaleは無次元|
|DIMENSION|line/text：dict、sxf_mode：intまたはNone、aux_lines：2個のlist[dict]、aux_points：4個のlist[dict]。0.2.13では内包base/typeが欠けることがある|
|block_defs内の定義|number：int、is_referenced：bool、name：str、base：dict、entities：list[dict]。0.2.13は定義timestampを公開していない|

独自wrapperは数値/属性/要素数をnativeと突き合わせるが、font_name/content/timestampは比較から除外し、内包base/typeのnative欠落も従来どおり許容する。その後entities/block_defsを原文字・内包属性・日時を保持する独自rawへ置換する。adapterはこの処理を引き受けず、順序や条件も変えない。

### 設定・参照検証・診断

- metadata_settingsの各項目はentity_index:int、key/value/raw:str。対応するentities[entity_index]はTEXTで、contentとrawが対応する。値を数値/boolへ勝手に変換せず、原文字で保持。設定キーを既知6種へ限定した新分類処理は追加しない。
- validationはtotal_references/resolved_references:int、unresolved_def_numbers:list[int]、has_unresolved:bool。未解決を空へ補正しない。nativeの参照検証結果は循環の安全性等すべてを保証する意味ではなく、既存の独自構造検査も維持する。
- diagnosticsのnative項目はcode/severity/message/action:str、details:dict。復号のdetailsはencoding/field、byte_offset/byte_length/replacement_characters:int、had_errors:bool等。切断ではbyte_offset/expected_entities/parsed_entities:int、error:str等。フィールドを省略/統一しない。
- 独自wrapperの補足失敗時には従来どおり文字列診断が追加される場合がある。これはadapterからのnative出力とは区別する。保存時は既知header CP932警告だけ限定許容、その他を拒否する既存処理を維持。

## 契約テストと変更しない境界

開発時に、呼出し窓口の集約、返却オブジェクトと追加欄の保持、例外の伝播と無再試行、v600/v700の読取り結果を照合した。公開フォルダの動作確認は [検証の方法と結果](../VERIFICATION.md) の手順で実行できる。

窓口追加によって読める版/クラス/スキーマ/フラグは増やさない。原ヘッダー保持・本文往復・Rebro明示読取り専用・未知拒否・上書き拒否は変更しない。
