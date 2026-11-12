"""従来APIの互換窓口。要素モデル・読取り・保存処理は役割別モジュールで管理する。"""
from model.line import Line
from model.circle import Circle
from model.point import Point
from model.text import Text
from model.solid import Solid
from model.dimension import Dimension
from model.block_reference import BlockReference
from model.block_definition import BlockDefinition
from reader.template_names import template_layout_names
from writer.strings import cstring
from writer.mfc import records_bytes, payload_bytes
from writer.template_constants import ROOT, TEMPLATE, HEADER_END, NAME_TABLE_START, NAME_TABLE_END, BASE_KEYS
from writer.template_document import JwwDocument
