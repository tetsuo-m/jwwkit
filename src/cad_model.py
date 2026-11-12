"""編集用公開APIの互換窓口。実寸換算・既存図面編集はmodel.documentで管理する。"""
from model.common_entities import CadEntity, CadBlockDefinition, model_entity
from model.document import CadDocument

from reader.jws import JwsDocument
