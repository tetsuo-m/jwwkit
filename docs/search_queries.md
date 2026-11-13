# 条件を組み合わせて図面を検索する

検索は読取りのみ。既存の `find_entities(entity_type="LINE", layer=3)` はそのまま使える。戻り値は現在の公開要素番号のtupleであり、削除等で番号が変わった後に使い回さない。非表示要素も既定で含む。

次のコードは、任意の入力ファイル名を受け取る実行例である。文字・図形の内容をガイドへ転記する必要はない。`inspect_drawing`は検索だけ、`plan_search_move`は計画JSONを作って終了する。計画の内容とSHAを利用者にチャットで示し、承認を得るまで`execute_plan`を呼ばない。

```python
from jwwkit import CadDocument
from jwwkit.safe_edit import write_plan

LONG_SHAPES = {"all": [
    {"field": "layer_group", "in": [0]},
    {"field": "layer", "in": [3, 5]},
    {"field": "entity_type", "in": ["LINE", "ARC"]},
    {"field": "length", "min": 1000, "units": "real"}
]}

def inspect_drawing(source):
    cad = CadDocument.open(source)
    return {
        "long_shapes": cad.find_entities(query=LONG_SHAPES),
        "aw_texts": cad.find_entities(query={
            "field": "text", "match": "prefix", "value": "AW-"}),
        "marked_lines": cad.find_entities(query={"all": [
            {"field": "entity_type", "in": ["LINE"]},
            {"field": "flag_bits", "mask": 4096, "mode": "all_set"}]}),
        "horizontal_lines": cad.find_entities(query={
            "field": "line_angle", "min": 0, "max": 0,
            "units": "deg", "tolerance": 0.1}),
        "displayed_elements": cad.find_entities(query={"all": [
            {"field": "group_state", "in": ["display_only", "editable", "writing"]},
            {"field": "layer_state", "in": ["display_only", "editable", "writing"]}]})
    }

def plan_search_move(source, output, plan_path):
    cad = CadDocument.open(source)
    indices = cad.find_entities(query=LONG_SHAPES)
    if not indices:
        raise ValueError("対象が0件です。計画を作らず条件を確認してください")
    actions = [{"op": "move_entities", "indices": list(indices),
                "kwargs": {"delta": [10, 0], "units": "real"}}]
    return write_plan(cad, None, actions, output, plan_path, selection=LONG_SHAPES)
```

関数を読み込んだ後、`inspect_drawing("input.jww")`で一覧を確認する。計画は`plan_search_move("input.jww", "new_output.jww", "review.plan.json")`で作る。保存後の確認は、既存の`execute_plan`の実行記録と`new_output.changes.json`を使う。これらの呼出し・保存読戻しもテストと配布版の単独点検で実行している。実図面の編集は、実際の対象一覧・出力先・計画SHAの承認後に限る。

## 条件の書き方

- 一覧内のOR：`entity_type=["LINE","ARC"]`、`layer=[3,5]`等。群・層・種類・色・線種・保存ブロック名を一覧にできる。引数同士はAND、queryとの併用もAND。
- JSON：`{"all":[条件,条件]}`、`{"any":[条件,条件]}`、`{"not":条件}`を入れ子にする。空all/any/値一覧、不明キー、不明種類、NaN/Infinity、JSON文字列の重複キーは拒否する。Python式・eval・コールバックは使わない。
- 詳細結果：`cad.search_entities(query)`でinput_query/effective_query、hits、未判定理由、complete、規則版、実効制限を取得する。find_entitiesは未判定が残れば例外にする。適用外はNOTで一致へ反転しない。未判定が他条件の真偽に影響しなければ、ANDの不一致やORの一致は確定できる。

| field | 指定と範囲 |
|---|---|
| entity_type / layer_group / layer | `in`で種類／群0～15／層0～15。別の保存属性groupと混同しない |
| color / linetype | `in`に保存番号または完全一致SXF名。未定義・重複名は拒否。色番号は見かけのRGBではない |
| block_name | `in`と`name_kind:"stored"`または`"display"`。既定stored。既知の末尾印1～4だけを除去し、未知印はそのまま |
| text | `match:"contains"/"prefix"/"exact"/"regex"`とvalue。TEXTとDIMENSION内包文字を検索 |
| length / radius | min/maxと`units:"real"/"paper"`を必須指定。範囲は両端を含む |
| text_width / text_height | min/maxと`units:"paper"`。`basis:"effective"`既定、または`"stored"` |
| pen_width | min/maxと`units:"stored"`。保存欄の数値であり、有効印刷幅やmmには換算しない |
| rect | bounds:[xmin,ymin,xmax,ymax]、units:real/paper、mode:anchor/intersects/contained |
| flag_bits | mask:1～65535の整数、mode:all_set/all_clear。指定マスクの全ビットが立つ／全ビットが立たない条件 |
| line_angle | min/max、units:deg/rad、toleranceをすべて必須指定。0をまたぐ範囲だけwrap:true |
| group_state / layer_state | `in`に0/1/2/3またはhidden/display_only/editable/writing。保存状態を別々に比較 |

