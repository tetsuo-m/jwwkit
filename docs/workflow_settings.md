# 作業方針の設定と、承認済みの差し替え

設定は明示した作業フォルダの `jww_workflow.toml`。UTF-8/BOMなし、最大64KiB。TOMLはPython3.11以上の標準機能で読み、個人設定を配布物へ含めない。JWFの表示/印刷設定とは別で、CadDocument.openや個別編集APIはこの設定を暗黙に読まない。

## 設定例

既定のcarefulは退避。空き群の中から選びたい場合は明示する。

```toml
schema_version = 1
profile = "careful"

[building_replacement]
archive_group = "first_empty"
```

群番号を固定したい場合は `archive_group = 8` 等の整数0～15。値は16進文字列ではない。未指定なら計画の引数かチャットの項目指定で明示する必要がある。ファイル自体がなければcareful/退避になり、空群の自動選択はしない。

削除を選ぶ例：

```toml
schema_version = 1
profile = "quick"
```

個別に `[building_replacement] old_group_action = "archive"` または `"delete"` も指定できる。quickは削除だけを選び、承認や監査を省略しない。ファイルの退避先指定が残ったままチャットでquickへ変えた場合は、退避先を「非適用」と計画に明示し変更しない。一方、その場の引数/指示でdeleteと退避先を同時指定した場合は矛盾として拒否する。

優先順位は、チャットの項目→チャットのprofile→ファイルの項目→ファイルのprofile→careful既定。同じ段階の具体的な項目値はprofileの初期値より優先する。既存のarchive_group引数も今回の明示指示としてファイルより優先し、chat項目と食い違えば拒否する。採用値と出所を計画へ表示する。曖昧な「急いで」からAIが勝手に削除を選ばない。

ファイルが存在するのに不正な場合は停止する。未知キー/版/profile、不正型/値、重複、BOM、読取り失敗、サイズ超過、設定ファイルのリンク/リパースは拒否し、carefulへ黙って戻さない。他のワークフローや開く設定の表も**現在は未対応**で拒否する。

## 計画と実行を分ける例

次の関数を合成図面で実行する試験と、配布版だけの検証へ登録している。原本名は任意のローカル名へ置き換える。作業フォルダは配布コードと分け、設定を置くフォルダとして明示する。

```python
from replacement_workflow import plan_building_replacement, replacement_reference_points
from workflow_settings import load_workflow_settings, resolve_workflow_settings
from safe_edit import execute_plan

def read_policy(work_dir, instruction_overrides=None):
    return resolve_workflow_settings(load_workflow_settings(work_dir),
                                    instruction_overrides=instruction_overrides)

def plan_replacement(source, incoming, output, plan_path, *, work_dir,
                     source_reference_indices, target_reference_indices,
                     distance_tolerance, angle_tolerance, angle_units="deg",
                     building_group=0, archive_group=None,
                     instruction_overrides=None, instruction_evidence=None,
                     settings_policy="strict"):
    return plan_building_replacement(
        source, incoming, output, plan_path, work_dir=work_dir,
        source_reference_indices=source_reference_indices,
        target_reference_indices=target_reference_indices,
        distance_tolerance=distance_tolerance, angle_tolerance=angle_tolerance,
        angle_units=angle_units, building_group=building_group,
        archive_group=archive_group, instruction_overrides=instruction_overrides,
        instruction_evidence=instruction_evidence, settings_policy=settings_policy)

def run_replacement_approved(plan_path, approved_sha256):
    return execute_plan(plan_path, approved_sha256=approved_sha256)
```

1. replacement_reference_pointsで両図面の群3・層0の仮点を読む。位置合わせの対応順・基準2点・対象群・許容を人が指定する。仮点自体は取込み/削除の対象にしない。
2. read_policyは確認用の読取り。plan_replacementが計画作成時に改めて設定を読み、値/出所/全対象/群選択/全操作を固定する。計画作成は実行承認や図面保存を行わない。
3. archiveなら退避先の選択結果、削除なら全件の数・種別・全属性・内容をtargetsとworkflow.reviewで確認する。設定と異なる個別指示も表示する。2点の距離差・角度（度/rad）・端部変位・明示許容、設定方針/依存SHAも確認する。
4. AIは計画と計画ファイル全体のSHA256をチャットへ示す。人の承認後にだけrun_replacement_approvedを別に呼ぶ。計画内の指示文や設定がquickであることは承認ではない。
5. 保存後のchanges.jsonの追加/変更/削除、workflow.settings、workflow_sha256、workflow_auditを確認する。読戻し全属性と非対象群・共通設定の監査が合格していることを確認する。GUI受入れが必要な実図面は別の承認計画で行う。

