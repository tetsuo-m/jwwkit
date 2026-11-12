"""チェックサムで固定した新規図面テンプレートの位置。任意ヘッダーには適用しない。"""
from pathlib import Path
from model.base import BASE_KEYS

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / 'src/resources/empty_template.jww'
HEADER_END = 16534
NAME_TABLE_START = 2548
NAME_TABLE_END = 3636
