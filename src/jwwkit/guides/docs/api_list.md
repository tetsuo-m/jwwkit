# 公開API一覧

表記揺れの半角カナ合成は固定表28組で行い、Python内蔵Unicodeに依存しない（既存対応表は不変）。計画の規則記録に合成表SHAを含め、旧規則で承認した検索計画を自動で読み替えない。対応Pythonと依存導入の制限はREADME参照。

読取りビュー→共通形状/文字枠→位置検索→明示した文字の表記揺れ検索→承認付き編集のつながりはdocs/reading_to_editing.md。詳細上限/count/summaryの既存機能と未判定/切詰めをそこで整理し、新しいcursor/別プロセス継続は追加していない。

共通結果はedit_resultの3関数とEditExecutionError.resultを使う。schema5ではCadDocument31名に対応し、旧窓口で直接未登録だった4名もこの契約内だけ許可する。既定の旧許可表/例外/戻り値は維持する。docs/edit_results.mdを読む。

ソースのASTから名前・引数・既定値・委譲先を抽出し、説明/拒否条件は実装の分岐を確認して記述した。各項目には実装の参照先を示す。`safe_edit` は `__all__` にある公開関数を掲載する。

schema_profile="rebro_schema0"は読取り/無編集別名保存専用。以下のCadDocument編集31APIは、このモードでは引数の有効性によらず変更前に拒否する。既定strictの編集条件は各項目に示す。このread-onlyモードでの編集は未対応。通常の編集には専用normalizationのschema6計画で別承認・別名出力後、strictで開く。schema以外のバイトを変更せず、欠けた短線を復元せず、元のパレットをJw_cad環境の値に置き換えない。正規化と業務編集は別計画/承認。

他CAD出力は取込む前に見た目も確認する。提供されたRebro 2026 Rev.6 build0918.1310ではDXFの長さ1未満の短線71本の欠落、TFAS 14eとJw_cad10.03.7による直接DXF読込みでは全体のブロック化、提供された10.03.7再保存例では図形の保存欄が一致してもパレット変化を観測した。各版/入力での観測で一般化しない。欠落がDXF読込み段階かJWW書出し段階かは区別できない。直接読込みは欠落やパレットを修復しない。詳細はusage_guide.md。

計画の編集28操作（ほかに開発環境専用GUI1操作）、直接未登録の4操作と別保存経路のAPIはplan_api_coverage.md。追加要素/定義は型別名、層群/レイヤ/定義はresource_targetsでレビューする。インストールしたファイルと動作は `jwwkit check` で確認できる。空テンプレートの場所は `jwwkit.template_path()` で取得できる。開発ログ/GUI/生成ツールは配布しない。

JWFの読取り専用入口はjwf。JwfDocument/JwfSettingはopen/getで取得し、適用・編集・書出しAPIはまだ持たない。詳しくはdocs/jwf_readonly.md。

独立図面比較はdrawing_comparison.compare_drawings/write_comparison。設計変更は群を指定して比較し、編集確認はexecute_planの実行記録と出力名.changes.jsonを使う。diff_reportは同一元図面の編集前後専用で、用途を区別する。対応範囲とcomplete判定はdocs/drawing_comparison.mdを読む。JWFはJwfDocument.get/summary/diff/compare_drawing、JwfSetting.values/numberで宣言を読む。環境適用/書出し/図面同期は未実装。個人JWFとAI_settings_summary.jsonは配布せず、別PCでもローカルに用意する。

CadDocument、JwwDocument、LegacyDocumentなどは `jwwkit` から直接読み込める。個別の機能は `jwwkit.record_reader`、`jwwkit.hatch_geometry`、`jwwkit.safe_edit` などを使う。内部Cursor・シリアライズ関数、重複する実装委譲関数、model_entity、record()等は除外した。CadDocument/JwsDocumentの内部保存情報を必要とする自動生成コンストラクタも対象外。

`cad`はCadDocument、`new`はJwwDocument。要素番号は設定を除いた現在の0始まり公開番号で、削除/置換で変わる。rawは原記録、未保存編集はgeometry/attributesを見る。paperは紙面mm、realは実寸mm。文字/ハッチ角度は度、円弧/参照/変換角度はrad。DXF原点補正をAPI座標に加えない。

```python
from jwwkit import CadDocument, JwsDocument
from jwwkit import JwwDocument, Line, Text
from jwwkit.safe_edit import write_plan, verify_plan, execute_plan, snapshot
```

プロパティは括弧なしで参照する。CadDocumentのsource/version/header/entities/metadata_settings/diagnostics/block_definitions、JwsDocumentのversion/base_point/group_scales/bounds/reserved/entities/block_definitions/sha256はデータ属性。CadBlockDefinition.name_infoは保存名解釈の読取プロパティでblock_name_infoを委譲する（`jwwkit.model.common_entities`）。CadEntity/CadBlockDefinitionは返却データ型で、内部状態を手動構築するコンストラクタは省略する。要素モデルの引数はdataclassフィールド定義であり、field(default_factory=...)は引数を省略した際に補助モデル群を新規生成する意味で、利用者がfield(...)を渡す指定ではない。

建築図の差し替えはset_entity_attributes/set_group_state/import_group/align_two_pointsとsafe_editを組み合わせるガイド手順であり、単独の汎用置換メソッドは存在しない。 配布ガイドのplan_building_replacementは同じ建築群・両図面1/100・仮点2組・倍率1の移動/回転を扱う。異縮尺の差し替えは計画前拒否、allow_scaleやsync_scaleで回避しない。距離/角度許容は毎回指定し、計画と実行をチャット承認で分ける。平行移動/5度回転の実図面受入れ済み範囲であり、任意の版/画像/入れ子/未知文字様式等へは拡張しない。旧建築を非表示にしてもDXFで非表示が維持される保証はない。削除は人の確認後に別計画で行う。

API範囲とGUI受入れは別に判定する。JWS700公開読込みと入れ子平坦化、業務18件で観測したJWS230読込み・平坦配置を追加。JWKはユーザー指定で対象外。

## 開く・保存

### `CadDocument.open`

```python
CadDocument.open(path: str | Path, *, include_metadata: bool=False, schema_profile: str='strict')
```

既存図面を読み、要素と保存用の原情報を保持する。

対応範囲・拒否条件：観測済みv600/v700。schema_profile="strict"既定。明示"rebro_schema0"はSen/Enko/Mojiのschema0だけの読取り/無編集別名保存用で、31編集APIと直接編集の保存を拒否。混在/他クラス/画像/定義へ広げない。include_metadata=Falseは設定を公開要素から除く。未知構造/診断付きは保存不能の場合がある。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L49)。

```python
cad = CadDocument.open('input.jww')
```

### `CadDocument.save`

```python
CadDocument.save(path: str | Path)
```

現在のモデルを別名の新規ファイルへ保存する。

対応範囲・拒否条件：既存出力と不正保存値を拒否。原本、未確認診断、v600/v700以外、未許可ヘッダー直接編集、未解決参照等を拒否。strictは設定込みモデルを拒否。rebro_schema0は設定込み読取りも無編集なら可、モデル全欄と宣言の検証/全バイト一致を経た別名保存だけで編集を拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L77)。

```python
cad.save('new_output.jww')
```

### `JwwDocument.__init__`

```python
JwwDocument()
```

確認済みテンプレートから新規図面を用意する。

対応範囲・拒否条件：テンプレートハッシュ/設定6件/名称表/本文の不一致を拒否。任意ヘッダーの新規生成ではない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L24)。

```python
new = JwwDocument()
```

### `JwwDocument.save`

```python
JwwDocument.save(path)
```

現在のモデルを別名の新規ファイルへ保存する。

対応範囲・拒否条件：既存出力と不正保存値を拒否。新規テンプレート保存。番号重複/未解決参照を拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L184)。

### `JwwDocument.from_sample`

```python
JwwDocument.from_sample(path)
```

テンプレート互換の既存図面の要素を限定Writerへコピーする。

対応範囲・拒否条件：v700・診断なし・参照解決済み・確認済み名称布局/要素型のテンプレート互換図面のみ。from_line_sampleは非LINE拒否。from_cad_documentは設定込み/原本と異なるヘッダー/入れ子等を拒否。原ヘッダー保持保存ではない。 原本文全バイト往復/読み込み中無変更を確認。日時を保持し、同梱画像や保存時再計算と異なる定義参照状態はコピー拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L205)。

### `JwwDocument.from_cad_document`

```python
JwwDocument.from_cad_document(document)
```

テンプレート互換の共通モデルを限定Writerへコピーする。

対応範囲・拒否条件：v700・診断なし・参照解決済み・確認済み名称布局/要素型のテンプレート互換図面のみ。from_line_sampleは非LINE拒否。from_cad_documentは設定込み/原本と異なるヘッダー/入れ子等を拒否。原ヘッダー保持保存ではない。 原本文全バイト往復/読み込み中無変更を確認。日時を保持し、同梱画像や保存時再計算と異なる定義参照状態はコピー拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L342)。

### `JwwDocument.open`

```python
JwwDocument.open(path)
```

テンプレート互換の既存図面の要素を限定Writerへコピーする。

対応範囲・拒否条件：v700・診断なし・参照解決済み・確認済み名称布局/要素型のテンプレート互換図面のみ。from_line_sampleは非LINE拒否。from_cad_documentは設定込み/原本と異なるヘッダー/入れ子等を拒否。原ヘッダー保持保存ではない。 原本文全バイト往復/読み込み中無変更を確認。日時を保持し、同梱画像や保存時再計算と異なる定義参照状態はコピー拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L377)。

### `JwwDocument.from_line_sample`

```python
JwwDocument.from_line_sample(path)
```

LINEだけのテンプレート互換図面をコピーする旧互換入口。

対応範囲・拒否条件：v700・診断なし・参照解決済み・確認済み名称布局/要素型のテンプレート互換図面のみ。from_line_sampleは非LINE拒否。from_cad_documentは設定込み/原本と異なるヘッダー/入れ子等を拒否。原ヘッダー保持保存ではない。 原本文全バイト往復/読み込み中無変更を確認。日時を保持し、同梱画像や保存時再計算と異なる定義参照状態はコピー拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L382)。

### `LegacyDocument.__init__`

```python
LegacyDocument(path)
```

旧版基本図面をCP932保存用に読み込む。

対応範囲・拒否条件：v600・ブロックなし・基本6種類・診断なしだけ。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/legacy_document.py#L13)。

### `LegacyDocument.open`

```python
LegacyDocument.open(path)
```

既存図面を読み、要素と保存用の原情報を保持する。

対応範囲・拒否条件：v600・ブロックなし・LINE/CIRCLE/ARC/POINT/TEXT/SOLID・診断なしだけ。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/legacy_document.py#L32)。

### `LegacyDocument.save`

```python
LegacyDocument.save(path)
```

現在のモデルを別名の新規ファイルへ保存する。

対応範囲・拒否条件：既存出力と不正保存値を拒否。CP932のみ、版変換/ヘッダー編集はしない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/legacy_document.py#L56)。

### `safe_edit.save_checked`

```python
safe_edit.save_checked(cad, before, source_sha256, output, *, approved_plan_sha256=None, alignment_results=(), import_results=(), workflow_plan=None)
```

