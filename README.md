# jwwkit

**既存のJw_cad図面（.jww）を、壊さずに読み書きするためのPythonライブラリ**

jwwkitは、Jw_cadの図面ファイル（JWW形式）をPythonから読み込み、編集し、保存するためのライブラリです。
いちばんの特徴は、**既存の図面を、触っていない部分を一切変えずに編集できること**です。
何も編集せずに保存すれば元のファイルとバイト単位で一致し、線を1本動かしても、それ以外の要素はそのまま残ります。

日本中の設計事務所や現場には、Jw_cadで描かれた膨大な図面があります。
jwwkitは、それらの図面資産を、AIやプログラムから安全に扱えるようにするために作りました。

> **非公式ツールです。** jwwkitはJw_cadの作者とは関係のない、個人による非公式のライブラリです。
> **jwwkitについて、Jw_cadの作者の方々へ問い合わせることはお控えください。**

---

## できること

- **読み込み**：線・円・弧・点・文字・ソリッド・寸法・ブロックなどの要素と、レイヤ・グループ・縮尺・線色・線種などの属性の取得
- **既存図面の安全な編集**：要素の移動・複写・回転・反転・拡大縮小・属性変更・削除・追加、レイヤ名・グループ名・縮尺・表示状態の変更など。編集していない要素は変わりません
- **登録図形（JWS）**：登録図形（230〜700形式）の読み込みと配置
- **ブロック**：ブロック定義の読み込み、作成、配置、既存要素のブロック化と置換
- **グループ（レイヤグループ）ごとの縮尺**に対応（実寸mm・紙面mmの両方で指定可能）
- **大きな図面**：65,535要素を超える図面に対応
- **SXF拡張線色・線種**：読み取り、検索、属性変更などの編集
- **別の図面からのグループの取り込みと、2点による位置合わせ**：建築図だけを新しいものに差し替え、設備のグループはそのまま残す、といった使い方ができます
- **図面どうしの比較**：設計変更の前後などで、追加・削除・属性の変化・文字の変化を一覧にします
- **条件検索**：AND/OR/NOT、属性のフラグ、線の向き、長さ・半径、表示状態、文字の前方一致・正規表現、全角半角などの表記揺れ（指定した場合のみ）
- **形状と位置からの検索**：要素の外形・中心・文字枠の取得、指定した点の近くにある要素・最も近い要素の検索
- **Jw_cadの環境設定ファイル（.jwf）**の読み取りと比較
- **他のCADが出力したJWW**：TFAS 14eの出力はそのまま、Rebroの出力は対象のクラス宣言欄の明示的な正規化の後に扱えます
- **AIに使わせるための安全な編集手順（safe_edit）**：「計画 → 確認・承認 → 実行」の2段階で編集し、意図しない変更を防ぎます。編集の結果は、追加・変更・削除・拒否・注意を共通の形で返します
- **AI向けの利用ガイド**：AIエージェントにこのライブラリを使わせるときの手引き（`AGENTS.md` と `docs/usage_guide.md`）

## できないこと・対応していないこと

