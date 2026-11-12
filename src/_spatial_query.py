"""Use the existing JSON query engine on a detached snapshot, without file I/O."""
from types import SimpleNamespace
from read_view import _unpack
from model.common_entities import model_entity
from model.query import search


class FrozenDocument:
    def __init__(self,view,context):
        self.header=context.header;self.includes_metadata=view.includes_metadata
        self._source_bytes=None;self._header=view._source_header_bytes
        blobs=view._records if context.o['basis']=='current'else view._persisted
        self.missing=[i for i,b in enumerate(blobs)if b is None]
        self.entities=tuple(model_entity(_unpack(b if b is not None else view._records[i]),source_index=view._indices[i])for i,b in enumerate(blobs))
        self.block_definitions=tuple(SimpleNamespace(number=r['number'],name=r['name'],entities=())for r in context.definitions.values())
        self.presets=context.presets

    def get_group_scale(self,group):return self.header['layer_groups'][group]['scale']

    def get_text_preset(self,number):
        if self.presets['status']!='exact':raise ValueError('Frozen text presets are undetermined')
        return dict(self.presets['values'][number-1])


def select(view,context,query,remaining_seconds):
    if query is None:return range(view.entity_count),[],None
    doc=FrozenDocument(view,context);missing=set(doc.missing)
    result=search(doc,query,scope='drawing',limits={'total_seconds':min(30.,remaining_seconds),'regex_seconds':min(5.,remaining_seconds)},
                  _indices=[i for i in range(view.entity_count)if i not in missing])
    unresolved=[dict(index=r['index'],reason=r['reason'])for r in result['unresolved']]
    unresolved.extend(dict(index=i,reason='No persisted record to evaluate query')for i in doc.missing)
    info={k:result[k]for k in ('input_query','effective_query','examined_count','resolutions','rules')}
    info.update(source_sha256=view.source_sha256,model_sha256=view.model_sha256,basis=context.o['basis'],complete=not unresolved)
    return [x['index']for x in result['hits']],unresolved,info
