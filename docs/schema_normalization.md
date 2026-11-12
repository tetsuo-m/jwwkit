# レブロ出力の明示的なスキーマ正規化

対象は、観測済みv600/v700のCDataSen・CDataEnko・CDataMojiだけを持ち、全クラス宣言のschemaが0の図面。版を変えずschemaのWORDだけを600/700へ変更する。メモ・パレット・SXF名・状態記録・図形を補完しない。短い線の欠落など、元の書出しで失われたデータは戻らない。パレットは元の値を保持し、Jw_cadで保存し直した場合の環境パレット/メモ/SXF名/状態記録へ合わせない。元DXFの正しい色を復元したり、異なるPCで同じ見え方を保証したりする正規化ではない。

通常のCadDocument.openは設定を読まない。既定strict、schema_profile="rebro_schema0"の読取り/無編集保存専用の制限も従来どおり。通常の編集を行うには、以下の別名正規化を承認・実行した後、その出力をstrictで開く。既存の全要素/属性/版等の拒否条件は維持する。

作業フォルダのjww_workflow.tomlをUTF-8で明示的に読み込む。schema_version=2とし、[opening]のrebro_schema0を"reject"（既定）または"normalize"とする。careful/quickは正規化を有効にしない。チャットの指示>ファイル>reject。設定は許可を代替しない。

設定ファイルの例（作業フォルダ直下のjww_workflow.toml）：

```toml
schema_version = 2
[opening]
rebro_schema0 = "normalize"
```

次の手順例は関数を定義するだけで、勝手に正規化しない。prepare_normalizationの戻り値のplan全体、対象/不要の一覧、各SHA、変更宣言のoffset/before/after、出力先とplan_sha256をチャットで示して承認を得てから、run_normalization_approvedを別に呼ぶ。

```python
from pathlib import Path
from cad_model import CadDocument
from workflow_settings import load_workflow_settings, resolve_opening_settings
from normalization import (inspect_schema_normalization, write_schema_normalization_plan,
                           execute_schema_normalization_plan, normalization_edit_dependencies)
from safe_edit import write_plan

def prepare_normalization(work_dir, sources, output_dir, plan_path,
                          instruction_overrides=None, instruction_evidence=None):
    settings = resolve_opening_settings(
        load_workflow_settings(work_dir), instruction_overrides=instruction_overrides,
        instruction_evidence=instruction_evidence)
    return write_schema_normalization_plan(
        list(sources), output_dir, plan_path, opening_settings=settings)

def run_normalization_approved(plan_path, approved_hash):
    return execute_schema_normalization_plan(plan_path, approved_sha256=approved_hash)

def prepare_separate_edit(result_path, normalized_source, output, plan_path,
                          indices, delta_real_mm):
    dependencies = normalization_edit_dependencies(result_path, normalized_source)
    cad = CadDocument.open(normalized_source)  # 設定を読まず、通常のstrict
    actions = [{'op': 'move_entities', 'indices': list(indices),
                'kwargs': {'delta': list(delta_real_mm), 'units': 'real'}}]
    return write_plan(cad, list(indices), actions, output, plan_path,
                      dependencies=dependencies)
```

## 計画・実行の契約

- 正規化専用schema_version=6、kind=jww_schema_normalization、normalization_rule_version=1。safe_editの業務編集schema2～5とは別。approved_sha256は利用者が承認した計画ファイルのSHA256。計画の作成だけではJWWを出力しない。
- entriesは順序付き。status=normalizeが対象、status=not_neededは「正規化不要・出力なし」、output_name=null。標準図面も全体読込みと無編集バイト一致を確認してから不要と判定する。未知/壊れた非0スキーマを標準扱いしない。対象と不要の両方の原本SHA・判定・宣言を固定する。
- 不要の図面を含んでも残りを処理できる。全件不要ならnothing_to_normalize、JWW/出力フォルダは作らず実行記録だけ新規保存。不要ファイルをコピーしない。実行時に対象/不要を再分類して計画を書き換えない。SHA/判定の差は再計画・再承認。
- failure_policyはall_or_nothingだけ。対象外/検証失敗が1件でもあれば全件中止。一時領域で全対象を準備し、strict読込み・無編集保存のバイト一致・元との全要素欄/非schemaバイト一致を検証する。全入力を再確認して、新規1フォルダへまとめて確定する。
- Windowsの同一親フォルダ間の置換しない移動を使用する。既存の出力先・計画・実行記録・準備領域は拒否。親フォルダは事前に用意する。リンク/再解析ポイント・入力重複・出力名衝突も拒否。初版の確定処理はWindows専用。
- 成功フォルダには対象JWWと_normalization_manifest.jsonだけを入れる。manifestは全入力/不要一覧・宣言変更・各SHA・設定snapshot/計画SHAを持つ。外側の計画名.normalization-result.jsonに完了状態を記録する。実行時には設定ファイルを読み直さず、承認した原文/実効値/出所/SHAを使用する。
- NormalizationPlanError.diagnosticsは検査した全入力の理由。未知クラスでは検出済みの名前・schema・offsetを返す。先を走査して補完せず、enumeration_complete=falseと停止offset/未検査バイト数を表示する。検出一覧を全クラス一覧と呼ばない。
- NormalizationExecutionError.resultには失敗理由、published/verified、残存ファイルのパス/SHAがある。確定前の失敗では最終フォルダを公開せず、一時領域を証拠として残す。確定後の再検査/実行記録保存が失敗した場合は、出力済みである事実を報告して停止する。停電や他プロセスの競合まで戻せる仕組みではない。失敗後、残った出力を無条件で業務編集へ流さない。
- 1計画は最大256入力、1入力256MiB、合計512MiB、JSON8MiB。上限を超えた計画は分割して別に承認を得る。成功分だけの部分出力は未対応。

## その後の業務編集

prepare_separate_editは、成功した正規化計画/実行記録/manifest/全原本を検証して別の編集計画の依存SHAにする。新しい編集対象・変更内容・編集計画SHAを示して**別に承認**を得る。正規化の承認を編集やGUIの承認として使わない。現在の設定による再正規化や由来の自動生成は行わない。正規化不要の図面は元の標準図面を通常のstrictで扱う。

実サンプルでは、Rebro 2026 Rev.6 build0918.1310のv600/v700各1件（632図形）で、承認後の正規化と通常strict読込み/無編集保存の全バイト一致を確認した。別の承認済み編集計画で、既存線の層変更/層名変更、LINE/TEXT/SOLID追加後635件の全属性・非対象631件/他設定不変・CDataSolid含む全宣言が600/700で0混在なしを確認済み。この版/試料での観測を他の形式へ一般化しない。派生物は配布しない。GUI確認は未実施で別依頼まで保留。v6→Jw_cad10.03.7再保存は版700になっているため、v600のschemaだけ600にする直接の正解にはしない。利用者のJw_cad環境に由来する値を推測で生成しない。
