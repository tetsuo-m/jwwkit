# 平面建具の候補認識（読取り専用・初版）

入口は `tategu_recognition.recognize_planar_tategu`。平面の開戸、折れ戸、フィックス、引き違い窓について、形の根拠がある候補を返す。建具データの変形を再現したテンプレート照合、断面・立面、建具符号の対応付けは行わない。単なる平行線等が似た形になる可能性は残るため、一般の実図面で全建具を保証するものではない。

種類別の建具印は `find_entities(query=...)` の `flag_bits` で抽出する。LINE 0x1000、ARC/CIRCLE 0x0080、TEXT 0x2000を別々に指定し、異なる種類へ意味を一般化しない。印のない線・円弧も別の候補として調べる。印あり/なしは別の接続集合を使うため、片方にだけ印がある混合図形の統合は保証しない。TEXTの印は拾うが、文字を建具符号へ読み替えない。曲線属性番号は候補の説明として記録するだけで、分離や種類判定に使わない。

出力には `type_candidates`、`clear_width_mm`、`position_real_mm`（開口中点）、`opening_endpoints_real_mm`、`opening_direction`、`element_indices`、`evidence`、`ambiguities` を含む。座標と幅は群ごとの縮尺で換算した実寸mm。番号は入力の現在の0始まり公開番号。異なる種類が当てはまる場合はalternativesを残す。幅が確定しなければNoneにし、外形や円弧の半径だけで内法を代用しない。

開戸は戸先線・開き円弧と両端の枠内面、折れ戸は両端の折れた二重線につながる開口基準線、窓は枠の内面または向かい合う枠断面の内向き端を測る。フィックスの水切り等の出を内法に含めない。窓の中央で左右にずれた戸線は引き違いの根拠にする。寸法値・DAT項目番号の規格値へ丸めない。同種に属する別パターンはDAT番号として区別しない。

開戸ではヒンジ・閉鎖側/戸先の角度・符号付き開き角、窓では軸と固定/軸方向の動き、折れ戸では軸と折れ側を記録する。実寸座標の正Xを0度、反時計回りを正とする。建物の内外の基準がないため、内開き/外開き・右勝手/左勝手は未確定のままにする。

## 許容値と呼び出し

対象ごとに利用者が確認した許容値JSONを用意する。APIに距離許容の既定値はなく、他図面へ自動適用しない。`tategu_input_fingerprint(path)` で得た原本SHA256をbindingへ記載する。fileは無編集の原本モデル専用、合成図形の試験だけはmemory_modelで現在のモデルに結び付けられる。ハッシュは対象一致の検査であり、利用者の承認を自動で証明する仕組みではない。

JSONの必須欄はschema_version=1、binding（kindとsha256）、coincidence_mm（正の接続許容）、width_error_mm（内法整合/評価許容）、position_error_mm（中点評価許容）、angle_rule="atan(epsilon/longer_length)"。角度は長い方の線長Lに対するatan(coincidence_mm/L)radを使う。position_error_mmは正解との評価用であり、別々の候補をその距離内だけで結合する条件ではない。余分な欄、期待する種類/幅/位置/正解ファイル等は受け付けない。

以下は `input.jww` と、その入力について確認済みの `approved_tolerances.json` を読む例。原図には書き込まない。candidateがあってもcomplete=Falseやambiguities/unsupported/excludedを必ず確認する。

```python
import json
from pathlib import Path
from tategu_recognition import recognize_planar_tategu

options = json.loads(Path('approved_tolerances.json').read_text(encoding='utf-8'))
result = recognize_planar_tategu('input.jww', tolerances=options)
with Path('candidates.json').open('x', encoding='utf-8') as stream:
    json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
```

コマンドは `python tools/recognize_planar_tategu.py --source input.jww --tolerances approved_tolerances.json --output candidates.json`。出力重複を拒否する。終了値0はcomplete、2は保留を含む結果を保存した状態。入力違い・不正指定等は例外で停止する。結果JSONには図面の座標・番号が入るため、図面と同じ範囲で扱う。

## 初版の保留

円弧付きの扉線だけでは枠内法を確定せず、幅不明とする。重複図形、複数の解釈、複数の本体に包含される断片も保留。楕円や複合要素の展開は未対応。周囲の普通線はexcludedへ記録するが、除外は「建具ではない」という証明ではない。complete=Trueもこの限定規則で検査した入力の完全性であり、見落としのない一般認識の保証ではない。

接続調査は各印集合につき最大2,000,000組（引数で変更可）、1つの接続本体512要素、枠断面候補128組を上限とする。上限到達では処理を拒否または当該本体をunsupportedにする。大規模な図面全体への速度・精度は未検証。

見本の受入れでは正解ファイルを認識から隔離し、保存した認識結果を別処理で答え合わせする。印なしの正例は元図面を編集せず、独立に構築したメモリ上の図形で試験する。許容値・正解の訂正・見本固有の保存差は当該試験に限定し、一般の比較APIや正規化条件を緩めない。