別名保存し全公開欄を読み直し、差分JSONと入力/出力ハッシュを記録する。

対応範囲・拒否条件：入力ハッシュ・正常な編集前snapshot必須。workflow_planはschema4の設定/計画/出力と全群の監査を保存前後に検査して記録。上書き・保存不一致を拒否。単独呼出しでも利用者承認は別途必要。不一致では新規生成ファイルが残る場合がある。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/safe_edit.py#L54)。

### `write_schema_normalization_plan`

```python
write_schema_normalization_plan(sources, output_dir, plan_path, *, opening_settings)
```

対象と不要の全入力/SHA/宣言変更/設定を固定した専用schema6計画を新規保存する。

対応範囲・拒否条件：opening_settings必須、normalizeの明示指定と生設定一致。全件中止のみ、新規出力フォルダ。最大256件/各256MiB/合計512MiB/JSON8MiB、衝突/リンク/未知を拒否。図面出力なし。 詳細docs/schema_normalization.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/normalization.py#L128)。

### `execute_schema_normalization_plan`

```python
execute_schema_normalization_plan(plan_path, *, approved_sha256)
```

承認SHAを検証し、schema WORDだけを変更した全出力をまとめて確定する。

対応範囲・拒否条件：schema6のみ。入力/不要のSHA/分類を再検査。設定は計画snapshot。標準図面は出力なし、全件不要ならフォルダなし。Windows同一親/置換禁止。失敗はNormalizationExecutionError.result、確定前は一時領域を保持。 詳細docs/schema_normalization.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/normalization.py#L205)。

## 読取り・検索

### `CadDocument.get_sxf_colors`

```python
CadDocument.get_sxf_colors(*, include_unnamed=False)
```

原ヘッダーのSXF色名・番号・表示/印刷RGB・生幅・点半径を読む。

対応範囲・拒否条件：観測済みJWW600/700原ヘッダーだけ。include_unnamedはbool、既定Falseで名前付き非予約行のみ、Trueで予約/未使用を含む色257/線種33行。表示/印刷色と生幅を区別し、定義は作成せず編集許可も付与しない。ヘッダー境界不一致・切断・非有限設定・区間数10超を拒否。返り値は独立コピー。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L86)。

### `CadDocument.get_sxf_linetypes`

```python
CadDocument.get_sxf_linetypes(*, include_unnamed=False)
```

原ヘッダーのSXF線種名・番号・パターン・区間数・生長さを読む。

対応範囲・拒否条件：観測済みJWW600/700原ヘッダーだけ。include_unnamedはbool、既定Falseで名前付き非予約行のみ、Trueで予約/未使用を含む色257/線種33行。表示/印刷色と生幅を区別し、定義は作成せず編集許可も付与しない。ヘッダー境界不一致・切断・非有限設定・区間数10超を拒否。返り値は独立コピー。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L93)。

### `CadDocument.get_sxf_color`

```python
CadDocument.get_sxf_color(value)
```

SXF色の保存番号または完全一致名から1行を読む。

対応範囲・拒否条件：整数保存番号または非空完全一致名。bool・範囲外・不存在名・同名複数を拒否。SXF名redと標準色の赤を混同しない。予約/無名の行を番号で読めても編集許可ではない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L100)。

### `CadDocument.get_sxf_linetype`

```python
CadDocument.get_sxf_linetype(value)
```

SXF線種の保存番号または完全一致名から1行を読む。

対応範囲・拒否条件：整数保存番号または非空完全一致名。bool・範囲外・不存在名・同名複数を拒否。SXF名redと標準色の赤を混同しない。予約/無名の行を番号で読めても編集許可ではない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L105)。

### `CadDocument.find_entities`

```python
CadDocument.find_entities(*, layer=None, layer_group=None, entity_type=None, block_name=None, text=None, rect=None, units='paper', rect_mode='anchor', color=None, linetype=None, query=None)
```

既存条件と一覧OR/JSON条件で図面直下の現在の公開番号tupleを検索する。

対応範囲・拒否条件：従来スカラー条件は互換維持。種類/群/層/色/線種/保存ブロック名は一覧OR、引数間/queryはAND。queryはsearch_queries.mdのJSON条件、未判定時は例外。定義内は対象外、非表示は既定で含む。SXF名は定義済み完全一致だけ。TEXT/POINT/円ソリッドの別用途の欄を線種とみなさない。空一覧・不正条件を拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L181)。

```python
ids = cad.find_entities(entity_type='LINE', layer=2)
```

### `CadDocument.search_entities`

```python
CadDocument.search_entities(query, *, scope='drawing', limits=None)
```

JSON論理式・文字/数値/flag/方向/状態で読み取り検索する。normalizationで承認済み文字同一視を明示でき、規則/表SHA・一致理由を返す（docs/text_equivalence.md）。

対応範囲・拒否条件：queryはall/any/notと名前付き葉だけ。scope drawing既定、definitions/drawing_and_definitionsは保存定義を1回ずつ読み、別識別子/ローカル紙面mmだけ。未判定はcomplete=false、timeoutは部分結果なしで例外。length/radiusの単位必須、楕円は未判定。flag_bitsは外側uint16の全set/clearで意味を一般化しない。line_angleは+X反時計回り[0,180)・端点反転同一・deg/radと許容必須。状態は群/層の保存値0..3。regexは子プロセス5秒既定/最大30秒。固定/時間制限と規則版を返す。詳細はsearch_queries.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L190)。

### `CadDocument.get_text_preset`

```python
CadDocument.get_text_preset(text_type: int)
```

原図面の文字種の幅・高さ・間隔・色を読む。フォント設定は含まない。

対応範囲・拒否条件：文字種1～10の整数だけ。設定位置を確認済みの原ヘッダーから読み、フォントは返さない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L293)。

### `CadDocument.get_layer_name`

```python
CadDocument.get_layer_name(layer_group, layer)
```

編集後のレイヤ保存名を読む。空名を表示用仮名に置き換えない。

対応範囲・拒否条件：層/群0～15、名称は文字列。CadDocumentは原CString符号化を保持し、表現できない名称は拒否。空/不完全CP932保存名は読取り時に補完しない。未知のヘッダー状態は編集しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L374)。

### `CadDocument.get_group_name`

```python
CadDocument.get_group_name(layer_group)
```

編集後の層群保存名を読む。空名を表示用仮名に置き換えない。

対応範囲・拒否条件：層/群0～15、名称は文字列。CadDocumentは原CString符号化を保持し、表現できない名称は拒否。空/不完全CP932保存名は読取り時に補完しない。未知のヘッダー状態は編集しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L379)。

### `CadDocument.get_group_state`

```python
CadDocument.get_group_state(layer_group)
```

層群の保存状態と表示・編集可・書込み選択の判定を独立辞書で読む。

対応範囲・拒否条件：観測済みv600/v700。群/層0～15、bool拒否。raw_valueは0非表示・1表示のみ・2編集可・3書込み選択。返り値は独立辞書。層のselected_for_writingは各群内の選択で、親群が非書込みなら現在の全図面書込み先を意味しない。effective_visible/effective_editableは群と層の状態だけの合成で、保護設定等の追加制限を保証しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L383)。

### `CadDocument.snapshot_group`

```python
CadDocument.snapshot_group(layer_group)
```

群の全保存要素・保存順序・群/層の全欄・参照定義閉包をSHA付きで捕捉する。

対応範囲・拒否条件：観測済みv600/v700の保存可能なモデルだけ。群0～15、bool拒否。全保存根要素（設定TEXTも含む）、順序/重複数、群/層の状態・保護・名称CString/縮尺、参照定義の全欄/日時と共有・入れ子閉包を厳密照合する。内包要素/定義の参照群ヘッダー・共通設定TEXT・共通ヘッダーも比較するため、未解析共通設定やGUIの保存表現変化も差とする。絶対アーカイブ番号は比較しない。無関係な群や未参照定義の変更は影響しない。画像依存群/循環・深いグラフ/未解決参照/改変snapshotのSHA不一致は理由付き拒否。差を正規化せず、差がある場合はpassed=False。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L388)。

### `CadDocument.audit_group_unchanged`

```python
CadDocument.audit_group_unchanged(layer_group, before)
```

保存済みスナップショットと厳密照合し、差分全欄と合否を返す。

対応範囲・拒否条件：観測済みv600/v700の保存可能なモデルだけ。群0～15、bool拒否。全保存根要素（設定TEXTも含む）、順序/重複数、群/層の状態・保護・名称CString/縮尺、参照定義の全欄/日時と共有・入れ子閉包を厳密照合する。内包要素/定義の参照群ヘッダー・共通設定TEXT・共通ヘッダーも比較するため、未解析共通設定やGUIの保存表現変化も差とする。絶対アーカイブ番号は比較しない。無関係な群や未参照定義の変更は影響しない。画像依存群/循環・深いグラフ/未解決参照/改変snapshotのSHA不一致は理由付き拒否。差を正規化せず、差がある場合はpassed=False。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L393)。

### `CadDocument.get_layer_state`

```python
CadDocument.get_layer_state(layer_group, layer)
```

レイヤの保存状態と、親群の表示・編集状態を合成した有効状態を読む。

対応範囲・拒否条件：観測済みv600/v700。群/層0～15、bool拒否。raw_valueは0非表示・1表示のみ・2編集可・3書込み選択。返り値は独立辞書。層のselected_for_writingは各群内の選択で、親群が非書込みなら現在の全図面書込み先を意味しない。effective_visible/effective_editableは群と層の状態だけの合成で、保護設定等の追加制限を保証しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L398)。

### `JwwDocument.layer_groups`

```python
JwwDocument.layer_groups
```

新規図面の表示用16層群情報を独立コピーで返す。

対応範囲・拒否条件：16層群の独立コピー。空名を既定表示名に補完する表示用情報で、CadDocumentの保存名getterとは異なる。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L53)。

### `LegacyDocument.header`

```python
LegacyDocument.header
```

原図面の読取りヘッダーを独立コピーで返す。

対応範囲・拒否条件：独立コピー、返却値の直接変更は元モデルに反映しない。LegacyDocumentの読込範囲に限定。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/legacy_document.py#L36)。

### `LegacyDocument.entities`

```python
LegacyDocument.entities
```

旧版図面の全生要素を独立コピーで返す。

対応範囲・拒否条件：独立コピー、返却値の直接変更は元モデルに反映しない。LegacyDocumentの読込範囲に限定。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/legacy_document.py#L40)。

### `safe_edit.file_sha256`

```python
safe_edit.file_sha256(path)
```

ファイルを読取りSHA256を返す。

対応範囲・拒否条件：入力を変更しない。存在しない/読めないファイルは例外。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/safe_edit.py#L17)。

### `safe_edit.entity_view`

```python
safe_edit.entity_view(entity)
```

現在の要素型・属性・幾何のコピーを返す。

対応範囲・拒否条件：geometry_paper_mmは紙面座標。編集前rawではない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/safe_edit.py#L27)。

### `safe_edit.snapshot`

```python
safe_edit.snapshot(cad)
```

全公開要素・定義内欄・名称・縮尺のスナップショットを返す。

対応範囲・拒否条件：完全内部バイトの監査ではない。保存用の正常CadDocumentを使用。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/safe_edit.py#L31)。

