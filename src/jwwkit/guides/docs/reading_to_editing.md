# 読取り・形状・検索から承認付き編集へ

この例は、指定群のAW文字を確認して一括移動する依頼を扱う。文字の揺れを許す検索、同じ不変ビューでの形状と距離の確認、原本を開き直した承認計画、保存後の共通結果を順につなぐ。ローカルの `input.jww` 等を差し替えて使う。

AIは、利用者から頼まれた作業に必要な範囲で図面を読んでよい。図面の文字・形状・画像・名前・パスと、図面から作った計画、結果、集計、画面画像は、同じ作業の会話内で扱う。利用者が明示的に指示した場合を除き、これらをウェブ検索の語句に使ったり、外部サイト・API・他サービスや第三者へ送ったり、公開リポジトリやIssueに載せたりしない。会話では件数や要約を優先し、全文の一覧などは利用者に求められたときだけ示す。計画・結果ファイルにも図面の内容が含まれるため、図面と同じ扱いでローカルに保管する。

|段階|使う入口|次の段階へ進む前の確認|
|---|---|---|
|開く|CadDocument.open|通常strict。レブロschema0は先に別承認で正規化する|
|値を固定する|create_read_view|保存値/現在値・意味・表示を区別。同じビューの番号を使う|
|形を調べる|entity_geometry / geometry_page|文字枠と字形を区別し、status/未判定理由を残す|
|位置を確かめる|at_point / nearest|範囲・単位・明示許容、completeと同距離の全候補を確認|
|文字を探す|CadDocument.search_entities|表記揺れはnormalizationを明示。保存本文は変更しない|
|変更を計画する|write_edit_plan|原本を開き直し、同じJSON条件をselectionに固定。全対象とSHAをチャットへ示す|
|承認後に実行する|execute_plan_result|承認したSHAだけを渡す。保存/読戻し後のphase/counts/資源差を報告|

位置検索は、この例では文字の配置を確かめるために使う。編集対象は同じ群のAW文字全件であり、最近の1件へ勝手に絞らない。位置による選択を編集条件に加えるときは、対象と根拠を別途計画で示す。旧ビューの参照を直接編集指示として使わない。

```python
from jwwkit import CadDocument
from jwwkit.read_view import create_read_view
from jwwkit.geometry_view import geometry_page
from jwwkit.spatial_search import nearest
from jwwkit.edit_result import write_edit_plan, execute_plan_result

def aw_condition(group):
    return {'all': [
        {'field': 'layer_group', 'in': [group]},
        {'field': 'entity_type', 'in': ['TEXT']},
        {'field': 'text', 'match': 'prefix', 'value': 'aw-',
         'normalization': {'width': True, 'case': 'unicode_casefold',
                           'spaces': 'ignore_listed', 'hyphens': 'dash_only'}},
    ]}

def inspect_local(source, point_real, *, group, tie_tolerance, detail_limit=20):
    cad = CadDocument.open(source)
    view = create_read_view(cad)
    query = aw_condition(group)
    text_matches = cad.search_entities(query)
    return {
        'source_sha256': view.source_sha256,
        'summary': view.summary(),
        'details': view.entities(limit=detail_limit),
        'geometry': geometry_page(view, mode='summary', fields=['bbox'],
                                  units='real', text_mode='frame'),
        'closest': nearest(view, point_real, query=query, units='real',
                           text_mode='frame', tie_tolerance=tie_tolerance,
                           limit=detail_limit),
        'text_condition': query,
        'text_match_count': text_matches['match_count'],
        'text_search_complete': text_matches['complete'],
    }

def prepare_change(source, output, plan_path, *, group, delta_real_mm):
    cad = CadDocument.open(source)  # 旧ビューではなく原本を再確認
    query = aw_condition(group)
    matches = cad.search_entities(query)
    if not matches['complete']:
        raise ValueError('文字検索が未完了です。計画を作らず理由を報告してください')
    indices = [hit['index'] for hit in matches['hits']]
    if not indices:
        raise ValueError('対象0件です。条件を確認してください')
    actions = [{'op': 'move_entities', 'indices': indices,
                'kwargs': {'delta': list(delta_real_mm), 'units': 'real'}}]
    return write_edit_plan(cad, indices, actions, output, plan_path,
                           selection=query)

def run_approved_change(plan_path, approved_hash):
    return execute_plan_result(plan_path, approved_sha256=approved_hash)
```

