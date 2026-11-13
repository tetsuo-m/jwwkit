# 文字検索の表記揺れ

検索条件のnormalizationを明示した場合だけ同一視する。保存文字は変更しない。TEXTと寸法内の文字をそれぞれ1本文として扱い、別の要素を連結しない。既存のwidth_fold/ignore_caseは従来どおり使え、新しいnormalizationとの同時指定は拒否する。

```python
from jwwkit import CadDocument

def find_aw(source):
    cad = CadDocument.open(source)
    condition = {
        'field': 'text', 'match': 'prefix', 'value': 'aw-',
        'normalization': {
            'width': True, 'case': 'unicode_casefold',
            'spaces': 'ignore_listed', 'hyphens': 'dash_only',
        },
    }
    result = cad.search_entities(condition)
    if not result['complete']:
        raise ValueError('未判定があるため、編集対象として使えません')
    return result
```

例えば「ＡＷ－01」「aw ‐01」を同じ前方一致で検索できる。条件はそのままsafe_edit.write_planのselectionへ渡せるが、編集には従来どおり計画一覧とSHAの承認が必要。find_entities(query=...)、ReadViewの検索、位置検索のqueryでも同じ条件を使用できる。

|項目|省略時|指定時|
|---|---|---|
|width|false|true：全角ASCII/空白95字と半角カナ/句読点63字の限定変換。半角カナの連続区間のみ濁点を合成|
|case|sensitive|リテラルはunicode_casefold、正規表現はregex_ignorecase。両規則の混用は拒否|
|spaces|preserve|ignore_listed：承認された空白25字だけ除去|
|hyphens|preserve|dash_only：10字をASCIIハイフンへ。dash_and_prolongedはさらに「ー」「ｰ」を含む|

処理順は幅→case→空白→ハイフン。全文字の一般NFKCは行わない。旧字体・異体字・丸数字・漢数字・ひらがな/カタカナ・大小カナ等は同一視しない。全角「カ＋結合濁点」も「ガ」に変えない。空白の除去だけで非空の検索値が空になる指定は、意図せぬ全件一致を避けるため拒否する。

当初の候補は[設計記録](https://github.com/tetsuo-m/jwwkit/blob/main/docs/design/text_equivalence_proposal.md)を参照。実行時はjwwkit/resources/text_equivalence_v1.jsonの固定表を使う（Unicode16.0.0、casefold1557項目）。表の全対応を試験し、SHAを検査する。半角カナの合成も固定表28組（jwwkit/resources/halfwidth_kana_composition_v1.json）を使い、Python内蔵Unicodeの表を呼ばない。承認済みの単字表・casefold・空白・ハイフンの対応は変更しない。半角カナ1〜3字の全254,079組について旧Unicode16の結果と一致する。動作を確認したPythonは[README](https://github.com/tetsuo-m/jwwkit/blob/main/README.md)を参照。表SHAが変わった既存計画は再検索で拒否し、別の承認計画を作る。正規表現のエンジンや旧ignore_caseの規則までPythonから独立したという意味ではない。

長音を含めると「コード」と「コ-ド」まで同じになるため、意味が変わり得る注意を結果にも返す。長音を含めるのは別の明示指定であり、width=trueやdash_onlyだけでは含めない。

正規表現は対象本文だけを整形し、パターンを変更しない。整形後の本文に対するパターンを書く。幅/空白/ハイフン変換でパターン自体も変わる指定は拒否する。「[A-Z]」「\\S」等の構文をcasefoldして書き換えない。regex_ignorecaseはre.IGNORECASEなので、リテラルのß→ss等とは異なる。既存の別プロセス・5秒既定/最大30秒・パターン/入力量上限を維持し、時間切れの部分結果は返さない。

新しいnormalizationを使う検索だけquery_schema_version=2となる。旧検索の規則/有効条件は維持する。結果のinput_query/effective_query、rules.text_equivalenceに規則版/Unicode版/対応表SHAを返す。text_match_detailsは一致した本文の原文/整形後/理由/注意を最大100件返し、total/returned/truncatedを示す。未返却分も含めたmatch_countと詳細の省略を区別する。

safe_editの計画は元条件・有効条件・規則と表SHA・確定対象を固定する。実行前の再検索で規則や対象が変わっていれば拒否し、再計画を求める。計画の承認なしに、この同一視で文字を書き換えたり削除したりしない。
