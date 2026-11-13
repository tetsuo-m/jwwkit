"""Observed v600 basic drawings: preserve raw header and serialize CP932.

Only LINE/CIRCLE/ARC/POINT/TEXT/SOLID with no block definitions. Header editing
and version conversion are not exposed. Non-CP932 text is rejected strictly.
"""
from pathlib import Path
import copy
from jwwkit.reader.archive import read_records, read_document
from jwwkit.writer.mfc import records_bytes


class LegacyDocument:
    def __init__(self, path):
        """確認済みv600基本図面の原ヘッダーを保持する。ブロック定義や未知要素は対応しない。"""
        source = Path(path)
        from jwwkit.writer.preserved import capture_source
        self._raw,parsed=capture_source(source)
        if parsed['version'] != 600 or parsed['block_defs']:
            raise ValueError('Only observed v600 drawings without blocks')
        if any(e['type'] not in ('LINE','CIRCLE','ARC','POINT','TEXT','SOLID') for e in parsed['entities']):
            raise ValueError('Unsupported legacy entity type')
        checked = read_document(source)
        if checked['diagnostics'] or checked['validation']['has_unresolved']:
            raise ValueError('Legacy structure not verified')
        if source.read_bytes()!=self._raw:raise ValueError('Source changed during legacy loading')
        self._header = self._raw[:parsed['header_end']]
        self._entities = copy.deepcopy(parsed['entities'])
        self._decoded_header = copy.deepcopy(checked['header'])
        self.raw_layer_names = tuple(parsed['layer_names'])

    @classmethod
    def open(cls, path):
        return cls(path)

    @property
    def header(self):
        return copy.deepcopy(self._decoded_header)

    @property
    def entities(self):
        return copy.deepcopy(self._entities)

    def set_text(self, index, content):
        """旧版文字の本文だけ変更する。CP932で表せない文字は拒否する。"""
        if type(index) is not int or not 0<=index<len(self._entities):raise IndexError('Entity index must be a nonnegative in-range integer')
        if self._entities[index]['type'] != 'TEXT':
            raise ValueError('Index is not a text entity')
        if not isinstance(content,str):
            raise TypeError('Text must be a string')
        content.encode('cp932')
        from jwwkit.model.preflight import check
        candidate=copy.deepcopy(self._entities[index]);candidate['content']=content
        check(self,candidate,version=600,encoding='cp932')
        self._entities[index]['content'] = content

    def save(self, path):
        """原ヘッダーとCP932本文を別名保存する。版変換・ヘッダー編集・上書きは行わない。"""
        registry = dict(classes={}, next_index=1)
        body = records_bytes(self._entities, registry, version=600, encoding='cp932')
        body += records_bytes([], registry, version=600, encoding='cp932')
        with Path(path).open('xb') as stream:
            stream.write(self._header + body)
