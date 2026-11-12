# 位置からの検索

不変のReadViewに対して `spatial_search.at_point` と `nearest` を使う。元図面や元モデルを編集しない。返す参照はそのビュー内だけの場所であり、図面間の対応キー・永続IDや編集承認ではない。

大きな図面では、種類・群・レイヤなどをqueryで絞り込んでから検索する。全体を検索すると未判定の文字・楕円等も対象に入り、走査を完了しても全体の最近要素や同距離候補を確定できないことがある。completeとunresolvedを必ず確認し、provisional_hitsを確定結果として使わない。絞込みは検索の対象範囲を変えるもので、対象外を含む図面全体の最近要素を証明するものではない。

## 実行例

次のコード全体を合成図面で実行するテストに登録している。input.jwwは任意のローカル入力へ置き換え、点と許容値は依頼に合わせて**毎回明示**する。以下の数字は業務図面へ自動適用する既定値ではない。

```python
import json
from read_view import create_read_view
from spatial_search import at_point, nearest

view = create_read_view('input.jww')
scope = {'field': 'entity_type', 'in': ['LINE', 'CIRCLE', 'ARC', 'POINT']}
on_point = at_point(view, [1000, 2000], tolerance=0.5,
                    units='real', query=scope, limit=50)
closest = nearest(view, [1000, 2000], tie_tolerance=0.001,
                  units='real', query=scope, limit=50)
with_text_frames = nearest(view, [1000, 2000], tie_tolerance=0,
                          units='real', text_mode='frame', mode='summary')
anchors = nearest(view, [1000, 2000], tie_tolerance=0,
                  units='real', target='anchors', mode='count')
with open('spatial_inspection.json', 'x', encoding='utf-8') as stream:
    json.dump(dict(on_point=on_point, closest=closest,
                   with_text_frames=with_text_frames, anchors=anchors),
              stream, ensure_ascii=False, indent=2, allow_nan=False)
```

## 距離と対象範囲

- units=real（既定）は実寸mm、paperは紙面mm。点、tolerance、tie_tolerance、max_distanceと返す距離は同じunits。ルートの群縮尺とブロック配置を共通形状と同じように適用する。
- at_pointは距離が明示したtolerance以下の全ルート。nearestは全対象の最小距離d_minに対して `distance <= d_min + tie_tolerance` の全候補。同距離候補を1件に絞らず、距離と公開番号の順で返す。許容内の候補同士を連鎖させて集合を広げない。どちらの許容も必須・有限・非負で、自動の図面用許容値はない。
- max_distanceを明示するとnearestの返却候補をその距離以下にも限定する。全対象での最小距離そのものはこの指定で書き換えない。max_distance内にない場合は空になる。
- LINEは有限線分（ゼロ長なら点）、POINTは幾何点、真円/円弧は曲線への解析的距離。円の中心やbboxへの距離で代用しない。破線の隙間、線幅、印刷状態のピクセル選択を再現するものではない。
- SOLIDは塗り領域、確認済み円板/弓形/円環も塗り領域の内部なら0。円環の穴は塗りではない。円弧は負の掃引・0度またぎ・傾き・反転と端点を考慮する。
- 現在の直下ルートを検索する。寸法/ブロックの部品が複数当たっても親は1候補、当たったchild_pathをmatched_partsに載せる。同じ定義の別配置は別候補。配置先のない定義単体の世界座標検索は公開しない。新しい入れ子の編集が許可される意味でもない。
- 非表示の群・層も既定で対象。queryに既存のJSON条件（群/層/状態/種類/保存flag/色・線種/文字/ブロック名等）を渡して限定できる。条件は直下ルートの保存属性を評価し、子のレイヤ等へ自動で条件を広げない。定義内の保存属性と配置先の有効属性は混同しない。

queryは既存の検索規則・正規表現の制限と時間切れ防御を使い、不変ビューの値から選ぶ。SXF名照合に必要な原ヘッダーバイトもビューへ凍結し、元ファイルがその後なくなっても読み直さない。text_width/height等の文字種解決も凍結した宣言を使う。basis=persistedなら元の値/設定から検索し、現在の新規ルートに保存時の値がなければ条件も未判定とする。削除済みルートの復元は行わない。

