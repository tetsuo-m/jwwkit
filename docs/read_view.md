# 不変の読取りビュー

`read_view.create_read_view` はCadDocumentの現在の公開要素・定義・ヘッダー・設定・診断を、参照を共有しない読取りスナップショットへ固定する。srcの既存入口・受理/拒否・保存処理を変えない。ezjwwは0.2.13の必須依存のまま。図面の編集や保存を行わない。

## 利用例

この例は別名の結果JSONだけを新規作成する。図面に書き込まず、既存の出力は拒否する。

```python
import json
from pathlib import Path
from read_view import create_read_view, resolve_file_reference

view = create_read_view('input.jww')
brief = view.entities(mode='summary')
detail = view.entities(limit=10)
reference = view.file_reference(0)
same_item = resolve_file_reference('input.jww', reference)
with Path('inspection.json').open('x', encoding='utf-8') as stream:
    json.dump({'summary': brief, 'details': detail, 'reference': reference,
               'same_item': same_item}, stream, ensure_ascii=True, indent=2)
```

CadDocumentを渡せば、未保存の編集も含めてその時点を固定する。元モデル・返却辞書を変更してもビューの値は変わらない。旧ビューは旧時点を読み続けるので、編集計画にはそのまま流さず、既存safe_editで原本/現在対象/計画SHAを再検証する。ビュー作成中に別スレッドからモデルを変更する使い方は対象外で、呼出し側で編集と同期する。

include_metadata/schema_profileのNoneは、パス入力ならFalse/strict、CadDocument入力なら読み込んだ状態を維持する。CadDocumentに矛盾する明示指定は拒否する。既定では従来同様、設定TEXTを通常要素から除外する。

## API

- `create_read_view(source, *, include_metadata=None, schema_profile=None, max_snapshot_bytes=536870912, max_entities=1000000)`：パスまたはCadDocumentから作成。原ファイルの開始/終了時の同一性を確認。モデル内に不正層/群・重複元番号・不正/重複/未管理定義・非有限/非JSON値がある場合は拒否する。スナップショットの直列化バイト量上限は512MiB、公開要素数上限100万。実プロセスのRAM使用量上限を保証する値ではない。
- `view.entity(element_index, *, child_path=None)`：ビューの0始まり公開番号から1件取得する。子は後述の明示パスだけ。図形を描画/座標変換しない。
- `view.resolve(reference)`：同じview_idの参照だけ解決する。別ビューやfile参照への暗黙変換はしない。
- `view.entities(*, limit=100, mode='details')`：直下要素を保存/現在モデルの順で取得。limitは0～1000の整数。modeはdetails/count/summary。
- `view.summary()`：全直下要素数・kind別件数・保存群/層別件数・定義数・設定数を返す。limitによる先頭の要約ではない。
- `view.file_reference(element_index, *, child_path=None)`：同じファイルを再読込みし、現在モデルがファイルと一致する場合だけ状態を持たない参照を発行する。未変更の1要素でも、図面の他部分/群名/縮尺/版/定義等を編集していれば拒否する。新規未保存要素には発行しない。
- `resolve_file_reference(path, reference, *, schema_profile='strict')`：SHAを照合してから通常Readerで開き直して解決する。パスは参照内に含まず、呼出し側がローカルの場所を渡す。同一バイトの別名コピーにも使える。通常の読込み条件を回避しない。

view_idはそのセッションだけの識別、source_sha256は元ファイル全バイトのSHA、model_sha256は現在値/順序/版/定義/設定等を含むスナップショットの検査値。どれも図面間の同一要素を表すキーではない。version/entity_count/includes_metadataも読取り値として参照できる。返却された辞書やリストは変更しても内部に影響しない。

### 件数制限と返却モード

`total`は全直下件数、`returned`は今回の詳細数、`truncated`はdetailsモードでlimitにより切り詰めたかを示す。count/summaryではitems=[]、details_omitted=Trueとし、意図した詳細省略を切詰めと混同しない。summaryはkind/群・層別等を全件で数える。

制限は**件数**であり、結果JSONのバイト量や1文字列の長さの上限ではない。長い文字/複合レコードは切らずに返すため、詳細不要ならcount/summaryを使う。読取りビューは幾何を評価しないのでgeometry_evaluated=False。evaluation_complete=Trueは直下の列挙/数え上げが完了した意味で、形状判定完了ではない。