```python
before = snapshot(cad)
```

### `read_records`

```python
read_records(path, *, schema_profile='strict')
```

既知JWWの全生要素・定義・本文情報を読み込む。

対応範囲・拒否条件：strict既定。明示schema_profile="rebro_schema0"はv600/v700のschema0のSen/Enko/Mojiだけで宣言の順序/値も返す。混在・他クラス・画像/定義は拒否。未知クラス/末尾、切断、64bit/非正規/上限超の個数と未知参照を拒否。65535以上はWORDマーカー+DWORD。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/reader/archive.py#L63)。

### `read_records_bytes`

```python
read_records_bytes(data, *, schema_profile='strict')
```

既知JWWの全生要素・定義・本文情報をbytesから読み込む。

対応範囲・拒否条件：strict既定。明示schema_profile="rebro_schema0"はv600/v700のschema0のSen/Enko/Mojiだけで宣言の順序/値も返す。混在・他クラス・画像/定義は拒否。未知クラス/末尾、切断、64bit/非正規/上限超の個数と未知参照を拒否。65535以上はWORDマーカー+DWORD。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/reader/archive.py#L68)。

### `read_document`

```python
read_document(path, *, schema_profile='strict')
```

標準Readerと生本文Readerを照合し、文字・寸法属性を補完する。

対応範囲・拒否条件：strict既定、schema0等のクラススキーマ違反は拒否。明示schema_profile="rebro_schema0"は観測済み3クラス限定、失敗時のフォールバックなし。それ以外のstrict本文読込み失敗では限定フォールバックと診断を返す場合があり、診断は安全な編集保存を保証しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/reader/archive.py#L263)。

### `jwf_setting_catalog`

```python
jwf_setting_catalog()
```

認識するJWFキー230件について、各項目の名前（`name`）と保存区分（`storage`）を返す。

対応範囲・拒否条件：設定値の既定値や適用結果は返さない。保存欄との対応が未確認の場合は `unresolved` を返す。区分の意味は[JWFのキー一覧](jwf_key_catalog.md)を参照。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/jwf.py#L9)。

### `JwfSetting.values`

```python
JwfSetting.values()
```

原値をJWFの空白/カンマ/フォント構文に沿って文字列欄へ分ける。

対応範囲・拒否条件：不完全文字拒否。名前の空欄保持、フォント先頭引用符以降は全文保持。数値の基数は推測しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/jwf.py#L29)。

### `JwfSetting.number`

```python
JwfSetting.number(index, *, base=10)
```

0始まり欄を明示の10進/16進で数値取得する。

対応範囲・拒否条件：非有限・不正数値・負index/bool・未確認基数を拒否。範囲/桁内フラグの有効性までは一般検証しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/jwf.py#L43)。

### `JwfDocument.open`

```python
JwfDocument.open(path, *, encoding='cp932', errors='strict')
```

JWFを指定文字コードで読み、設定の宣言と診断を取得する。

対応範囲・拒否条件：CP932既定/strict。不完全CP932は明示errors=preserveで生値保持し、当該値の解釈を拒否。UTFは明示指定の検査のみでJw側受入れ保証ではない。END以降非活性、未記載は既定値にしない。適用/保存なし。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/jwf.py#L69)。

```python
from jwwkit import JwfDocument
config = JwfDocument.open('settings.jwf')
```

### `JwfDocument.get`

```python
JwfDocument.get(name, *, include_inactive=False)
```

キー名に完全一致する設定レコードを返す。

対応範囲・拒否条件：未記載/END以降はKeyError、重複はValueError。include_inactiveは説明行の検査用。不正文字はvalues/numberで拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/jwf.py#L106)。

### `JwfDocument.summary`

```python
JwfDocument.summary()
```

AI向けに宣言一覧・診断・入力SHAを返す。

対応範囲・拒否条件：実行中Jwの有効設定ではない。業務名/パスを含み得るのでローカル限定。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/jwf.py#L113)。

### `JwfDocument.diff`

```python
JwfDocument.diff(other, *, include_inactive=False)
```

2つのJWFの宣言値・片方のみ・重複・文字異常を一覧にする。

対応範囲・拒否条件：空白区切りを除いた字句比較。1と1.0等を同じ有効値と推測しない。未記載は未指定、include_inactiveは非活性の説明例も含む明示指定。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/jwf.py#L120)。

### `JwfDocument.compare_drawing`

```python
JwfDocument.compare_drawing(document)
```

確認済みのJWF欄とJWW保存値を比較し、他は比較不能/未確定として返す。

対応範囲・拒否条件：文字種幅/高さ/間隔/色、16群縮尺、名称、標準表示RGBだけの対応。幅/印刷色/未知ビット等は推測しない。0縮尺/空名は無変更条件、適用順/保護/占有群は注記。環境や図面を変更しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/jwf.py#L139)。

### `compare_drawings`

```python
compare_drawings(left, right, *, left_scope=None, right_scope=None, units='real', position_tolerance=0.0, angle_tolerance_degrees=0.0, text_size_tolerance=0.0, right_transform=None, line_coverage=True, max_candidate_pairs=2000000)
```

独立した2つのJWWを幾何・全属性・文字内容・群/層設定で比較し、5分類と保留を返す。

対応範囲・拒否条件：LINE/CIRCLE/ARC/POINT/TEXTと、mode0寸法・ブロック・ソリッド・確認済み円ソリッド。寸法は内包を含め1件。ブロックは配置/定義全内容を比較し番号/日時の保存差を区別。到達可能な入れ子は局所構造で比較、画像/欠落/循環/未確認優先表現/未知塗り/曖昧/部分被覆はcomplete=False。units=real・許容0が既定、明示した右側剛体変換だけ。候補/複合展開上限、不正指定、入力変化は拒否。図面編集・確認JWWなし。詳細drawing_comparison.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/drawing_comparison.py#L288)。

```python
result = compare_drawings('before.jww', 'after.jww')
```

### `tategu_input_fingerprint`

```python
tategu_input_fingerprint(source, *, binding='file')
```

入力JWWまたはメモリ上モデルのSHA256を読み取り専用で取得する。

対応範囲・拒否条件：fileは原本の未編集モデルと実ファイルの一致必須。memory_modelは現在の全公開要素と16群縮尺をハッシュする。未知binding・保存不能モデル・入力変更は拒否。承認自体は証明しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/tategu_recognition.py#L20)。

### `recognize_planar_tategu`

```python
recognize_planar_tategu(source, *, tolerances, include_unmarked=True, max_candidate_pairs=2000000)
```

型別flag_bits検索と平面形状から建具候補・内法幅・開口中点・構成番号・根拠・曖昧さを返す。

対応範囲・拒否条件：平面LINE/真円ARC/CIRCLEの初版。入力SHAに結び付いた明示許容値必須。印なしも既定で検索し曲線属性番号は判定に使わない。複数解釈は保持し内法不明はNone。楕円/複合要素/未割当の建具印/関連付け不明はcomplete=False。組合せ上限は拒否または保留。内外・勝手は未確定、文字符号対応/断面立面/DAT照合/図面編集なし。completeは検査した候補の完全性であり全建具の検出保証ではない。許容値の自動流用禁止。docs/tategu_recognition.md参照。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/tategu_recognition.py#L106)。

### `create_read_view`

```python
create_read_view(source, *, include_metadata=None, schema_profile=None, max_snapshot_bytes=536870912, max_entities=1000000)
```

現在モデルを独立した不変の読取りビューへ固定する。

対応範囲・拒否条件：CadDocument/パスのみ。初期Reader条件を維持し、原本の開始/終了ハッシュ一致、不正番号/重複・未管理定義/非有限値、直列化512MiB/100万要素の上限を検査。数値上限はRAM上限でない。geometry/編集/保存/正規化なし。同時モデル更新は呼出し側で同期。 詳細docs/read_view.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/read_view.py#L203)。

### `resolve_file_reference`

```python
resolve_file_reference(path, reference, *, schema_profile='strict')
```

SHA付きの保存根番号＋子経路を、同一バイトのファイルから再取得する。

対応範囲・拒否条件：SHA違いは解析前拒否、schema_profileは明示一致。保存根番号は設定TEXTの除外前。型付き子経路/範囲/循環/深さを検査。編集/版変更をまたぐID、図面間対応/承認署名ではない。別プロセスのページ継続は未実装。 詳細docs/read_view.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/read_view.py#L279)。

### `ReadView.entity_count`

```python
ReadView.entity_count
```

この不変ビューの公開直下要素数を返す。

対応範囲・拒否条件：プロパティ。設定TEXTはビュー作成条件に従い、子は数えない。 詳細docs/read_view.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/read_view.py#L144)。

### `ReadView.entity`

```python
ReadView.entity(element_index, *, child_path=None)
```

現在のビューの公開番号・任意の型付き子経路から値を返す。

対応範囲・拒否条件：返却はJSONの独立コピー。値の3層とkind/bbox/text/properties/values/placement。読取りビューはbbox/幾何未計算。子の配置を適用しない。源の同経路の値は同一性の対応表でない。 詳細docs/read_view.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/read_view.py#L147)。

### `ReadView.resolve`

```python
ReadView.resolve(reference)
```

同じビュー識別子の参照だけを解決する。

対応範囲・拒否条件：別ビュー/file参照、未知キー、番号/経路の型/範囲を拒否。永続IDでない。 詳細docs/read_view.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/read_view.py#L160)。

### `ReadView.summary`

```python
ReadView.summary()
```

直下の全件数・kind/保存群層別件数・定義/設定数を要約する。

対応範囲・拒否条件：表示中の先頭件数ではなく全ルート集計。子を根の件数へ二重計上しない。幾何の要約/評価ではない。 詳細docs/read_view.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/read_view.py#L168)。

### `ReadView.entities`

```python
ReadView.entities(*, limit=100, mode='details')
```

直下の一覧を件数制限付き、または件数/要約だけで返す。

対応範囲・拒否条件：limitは整数0～1000。mode details/count/summary。total/returned/truncated/details_omittedを区別する。バイト上限やカーソル/offset/別プロセス継続は未実装。 詳細docs/read_view.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/read_view.py#L175)。

### `ReadView.file_reference`

```python
ReadView.file_reference(element_index, *, child_path=None)
```

未編集モデルを再読込み照合して、SHA付きファイル参照を発行する。

対応範囲・拒否条件：他部分/ヘッダー/定義/版等を変更したビュー、新規未保存要素、変化した原本を拒否。source_indexを固定保存根番号へ変換。通常Readerで再読込みするので大図面では費用がかかる。 詳細docs/read_view.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/read_view.py#L187)。

### `entity_geometry`

```python
entity_geometry(view, element_index, *, child_path=None, units='real', basis='current', text_mode='glyph', fields=None, curve_tolerance=None, limits=None)
```

不変ビューの1要素・子経路を共通形状で返す。

対応範囲・拒否条件：real/paper、current/persisted、欄別status。論理外形・輪郭・中心・代表点・通常文字枠。字形は未判定、特殊flag/楕円/未知構造を推測しない。通常文字枠の終点数値ガードはmax(64*ulp(M),1e-9*L)、実寸換算1e-4mm以上なら未判定。図面許容でなく元終点は変更しない。曲線の折線化は明示誤差必須。編集・保存なし。 詳細docs/geometry_view.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/geometry_view.py#L93)。

