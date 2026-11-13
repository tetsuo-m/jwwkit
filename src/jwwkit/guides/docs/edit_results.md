# 編集結果の共通形（CadDocument31メソッド）

従来のCadDocumentの戻り値と例外、safe_edit.execute_planの結果は変えない。共通結果が必要な場合だけedit_resultの新しい窓口を使う。直接編集する承認不要の入口は追加しない。元図面を上書きせず、具体的な計画とSHAをチャットで示し、利用者承認後に実行する。

```python
from jwwkit import CadDocument
from jwwkit.edit_result import write_edit_plan, preview_plan_result, execute_plan_result

def prepare_move(source, output, plan_path, indices, delta_real_mm):
    cad = CadDocument.open(source)
    actions = [{'op': 'move_entities', 'indices': list(indices),
                'kwargs': {'delta': list(delta_real_mm), 'units': 'real'}}]
    return write_edit_plan(cad, list(indices), actions, output, plan_path)

def inspect_plan(plan_path, plan_sha):
    return preview_plan_result(plan_path, plan_sha256=plan_sha, mode='summary')

def run_approved(plan_path, approved_hash):
    # approved_hashは、この計画の一覧をチャットで示し承認を得た後に渡す。
    # EditExecutionErrorが出たら、その.resultを報告して処理を止める。
    return execute_plan_result(plan_path, approved_sha256=approved_hash)
```

prepare_moveは計画JSONだけを書き、図面は保存しない。戻ったplan.path/sha256と、計画内の全対象・操作・出力を示して承認を得る。status=plannedのprojected_countsは見込みであり実施件数ではない。inspect_planはSHAが一致する計画の読取り/試行だけで、実行の承認にはならない。

write_edit_planはcommon_result=Trueのsafe_edit計画schema5を作る。CadDocument31メソッドだけの許可表を持ち、任意メソッド名・任意Pythonを実行しない。未編集のファイル由来CadDocumentと従来の対象/依存/全属性検査が必要。JwwDocument・LegacyDocument・place_jws・GUIはこの窓口の対象外。

旧計画schema1～4でも31メソッドの範囲ならexecute_plan_resultで共通結果を受け取れる。既知のworkflow付きschema4も既存の完全監査を維持する。新しいschema5を従来execute_planへ渡した場合は拒否し、共通結果窓口へ案内する。schema5とworkflowの同時計画作成は拒否し、既存schema4を共通結果で実行する。旧計画の内容や承認SHAは書き換えない。

## 結果

- schema_version/operation/status/phase：planned/applied/unchanged/rejected/failed、plan/memory/saved/verifiedを区別する。各操作はメモリ段階、全体は保存/読戻しが合格して初めてverifiedとなる。
- counts：added/modified/deleted/rejected/unchangedは図面直下の要素数。定義の子を直下要素として重複計上しない。新しい要素のsource_index=Noneが複数あっても、操作内の位置でそれぞれ数える。
- resource_counts：definitions/groups/layersを別集計。群の名前/縮尺/状態と、各レイヤの名前/状態を分離する。定義は日時を含む保存レコードの全欄で比べる。
- changes：before_index/after_index、前後の内容、resource_type。source_indexや番号は同じ取引内の追跡用で、別図面の対応付けや永続IDではない。
- rejections/rejected_operation_count：拒否された操作と理由。counts.rejectedは特定できる既存対象数、対象を特定できなければnull。新規追加の拒否はrejected_addition_count、資源はresource_rejectionsへ分ける。
- warnings/warning_count/warning_codes：群縮尺の変更で実寸が変わること、destination設定方針、既知の定義内flag2正規化等の注意。error_summaryはcount/summaryでも拒否理由を示す（長大な文面は4096文字まで、切詰めを明示）。
- before_model_sha256/after_model_sha256：現在の要素・定義・群/層・metadata等を含むモデル監査値。原本ファイルのSHAとは別。approval_plan_sha256で承認した計画を識別する。
- operation_data：必要な場合の旧戻り値のJSON表現。operation_totalsは操作別合計、最上位countsは元図面からの純変更。追加→変更→削除等では一致しないことがある。

operation_countはCadDocumentメソッドの呼出し件数、action_countは計画の行数。1行が複数対象へ単体メソッドを呼ぶ場合は異なる。試行ではprojected_operation_totals、破棄されたメモリ処理ではstaged_operation_totalsを使い、実施済みの合計と混同しない。

ブロック置換は従来の取引追跡に合わせ、先頭対象のsource_indexを参照が引き継ぐため変更1、残りの対象は削除として数える。定義追加は別。内容ハッシュの一致で別の要素を勝手に同一視しない。

## 原子的な処理と失敗

モデルと引数をコピーしたステージ上でメソッドを呼び、保存前検証まで通った場合だけその取引内へ反映する。呼出し元のモデルや要素リストを途中で変更しない。既知のValueError/TypeError/IndexErrorによる拒否は、元の文面と型を保ってrejectedへ写す。許容超過をpassed=Falseで返す位置合わせも拒否とする。

予期しない不具合、読書き、監査、保存後の検査失敗はEditExecutionErrorとして再送出し、.resultに証拠を付ける。例外を無視して次の操作へ進めない。途中で拒否された計画は、前のメモリ操作も取引として破棄し、prior_operations_discarded/各操作のdiscardedを示す。前の操作のメモリ件数を、保存済みの変更数と呼ばない。

成功時は別名JWW・従来.changes.jsonに加え、同じ出力名の.edit-result.jsonを新規保存する。入力/依存/計画/設定と重なる場合、または既存ファイルがある場合は事前に停止する。報告書だけの保存が失敗しても例外で止まり、既に検証済みの図面と未検証の残存ファイルを区別してfiles_createdへ残す。失敗ファイルを自動削除せず、原本を変更しない。

## 詳細の上限

limit既定100/最大1000、mode=details/summary/count。見込み/実件数は全対象を検査した集計であり、詳細の切詰めと別。changes/operations/拒否/注意にtotal/returned/truncatedを付け、1一覧の詳細JSONは最大1MiBとする。巨大な1件が枠に収まらなければ省略を明示する。count/summaryでは詳細・operation_dataを返さないが、件数・ハッシュ・検証・error_summaryは残す。別プロセスの続き取得やnext_cursorは作っていない。

完全なステージ検証のため内部ではモデルを複製する。件数だけの指定が処理を省略する意味ではない。大図面での速度/メモリ保証はしていない。diff_reportは同じ元の編集追跡、群不変監査は対象外の保全、図面比較は独立図面の意味照合として使い分ける。

全31メソッドの一覧は[common_edit_result_coverage.md](common_edit_result_coverage.md)、関数引数は[api_list.md](api_list.md)。
