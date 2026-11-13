# JWF 読取り・要約を前提にした作図運用

目的は、AIの作図と人の目視確認で同じ前提を共有すること。現段階は**読取り・宣言値の比較のみ**。Jw_cadへの適用、JWF/JWWの編集、書出しは行わない。識別できるキーと保存区分は[JWFのキー一覧](jwf_key_catalog.md)または `jwf_setting_catalog()` で確認できます。設定値の詳しい意味は、お手元のJw_cadのヘルプを参照してください。

## 書式と読取りの範囲

- Jw_cad同梱Sample.jwfと単位指定例はCP932で検査した。利用者のJWFには不完全なCP932名を含む場合もある。置換・補完・切捨てはしない。openの既定はstrict、明示errors="preserve"なら生バイト/不完全値を保持し、値の解釈は拒否する。UTF-8/UTF-16は明示指定で検査できるが、Jw_cadがその符号化を読めると確認した意味ではない。自動推測しない。
- `KEY = values`。半角スペースを数値区切りとする。同梱例にはタブもあり本Readerでは区切るが、Jw側の全ケースの受入れを保証しない。全角空白は数値区切りにせず診断する。
- `#`行は注釈、`END`以降は非活性。Sample冒頭ENDを削除したものと勝手に読み替えない。未記載は未指定であり、前回環境/プロフィール/JWW/既定値のいずれになるかを推測しない。
- 名前は半角カンマ区切り、空欄も保持。`LAYNAM_N=0`の空欄は無変更、1は無名指定。名前の途中のカンマにCSVの引用規則を推測適用しない。17欄超は図面との比較を未確定にする。
- 通常数値、16進bitパターン、`S_COMM_0`の群層16進やA0/2A用紙名、桁別の複数フラグが混在する。valuesは文字列、numberは明示base=10/16だけ。意味の未確認な値を汎用の浮動小数へ変換しない。
- フォントの `"$<ＭＳ ゴシック>` は通常の閉じた引用文字列ではない。先頭の引用符から行末を保持する。`#`を値の途中でコメント開始と推測しない。
- 重複キーの優先順位は未確認。勝手なlast-winsにせずgetを拒否、diffではambiguous_duplicate。未知キー/未知構文も診断し、他設定の読取りと区別する。
- `A-Read` / `A-Read0` が先頭10行にある場合は、編集後自動読込の指示として記録するだけで、本APIでは実行しない。起動時専用指定と手動読込みの違いもある。

## 使い方（読み取りだけ）

```python
from pathlib import Path
from jwwkit import JwfDocument, jwf_setting_catalog
from jwwkit import CadDocument

config = JwfDocument.open(Path("settings.jwf"), errors="preserve")
red = config.get("PCOLLOR_1").number(0)  # 先頭のR値。0始まり。
fields = config.get("PCOLLOR_1").values()
info = jwf_setting_catalog()["PCOLLOR_1"]  # 項目名と保存区分
other = JwfDocument.open(Path("other.jwf"))
changes = config.diff(other)
stored = config.compare_drawing(CadDocument.open(Path("drawing.jww")))
```

JWFの要約や差分は、業務名やパスを含むことがあるため、図面と同じ範囲で扱う。JSONに保存するときはensure_ascii=Trueで不完全CP932のsurrogate escapeを欠損せず記録する。

コマンドで調べる場合：`jwwkit inspect-jwf --source settings.jwf --other other.jwf --drawing drawing.jww --preserve-invalid --output new_report.json`。同名出力は拒否する。比較にSampleを使う場合は既定では適用0件同士の比較となる。END後の例を意図して参照するときだけ `--include-after-end` を指定し、既定値や有効環境と混同しない。

## JWW保存の区別と比較の意味

| 分類 | 例 | 確認範囲 |
|---|---|---|
| drawing_saved | LAYSCALE、LAYNAM_0〜F、MWIDE/MHIGH/MDIST/MPEN | 同梱説明と既存の確定JWW欄。縮尺0/既存データ群、空名/保護など、JWF適用には条件がある |
| drawing_saved_or_conditional | 表示/印刷色、線種、寸法設定、文字基準点ずれ | 同梱HelpがJWW保存と読込選択を説明。全ビットの保存位置/対照は未確定 |
| environment_behavior | キー/クロック割当、コマンド層切替、外部変形登録、入力時層色/幅/種、画面操作 | 環境動作の説明は確認。これらの値がJWW内に絶対存在しないことを全バイト対照で証明した区分ではない |
| mixed_or_control | S_COMM_*、MSET、MHEN等 | 保存される値/環境操作/適用制御が混在。一行全体を「JWWだけ/環境だけ」と断定しない |
| unresolved | その他未確定欄 | 未確定のまま返す。必要なら計画/承認後にネイティブ対照 |