### `geometry_page`

```python
geometry_page(view, *, units='real', basis='current', text_mode='glyph', fields=None, curve_tolerance=None, limits=None, limit=100, mode='details', max_seconds=30.0)
```

共通形状の件数制限付き詳細、件数のみ、全件の判定要約を返す。

対応範囲・拒否条件：detailsは最大1000ルート。時間上限/展開上限を明記し、評価完了と全欄確定を分離。countは幾何計算なし。別プロセス継続なし。 詳細docs/geometry_view.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/geometry_view.py#L99)。

### `text_frame_distance`

```python
text_frame_distance(geometry, point_value, *, boundary=False)
```

確定した文字枠の領域または境界への距離を返す。

対応範囲・拒否条件：字形への距離ではない。枠未判定なら距離も未判定。geometryのunitsを用い、非有限点/不正な入力を拒否。全要素の最近検索ではない。 詳細docs/geometry_view.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/geometry_view.py#L128)。

### `at_point`

```python
at_point(view, point, *, tolerance, units='real', query=None, text_mode='glyph', target='shape', basis='current', limit=100, mode='details', max_seconds=30.0, limits=None)
```

指定点から明示距離以内にある全ルートを、不変ビューから検索する。

対応範囲・拒否条件：tolerance必須、real/paper、既存JSON query。文字枠はtext_mode=frameを明示。未判定を除外せず理由と上下限を返す。親1候補/部品経路、件数制限/要約。図面編集/GUI/続き取得なし。 詳細docs/spatial_search.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/spatial_search.py#L137)。

### `nearest`

```python
nearest(view, point, *, tie_tolerance, max_distance=None, units='real', query=None, text_mode='glyph', target='shape', basis='current', limit=100, mode='details', max_seconds=30.0, limits=None)
```

全対象の最小距離から明示tie_tolerance以内の同距離候補を全て返す。

対応範囲・拒否条件：tie_tolerance必須、max_distance任意。未知候補があれば既知最小を全体最近と呼ばず、confirmed/provisional/unresolvedを分ける。target=anchorsは保存基点距離だけ。上限/時間切れ/未知はcomplete=False。 詳細docs/spatial_search.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/spatial_search.py#L142)。

### `load_workflow_settings`

```python
load_workflow_settings(work_dir)
```

明示した作業フォルダ直下のTOMLを読取り、原文/生SHA/解析値を返す。

対応範囲・拒否条件：UTF-8/BOMなし/64KiBまで。既定careful、不在のみ既定扱い。不正/未知/安全設定/リンクを拒否。openから暗黙に呼ばない。 詳細docs/workflow_settings.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/workflow_settings.py#L54)。

### `resolve_workflow_settings`

```python
resolve_workflow_settings(loaded, *, instruction_overrides=None, instruction_evidence=None)
```

チャット>設定>carefulで差し替えの実効値・出所・設定スナップショットを解決する。

対応範囲・拒否条件：archive/delete、archive_groupは整数0～15/first_empty。profileはcareful/quickのみ。file退避先の非適用を明示、deleteと今回の退避指定矛盾/不正な内容/改ざんを拒否。承認や図面編集なし。 詳細docs/workflow_settings.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/workflow_settings.py#L86)。

### `resolve_opening_settings`

```python
resolve_opening_settings(loaded, *, instruction_overrides=None, instruction_evidence=None)
```

明示ロード済み設定からチャット>ファイル>rejectで開く方針と出所/SHAを解決する。

対応範囲・拒否条件：設定v1/v2、v2 opening.rebro_schema0=reject/normalize。careful/quickとは独立。openや正規化を実行せず、未知項目/不正値/改ざんを拒否。 詳細docs/workflow_settings.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/workflow_settings.py#L124)。

### `replacement_reference_points`

```python
replacement_reference_points(source)
```

群3/層0の仮点の公開番号・実寸座標・内容を読む。

対応範囲・拒否条件：現行strict Readerを使用。点は読取りだけで、取込み/削除対象にしない。番号はその元図面の現在のもの。 詳細docs/workflow_settings.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/replacement_workflow.py#L10)。

### `inspect_schema_normalization`

```python
inspect_schema_normalization(source)
```

原本を読取りだけで正規化対象/不要/対象外と診断する。

対応範囲・拒否条件：観測済みv600/v700の3クラスschema0だけ。未知名/schema/offset・列挙完了/停止位置を返し、未知本文を走査で飛ばさない。 詳細docs/schema_normalization.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/normalization.py#L82)。

### `normalization_edit_dependencies`

```python
normalization_edit_dependencies(result_path, normalized_source)
```

正規化の成功結果/計画/manifest/原本を検証し別の編集計画の依存パスを返す。

対応範囲・拒否条件：検証済みpublished結果に含まれる出力だけ。欠落/改ざん/原本・出力変更を拒否。編集/承認/再正規化はしない。 詳細docs/schema_normalization.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/normalization.py#L263)。

## 縮尺・座標

### `CadDocument.get_group_scale`

```python
CadDocument.get_group_scale(layer_group: int)
```

指定層群の縮尺分母を読む。

対応範囲・拒否条件：層群0～15の整数、縮尺は有限正数、座標は有限2成分。paper/real以外を拒否。line_pointsはLINEのみ。縮尺変更で紙面位置は変わらず実寸が変わる。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L222)。

### `CadDocument.set_group_scale`

```python
CadDocument.set_group_scale(layer_group: int, scale: float)
```

縮尺分母を変更する。既存要素の紙面座標は自動変更しない。

対応範囲・拒否条件：層群0～15の整数、縮尺は有限正数、座標は有限2成分。paper/real以外を拒否。line_pointsはLINEのみ。縮尺変更で紙面位置は変わらず実寸が変わる。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L227)。

### `CadDocument.convert_point`

```python
CadDocument.convert_point(point, *, layer_group=0, from_units='paper', to_units='real')
```

指定層群の縮尺で紙面mmと実寸mmの座標を換算する。DXF用紙原点は加算しない。

対応範囲・拒否条件：層群0～15の整数、縮尺は有限正数、座標は有限2成分。paper/real以外を拒否。line_pointsはLINEのみ。縮尺変更で紙面位置は変わらず実寸が変わる。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L237)。

### `CadDocument.line_points`

```python
CadDocument.line_points(index, *, units='paper')
```

LINE両端点を指定単位で返す。

対応範囲・拒否条件：層群0～15の整数、縮尺は有限正数、座標は有限2成分。paper/real以外を拒否。line_pointsはLINEのみ。縮尺変更で紙面位置は変わらず実寸が変わる。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L251)。

### `JwwDocument.get_group_scale`

```python
JwwDocument.get_group_scale(layer_group)
```

指定層群の縮尺分母を読む。

対応範囲・拒否条件：層群0～15の整数、縮尺は有限正数、座標は有限2成分。paper/real以外を拒否。line_pointsはLINEのみ。縮尺変更で紙面位置は変わらず実寸が変わる。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L77)。

### `JwwDocument.set_group_scale`

```python
JwwDocument.set_group_scale(layer_group, scale)
```

縮尺分母を変更する。既存要素の紙面座標は自動変更しない。

対応範囲・拒否条件：層群0～15の整数、縮尺は有限正数、座標は有限2成分。paper/real以外を拒否。line_pointsはLINEのみ。縮尺変更で紙面位置は変わらず実寸が変わる。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L83)。

### `text_advance`

```python
text_advance(content, *, size_x=2.5, spacing=0.0)
```

限定した文字セル幅から保存用の文字送り長さを計算する。

対応範囲・拒否条件：紙面mm、有限正幅、width+spacing>0、空/制御文字/不対サロゲートを拒否。text_endpointは確認済みフォント・alignment1～9・文字角度は度。描画フォントの字幅測定ではない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/text_metrics.py#L19)。

### `text_endpoint`

```python
text_endpoint(start, content, *, size_x=2.5, size_y=2.5, spacing=0.0, angle=0.0, font_name='ＭＳ ゴシック', alignment=1)
```

確認済みフォントの保存文字送りから終点を求める。描画境界ではない。

対応範囲・拒否条件：紙面mm、有限正幅、width+spacing>0、空/制御文字/不対サロゲートを拒否。text_endpointは確認済みフォント・alignment1～9・文字角度は度。描画フォントの字幅測定ではない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/text_metrics.py#L47)。

## 追加

### `CadDocument.add_line`

```python
CadDocument.add_line(start, end, *, layer_group=0, units='paper', **attributes)
```

直線を追加し、追加モデルを返す。

対応範囲・拒否条件：有限2次元位置と確認済み保存属性。CadDocumentの位置/半径はunits、JwwDocumentは紙面mm。TEXTの幅/高さ/間隔は紙面mm・角度は度、円弧/傾きはrad。層/群0～15、候補全保存欄の直列化/読戻し一致を追加前検査。未定義色/線種、不正整数欄、保存不能な符号化は追加前拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L261)。

```python
cad.add_line((0, 0), (1000, 0), units='real', layer=2)
```

### `CadDocument.add_text`

```python
CadDocument.add_text(start, end=None, content=None, *, layer_group=0, units='paper', **attributes)
```

文字を追加する。end省略時は限定した規則で終点を計算する。

対応範囲・拒否条件：有限2次元位置と確認済み保存属性。CadDocumentの位置/半径はunits、JwwDocumentは紙面mm。TEXTの幅/高さ/間隔は紙面mm・角度は度、円弧/傾きはrad。層/群0～15、候補全保存欄の直列化/読戻し一致を追加前検査。未定義色/線種、不正整数欄、保存不能な符号化は追加前拒否。 end省略時は確認済みフォント/alignment、幅欄・flag0等の自動計算条件に限定。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L275)。

```python
cad.add_text((0, 0), content='ABC', size_x=3, size_y=3)
```

### `CadDocument.add_circle`

```python
CadDocument.add_circle(center, radius, *, layer_group=0, units='paper', flatness=1.0, tilt_angle=0.0, **attributes)
```

全周円または楕円を追加する。

対応範囲・拒否条件：有限2次元位置と確認済み保存属性。CadDocumentの位置/半径はunits、JwwDocumentは紙面mm。TEXTの幅/高さ/間隔は紙面mm・角度は度、円弧/傾きはrad。層/群0～15、候補全保存欄の直列化/読戻し一致を追加前検査。未定義色/線種、不正整数欄、保存不能な符号化は追加前拒否。 扁平率は有限正数。全周専用なのでstart_angle/arc_angle/is_full_circleの上書きを拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L301)。

### `CadDocument.add_point`

```python
CadDocument.add_point(position, *, layer_group=0, units='paper', **attributes)
```

通常点またはコード点の保存モデルを追加する。

対応範囲・拒否条件：有限2次元位置と確認済み保存属性。CadDocumentの位置/半径はunits、JwwDocumentは紙面mm。TEXTの幅/高さ/間隔は紙面mm・角度は度、円弧/傾きはrad。層/群0～15、候補全保存欄の直列化/読戻し一致を追加前検査。未定義色/線種、不正整数欄、保存不能な符号化は追加前拒否。 普通点は角度/倍率が保存されないため非ゼロ拒否。コードはuint32。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L321)。

