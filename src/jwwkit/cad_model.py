"""編集用公開APIの互換窓口。実寸換算・既存図面編集はmodel.documentで管理する。"""
from jwwkit.model.common_entities import CadEntity, CadBlockDefinition, model_entity
from jwwkit.model.document import CadDocument

from jwwkit.reader.jws import JwsDocument