inspect_localは読取りだけ。detail_limitはビュー詳細と位置候補それぞれの上限で、形状summaryは全ルートを評価する。文字検索の対象はこの例ではTEXTだけ。寸法内文字も対象にする場合はentity_typeの範囲を依頼に合わせて変え、条件そのものをレビューする。

prepare_changeは計画と見込みだけを返す。plan.path/sha256、全対象、移動量、単位、queryと採用した表記揺れの規則をチャットで示して承認を得る。run_approved_changeはその承認後の別の呼出しにする。結果のstatusがapplied/unchangedかつphase=verifiedかを確認し、countsのadded/modified/deleted、resource_counts、warnings/rejectionsを報告する。メモリ段階やprojected_countsを保存済みの結果と呼ばない。EditExecutionErrorでは.resultの保存済み/残存物も報告して停止する。

## 文字枠の数値誤差と未判定

文字枠は保存された始点・終点・高さ・角度から決まる論理枠で、字形の輪郭ではない。通常文字の終点比較は、紙面の文字長Lと座標桁Mに対するmax(64×ulp(M), 1e-9×L)という数値丸めのガードを使う。実寸に換算したガードが1e-4mm以上なら未判定とし、上限への切詰めや元終点の補正はしない。図面の寸法許容や位置検索のtoleranceへ転用しない。検証済み文字249件の丸め差を解消し、従来の確定を保ち、0.01mmの実際の差は拒否する試験済み。特殊flag/保存線幅/未確認字体等の未判定条件はそのまま。

nearestのtext_mode='frame'は文字枠への距離。字形への距離を求めた結果として説明しない。未知候補が残るとき、confirmed/provisional/unresolvedを区別し、未判定を無視して全体の最近要素を確定しない。大図面は種類・群・レイヤで対象範囲を絞る。

## 表記揺れは検索時の明示指定

既定は原文どおり区別する。幅、大文字小文字、空白、ハイフンの同一視は承認済みの[対応表](text_equivalence.md)を指定した場合だけ。長音「ー」まで同一視するのは別の明示オプションで、上例のdash_onlyには含めない。保存本文や文字位置を変更する機能ではない。既存width_fold/ignore_caseとnormalizationを重ねて指定したり、任意の文字を推測で同一視したりしない。

## 詳細の上限、件数、要約の使い分け

|対象|詳細上限|件数だけ/要約|未完了・切詰めの判断|
|---|---|---|---|
|ReadView.entities|limit既定100、最大1000|mode=count/summary|total/returned/truncatedとdetails_omitted。列挙完了は形状確定ではない|
|geometry_page|limit既定100、最大1000|countは幾何計算なし、summaryは全ルート評価|evaluation_completeとdetermination_completeを分ける。時間切れと未判定も別|
|位置検索|各候補一覧にlimit既定100、最大1000|mode=count/summary|complete、confirmed/provisional/unresolvedとtruncatedを別に見る|
|共通編集結果|limit既定100、最大1000、1詳細一覧最大1MiB|mode=count/summary|全対象の件数と詳細省略を分離。summary/countでも拒否理由を報告|
|JSON条件検索|total_seconds/regex_secondsと条件構造の制限（詳細件数limitなし）|上例ではmatch_countだけ返す|complete=falseや未完了の対象を編集へ流さない。limitを持つ他APIと混同しない|

文字検索は完了したヒットを全件返し、limit/countモードは持たない。上例は表示する値をmatch_countに絞ったもので、検索自体の件数計算を省略しない。

件数上限を指定しても入力ファイルの読込みや全件の監査を省略するとは限らない。大きい結果はまずcount/summary、次に必要な範囲のdetailsを読む。承認計画の対象一覧は切り捨てない。実時間/RAM/JSONの一律上限や、API間で共有されるページ番号は提供しない。

別プロセスの続き取得やcursorは追加していない。SHA＋保存番号＋子経路のファイル参照は同一SHAのファイルを引き直すためだけで、編集/版の変更や図面間の対応付けには使わない。