### `CadDocument.add_solid`

```python
CadDocument.add_solid(points, *, rgb=None, layer_group=0, units='paper', **attributes)
```

4つの保存頂点スロットからソリッドを追加する。

対応範囲・拒否条件：有限2次元頂点4個。外周順1,3,2,4。色1～10、RGBは色10の0～255整数3個のみ。不正組合せを拒否。 作図見本SXF102/104/110/112のstyle1/31・flag0、ネイティブ移動対照の102/104/110/112のstyle1・flag2に限定。新規SXF省略線種は作成見本の31、既存値は変更しない。CadDocumentはpoints/rgb/units引数、JwwDocumentはSolidモデル。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L333)。

### `CadDocument.add_circle_solid`

```python
CadDocument.add_circle_solid(center, radius, *, solid_mode=100.0, flatness=1.0, tilt_angle=0.0, start_angle=0.0, arc_angle=2 * math.pi, rgb=None, inner_radius=None, layer_group=0, units='paper', **attributes)
```

円/楕円の全円・弓形ソリッドを追加する。塗り種別と保存属性を保持する。

対応範囲・拒否条件：標準色ではpen_style101、solid_mode5(弓形)/100(全円)、flag0/2048。有限正半径/扁平率、正の掃引は2π以下、全円は2πと開始角0。位置/半径はpaper/real、角度rad。追加属性はLineモデルと同じcolor/width/layer/group/flagでlinetype指定不可。色1～10、10の場合だけrgb整数0～0xffffffを指定。未観測モード/円周、退化、未知フラグ、不正属性は追加前に拒否。 実測したSXF107全円/104正掃引弓形はflag0/2、114負掃引弓形もflag0/2。SXF楕円は未観測で拒否。inner_radiusを指定するとSXF107・flag0/2・真円全周の円環105（内半径が正かつ外半径未満）。座標/内外半径はunits、回転はrad。円環の非等方変形・楕円/部分円環/未観測色フラグを拒否。円環の内半径は、Jw_cadのDXF出力では失われる。JWW全属性一致と無編集native対照を条件に、この欠落だけ承認済み。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L345)。

```python
cad.add_circle_solid((0, 0), 3, solid_mode=100., color=7)
```

### `CadDocument.add_arc`

```python
CadDocument.add_arc(center, radius, start_angle, arc_angle, *, layer_group=0, units='paper', **attributes)
```

共有円レコードを使って円弧を追加する。

対応範囲・拒否条件：有限2次元位置と確認済み保存属性。CadDocumentの位置/半径はunits、JwwDocumentは紙面mm。TEXTの幅/高さ/間隔は紙面mm・角度は度、円弧/傾きはrad。層/群0～15、候補全保存欄の直列化/読戻し一致を追加前検査。未定義色/線種、不正整数欄、保存不能な符号化は追加前拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L470)。

### `JwwDocument.add_line`

```python
JwwDocument.add_line(start, end, **attributes)
```

直線を追加し、追加モデルを返す。

対応範囲・拒否条件：有限2次元位置と確認済み保存属性。CadDocumentの位置/半径はunits、JwwDocumentは紙面mm。TEXTの幅/高さ/間隔は紙面mm・角度は度、円弧/傾きはrad。層/群0～15、候補全保存欄の直列化/読戻し一致を追加前検査。未定義色/線種、不正整数欄、保存不能な符号化は追加前拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L92)。

### `JwwDocument.add_rectangle_hatch`

```python
JwwDocument.add_rectangle_hatch(bounds, **parameters)
```

矩形で切り取った平行LINE群を追加する。境界と関連付けは作成しない。

対応範囲・拒否条件：有限正pitch/spacing、lines_per_groupは1/2/3、max_linesは正整数、組幅<pitch。角度は度、既定flag32。既知GUI一致条件以外は数学的生成であり、登録ハッチの意味は推定しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L100)。

```python
new.add_rectangle_hatch((0, 0, 100, 100), angle_degrees=45, pitch=10)
```

### `JwwDocument.add_circle`

```python
JwwDocument.add_circle(center, radius, **attributes)
```

全周円または楕円を追加する。

対応範囲・拒否条件：有限2次元位置と確認済み保存属性。CadDocumentの位置/半径はunits、JwwDocumentは紙面mm。TEXTの幅/高さ/間隔は紙面mm・角度は度、円弧/傾きはrad。層/群0～15、候補全保存欄の直列化/読戻し一致を追加前検査。未定義色/線種、不正整数欄、保存不能な符号化は追加前拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L111)。

### `JwwDocument.add_arc`

```python
JwwDocument.add_arc(center, radius, start_angle, arc_angle, **attributes)
```

共有円レコードを使って円弧を追加する。

対応範囲・拒否条件：有限2次元位置と確認済み保存属性。CadDocumentの位置/半径はunits、JwwDocumentは紙面mm。TEXTの幅/高さ/間隔は紙面mm・角度は度、円弧/傾きはrad。層/群0～15、候補全保存欄の直列化/読戻し一致を追加前検査。未定義色/線種、不正整数欄、保存不能な符号化は追加前拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L119)。

### `JwwDocument.add_point`

```python
JwwDocument.add_point(position, **attributes)
```

通常点またはコード点の保存モデルを追加する。

対応範囲・拒否条件：有限2次元位置と確認済み保存属性。CadDocumentの位置/半径はunits、JwwDocumentは紙面mm。TEXTの幅/高さ/間隔は紙面mm・角度は度、円弧/傾きはrad。層/群0～15、候補全保存欄の直列化/読戻し一致を追加前検査。未定義色/線種、不正整数欄、保存不能な符号化は追加前拒否。 普通点は角度/倍率が保存されないため非ゼロ拒否。コードはuint32。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L125)。

### `JwwDocument.add_text`

```python
JwwDocument.add_text(start, end=None, content=None, **attributes)
```

文字を追加する。end省略時は限定した規則で終点を計算する。

対応範囲・拒否条件：有限2次元位置と確認済み保存属性。CadDocumentの位置/半径はunits、JwwDocumentは紙面mm。TEXTの幅/高さ/間隔は紙面mm・角度は度、円弧/傾きはrad。層/群0～15、候補全保存欄の直列化/読戻し一致を追加前検査。未定義色/線種、不正整数欄、保存不能な符号化は追加前拒否。 end省略時は確認済みフォント/alignment、幅欄・flag0等の自動計算条件に限定。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L133)。

### `JwwDocument.add_dimension`

```python
JwwDocument.add_dimension(line, text, **attributes)
```

Line・Text・補助線・点から固定構造の寸法を追加する。

対応範囲・拒否条件：寸法自動計算/自動関連付けはしない。新規寸法はSXF0、Line/Text、補助線2本/補助点4個の確認済み構造。set_dimension_textは既存DIMENSIONと文字列のみ。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L145)。

### `JwwDocument.add_solid`

```python
JwwDocument.add_solid(points, **attributes)
```

4つの保存頂点スロットからソリッドを追加する。

対応範囲・拒否条件：有限2次元頂点4個。外周順1,3,2,4。色1～10、RGBは色10の0～255整数3個のみ。不正組合せを拒否。 作図見本SXF102/104/110/112のstyle1/31・flag0、ネイティブ移動対照の102/104/110/112のstyle1・flag2に限定。新規SXF省略線種は作成見本の31、既存値は変更しない。CadDocumentはpoints/rgb/units引数、JwwDocumentはSolidモデル。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L153)。

### `rectangle_hatch_lines`

```python
rectangle_hatch_lines(bounds, *, angle_degrees=45, pitch=10, origin=(0, 0), lines_per_group=1, line_spacing=1, max_lines=10000, **attributes)
```

矩形で切り取った平行Lineモデル群を返す。図面にはまだ追加しない。

対応範囲・拒否条件：有限正pitch/spacing、lines_per_groupは1/2/3、max_linesは正整数、組幅<pitch。角度は度、既定flag32。既知GUI一致条件以外は数学的生成であり、登録ハッチの意味は推定しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/hatch_geometry.py#L12)。

### `Line`

```python
Line(start: tuple[float, float], end: tuple[float, float], color: int=2, linetype: int=1, width: int=0, layer: int=0, layer_group: int=0, group: int=0, flag: int=0)
```

保存可能な子要素/参照/定義のモデルを構築する。

対応範囲・拒否条件：dataclass構築自体では検証せず、record生成・図面追加/保存時に検証する。有限2次元位置と確認済み保存属性。CadDocumentの位置/半径はunits、JwwDocumentは紙面mm。TEXTの幅/高さ/間隔は紙面mm・角度は度、円弧/傾きはrad。層/群0～15、候補全保存欄の直列化/読戻し一致を追加前検査。未定義色/線種、不正整数欄、保存不能な符号化は追加前拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/line.py#L7)。

### `Circle`

```python
Circle(center: tuple[float, float], radius: float, start_angle: float=0.0, arc_angle: float=2 * math.pi, tilt_angle: float=0.0, flatness: float=1.0, is_full_circle: bool=True, color: int=2, linetype: int=1, width: int=0, layer: int=0, layer_group: int=0, group: int=0, flag: int=0)
```

保存可能な子要素/参照/定義のモデルを構築する。

対応範囲・拒否条件：dataclass構築自体では検証せず、record生成・図面追加/保存時に検証する。有限2次元位置と確認済み保存属性。CadDocumentの位置/半径はunits、JwwDocumentは紙面mm。TEXTの幅/高さ/間隔は紙面mm・角度は度、円弧/傾きはrad。層/群0～15、候補全保存欄の直列化/読戻し一致を追加前検査。未定義色/線種、不正整数欄、保存不能な符号化は追加前拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/circle.py#L7)。

### `Point`

```python
Point(position: tuple[float, float], is_temporary: bool=False, code: int=0, angle: float=0.0, scale: float=0.0, color: int=2, width: int=0, layer: int=0, layer_group: int=0, group: int=0, flag: int=0)
```

保存可能な子要素/参照/定義のモデルを構築する。

対応範囲・拒否条件：dataclass構築自体では検証せず、record生成・図面追加/保存時に検証する。有限2次元位置と確認済み保存属性。CadDocumentの位置/半径はunits、JwwDocumentは紙面mm。TEXTの幅/高さ/間隔は紙面mm・角度は度、円弧/傾きはrad。層/群0～15、候補全保存欄の直列化/読戻し一致を追加前検査。未定義色/線種、不正整数欄、保存不能な符号化は追加前拒否。 普通点は角度/倍率が保存されないため非ゼロ拒否。コードはuint32。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/point.py#L7)。

### `Text`

```python
Text(start: tuple[float, float], end: tuple[float, float], content: str, text_type: int=0, size_x: float=2.5, size_y: float=2.5, spacing: float=0.0, angle: float=0.0, font_name: str='ＭＳ ゴシック', alignment: int=1, color: int=2, width: int=0, layer: int=0, layer_group: int=0, group: int=0, flag: int=0)
```

保存可能な子要素/参照/定義のモデルを構築する。

