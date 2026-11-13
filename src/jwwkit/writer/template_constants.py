"""チェックサムで固定した新規図面テンプレートの位置。任意ヘッダーには適用しない。"""
from importlib.resources import files
from jwwkit.model.base import BASE_KEYS

RESOURCES = files('jwwkit').joinpath('resources')
TEMPLATE = RESOURCES.joinpath('empty_template.jww')
HEADER_END = 16534
NAME_TABLE_START = 2548
NAME_TABLE_END = 3636
