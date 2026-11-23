# Jw_cad で画像を同梱した見本（公開試験用）

このフォルダの 29 件は、所有者が Jw_cad 10.03.6 で作った**架空の図面**です（Issue #19）。空の図面に線を 1 本描き、試験用の画像を貼って「画像同梱」をし、Ver.7.00 形式で保存しました。所有者の手元にある、非公開の図面ではありません。

- 画像は、所有者がペイントで作ったもの（`bmp_a` など）と、実装役が試験のために作ったもの（`bmp_rle8` など、ペイントで保存できない形）です。どれも 258×124 画素の、単色の四角だけの画像です。
- 中身は Issue #19 で確かめました。図面の中の文字は、Jw_cad の設定の文字 6 つと、画像を指す文字だけです。画像の名前は、利用者名を含まない画像の置き場所の名前と、画像の名前だけです。ファイル全体を ASCII と UTF-16 で走査し、利用者名やほかのフォルダの場所がないことを確かめました。
- 所有者は、試験用のデータとして公開することを了承しています。
- 試験だけに使います。配布物（wheel と sdist）には入りません（`MANIFEST.in` で `tests` を外しています）。

| ファイル | 中身 | 同梱された画像 | 大きさ（バイト） | SHA256 |
|---|---|---|---:|---|
| `a1.jww` | BMP 1 枚 | BMP | 18,135 | `6279d1998063bd4c5ffa9a1aab8815522597c17e5afa2d0af8dcaedfe913ffce` |
| `a2.jww` | BMP 2 枚 | BMP、BMP | 18,897 | `2863a4b1a4c0170bc06f05f6b4cd9cfbd8e54a24113c08bc2068981699026d9c` |
| `a3.jww` | JPEG 1 枚 | JPEG | 18,253 | `535060c83f71f6a7d73ebef166ba51ac26dc0e87560b1f924d2cb7e98029d9e9` |
| `a4.jww` | JPEG 2 枚 | JPEG、JPEG | 24,395 | `cd121594bec881e6f7037512ea951cfaaf9459c506107c4beec4d29dd549b86c` |
| `a5.jww` | BMP と JPEG | JPEG、BMP | 18,892 | `4a18f5a4619796cbcf07a6156e7280b56b28ff46290a198d460375f58b6073e8` |
| `a6.jww` | a5 と同じ図面で、同梱しない（画像を指す文字だけ） | なし | 17,874 | `b89afdde8943779da1947bc99230b9e5fa45b5f6046b5c33f292297caf66660c` |
| `a7.jww` | 同じ BMP を 2 か所に貼る（同梱は 1 枚） | BMP | 18,384 | `7e72ced1d386bfd6e4bbc9b5a6cc9e5362701a9bf990d23136c1759bc68d3d24` |
| `a8.jww` | BMP を大きさ 1.5 倍・回転 30° で貼る | BMP | 18,137 | `8d17249d0f2d64b4bee5a809181cb17c219b94efc782296d317a9057570958ac` |
| `a9.jww` | BMP を貼ってブロックにする | BMP | 18,296 | `65f1267d21759de67f3369c3f70c5f15a88140e5d787192e7816707ba07be9a3` |
| `s_bmp_16.jww` | 形式ごと：`bmp_16` を 1 枚 | BMP | 18,446 | `f9a687d5b9b54d0334f6fa19bcd6af40912e6badc83bcc0ded44f0fc0fec240d` |
| `s_bmp_16bit.jww` | 形式ごと：`bmp_16bit` を 1 枚 | BMP | 18,152 | `e641302e65299ab23bbec5f998c1360eea8e25855ed322a87308f77ef266e989` |
| `s_bmp_256.jww` | 形式ごと：`bmp_256` を 1 枚 | BMP | 19,015 | `71787ea3f5485ed53242e6f9cc44fb845ffd80aca3279f76fe72b3ef064e83a1` |
| `s_bmp_32bit.jww` | 形式ごと：`bmp_32bit` を 1 枚 | BMP | 18,252 | `01f8740e3f013b9884c74f7bfb0730e35b3bdd18c512ff6bfaf42e66511d75b2` |
| `s_bmp_mono.jww` | 形式ごと：`bmp_mono` を 1 枚 | BMP | 18,331 | `62a69c6af079fb80e5d5895fa4701ba3125e1901cfb3a6e8a74505915d1166e8` |
| `s_bmp_rle4.jww` | 形式ごと：`bmp_rle4` を 1 枚 | BMP | 17,927 | `33506258fa08313457457b511f0287005694afe1fb2dc44f8397e0221fec2f8e` |
| `s_bmp_rle8.jww` | 形式ごと：`bmp_rle8` を 1 枚 | BMP | 17,934 | `45881baa4d81adbabd6975612428acf3b50bb1d5766114748a503e5fe5e0be47` |
| `s_bmp_topdown.jww` | 形式ごと：`bmp_topdown` を 1 枚 | BMP | 18,315 | `a0e4ea1c1cb690fa703acb8e324cd495c183dd4f346c1b09bf955fd5d57dcf97` |
| `s_bmp_v4header.jww` | 形式ごと：`bmp_v4header` を 1 枚 | BMP | 18,329 | `a51e77b9c2592bae4096072aba845329f871615acb28c3e3f0d76f1d5839329d` |
| `s_bmp_v5header.jww` | 形式ごと：`bmp_v5header` を 1 枚 | BMP | 18,332 | `244d85d012c0e223aaedde4f243ebe6317319271bf7c3e40d83ce7846e51a040` |
| `s_gif_a.jww` | 形式ごと：`gif_a` を 1 枚 | GIF | 23,433 | `5bf415a185ff60c1ab41c5685d2a8061a39054fa8ce507e79d69b897b6068a89` |
| `s_jpg_cmyk.jww` | 形式ごと：`jpg_cmyk` を 1 枚 | JPEG | 19,218 | `7164c26211c7d517724b2a5f383b7f8c0df68aec6ecbb542f650ee3717c58521` |
| `s_jpg_gray.jww` | 形式ごと：`jpg_gray` を 1 枚 | JPEG | 19,178 | `493841522220eef2f02ffcdf76087c44f6f1725bfa595a3760f0a96dd027ccef` |
| `s_jpg_progressive.jww` | 形式ごと：`jpg_progressive` を 1 枚 | JPEG | 19,908 | `1e6a013d92a191719ee7ab91dff31a84b887f14b399e31ee1a21e2f38723d617` |
| `s_png_a.jww` | 形式ごと：`png_a` を 1 枚 | PNG | 19,116 | `90b4dcbd890c8466cb68c825bedb71298d3e4c41fb1462a7aaca5bac7e4d8ddb` |
| `s_tif_a.jww` | 形式ごと：`tif_a` を 1 枚 | TIFF | 29,792 | `46ad41be9716e81844761437dbc29bdd6db322da6d89d75570965a61b585b971` |
| `s_png_palette.jww` | 形式ごと：`png_palette` を 1 枚 | PNG | 18,064 | `fe19e785c978b6ea9e1b64731f5a7840b9a055ff6b7708c83feb84d0fa3e24fc` |
| `s_png_rgb.jww` | 形式ごと：`png_rgb` を 1 枚 | PNG | 18,055 | `2e5bea91409d8b31f8b27bdef103dafde3ea6ad5652fd21406af4cc7e453e2d8` |
| `s_tif_none.jww` | 形式ごと：`tif_none` を 1 枚 | TIFF | 18,282 | `bc3bd84a54274c9b424b0c26fe3f626d25ccfa210f5ac889d63ab0e3557fdc00` |
| `s_gif87a.jww` | 形式ごと：`gif87a` を 1 枚 | GIF | 18,597 | `1f9c2e17b7a0eb95a0808067c0ab81b386b78b04c89a1cd3eef07f40a6318a10` |