対応範囲・拒否条件：dataclass構築自体では検証せず、record生成・図面追加/保存時に検証する。有限2次元位置と確認済み保存属性。CadDocumentの位置/半径はunits、JwwDocumentは紙面mm。TEXTの幅/高さ/間隔は紙面mm・角度は度、円弧/傾きはrad。層/群0～15、候補全保存欄の直列化/読戻し一致を追加前検査。未定義色/線種、不正整数欄、保存不能な符号化は追加前拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/text.py#L7)。

### `Solid`

```python
Solid(points: tuple, rgb: tuple | None=None, color: int=2, linetype: int | None=None, width: int=0, layer: int=0, layer_group: int=0, group: int=0, flag: int=0)
```

保存可能な子要素/参照/定義のモデルを構築する。

対応範囲・拒否条件：dataclass構築自体では検証せず、record生成・図面追加/保存時に検証する。有限2次元頂点4個。外周順1,3,2,4。色1～10、RGBは色10の0～255整数3個のみ。不正組合せを拒否。 作図見本SXF102/104/110/112のstyle1/31・flag0、ネイティブ移動対照の102/104/110/112のstyle1・flag2に限定。新規SXF省略線種は作成見本の31、既存値は変更しない。CadDocumentはpoints/rgb/units引数、JwwDocumentはSolidモデル。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/solid.py#L7)。

### `Dimension`

```python
Dimension(line: Line, text: Text, aux_lines: list=field(default_factory=lambda: [Line((0, 0), (0, 0)) for _ in range(2)]), aux_points: list=field(default_factory=lambda: [Point((0, 0)) for _ in range(4)]), sxf_mode: int=0, color: int=2, linetype: int=1, width: int=0, layer: int=0, layer_group: int=0, group: int=0, flag: int=8192)
```

保存可能な子要素/参照/定義のモデルを構築する。

対応範囲・拒否条件：dataclass構築自体では検証せず、record生成・図面追加/保存時に検証する。寸法自動計算/自動関連付けはしない。新規寸法はSXF0、Line/Text、補助線2本/補助点4個の確認済み構造。set_dimension_textは既存DIMENSIONと文字列のみ。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/dimension.py#L10)。

## 編集

### `CadDocument.delete_entity`

```python
CadDocument.delete_entity(index)
```

指定公開番号の要素1個を削除する。定義は自動削除しない。

対応範囲・拒否条件：公開番号を指定し、不正番号/bool/一括番号重複を拒否。削除は形状変換をしないため未知型も選択自体は可能。空の一括選択は何もしない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L110)。

### `CadDocument.delete_entities`

```python
CadDocument.delete_entities(indices)
```

指定公開番号の要素群を一括削除する。定義は自動削除しない。

対応範囲・拒否条件：公開番号を指定し、不正番号/bool/一括番号重複を拒否。削除は形状変換をしないため未知型も選択自体は可能。空の一括選択は何もしない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L116)。

### `CadDocument.move_entities`

```python
CadDocument.move_entities(indices, delta, *, units='paper')
```

選択要素群を全件検証後に一体として平行移動する。

対応範囲・拒否条件：既知9種類。円ソリッドの標準色は101・mode5/100・flag0/2048、SXFはadd_circle_solid記載の観測プロフィールと105真円円環に限定。移動は中心だけ変更し他欄を保持。不正番号/bool/一括重複、未知形状/未観測円ソリッドを拒否。移動量は有限値、unitsはpaper/real。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L122)。

```python
cad.move_entities([0, 1], (100, 0), units='real')
```

### `CadDocument.move_entity`

```python
CadDocument.move_entity(index, delta, *, units='paper')
```

要素1個の関連保存座標を一体として平行移動する。

対応範囲・拒否条件：既知9種類。円ソリッドの標準色は101・mode5/100・flag0/2048、SXFはadd_circle_solid記載の観測プロフィールと105真円円環に限定。移動は中心だけ変更し他欄を保持。不正番号/bool/一括重複、未知形状/未観測円ソリッドを拒否。移動量は有限値、unitsはpaper/real。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L128)。

### `CadDocument.set_entity_attributes`

```python
CadDocument.set_entity_attributes(index, *, color=None, linetype=None, width=None, layer=None, layer_group=None, preserve='paper')
```

色・線種・幅・レイヤ・層群を変更し、紙面または実寸の保持を指定する。

対応範囲・拒否条件：色は標準保存欄0～9/定義済みSXF、RGBソリッドだけ10、線種は標準1～9/定義済みSXF。完全一致SXF名も可、未定義/予約/無名未確認欄は拒否。幅0～65535、層/群0～15。円ソリッドの標準色は101・mode5/100・flag0/2048、SXFはadd_circle_solid記載の観測プロフィールと105真円円環に限定。線種欄は原本の101/105から変更不可、RGB保存形式の切替えを拒否。異縮尺realは中心/外半径/円環内半径を換算し他欄を保持。TEXT/POINT/BLOCKの線種、TEXT/DIMENSIONの幅、文字種付き寸法の色変更と未観測の群変更、文字種付き文字/コード点の異縮尺実寸保持を拒否。v700/文字種1/等縮尺/群だけの指定/既知flag0または2/mode0で補助線と点がゼロのプレースホルダー/内包線と文字の所属が元群と一致、に限り外側群のみ変更して内包全属性とflagを保持する限定対応（承認済み計画の実行・全属性/DXF/PDF受入れ済み）。他の文字種・異縮尺・色/線種/幅/レイヤとの同時変更は拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L172)。

```python
cad.set_entity_attributes(0, layer_group=1, preserve='real')
```

### `CadDocument.set_text`

```python
CadDocument.set_text(index: int, content: str, *, recalculate_end: bool=False)
```

文字本文を変更する。CadDocumentでは指定時だけ終点も再計算する。

対応範囲・拒否条件：負/bool/範囲外番号、非TEXT/非文字列、保存不能な符号化/不対サロゲートを変更前拒否。終点自動計算は確認済みフォント、alignment1～9、幅欄/flag0のみ。空/制御文字、不正幅/間隔を拒否。候補全保存欄をメモリ往復で検証。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L195)。

```python
cad.set_text(0, '変更文字', recalculate_end=True)
```

### `CadDocument.recalculate_text_endpoint`

```python
CadDocument.recalculate_text_endpoint(index: int)
```

始点・本文・属性を保ち、限定した字幅規則でTEXT終点を更新する。

対応範囲・拒否条件：負/bool/範囲外番号、非TEXT/非文字列、保存不能な符号化/不対サロゲートを変更前拒否。終点自動計算は確認済みフォント、alignment1～9、幅欄/flag0のみ。空/制御文字、不正幅/間隔を拒否。候補全保存欄をメモリ往復で検証。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L213)。

### `CadDocument.set_group_state`

```python
CadDocument.set_group_state(layer_group, state)
```

非書込み群の表示状態だけを変更し、全要素・名称・縮尺を保持する。

対応範囲・拒否条件：hidden/display_only/editable（整数0/1/2も可）の状態欄DWORDだけ変更。bool/不正番号/未知状態、書込み選択3への変更・3からの変更、保護された群/層の変更を事前拒否。現在値3への同値指定は無変更。未解析ヘッダー・要素・定義・縮尺・名称・書込み先を保持。独立メモリで全保存/読戻し検証後だけ確定し、safe_editの計画にも対応。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L403)。

### `CadDocument.set_layer_state`

```python
CadDocument.set_layer_state(layer_group, layer, state)
```

非書込みレイヤの表示状態だけを変更し、親群の状態を保持する。

対応範囲・拒否条件：hidden/display_only/editable（整数0/1/2も可）の状態欄DWORDだけ変更。bool/不正番号/未知状態、書込み選択3への変更・3からの変更、保護された群/層の変更を事前拒否。現在値3への同値指定は無変更。未解析ヘッダー・要素・定義・縮尺・名称・書込み先を保持。独立メモリで全保存/読戻し検証後だけ確定し、safe_editの計画にも対応。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L409)。

### `CadDocument.set_layer_name`

```python
CadDocument.set_layer_name(layer_group, layer, name)
```

指定レイヤの名前だけを変更する。

対応範囲・拒否条件：層/群0～15、名称は文字列。CadDocumentは原CString符号化を保持し、表現できない名称は拒否。空/不完全CP932保存名は読取り時に補完しない。未知のヘッダー状態は編集しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L423)。

### `CadDocument.set_group_name`

```python
CadDocument.set_group_name(layer_group, name)
```

指定層群の名前だけを変更する。

対応範囲・拒否条件：層/群0～15、名称は文字列。CadDocumentは原CString符号化を保持し、表現できない名称は拒否。空/不完全CP932保存名は読取り時に補完しない。未知のヘッダー状態は編集しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L434)。

### `CadDocument.set_dimension_text`

```python
CadDocument.set_dimension_text(index: int, content: str)
```

寸法内包文字の表示本文だけ変更する。測定値や位置の自動計算はしない。

対応範囲・拒否条件：寸法自動計算/自動関連付けはしない。新規寸法はSXF0、Line/Text、補助線2本/補助点4個の確認済み構造。set_dimension_textは既存DIMENSIONと文字列のみ。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L488)。

### `JwwDocument.set_layer_name`

```python
JwwDocument.set_layer_name(layer_group, layer, name)
```

指定レイヤの名前だけを変更する。

対応範囲・拒否条件：層/群0～15・文字列・CString表現可能な名称。空名の表示情報は既定表示名に戻る。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L57)。

### `JwwDocument.set_group_name`

```python
JwwDocument.set_group_name(layer_group, name)
```

指定層群の名前だけを変更する。

対応範囲・拒否条件：層/群0～15・文字列・CString表現可能な名称。空名の表示情報は既定表示名に戻る。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L67)。

### `LegacyDocument.set_text`

```python
LegacyDocument.set_text(index, content)
```

文字本文を変更する。CadDocumentでは指定時だけ終点も再計算する。

対応範囲・拒否条件：TEXTと文字列のみ。CP932で表せない文字を拒否。終点は再計算しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/legacy_document.py#L43)。

### `safe_edit.write_plan`

```python
safe_edit.write_plan(cad, indices, actions, output, plan_path, *, dependencies=(), selection=None, selection_limits=None, workflow=None, common_result=False)
```

対象/操作/各SHAを新規JSONへ出して終了する。通常schema2、selection付きschema3、workflow付きschema4、common_result=Trueで31メソッドのschema5。

対応範囲・拒否条件：未編集CadDocument・許可操作だけ。selectionは直下complete必須。workflowは既知の差し替えレシピ・設定スナップショット/実効値とactions/全監査の一致が必要。設定変化中の計画/未知/既存出力/競合/無許可対象を拒否。旧schema1～4維持。schema5は共通窓口だけ、workflow同時計画を拒否。承認や実行は行わない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/safe_edit.py#L186)。

```python
receipt = write_plan(cad, [0], [{'op': 'move_entities', 'indices': [0], 'kwargs': {'delta': [100, 0], 'units': 'real'}}], 'new.jww', 'plan.json')
```

### `safe_edit.verify_plan`

```python
safe_edit.verify_plan(plan_path, *, approved_sha256)
```

承認した計画SHA256を照合し、元図面/要素/層群/レイヤ/定義/依存を再読込み検査する。