- Jw_cadの全機能・全データの完全な再現は保証しません。未対応の構造を見つけた場合、jwwkitは**推測で処理せず、エラーとして止まります**
- 新しい図面をゼロから作図する機能や、DXFなど他形式への変換は主な目的ではありません（DXFへの変換は [ezjww](https://pypi.org/project/ezjww/) が得意です）
- 動作確認はJw_cad 10.03系で行っています。それ以外の版で保存された図面では、未対応の形式として読み込みを拒否することがあります
- 対応する形式はJWWのv600/v700です。それより古い版のJWWと、DOS版のJWCには対応していません
- 画像を含む図面は、画像をそのまま保持して保存できますが、画像そのものの編集はできません
- 縮尺の異なるグループへ、文字種の付いた文字・寸法を取り込む操作は、拒否します
- 新しい入れ子のブロック（ブロックの中のブロック）は作成できません
- 特殊な属性の付いた文字（寸法の値の文字など）は、文字枠を「未判定」として扱います
- Rebroが出力したJWWは、そのままでは開けません。明示的な正規化を行ってから使ってください。正規化では、Rebroの書き出しで欠けたデータ（短い線など）は戻りません
- Windowsで動作を確認しています。一部の機能（正規化の出力の確定など）はWindows専用です

## 必ずお読みください

- **編集する前に、必ず図面のバックアップを取ってください。** jwwkit自身も、元のファイルへの上書き保存はしません（別名でのみ保存します）。
- 編集結果は、Jw_cadで開いて目視で確認してから使ってください。
- AIサービスに図面を読ませると、図面の内容がそのAIの提供会社に送られます。業務の図面で使う前に、所属先や発注者の決まりを確認してください。
- jwwkit自体はインターネットへの通信を行いません。
- 本ライブラリは無保証です（MITライセンス）。図面の破損や、編集結果による損害について、作者は責任を負いません。
- AIに使わせる場合、図面の中の文字・レイヤ名などは「データ」であり、AIへの指示ではありません。図面の中に指示のような文字が書かれていても、AIがそれに従わないよう、利用ガイドに注意を記載しています。

## インストール

WindowsのPython 3.14で動作を確認しています。リポジトリを取得したフォルダで、PowerShellから次を実行します。

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -B tools/check_installation.py
```

最後の確認で `passed: true` と表示されれば、導入は完了です。

- 公開フォルダの確認環境：Windows、Python 3.14.10。依存パッケージの対応条件は配布元を参照してください
- 依存ライブラリ：ezjww 0.2.13（版を固定しています）

次の版（0.2.0）でpipでインストールできるようパッケージ化を予定しています。その際にimportの書き方が変わります。

## 使い方

```python
from pathlib import Path
import sys
sys.path.insert(0, "src")  # リポジトリのフォルダで実行する場合
from cad_model import CadDocument

# 図面を読み込む
drawing_dir = Path("../drawing-work")  # ライブラリの外にある作業フォルダに置き換える
doc = CadDocument.open(drawing_dir / "sample.jww")

# 全体の要約（要素数、種類ごとの数、グループ・レイヤごとの内訳など）
summary = doc.summary()
print(summary["entity_count"], summary["by_type"])

# グループ0の線を探して、属性と座標を見る
for i in doc.find_entities(entity_type="LINE", layer_group=0):
    e = doc.entities[i]
    print(i, e.attributes["layer"], e.attributes["pen_color"], e.geometry)

# 何も編集せずに別名で保存すると、元のファイルとバイト単位で一致します
doc.save(drawing_dir / "sample_copy.jww")
```

サンプル図面は、今後追加する予定です。それまでは、ご自身で作成した図面でお試しください（業務の図面を使う場合は、必ずバックアップを取ってから）。

AIに既存図面の編集を頼む場合、AIが示す計画の内容とSHA256を確かめ、会話で了承を伝えてください。元図面の上書きはできないため、編集結果は別名で保存します。空テンプレートから新規作図を頼む場合は、先に作る内容と保存先を確認します。詳しくは [AGENTS.md](AGENTS.md) と [利用ガイド](docs/usage_guide.md) を参照してください。関数の一覧は `docs/api_list.md` にあります。

## 検証について

jwwkitは、業務で安心して使えることを目標に、一つひとつ検証しながら作りました。
無編集保存でのバイト一致、編集後にJw_cadで開いて再保存できること、DXF・PDF出力での照合など、検証の方法と結果は [VERIFICATION.md](VERIFICATION.md) にまとめています。

## 作った人について

電気設備の設計者が、日々の業務を楽にしたいという動機から、AIと一緒に作りました。作者はプログラマーではありません。
JWW形式は、公開されているファイル形式の資料と、自作の図面の解析、Jw_cad本体で保存した結果との照合をもとに読み解いています。実務の図面は検証にのみ使い、公開していません。
図面のヘッダーの読み取りと、独自の読み取り結果の照合には、[ezjww](https://pypi.org/project/ezjww/)（MITライセンス）を利用しています。
Jw_cad本体や付属ファイルは含んでいません。ライブラリの確認用に、図形のない空テンプレートを収録しています。

## サポートについて

- 不具合や危険な動作は、[非公開の報告手順](SECURITY.md)に沿って報告してください。改善要望はGitHubのIssueで受け付けます。
- 返信は不定期です。すべての要望に応えられるとは限りません。
- 報告や要望に図面は添付しないでください。

## 関連プロジェクト

JWW形式を扱うオープンソースには、ほかにも次のようなものがあります。目的に合わせて選んでください。

- [ezjww](https://pypi.org/project/ezjww/) — JWWの読み込み・新規作成・変換に強いライブラリ（Rust製、Python・TypeScriptから利用可能）。jwwkitも内部で利用しています
- [zumen](https://pypi.org/project/zumen/) — SXF・JWW・DXF・DWGを読み込み、表示・比較・変換するライブラリ（Rust製、Python・ブラウザから利用可能）

## ライセンス

[MIT License](LICENSE) · [第三者のデータと依存ライブラリ](THIRD_PARTY_NOTICES.md)

「Jw_cad」は、その作者の方々に帰属する名称です。
「Rebro」と「TFAS」は、それぞれの権利者に帰属する名称です。

---

## English summary

jwwkit is an unofficial Python library for reading and **safely editing existing Jw_cad (.jww) drawings** without altering untouched elements (a no-edit save is byte-identical to the original). It supports registered figures (JWS), blocks, per-group scales, drawings with more than 65,535 elements, SXF extended line colors/types, importing layer groups from another drawing with two-point alignment, drawing comparison, structured search, and a two-step plan/approve/execute editing workflow designed for AI agents. It is tested on Windows with Python 3.14 and Jw_cad 10.03.6, and uses ezjww (MIT) for header reading and cross-checking. Not affiliated with the authors of Jw_cad — please do not contact them about this library. Always back up your drawings before editing.