## 入れる・消す・入れ替えの見本（Issue #57）

次の 4 件も、所有者が Jw_cad 10.03.6 で作った架空の図面です。図面と画像を同じフォルダ（利用者名を含まない場所）に置き、画像同梱の「相対パス」にチェックを入れて作りました。画像は、指揮役が試験のために作った 258×124 画素の画像（緑に丸の BMP、白地に赤い矢印の JPEG、黄色に三角の PNG）です。ファイル全体を ASCII と UTF-16 で走査し、利用者名やほかのフォルダの場所がないことを確かめました。所有者は、試験用のデータとして公開することを了承しています。

| ファイル | 中身 | 同梱された画像 | 大きさ（バイト） | SHA256 |
|---|---|---|---:|---|
| `p1_ireru.jww` | 空の図面に、同じフォルダの `irekae.bmp` を入れた | BMP（`irekae_bmp.bmp`） | 18,339 | `e4337494b44f1a0ee6ec448806b019deb4dfa7b06bc8f908e59125e92716cb8b` |
| `p2_kesu.jww` | `a2` から 2 枚目の画像を消して保存した | BMP | 18,135 | `f87870d9e2877e449819021bd096756467a0b4f945e09eebab8703b10efa3d9a` |
| `p3_irekae.jww` | `a2` の 2 枚目を消し、同じ位置に `irekae.bmp` を入れた | BMP、BMP（`irekae_bmp.bmp`） | 19,039 | `df925622a0c90c5027013199bf8f9143293af17f964f1757481fc45084c9d303` |
| `p4_jpg_png.jww` | 空の図面に `shashin.jpg` と `zukei.png` を入れた | JPEG（`shashin.jpg`）、PNG（`zukei.png`） | 23,247 | `ad72d071e253edd10e4e763209c0a7fed0ab8a9bb1bef236960bcd6ab95c6edd` |
| `p5b_nihongo.jww` | 空の図面に `写真.jpg`（`shashin.jpg` の写し）と `画像 1.bmp`（`irekae.bmp` の写し。半角の空白入り）を入れた | JPEG（`写真.jpg`）、BMP（`画像 1_bmp.bmp`） | 23,073 | `61c3dd790e3b596dd4456a746611303480f7c889b5f792fa7701b4c2189ef11f` |

## 分かったこと
- Jw_cad 10.03.6 は、どの形式の画像も変換しないで、元のファイルのまま gzip で圧縮して同梱します（gzip の中身は元の画像ファイルとバイト単位で同じ）。
- 同梱の名前は、元の拡張子に `.gz` を足した形です。画像を指す文字は `^@BM%temp%` に、同梱の名前から `.gz` を外したものが続きます。

- 「相対パス」で同梱すると、名前は図面のフォルダからの場所で作られます（同じフォルダの画像はファイル名だけ。BMP は `<名前>_bmp.bmp`、ほかは `<名前>.<拡張子>`）。消した画像は同梱から外れ、入れ替えた画像は末尾の最後に付きます（Issue #57）。

## 使っている試験
`tests/test_embedded_images.py`、`tests/test_image_editing.py`