対応範囲・拒否条件：チャットで承認した64桁SHAを必須指定。変更・不正スキーマ/対象/操作・既存出力・入力/依存との競合を拒否。schema1は従来操作のみ。人の承認を署名で証明するAPIではない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/safe_edit.py#L265)。

```python
cad, plan = verify_plan('plan.json', approved_sha256=approved_plan_hash)
```

### `safe_edit.execute_plan`

```python
safe_edit.execute_plan(plan_path, *, approved_sha256)
```

検証後、宣言した編集だけ実行し別名保存/読直し/図形・定義・名称/縮尺差分を報告する。

対応範囲・拒否条件：編集24操作。元番号追跡・要素/定義の型別名。未知API/GUI実行/無許可対象/別名混用/依存変化/既存定義改変/保存不一致等を拒否。途中拒否は元図面不変・未保存。対応一覧はplan_api_coverage.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/safe_edit.py#L402)。

```python
report = execute_plan('plan.json', approved_sha256=approved_plan_hash)
```

### `plan_building_replacement`

```python
plan_building_replacement(source, incoming, output, plan_path, *, work_dir, source_reference_indices, target_reference_indices, distance_tolerance, angle_tolerance, angle_units='deg', building_group=0, settings_policy='strict', archive_group=None, instruction_overrides=None, instruction_evidence=None)
```

明示work_dirの設定と今回の指示で、退避または削除を行うschema4承認計画だけを作成する。

対応範囲・拒否条件：v700/両建築群1:100/倍率1/非空・対象にブロック参照なし。基準2点/距離・角度許容必須。空でない/書込み/保護/退避先欠落/未知/不整合を変更前拒否。first_emptyは最小適格番号を固定。全非対象群と全体設定の不変を監査。実行は別のexecute_planとチャット承認。 詳細docs/workflow_settings.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/replacement_workflow.py#L14)。

### `edit_result.preview_plan_result`

```python
edit_result.preview_plan_result(plan_path, *, plan_sha256, limit=100, mode='details')
```

SHAが一致する計画を保存せず試行しprojected_countsを返す。

対応範囲・拒否条件：試行は承認ではない。現入力と対象/規則の一致必須、未知操作拒否。 limit=100/最大1000・mode=details/summary/count。詳細はdocs/edit_results.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/edit_result.py#L86)。

### `edit_result.write_edit_plan`

```python
edit_result.write_edit_plan(cad, indices, actions, output, plan_path, *, dependencies=(), selection=None, selection_limits=None, limit=100, mode='details')
```

31メソッドの承認計画と共通の見込み結果を作成する。

対応範囲・拒否条件：元モデル/図面を編集しない。schema5・対象/依存SHA/許可表を検証。JwwDocument/LegacyDocument/JWS/GUIは対象外。 limit=100/最大1000・mode=details/summary/count。詳細はdocs/edit_results.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/edit_result.py#L103)。

### `edit_result.execute_plan_result`

```python
edit_result.execute_plan_result(plan_path, *, approved_sha256, limit=100, mode='details')
```

承認SHAを検証しステージ編集・別名保存/読戻し・共通結果を記録する。

対応範囲・拒否条件：旧APIの戻り値/例外は維持。新窓口の既知拒否は結果へ、予期しない失敗はEditExecutionError.resultを付け再送出。新規.edit-result.jsonも上書き/入力競合を拒否。 limit=100/最大1000・mode=details/summary/count。詳細はdocs/edit_results.md。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/edit_result.py#L118)。

## 複写・変形

### `CadDocument.transform_entities`

```python
CadDocument.transform_entities(indices, **options)
```

基準点まわりに縦横倍率→回転→移動を行い、属性と非対象を保持する。

対応範囲・拒否条件：既知9種類の表現可能な変換のみ。円ソリッドは101・モード5/100・フラグ0/2048に限定し、特異変換と未検証の塗りを拒否。空/重複/不正選択、非有限値、ゼロ倍率、文字グリフ反転、制御文字、未観測文字種/flag、文字種付き文字/寸法の拡縮・反転、コード点線形変換、参照/文字のせん断を拒否。変換角度はrad、unitsはpaper/real。剛体回転の対照で確認した文字種2/3/4/5と観測flag、mode0文字種3/flag8192寸法は倍率1の剛体移動/回転に限定対応し、角度以外の文字様式を保持する。mode0未使用補助欄は非ゼロ/符号付きゼロも含め保存値を変換せず保持。全円の開始角も剛体変換では保持。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L134)。

委譲先の有効引数：`transform_entities(indices, *, base_point=(0, 0), translation=(0, 0), rotation=0, scale_x=1, scale_y=1, units='paper', copy_entities=False)`（[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/transformations.py#L120)）。

### `CadDocument.copy_entities`

```python
CadDocument.copy_entities(indices, delta=(0, 0), *, units='paper')
```

選択要素の独立コピーを末尾へ追加し、delta分移動する。

対応範囲・拒否条件：既知9種類。円ソリッドの検証済み全円/弓形も対象。空/重複/不正選択、未対応型、非有限移動を拒否。元要素は保持し、定義は複写せず再利用する。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L140)。

```python
cad.copy_entities([0, 1], (100, 0), units='real')
```

### `CadDocument.align_two_points`

```python
CadDocument.align_two_points(indices, source_points, target_points, *, distance_tolerance, angle_tolerance, angle_units='rad', allow_scale=False)
```

実寸2点対から移動・回転を求め、許容値内の場合だけ原子的に適用する。

対応範囲・拒否条件：距離許容mmと角度許容は必須。angle_units=rad/deg、結果は両単位と基線端部の角度許容変位mm。角度許容は対応点対の向きの差の上限。既定は倍率1、allow_scale=Trueだけ一様倍率補正。実寸専用。重複点・非有限値・許容超過・表現不能要素を拒否。補正有効でも元の距離差の許容判定を省略しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L145)。

### `CadDocument.rotate_entities`

```python
CadDocument.rotate_entities(indices, angle, **options)
```

基準点まわりに選択要素を回転する。copy=Trueで複写する。

対応範囲・拒否条件：既知9種類の表現可能な変換のみ。円ソリッドは101・モード5/100・フラグ0/2048に限定し、特異変換と未検証の塗りを拒否。空/重複/不正選択、非有限値、ゼロ倍率、文字グリフ反転、制御文字、未観測文字種/flag、文字種付き文字/寸法の拡縮・反転、コード点線形変換、参照/文字のせん断を拒否。変換角度はrad、unitsはpaper/real。剛体回転の対照で確認した文字種2/3/4/5と観測flag、mode0文字種3/flag8192寸法は倍率1の剛体移動/回転に限定対応し、角度以外の文字様式を保持する。mode0未使用補助欄は非ゼロ/符号付きゼロも含め保存値を変換せず保持。全円の開始角も剛体変換では保持。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L157)。

委譲先の有効引数：`rotate_entities(indices, angle, *, base_point=(0, 0), units='paper', copy=False)`（[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/transformations.py#L164)）。

```python
cad.rotate_entities([0, 1], 0.5, copy=True)
```

### `CadDocument.reflect_entities`

```python
CadDocument.reflect_entities(indices, **options)
```

axis_pointを通るaxis_angle方向の軸で要素を反転する。

対応範囲・拒否条件：既知9種類の表現可能な変換のみ。円ソリッドは101・モード5/100・フラグ0/2048に限定し、特異変換と未検証の塗りを拒否。空/重複/不正選択、非有限値、ゼロ倍率、文字グリフ反転、制御文字、未観測文字種/flag、文字種付き文字/寸法の拡縮・反転、コード点線形変換、参照/文字のせん断を拒否。変換角度はrad、unitsはpaper/real。剛体回転の対照で確認した文字種2/3/4/5と観測flag、mode0文字種3/flag8192寸法は倍率1の剛体移動/回転に限定対応し、角度以外の文字様式を保持する。mode0未使用補助欄は非ゼロ/符号付きゼロも含め保存値を変換せず保持。全円の開始角も剛体変換では保持。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L162)。

委譲先の有効引数：`reflect_entities(indices, *, axis_point=(0, 0), axis_angle=0, units='paper', copy=False)`（[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/transformations.py#L173)）。

### `CadDocument.scale_entities`

```python
CadDocument.scale_entities(indices, scale_x, scale_y=None, **options)
```

基準点まわりに拡大縮小する。scale_y省略時は等方倍率。

対応範囲・拒否条件：既知9種類の表現可能な変換のみ。円ソリッドは101・モード5/100・フラグ0/2048に限定し、特異変換と未検証の塗りを拒否。空/重複/不正選択、非有限値、ゼロ倍率、文字グリフ反転、制御文字、未観測文字種/flag、文字種付き文字/寸法の拡縮・反転、コード点線形変換、参照/文字のせん断を拒否。変換角度はrad、unitsはpaper/real。剛体回転の対照で確認した文字種2/3/4/5と観測flag、mode0文字種3/flag8192寸法は倍率1の剛体移動/回転に限定対応し、角度以外の文字様式を保持する。mode0未使用補助欄は非ゼロ/符号付きゼロも含め保存値を変換せず保持。全円の開始角も剛体変換では保持。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L167)。

委譲先の有効引数：`scale_entities(indices, scale_x, scale_y=None, *, base_point=(0, 0), units='paper', copy=False)`（[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/transformations.py#L168)）。

### `CadDocument.import_group`

```python
CadDocument.import_group(path, source_group, target_group, *, sync_scale=False, sync_group_name=True, sync_layer_names=True, block_renames=None, settings_policy='strict')
```

別JWWの指定群を依存/全属性検証後に取り込む。

対応範囲・拒否条件：同版のみ。settings_policyはstrictが既定で全体設定差を拒否。明示destinationだけ同一性比較を外し、先の全体設定生バイト（未確定3バイト含む）を保持、源の要素属性番号は維持し見え方は先に従う。未定義色/線種番号は両方で事前拒否。計画には両設定ハッシュ/差を明記。sync_scale/sync_group_name/sync_layer_namesは独立bool。同名定義は番号以外の全内容一致だけ再利用、明示block_renames可。画像/新規入れ子/優先参照群変更/未知構造は全体拒否。文字種付き寸法はv700/mode0/補助線2点4のゼロ座標/同縮尺だけ。文字種1は根flag0,2で外側群だけ変更。文字種3は実測した属性の組み合わせ（根/線flag8192、文字flag16400/幅67/線種2、MSゴシック有限角（剛体回転の照合を含む）、宣言文字種3のサイズ/色一致、既定の観測ペン/補助属性）だけ、外側と文字の群を変更し、線/補助の群・全flagを保持。元/先の元縮尺が異なる場合はsync_scaleでも拒否。未観測の文字種/フラグ/様式・非ゼロ補助・定義内寸法・保持内包群設定の不一致は拒否。座標は原点位置を保持。文字種1は実図面で照合済み、文字種3はネイティブ21件対照と承認済みAPI1205件取込みのJWW全属性/DXF全数値/PDF受入れ合格。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L561)。

### `solve_two_point_alignment`

```python
solve_two_point_alignment(source_points, target_points, *, distance_tolerance, angle_tolerance, angle_units='rad', allow_scale=False)
```

実寸2点対の距離差と角度差、倍率候補を読取りだけで返す。

