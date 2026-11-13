"""従来APIの互換窓口。要素モデル・読取り・保存処理は役割別モジュールで管理する。"""
from jwwkit.model.line import Line
from jwwkit.model.circle import Circle
from jwwkit.model.point import Point
from jwwkit.model.text import Text
from jwwkit.model.solid import Solid
from jwwkit.model.dimension import Dimension
from jwwkit.model.block_reference import BlockReference
from jwwkit.model.block_definition import BlockDefinition
from jwwkit.reader.template_names import template_layout_names
from jwwkit.writer.strings import cstring
from jwwkit.writer.mfc import records_bytes, payload_bytes
from jwwkit.writer.template_constants import TEMPLATE, HEADER_END, NAME_TABLE_START, NAME_TABLE_END, BASE_KEYS
from jwwkit.writer.template_document import JwwDocument
