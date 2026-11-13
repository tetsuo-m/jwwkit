"""旧読取りAPIの互換窓口。確認済み本文の解析はreader.archiveで管理する。"""
from jwwkit.reader.archive import (BASE_KEYS, XY_KEYS, TEXT_KEYS, SOLID_KEYS, RecordError, Cursor, read_records, read_records_bytes, _read_records, read_document)