長さはLINEの線分長、真円CIRCLEの周長、真円ARCの弧長。radiusは真円CIRCLE/ARC。実寸は紙面値×要素の群縮尺で換算する。楕円の弧長・単一半径、未確認角度や退化円は未判定にし、円ソリッドへ自動拡張しない。寸法表示値をlengthと解釈しない。

文字の幅・高さは文字枠で、文字列の外形ではない。effectiveは文字種0の本文欄、文字種1～10の図面保存プリセットを使う。storedは本文欄を直接比較する。DIMENSIONも内包TEXTを同じ規則で読む。環境/JWFの未確定優先や字体の実外形は推測しない。linetypeは確認済みの線/円/円弧/ソリッド/寸法だけ。TEXTの基準位置・POINTの記号種・円ソリッドの塗りモードを線種とみなさない。

## 追加3条件の意味

flag_bitsは要素の外側の保存flagを、そのままuint16として読む。4096はJSONでの0x1000の表記。LINEの0x1000を建具候補に使う場合も、上例のようにLINE条件と組み合わせる。他種の同じビットを「建具」と名付けない。寸法内包のflagを勝手に集約しない。複数ビットの「どれか」は各ビットの条件をanyで組む。

line_angleは図面の実寸座標の＋X軸を0度、＋Y側へ反時計回り。正の等方群縮尺なので紙面から実寸への換算で方向は変わらない。端点を逆にした線も同じ向きとして0度以上180度未満（ラジアンは0以上π未満）へ折り返す。水平はmin=max=0、垂直はmin=max=90。toleranceも指定した角度単位で、0～90度相当を明示する。例の0.1度は単なる例で、APIの既定値ではない。min=175,max=5のような0度またぎはwrap:trueが必要。許容は指定した閉区間の両端からの最短角距離で広げる。ゼロ長線・非有限座標は未判定。円弧や寸法主線をLINEに見立てない。定義内では配置前のローカル軸に対する角度となる。

group_stateとlayer_stateは保存値を独立に比較する。群がhiddenでも、層自身はwritingの場合がある。実際に表示される状態を選ぶには上例のように群・層の両方からhiddenを除く。writing層はその群内の選択であり、群もwritingでなければ図面全体の現在書込み先とは限らない。保護設定を含めた編集許可を保証する検索ではない。

## 文字と正規表現

全角半角・大小は既定で区別し、width_fold:true／ignore_case:trueを明示した場合だけ同一視する。幅変換は全角ASCII/空白と半角カナの限定対応で、①を1にしない。通常検索の大小無視はcasefold、regexはre.IGNORECASE。元の文字は変更しない。

regexはre.searchとしてローカル子プロセスでコンパイル・一括照合する。inline flagsは拒否する。幅変換を使う場合もパターン自体は書き換えず、変換後の文字に対して利用者が書く。全角の記号を勝手にメタ文字へ変えない。

既定のregex_secondsは5、total_secondsは30。`limits={"regex_seconds":2,"total_seconds":10}`等で明示でき、正の値～30秒に限定する。子プロセスは起動込みの上限を超えれば終了・回収し、検索全体を失敗にする。部分結果は返さず、計画にも使わない。条件128ノード/深さ16、一覧1葉1024値/全体8192値、regex8個/各512文字、対象1文字列16384文字、regex合計800万文字を上限とし、超過時は切り詰めず拒否する。クエリの構造/文字量にも上限がある。

## 定義内と承認計画

scopeはdrawing既定。definitionsまたはdrawing_and_definitionsを明示すれば、未参照を含む各保存定義を1回ずつ検索する。結果はdefinition_numberとentity_pathで直下indexと区別する。定義内BLOCKは保存された参照として扱い、再帰的な世界座標展開は行わない。寸法内包は別hitにしない。

定義内は保存属性・ローカル紙面mmで、配置倍率やレイヤ優先を適用した見かけの属性ではない。定義を含む検索でreal単位を指定したら事前拒否する。定義内の編集対象をsafe_editへ渡すことはできない。

selection付きwrite_planはschema3になる。元JSON・実効JSON・規則/Unicode/regex版・時間と固定制限・名前の解決先・確定番号/元番号・各SHAを保存する。実行前に原本SHAと全対象を確かめ、同じ条件を再検索して完全一致しなければ停止する。編集後に再検索して対象を増やさず、既存の元番号追跡で処理する。schema1/2の旧計画はそのまま使える。queryを伴わない従来の計画はschema2のまま。

21万要素級では、読込み、検索、結果JSON、計画作成の時間を分けて判断する。設計時の見込みと実装後の実測は別物であり、条件数・文字量・PCによって変わる。検索自体のためにJw_cadを起動する必要はない。