## 文字と未判定

既定のtarget=shape / text_mode=glyphでは、文字の字形への距離は未判定。text_mode=frameを明示すると、共通形状が確定できる通常文字の**論理文字枠の領域**への距離を使う。枠内は0で、distance_kind=text_frame_distanceとする。字形への距離ではない。複合要素はcomposite_shape_and_text_frame_distance等で区別する。

特殊/flag付き文字、保存線幅欄非0、終点不一致、文字制御、縦書き等、共通形状で枠が未判定になるものはそのまま未判定。フラグ付き文字にも、共通形状と同じ判定条件を適用する。楕円、未知属性/欠落/循環/上限の構造も推測しない。

target=anchorsを明示した場合だけ、保存された代表の基点1つへのanchor_distanceを使う。文字/線は始点、円・円弧・円ソリッドは中心、点は位置、ブロックは挿入点、寸法は有効線の始点、ソリッドは保存頂点1。これは形の最近点でも字形距離でもなく、未判定の形の代用品として自動使用しない。

## 結果の読み方

|欄|意味|
|---|---|
|confirmed_hits|条件と距離が確定し、今回の検索の一致が証明できた候補|
|provisional_hits|距離自体は既知でも、未知候補の影響で図面全体の最近とはまだ証明できない候補（nearest）|
|unresolved|距離やqueryでの対象資格が未判定の候補。理由と距離の下限/上限を残す|
|known_min_distance|確定した距離だけの最小値。全体最小とは限らない|
|minimum_distance|全対象の最小の確定値、または未判定と上下限。空範囲はempty|
|evaluation_complete / examined_count|選ばれた全ルートの距離を評価し終えたか／評価数|
|query_complete / selection_unresolved_count|対象資格に未判定が残っていないか／その数|
|complete|走査を完了し、対象資格・距離・部品詳細の未判定が残らないこと|
|total_hit_count|complete=Trueのときだけ全一致数。不完全時はnull|
|confirmed_hit_count / provisional_hit_count / unresolved_count|詳細を制限しても、評価済み範囲の各分類の件数|

例えば点まで10mmの線と、距離不明の楕円がある場合、線だけを全体最近と確定しない。既知最小10mm、全体の下限0/上限10mm、線はprovisional_hits、楕円はunresolvedとなる。

複合要素の一部だけ既知の場合、その部品への距離は全体距離の上限であり、確定距離へ昇格しない。既知部品まで0なら全体も0と証明できるが、未知の部品詳細はunresolvedへ残す。この場合、同じ親がconfirmed_hitsとunresolvedの両方に載り得るため、分類件数を足してルート数としない。minimum_distanceが0と確定しても、未判定の同距離候補が残ればcomplete=False。

## 上限・要約と性能

limitは既定100/最大1000で、confirmed_hits/provisional_hits/unresolvedの**各一覧**の上限。truncatedとreturned_countsを付ける。部品詳細は親ごとに一致/未判定各100件までで、全件数と切詰めを別に返す。mode=count/summaryは同じ全走査を行って件数・最小値・理由集計だけ返し、詳細を生成しない。要素番号や出力の丸め値で図面間の対応を作らない。

max_secondsは既定30/最大300秒の協調的な上限で、ルート間で確認する。準備/単一複合要素の計算の途中を強制終了するものではない。queryの正規表現には既存の別プロセス時間制限がある。時間切れはTIME_LIMIT、未走査数または対象総数不明を明記し、全体最近や総件数を断定しない。展開/深さ/線分のlimitsは共通形状と同じで、上限を緩める指定は拒否する。

初版は索引を使わず全件走査する（index_used=False）。bboxで未判定候補を落とす近道は入れていない。カーソルやオフセットによる検索の再開には対応していない。図面編集やGUI受入れはこの検索には含めない。