対応範囲・拒否条件：距離許容mmと角度許容は必須。angle_units=rad/deg、結果は両単位と基線端部の角度許容変位mm。角度許容は対応点対の向きの差の上限。既定は倍率1、allow_scale=Trueだけ一様倍率補正。実寸専用。重複点・非有限値・許容超過・表現不能要素を拒否。補正有効でも元の距離差の許容判定を省略しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/alignment.py#L24)。

## ブロック

### `CadDocument.add_block_definition`

```python
CadDocument.add_block_definition(name, entities, *, timestamp=0, compound_kind=None)
```

子モデルから名前付き定義を追加する。

対応範囲・拒否条件：新規入れ子定義は未対応。名前/子属性/日時uint32/符号化を検証。CadDocumentは非空。JwwDocumentは番号重複を拒否。compound_kindは1～4/None、既存印との二重指定を拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L444)。

```python
definition = cad.add_block_definition('記号A', [Line((0, 0), (10, 0))], compound_kind=4)
```

### `CadDocument.place_block`

```python
CadDocument.place_block(def_number, position, *, layer_group=0, units='paper', **attributes)
```

既存定義への参照を位置・回転・縦横倍率付きで配置する。

対応範囲・拒否条件：位置は指定単位（JwwDocumentは紙面）、回転rad、倍率無次元。不存在番号・不正保存値は両入口で追加前拒否。確認済み参照style0/1/2/3/64/65/66/67は優先等の専用欄で、SXF線種にしない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L504)。

```python
cad.place_block(definition.number, (20, 30), rotation=0.5)
```

### `CadDocument.block_reference_counts`

```python
CadDocument.block_reference_counts()
```

図面直下の参照を表示名別に集計する。定義内参照は重複加算しない。

対応範囲・拒否条件：直下参照のみ、表示名で集計。未解決定義参照を拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L520)。

### `CadDocument.replace_entities_with_block`

```python
CadDocument.replace_entities_with_block(indices, name, **options)
```

選択要素を定義＋参照へ原子的に置換し、同名定義は形状・属性一致時だけ再利用する。

対応範囲・拒否条件：正倍率、基準点/回転、混在属性、優先切替を扱う。空/重複選択、入れ子/制御・せん断文字、未観測bit2組合せ、同名複数定義/形状属性不一致を変更前に拒否。match_toleranceは0～1e-6紙面mm。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L525)。

委譲先の有効引数：`replace_entities_with_block(indices, name, *, base_point=(0, 0), rotation=0, scale_x=1, scale_y=1, layer_group=None, layer=None, layer_priority=True, reuse_existing=True, compound_kind=4, units='paper', match_tolerance=1e-08)`（[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/block_operations.py#L108)）。

```python
cad.replace_entities_with_block([0, 1], '記号A', base_point=(0, 0), layer_priority=True)
```

### `CadDocument.get_block_layer_priority`

```python
CadDocument.get_block_layer_priority(index: int)
```

通常参照の確認済みレイヤ優先ビットを読む。

対応範囲・拒否条件：BLOCK・pen_style0/1/2/3/64/65/66/67・幅0・flag0のみ。未知属性は拒否。enabledはbool。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L531)。

### `CadDocument.set_block_layer_priority`

```python
CadDocument.set_block_layer_priority(index: int, enabled: bool)
```

確認済み参照の優先ビット0x40だけ切り替え、定義と他属性を保持する。

対応範囲・拒否条件：BLOCK・pen_style0/1/2/3/64/65/66/67・幅0・flag0のみ。未知属性は拒否。enabledはbool。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L542)。

### `JwwDocument.add_block_definition`

```python
JwwDocument.add_block_definition(name, entities, *, number=None, timestamp=0, compound_kind=4)
```

子モデルから名前付き定義を追加する。

対応範囲・拒否条件：新規入れ子定義は未対応。名前/子属性/日時uint32/符号化を検証。CadDocumentは非空。JwwDocumentは番号重複を拒否。compound_kindは1～4/None、既存印との二重指定を拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L161)。

### `JwwDocument.add_block`

```python
JwwDocument.add_block(def_number, position, **attributes)
```

定義番号への参照モデルを追加する。

対応範囲・拒否条件：位置は指定単位（JwwDocumentは紙面）、回転rad、倍率無次元。不存在番号・不正保存値は両入口で追加前拒否。確認済み参照style0/1/2/3/64/65/66/67は優先等の専用欄で、SXF線種にしない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/writer/template_document.py#L174)。

### `block_name_info`

```python
block_name_info(name: str)
```

末尾の内部印1～4を認識し、保存名・表示名・種別・認識状態を返す。

対応範囲・拒否条件：文字列のみ。印は末尾に1個かつ1～4のときだけ認識する。未知/重複印は元名保持のunrecognized。現行GUI意味を断定しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/block_names.py#L28)。

### `BlockReference`

```python
BlockReference(position: tuple[float, float], def_number: int, scale_x: float=1.0, scale_y: float=1.0, rotation: float=0.0, color: int=2, linetype: int=1, width: int=0, layer: int=0, layer_group: int=0, group: int=0, flag: int=0)
```

保存可能な子要素/参照/定義のモデルを構築する。

対応範囲・拒否条件：dataclass構築自体では検証せず、record生成・図面追加/保存時に検証する。位置は指定単位（JwwDocumentは紙面）、回転rad、倍率無次元。不存在番号・不正保存値は両入口で追加前拒否。確認済み参照style0/1/2/3/64/65/66/67は優先等の専用欄で、SXF線種にしない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/block_reference.py#L7)。

### `BlockDefinition`

```python
BlockDefinition(number: int, name: str, entities: list, timestamp: int=0, base: dict=None)
```

保存可能な子要素/参照/定義のモデルを構築する。

対応範囲・拒否条件：dataclass構築自体では検証せず、record生成・図面追加/保存時に検証する。新規入れ子定義は未対応。名前/子属性/日時uint32/符号化を検証。CadDocumentは非空。JwwDocumentは番号重複を拒否。compound_kindは1～4/None、既存印との二重指定を拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/block_definition.py#L7)。

### `CadBlockDefinition.name_info`

```python
CadBlockDefinition.name_info
```

定義の保存名を変えず、表示名・内部印の認識状態を返すプロパティ。

対応範囲・拒否条件：文字列のみ。印は末尾に1個かつ1～4のときだけ認識する。未知/重複印は元名保持のunrecognized。現行GUI意味を断定しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/common_entities.py#L31)。

## 登録図形

### `JwsDocument.records`

```python
JwsDocument.records
```

登録図形の全生要素・全定義の深いコピーを返すプロパティ。

対応範囲・拒否条件：読込み時の保存生記録のコピー。返却値の変更で元モデルは変わらない。読取り後の任意編集をJWSへ保存するAPIはない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/reader/jws.py#L36)。

### `JwsDocument.open`

```python
JwsDocument.open(path)
```

JWS専用ヘッダーと全要素/定義を損失なく読む。

対応範囲・拒否条件：JWS保存版230/351/420/600/700。230/700予約72bytesは業務実測パターンのみ。230の線幅欄は存在せず0で表す。JWK、未知クラス/末尾、切断、不正値・縮尺・範囲、未解決/循環/過深参照、本文往復不一致を拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/reader/jws.py#L41)。

```python
figure = JwsDocument.open('my_symbol.jws')
```

### `JwsDocument.from_bytes`

```python
JwsDocument.from_bytes(data, *, source=None)
```

JWS専用ヘッダーと本文をメモリから厳密に読み込む。

対応範囲・拒否条件：JWS保存版230/351/420/600/700。230/700予約72bytesは業務実測パターンのみ。230の線幅欄は存在せず0で表す。JWK、未知クラス/末尾、切断、不正値・縮尺・範囲、未解決/循環/過深参照、本文往復不一致を拒否。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/reader/jws.py#L46)。

### `JwsDocument.to_bytes`

```python
JwsDocument.to_bytes()
```

検証済み原ヘッダーと全保存要素・定義を再直列化してbytesを返す。

対応範囲・拒否条件：読取済み全記録を再直列化。未参照定義・文字原バイト・検証済み原ヘッダーを保持する。登録図形の編集・ヘッダー変更・ファイル上書きAPIではない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/reader/jws.py#L125)。

### `JwsDocument.place_as_block`

```python
JwsDocument.place_as_block(document, name, position, *, layer_group=0, units='paper', layer=0, layer_priority=True)
```

保存基準点・元縮尺から実寸を保ち、CadDocumentへ定義と参照を配置する。

対応範囲・拒否条件：230/351/420/600は平坦、700は入れ子を1段へ平坦化して非空図形を新規名へ配置。円ソリッド101の弓形/全円を追加し、700葉フラグは実務6枚の値＋Jw_cadで保存した対照4組だけを許可する。全版で重複名、未観測bit2・他フラグ、未検証の円ソリッド塗り、未確認文字変換・せん断、ゼロ倍率、展開上限超過等を変更前に拒否。未参照定義は配置先に輸入しない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/reader/jws.py#L137)。

```python
figure.place_as_block(cad, '登録A', (1000, 2000), units='real')
```

## 要約出力

### `CadDocument.summary`

```python
CadDocument.summary()
```

レイヤ別件数、文字全文、寸法文字、定義と参照を区別した要約を辞書で返す。

対応範囲・拒否条件：直下と定義内を分離。設定込みモデル、非有限値、不正層/群、未解決参照/重複定義を拒否。write_summaryは同名出力を拒否し、NaN禁止・不完全CP932はJSONエスケープで保持。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L415)。

### `CadDocument.write_summary`

```python
CadDocument.write_summary(path)
```

要約を再現可能なJSONとして新規ファイルへ出力する。

対応範囲・拒否条件：直下と定義内を分離。設定込みモデル、非有限値、不正層/群、未解決参照/重複定義を拒否。write_summaryは同名出力を拒否し、NaN禁止・不完全CP932はJSONエスケープで保持。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L419)。

```python
cad.write_summary('new_summary.json')
```

### `CadDocument.entity_counts`

```python
CadDocument.entity_counts
```

公開要素の種類別件数を返すプロパティ。定義内子要素は加算しない。

対応範囲・拒否条件：現在の公開entitiesだけ集計する。定義内子要素・既定で除外した設定要素は数えない。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/model/document.py#L558)。

### `safe_edit.diff_report`

```python
safe_edit.diff_report(before, after)
```

元要素の変更/削除/追加の数と内容、定義の前後、層群/レイヤ名/縮尺のgroup_changesを返す。

対応範囲・拒否条件：編集前は読込み直後の一意なsource_indexが必要。未知/重複の元番号を拒否。名称/縮尺の変化は図形数と別に数える。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/safe_edit.py#L38)。

### `write_comparison`

```python
write_comparison(result, output)
```

独立図面の比較結果をローカルの新規JSONへ書き出す。

対応範囲・拒否条件：schema1比較結果だけ。.json以外/既存出力/非有限値を拒否。図面やレジストリへ書き込まない。保留も含むためcompleteを必ず確認する。

根拠：[ソース](https://github.com/tetsuo-m/jwwkit/blob/main/src/jwwkit/drawing_comparison.py#L423)。

```python
write_comparison(result, 'new_comparison.json')
```
