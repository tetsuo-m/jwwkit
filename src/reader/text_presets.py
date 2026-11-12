"""v600/v700ヘッダー末尾の文字種1〜10を読む。設定変更は未対応。"""
import math
import struct


def read_text_presets(raw, header_end, version):
    """既知版の確認済みヘッダー終端を使う。文字種位置をバイト探索で推測しない。"""
    if version not in (600, 700):
        raise ValueError('文字種設定の読取りはv600/v700だけに対応します')
    # ezjww公式実装の配置を参照し、空試料のGUI10値と生バイトを独立照合。
    start = header_end - 380
    if start < 12 or header_end > len(raw):
        raise ValueError('文字種設定のヘッダー範囲が不正です')
    result = []
    for index in range(10):
        offset = start + index * 28
        x, y, spacing, color = struct.unpack_from('<dddI', raw, offset)
        if not all(math.isfinite(v) for v in (x, y, spacing)) or x <= 0 or y <= 0:
            raise ValueError(f'未対応の文字種設定: element=text_presets[{index}], offset={offset}')
        if not 1 <= color <= 10:
            raise ValueError(f'未対応の文字種色: element=text_presets[{index}], offset={offset + 24}')
        result.append(dict(size_x=x, size_y=y, spacing=spacing, color=color))
    return result
