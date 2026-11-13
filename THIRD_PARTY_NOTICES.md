# 第三者のデータと依存ライブラリ

## Unicode Character Database 16.0.0

文字検索の固定対応表には、Unicode Character Database 16.0.0に由来するデータを含みます。Unicode, Inc. © 2024。対象は `src/jwwkit/resources/text_equivalence_v1.json`、`src/jwwkit/resources/halfwidth_kana_composition_v1.json` と、`docs/design/text_equivalence_proposal.md`、`docs/design/text_equivalence_proposal.json` に掲載した対応表です。case folding、空白の分類、半角カナの合成などに使っています。対応表はjwwkitの検索用に抽出・整形したものです。[Unicode 16.0.0 UCD](https://www.unicode.org/Public/16.0.0/ucd/ReadMe.txt) · [CaseFolding.txt](https://www.unicode.org/Public/16.0.0/ucd/CaseFolding.txt) · [Unicode License v3](https://www.unicode.org/license.txt)

```text
UNICODE LICENSE V3

COPYRIGHT AND PERMISSION NOTICE

Copyright © 1991-2026 Unicode, Inc.

NOTICE TO USER: Carefully read the following legal agreement. BY
DOWNLOADING, INSTALLING, COPYING OR OTHERWISE USING DATA FILES, AND/OR
SOFTWARE, YOU UNEQUIVOCALLY ACCEPT, AND AGREE TO BE BOUND BY, ALL OF THE
TERMS AND CONDITIONS OF THIS AGREEMENT. IF YOU DO NOT AGREE, DO NOT
DOWNLOAD, INSTALL, COPY, DISTRIBUTE OR USE THE DATA FILES OR SOFTWARE.
Permission is hereby granted, free of charge, to any person obtaining a
copy of data files and any associated documentation (the "Data Files") or
software and any associated documentation (the "Software") to deal in the
Data Files or Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, and/or sell
copies of the Data Files or Software, and to permit persons to whom the
Data Files or Software are furnished to do so, provided that either (a)
this copyright and permission notice appear with all copies of the Data
Files or Software, or (b) this copyright and permission notice appear in
associated Documentation.
THE DATA FILES AND SOFTWARE ARE PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT OF
THIRD PARTY RIGHTS.
IN NO EVENT SHALL THE COPYRIGHT HOLDER OR HOLDERS INCLUDED IN THIS NOTICE
BE LIABLE FOR ANY CLAIM, OR ANY SPECIAL INDIRECT OR CONSEQUENTIAL DAMAGES,
OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION,
ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THE DATA
FILES OR SOFTWARE.
Except as contained in this notice, the name of a copyright holder shall
not be used in advertising or otherwise to promote the sale, use or other
dealings in these Data Files or Software without prior written
authorization of the copyright holder.
```

## Pythonの依存ライブラリ

|依存|固定版|ライセンス|配布元|
|---|---|---|---|
|ezjww|0.2.13|MIT|[ezjww 0.2.13](https://pypi.org/project/ezjww/0.2.13/)|

依存のコードとバイナリは各配布元から取得します。