compare_drawingで現在対応するのは文字種40欄、16群縮尺、群/層名、LCOLLOR_1〜8のRGB。RGBは確定したJWW palette COLORREFの下位R/G/Bと比較。LCOLLOR幅やPCOLLOR印刷値のJWW欄は未確定で、比較不能を返す。0/空欄は無変更条件でnot_applicable。名前の保護/260byte制限、占有群、実読込順をシミュレートしない。sameは「保存値/宣言欄が一致」であり、画面/印刷まで同じ有効環境を保証しない。not_comparable/unresolvedを一致数に加えない。

重要な依存：Sample S_COMM_8の第3欄（0始まり2）は寸法設定の保存/読込制御（十の位保存、一の位読込）。Help基本設定の「ファイル読込項目」は線色/線種/点半径、描画印刷状態、文字基準点ずれの取込みを選べると説明している。したがって**同じJWFを使うだけでは、開いたJWWの後の画面/印刷が同じと断定できない**。JWF→JWWとJWW→JWFの順序、起動時専用指定、プロフィール、フォント、プリンタ/Direct2Dも確認する。

## 採用した運用：AIは要約を参照し、目視は利用者の環境で行う

JWFとJWWの設定優先関係・未解析欄は未確定として扱う。本手順はJw_cadの環境へJWFを読込ませず、追加のGUI対照や再試行を自動で行わない。公開読取りAPIで確定した保存欄と未確定を区別する。

AIが図面を作成・編集するときは、ローカルの `AI_settings_summary.json` を前提とし、利用者が自身のJw_cad環境で最終の表示・印刷を目視確認する。利用者は要約と対応するJWFをローカル作業フォルダに用意する。

1. 要約の `source_sha256` と参照元JWFの実ハッシュを照合する。JWFが変わっていたら、古い要約を流用せず差を報告して要約を更新する。要約自体のSHAも図面の計画/実行記録に残す。既存safe_editがこのJSONを自動依存登録する機能は実装されていないため、記録を省略せず、同期機能があるように説明しない。
2. 要約の設定宣言と利用者確認の意図を分けて読む。例えば書込みレイヤを赤、他をグレーにする確認用運用もあるが、配布版の既定ではない。採用したJWFの前提を利用者に確認し、要素の保存線色番号へ一律に反映しない。
3. 位置・寸法は実寸mmを基本にし、対象群の実際の縮尺を読む。文字種番号・幅/高さ/間隔・字体、線色/線種/線幅は要約の前提と図面の保存属性の両方を確認する。文字幅等の紙面mmと実寸mmを混同しない。依頼/図面/要約が食い違うときは勝手に優先順位を決めず報告する。
4. 既存図面の編集は従来の対象一覧→計画JSON/SHA→利用者承認→実行→保存後読戻し/差分報告を守る。要約を使うこと自体は編集や環境適用の承認ではない。JWWの設定や全体ヘッダーを要約へ自動同期しない。
5. 利用者へ別名出力、変更要素数/内容、参照JWF/要約のハッシュ、使用した設定・未確定欄を渡す。見え方、印刷色、線幅、字体、寸法の最終確認は利用者の環境で行う。読み直しや属性監査が合格しても、同じ有効環境/同じ表示を証明したとはしない。

要約は未指定値/未知値を補う既定値表ではない。JWF由来の名前や業務情報も、図面と同じ範囲で扱う。不完全CP932、名前の欄数超過、フォント/描画方式/出力機器/読込順の未確定をそのまま報告する。既存のPDF自動検査・JWW全属性/DXF監査を行う場面では、従来の条件も維持する。

## JWF作成・書出しの設計記録

JWFの作成や書出しは未実装です。検討内容は[JWF作成・書出しの設計記録](https://github.com/tetsuo-m/jwwkit/blob/main/docs/design/jwf_writing_proposal.md)にあります。

## 根拠

- Jw_cadの付属ヘルプとSample.jwfを参照し、JWWへの保存に関する確認結果を分類した。
- 公式配布：https://www.jwcad.net/download.htm
- 公式サイトの相談記録（同梱説明との照合に使用）：https://www.jwcad.net/log/infox3/infox3-0707-12/thread10524.htm 、https://www.jwcad.net/log/consult2/consult2-0610-12/thread17978.htm 。主根拠は現地同梱Help/Sampleと実ファイル・確定JWW欄であり、古い掲示板だけで現行値を断定しない。

## 別PCでの個人設定の用意

参照JWFとAI_settings_summary.jsonは利用者がローカルに用意し、元JWFのSHAと要約の対応を確認する。JWF・要約・設定値・診断ログは図面と同じ扱いでローカルに保管する。ファイルの移動や変更があれば、採用する参照とSHAを利用者と確認し直す。印刷色の宣言だけから描画状態やJWW読込み時の優先関係を推測しない。