今回cursor/offset/別プロセスのページ継続は実装していない（continuation_implemented=False）。同一ビュー内の特定番号はentityで取得できるが、これを永続IDや図面間対応へ流用しない。

## 共通の項目名とzumenとの差

参考を読んだのは、zumenの公開READMEとAPI説明のみ。実装コードは取得・転記・移植していない。依存も追加していない。[公開Python README/API説明](https://pypi.org/project/zumen/0.1.1/)、[プロジェクトREADME](https://github.com/zumenjs/zumen#readme)

|項目|このライブラリの読取りビュー|無理にそろえない点|
|---|---|---|
|kind|line/circle/arc/point/text/dimension/block_reference/solid/circle_solid等の分類|JWWの保存種別からの分類。特殊な楕円等の形状を判定済みとする意味ではない|
|bbox|status/value/reasonの共通欄。読取りビューはnot_requested/value=null|zumenの箱の座標配列そのものとは互換でない。[共通形状](geometry_view.md)が確定・未判定を返す|
|text|TEXTまたは寸法文字の原本文1件|行ごとの複数要素を連結せず、正規化もしない|
|properties|key/label/valueで保存属性の表示を列挙|現時点は番号等の表示。全CAD共通のスタイル解決や印刷時の色を表さない|
|values|整形していない現在の保存単位の値。start/end/center等とattributes/fieldsを保持|読取りビューでは紙面mm/ローカル紙面mmの原座標、角度は原規則のまま。実寸や配置後のworld座標へ黙って換算しない|
|placement|根の群/縮尺、子の経路、保存された参照の位置・倍率・回転等|geometry_transform_applied=False。読取りビューは配置の情報だけで、共通形状の座標合成を実行しない|

値の3層はstorage/semantic/displayで区別する。storage.persisted_recordは保存済みの復号レコード、pending_recordはそれと異なる現在値（新規はpersisted_record=null）。原CStringバイトそのものの公開や幾何の実寸換算は読取りビューでは行わない。semanticはkind/placementまで、displayは人に見せるpropertiesまで。semanticの形状や文字種の完全解決を実装済みと呼ばない。負の0と正の0の保存表現差もpendingとして残す。

定義内の値はローカル紙面mm、寸法子は保存欄をそのまま返す。親の倍率等を適用した点とは区別する。元の保存フラグに推測の意味を付けたり、未確認表現を読み飛ばしたりしない。

## 2種類の参照

### ビュー内参照

`{reference_schema:1, scope:"view", view_id, element_index, child_path}`。element_indexはこのビューの現在の公開番号。元モデルを編集しても旧ビューは旧値で解決する。他のview_idには渡せない。

### 状態を持たないファイル参照

`{reference_schema:1, scope:"file", source_sha256, numbering:"stored_root_record_0", element_index, child_path, schema_profile}`。

element_indexは**保存根レコードの0始まり番号**。設定TEXTの除外前の番号なので、公開番号やzumenのidと同じとは限らない。include_metadata=True/Falseの違いで参照先を変えない。付加欄は参照プロトコル/番号の意味/Reader条件を固定するためで、図面間IDを追加するものではない。

SHAが違えば**解析前に拒否**する。版を書き換えたもの、再保存/編集でバイトが変わったものに流用しない。変更後の図面を新しいSHAで読む場合は、別の参照として取り直す。schema0は参照に書いてあるだけでは自動許可せず、解決側でもschema_profile="rebro_schema0"の明示一致が必要。

参照は署名/承認ではない。有効な番号へ書き換えれば別の対象の指定になる。編集計画の承認をこの参照だけで代替しない。内容ハッシュや番号から、別図面に同じ要素があると推測しない。

### 子の経路

- 寸法：`["line"]`、`["text"]`、`["aux_lines",0]`～1、`["aux_points",0]`～3。
- ブロック参照：`["definition",子番号]`。入れ子は同じ組を続ける。定義番号はファイル内の参照関係から引き、外から勝手な別定義番号を指定させない。
- 組合せ例：`["definition",0,"text"]`。

任意の属性名/eval/getattrは使わない。型・要素種別・範囲・最大128トークン・欠落/重複定義・循環/深さ64を検査する。子を展開して図面要素数へ加算しない。persisted_recordは元ファイルの同じ経路の値であって、編集で子の順が変わった場合の同一性を保証する対応表ではない（origin_relationに明記）。

設計の背景は[ページ継続の検討](design/read_view_continuation.md)を参照してください。
