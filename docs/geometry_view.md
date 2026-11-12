# 共通形状

不変のReadViewに対して `geometry_view` を呼ぶ。元図面を編集・保存せず、実寸mmは `units="real"`（既定）、紙面mmは `"paper"` を指定する。実寸はルートの群縮尺を適用し、ブロックの子は定義の紙面座標に配置・回転・倍率を順次合成する。子の保存群の縮尺は重ねて掛けない。要素番号はこのビュー内だけの番号であり、図面間のIDではない。

## 使い方

次は全コードを合成図面で実行するテストに登録している。`input.jww` を利用者のローカルのファイル名へ置き換える。既存の `geometry.json` は上書きしない。

```python
import json
from cad_model import CadDocument
from read_view import create_read_view
from geometry_view import entity_geometry, geometry_page, text_frame_distance

view = create_read_view(CadDocument.open('input.jww'))
first = entity_geometry(view, 0, units='real', text_mode='frame')
details = geometry_page(view, limit=2, text_mode='frame')
counts = geometry_page(view, mode='count')
summary = geometry_page(view, mode='summary', fields=['bbox'], text_mode='frame')
frame_distance = text_frame_distance(first, [0, 0])
with open('geometry.json', 'x', encoding='utf-8') as stream:
    json.dump(dict(first=first, details=details, counts=counts,
                   summary=summary, frame_distance=frame_distance),
              stream, ensure_ascii=False, indent=2, allow_nan=False)
```

`entity_geometry` は1要素、`child_path` は読取りビューと同じ寸法の `['line']` / `['text']`、参照の `['definition', 子番号]` 等を指定できる。子を引いてもルートからの配置を合成した座標を返す。mode0寸法の未使用補助欄を描画形状に含めない。`basis="persisted"` は現在のルートに対応する保存時のレコードを使い、新規要素なら未判定となる。削除済み要素を復元する指定ではない。

## 返す値と判定

形状の各欄は `status/value/reason/method` を持つ。`exact` は保存情報から解析的に確定、`approximate` は明示した誤差内の折線近似、`undetermined` は未判定、`not_applicable` はその量なし、`not_requested` は要求していない欄。`complete` は要求欄について判定できたかを示し、Jw_cadの画面のピクセルや文字の字形との一致を保証しない。

| 欄 | 意味 |
|---|---|
| kind | line / circle / arc / point / text / solid / circle_solid / dimension / block |
| bbox | `[xmin,ymin,xmax,ymax]`。線幅・点記号・字形のはみ出しを含めない幾何範囲 |
| segments | 始終点の線分一覧。曲線は明示したcurve_toleranceがある場合だけ近似 |
| contours | 開いた線、解析的な円・円弧、閉じた多角形、円環の穴等。全てが閉輪郭とは限らない |
| center | 中点、支持円の中心、多角形面積重心等。center_kindで区別。複合要素の一意な中心は返さない |
| representative_points | 始終点・中点・頂点・配置点等。point_kind/on_geometryで区別 |
| text_frame | 保存始点・終点・高さ・角度による通常文字の論理枠。字形外形ではない |
| glyph_bbox | 実際の字体の字形範囲。共通形状では未判定 |

既定のfieldsはbbox/contours/center/representative_points/text_frame。`fields=['bbox','segments']` のように絞れる。円弧のbboxは端点と区間内の座標極値で解析的に求め、折線近似から推定しない。曲線の線分が必要なら `curve_tolerance=0.01` 等を**利用者が指定**する（選択したunitsのmm）。矢高の上限・実際の上限を返し、segment上限超過時は黙って粗くせず未判定とする。

文字は既定 `text_mode="glyph"` では字形bboxを未判定とする。`"frame"` を明示するとbbox/輪郭/中心も文字枠のものになる。枠は既存の通常文字の終点規則で保存終点を照合し、確認済み字体・基準点・通常flagの範囲に限って返す。64 ULPの照合幅は浮動小数点演算用であり、図面の業務許容値ではない。文字種の保存サイズと宣言サイズが矛盾する場合、縦書き・寸法文字等の特殊flag、未確認字体・制御文字、非等方なブロック内の文字は未判定とする。

`text_frame_distance` は枠の**領域**への距離（内部は0）、`boundary=True` は枠の境界への距離。`distance_kind` はそれぞれtext_frame_distance/text_frame_boundary_distanceで、字形への距離とは別。枠が未判定なら距離も未判定。全要素の最近検索は位置検索で扱い、共通形状には含めない。

真円・円弧と確認済みの円ソリッド（円板・弓形・円環）は解析的に返す。楕円や円が非等方倍率で楕円になる配置は、中心だけ確定し外形等は未判定とする。多角形は保存頂点順1,3,2,4から単純な非ゼロ面積の輪郭を確認する。自己交差等を推測で補正しない。ブロックの循環・欠落・未確認参照属性、未知要素は未判定。ある子の範囲が不明な場合、既知の子だけのpartial_bboxを全体bboxとして扱わない。これらは読取り専用で、入れ子の新規作成など編集の拒否条件を変更しない。

## 件数と実行量

`geometry_page` のdetailsは既定100/最大1000ルートまで、total/returned/truncatedを返す。子はpartsに含まれ、ルート件数へ二重計上しない。countは形状計算なし。summaryは全ルートを順次評価し、判定別件数・未判定の理由を返す。`evaluation_complete` と `examined` を必ず確認する。時間上限（既定30秒、最大300秒）はルート間で確認する協調的な上限で、1つのルートの計算中に強制終了するものではない。上限で残りを計算できなければTIME_LIMITと未完了を明記する。未判定0を意味するdetermination_completeとは区別する。

1ルートあたりmax_segments=10000、max_children=100000、max_depth=64を既定の上限とし、limitsでは小さくする指定だけ受ける。件数上限はJSONバイト数や厳密なRAM上限ではない。別プロセスの続き取得・カーソル・offsetは**今回作らない**。背景は[ページ継続の検討](design/read_view_continuation.md)を参照。

## 保存値・意味値・表示値

保存値は読取りビューの `storage.persisted_record`（元レコード）、現在の値は読取りビューのvalues等で読む。共通形状はそこから群縮尺と配置を適用した**意味としての幾何値**を返し、単位と計算根拠を明記する。人に見せる丸め・単位付き表現は読取りビューのdisplay/propertiesや利用側で作り、丸めた表示値を形状計算に戻さない。読取りビューの未計算bboxを書き換えたり、保存された値を共通形状の近似値に置き換えたりしない。名前はkind/bbox等を採用するが他ライブラリとのJSON互換を意味しない。
# 文字終点の数値比較

通常文字枠の既知終点を比較する丸めガードは、ローカル紙面の文字長Lと座標桁Mに対しmax(64*ulp(M), 1e-9*L)。図面の寸法誤差の許容ではない。群縮尺と等方なブロック配置倍率で実寸換算したガードが1e-4mm以上なら未判定とし、上限へ切り詰めない。紙面/実寸の出力指定で判定を変えず、元の終点も補正しない。特殊flag・保存線幅・文字種の条件は維持する。

