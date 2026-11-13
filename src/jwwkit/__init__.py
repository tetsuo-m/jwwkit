"""Read, inspect and safely edit Jw_cad drawings."""
from ._resources import guide_paths, template_path
from .cad_model import CadBlockDefinition, CadDocument, CadEntity, JwsDocument
from .jwf import JwfDocument, JwfSetting, jwf_setting_catalog
from .legacy_document import LegacyDocument
from .line_document import (
    BlockDefinition, BlockReference, Circle, Dimension, JwwDocument, Line, Point, Solid, Text,
)

__all__ = [
    "BlockDefinition", "BlockReference", "CadBlockDefinition", "CadDocument", "CadEntity",
    "Circle", "Dimension", "JwfDocument", "JwfSetting", "JwsDocument", "JwwDocument",
    "LegacyDocument", "Line", "Point", "Solid", "Text", "guide_paths", "jwf_setting_catalog", "template_path",
]
