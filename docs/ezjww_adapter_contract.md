# ezjww窓口の内部契約

対象はezjww **0.7.13**（依存の範囲は`>=0.7.13,<0.8`。Issue #46で0.2.13から上げた）。唯一の実行用窓口は `src/jwwkit/_ezjww_adapter.py` の `read_native_document(path)`。利用者向け公開APIではない。`src/jwwkit/reader/archive.py` と `src/jwwkit/writer/template_document.py` はこの窓口を使う。モデルの不要な直接importを除き、src内のezjww import/呼出しをこの1モジュールへ集約した。テストと開発監査の直接呼出しは独立した比較相手として維持する。

## 呼出し契約

- `ezjww.read_document(str(path))` を1回だけ呼ぶ。Pathでも文字列でも従来と同じstr変換を行う。
- 戻った**同一の辞書オブジェクト**を返す。浅い/深いコピー、型変換、キーの追加、文字復号、診断の正規化はしない。呼出し側は従来どおり辞書を更新できる。
- キーの削除は、下の「0.7.13で増えた欄の取り除き」に挙げた7つの欄だけを、その場で行う。それ以外のキーは削除しない。
- 例外を捕捉・再包装せず、その例外オブジェクトをそのまま伝播する。別Readerへの切替、再試行、部分成功の完全成功への変更はしない。
- importは従来どおり即時に行い、ezjwwを必須依存のままにする。
- 版の範囲はpyproject.tomlとrequirements.txtで指定する。公開試験`tests/test_ezjww_adapter.py`が、導入版がこの範囲の中であることと、窓口の結果の欄の名前が0.2.13と同じであることを確かめる。窓口に新たな版判定/型検証による実行時拒否は追加しない。契約違反をテストで検出する方式にして、既存の受理・拒否を変えない。

## 0.7.13で増えた欄の取り除き

0.7.13の結果には、0.2.13になかった次の7つの欄がある。窓口はこれだけを取り除き、照合・`read_document()`の限定の読取り・テンプレートの読取りのどれにも、0.2.13と同じ形の結果を渡す。jwwkitの公開の出力（`CadDocument.header`、`read_document()`の結果など）は、これで変わらない。見せるかどうかは別のIssueで決める。

|欄|場所|
|---|---|
|`pens`・`line_types`・`text_presets`|header|
|`images`・`text_encoding`|結果の一番上|
|`image`|TEXTの要素（図面直下とブロック定義の中）|
|`base`|DIMENSIONの中のline・text・aux_lines・aux_points（0.2.13では欠けていた。残すと照合で比べる相手が増える）|

- 取り除いた欄を指す診断も取り除く。`diagnostics` のうち、`details.field` が上の欄そのもの、またはその下（欄の名前の直後が終わり・`.`・`[`）を指すものだけ。名前の始まりが同じなだけの別の欄（`header.pens_extra` など）は残す。リストは同じものの中身を変える。
  - 例：0.7.13は、ヘッダーの線種の表のSXFの名前がCP932として正しくないとき `header.line_types.sxf[n].name` の警告を出す。表を取り除くので、この警告も取り除く。レイヤ名の警告（`header.layer_groups[…]…`）は0.2.13と同じく残る。
  - 要素の中の欄（文字の`image`、寸法の中の`base`）を指す診断は、`entities[n]…`・`block_defs[n].entities[m]…` の形のものを取り除く。ただし、実務図面の全件で見た要素の診断の場所は `entity.text.content` の形（番号なし）で、取り除いた欄を指すものは0件だった。この形の条件は念のためのもので、実物では確かめていない。
- 欄の名前は公開の見本で調べ、実務図面の全件でもほかに増えた欄がないことを確かめた（Issue #46）。例外は診断の中の欄で、0.7.13だけが出す同梱の画像の読取りの診断（場所の欄なし）が2件の図面にあった。どちらもjwwkitが拒否するクラスの版0の図面で、利用者には見えない。
- これ以外の知らない欄が増えたときは、捨てずに残す。公開試験の欄の名前の比べで気づける。
- 取り除いた後も、jwwkitが読めずezjwwが読めた図面では、`read_document()`の限定の読取りが返す要素が0.2.13と違うことがある。0.7.13が前より多く読めるためで、取り除きの対象ではない。