チャット上書き例は `instruction_overrides={"profile":"quick"}`、または `{"building_replacement":{"old_group_action":"archive","archive_group":8}}`。指示の引用はinstruction_evidenceへ入れる。設定の知らない項目や不正値を、上書きで隠して通さない。

## first_emptyの意味

元の図面を基準に、0～15のうち次を満たす最小番号を選ぶ：対象建築群でも基準点群3でもない、全保存ルート（非表示の設定TEXTを含む）が空、群が書込み状態3でない、群が保護されていない。適格な群がなければ停止する。既存のレイヤ名や縮尺だけで使用中と判定するものではない。

全候補の判定理由と実際に選んだ番号をplan.workflow.contextへ記録する。空き群の縮尺を1/100へ変える場合もactionsへ入れ、非表示にする。実行時に別の群を割り当てない。選択済み群が使用中になれば原本/スナップショットの変化として拒否し、固定した空/状態条件も検査する。

## 固定された設定と安全条件

schema4は設定の原文/生SHA、解析値、組込みprofile表の版、指示、実効値/出所と全体ハッシュを計画内に持つ。実行時は**現在の設定ファイルを読まない**。ファイルをcarefulへ変えても、承認済みdelete計画はdeleteのまま。今回へ変更を反映したいなら旧計画を実行せず、新しい計画とSHAで再承認する。実行記録にも採用した設定とSHAを残す。

原本/依存/計画/対象が変われば従来どおり拒否する。設定はlive dependencyへ登録せず内包して固定するが、図面・取込み元等の依存検査は解除しない。schema1～3は従来どおり動き、旧プログラムはschema4を拒否する。

原本/出力の上書き禁止、計画承認、ハッシュ検査、未知構造の拒否、毎回の許容指定、書込み状態/保護、非対象群・共有定義・共通設定の保持、読戻し/差分報告、図面と作業データの取扱いは設定で無効にできない。auto_approve/overwrite/tolerance等を入れると拒否する。

現在の新入口は観測済みv700・両建築群1/100・倍率1の剛体位置合わせ・対象群にブロック参照なしの範囲。別版・異縮尺・画像・未知/未解析表現の許可へ広げない。settings_policyの既定strictは維持し、destinationを選ぶ場合は計画に明示する。群名/層名は同期しない。

deleteは旧建築の図形だけを削除し、設定レコードと共有/未使用ブロック定義を自動削除しない。archiveと違って例外となる退避群もないため、全ての非対象群を不変監査する。保存後の検証に失敗すれば成功とせず、残った出力の場所を報告する。実図面でのdelete受入れは、別の一覧/計画/SHAによる承認が必要。

既存利用ガイドのarchive専用手順は後方互換で残し、設定ファイルを暗黙には読まない。この新入口を使う場合だけwork_dirを指定する。開く設定の背景は[設計記録](design/opening_settings_roadmap.md)を参照する。


## 設定v2：明示的に開く方針を解決する

旧schema_version=1と差し替えの解決規則は維持する。schema_version=2では[opening]にrebro_schema0="reject"または"normalize"を指定できる。既定reject、careful/quickとは独立。AI/呼出し側がload_workflow_settings→resolve_opening_settingsを明示し、そのsnapshotを専用正規化計画schema6へ渡す。open自体は設定を読まず、normalizeでも元ファイルを暗黙に書き換えない。原文/生SHA/解析値/実効値/指示/出所を計画と実行記録に固定し、実行時の設定変更は反映しない。設定v1のopeningや未知項目・不正値・安全条件の解除は拒否する。詳しい実行例と別の業務編集計画への由来の固定は[schema_normalization.md](schema_normalization.md)を読む。