## 戻り値の契約

窓口が返すJWW辞書は次の8キー（0.2.13と同じ形）。以下の型/意味は0.2.13で調べた使用契約であり、0.7.13でも前からある欄の値が同じであることを実務図面の全件で確かめた（Issue #46。違ったのは、0.2.13が要素を0個で返していた個数の書き方の図面と、上の画像の診断の2件だけ。詳しくはVERIFICATION.mdの13）。新しい版へ一般化しない。上の7つ以外の未知の追加キーが返った場合も、窓口は勝手に捨てない。

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
|DIMENSION|line/text：dict、sxf_mode：intまたはNone、aux_lines：2個のlist[dict]、aux_points：4個のlist[dict]。内包のbase/typeは欠けることがある（0.7.13が返す内包のbaseは窓口が取り除く）|
|block_defs内の定義|number：int、is_referenced：bool、name：str、base：dict、entities：list[dict]。定義timestampは公開していない|

独自wrapperは数値/属性/要素数をnativeと突き合わせるが、font_name/content/timestampは比較から除外し、内包base/typeのnative欠落も従来どおり許容する。その後entities/block_defsを原文字・内包属性・日時を保持する独自rawへ置換する。adapterはこの処理を引き受けず、順序や条件も変えない。

ブロック定義の数の上限：ezjwwは、定義が10,000個を超える図面で`block_defs`を空のlistで返し、diagnosticsも出さない（0.2.13と0.7.13で同じ動きを確認。10,000個までは全件を返す）。図面直下の`entities`は影響を受けず、`validation`では配置が未解決として数えられる。ezjww側には報告済み（monozukuri-ai/ezjwwのIssue #17）。独自wrapperは図面直下の照合の後、定義の照合の直前に「native定義0個かつraw定義が10,000個超」を見分け、`RecordError`（`Block definitions exceed the ezjww limit`）で拒否する。nativeの定義を補ったり照合を外したりはしない。それ以外の数の不一致は従来の`Native/raw record count mismatch`のまま。公開試験`tests/test_block_definition_limit.py`は、この上限が変わると落ちる。

### 設定・参照検証・診断

- metadata_settingsの各項目はentity_index:int、key/value/raw:str。対応するentities[entity_index]はTEXTで、contentとrawが対応する。値を数値/boolへ勝手に変換せず、原文字で保持。設定キーを既知6種へ限定した新分類処理は追加しない。
- validationはtotal_references/resolved_references:int、unresolved_def_numbers:list[int]、has_unresolved:bool。未解決を空へ補正しない。nativeの参照検証結果は循環の安全性等すべてを保証する意味ではなく、既存の独自構造検査も維持する。
- diagnosticsのnative項目はcode/severity/message/action:str、details:dict。復号のdetailsはencoding/field、byte_offset/byte_length/replacement_characters:int、had_errors:bool等。切断ではbyte_offset/expected_entities/parsed_entities:int、error:str等。フィールドを省略/統一しない。
- 独自wrapperの補足失敗時には従来どおり文字列診断が追加される場合がある。これはadapterからのnative出力とは区別する。保存時は既知header CP932警告だけ限定許容、その他を拒否する既存処理を維持。

## 契約テストと変更しない境界

開発時に、呼出し窓口の集約、返却オブジェクトと追加欄の保持、例外の伝播と無再試行、v600/v700の読取り結果を照合した。公開フォルダの動作確認は [検証の方法と結果](../VERIFICATION.md) の手順で実行できる。

窓口追加によって読める版/クラス/スキーマ/フラグは増やさない。原ヘッダー保持・本文往復・Rebro明示読取り専用・未知拒否・上書き拒否は変更しない。
