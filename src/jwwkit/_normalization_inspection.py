"""Read-only, bounded schema inspection. No class-byte scanning or file writes."""
from pathlib import Path
import hashlib,struct
from jwwkit.reader.archive import Cursor,_read_records,read_records_bytes
from jwwkit.writer.preserved import serialize_body
from jwwkit.model.rigid_audit import exact

CLASSES=frozenset(('CDataSen','CDataEnko','CDataMoji'))
MAX_FILE_BYTES=268435456
MAX_BATCH_BYTES=536870912
MAX_FILES=256

def sha(data):return hashlib.sha256(data).hexdigest()

def _roundtrip(raw,parsed,zero=False):
    for encoding in (('cp932','utf-16le')if parsed['version']==600 else ('utf-16le','cp932')):
        try:
            body=serialize_body(parsed['entities'],parsed['block_defs'],parsed['version'],encoding=encoding,
                raw_trailer=parsed['raw_trailer'],class_declarations=parsed['class_declarations']if zero else None)
            if raw[:parsed['header_end']]+body==raw:return
        except (ValueError,UnicodeError,struct.error):pass
    raise ValueError('Unedited serialization is not byte-identical')

def _observe(raw):
    c=Cursor(raw);c.schema_profile='rebro_schema0';c.class_declarations=[];observed=[]
    def observer(name,schema,offset,index):
        observed.append(dict(name=name.decode('ascii',errors='backslashreplace'),name_bytes_hex=name.hex(),schema=schema,
            declaration_offset=offset,schema_offset=offset+2,class_index=index))
    c._class_declaration_observer=observer
    try:return _read_records(c),observed,None,c.pos,c.context
    except (ValueError,UnicodeError,struct.error,OverflowError)as exc:return None,observed,str(exc),c.pos,c.context

def inspect_bytes(raw,source):
    version=struct.unpack_from('<I',raw,8)[0]if len(raw)>=12 and raw[:8]==b'JwwData.'else None
    base=dict(source=str(source),source_sha256=sha(raw),size=len(raw),version=version,status='unsupported',
        declarations=[],changed_declarations=[],unsupported_declarations=[],enumeration_complete=False,
        inspection_stopped_offset=None,uninspected_bytes=0,reason=None,expected_output_sha256=None)
    try:
        parsed=read_records_bytes(raw);_roundtrip(raw,parsed)
        base.update(status='not_needed',reason='already_standard',enumeration_complete=True,
            declarations=[dict(name=d['name'],schema=d['schema'],declaration_offset=d['offset'],schema_offset=d['offset']+2,class_index=d['class_index'])for d in parsed['class_declarations']])
        return base,None
    except (ValueError,UnicodeError,struct.error,OverflowError)as strict_error:
        base['strict_reason']=str(strict_error)
    parsed,observed,error,offset,context=_observe(raw)
    base['declarations']=observed
    base['unsupported_declarations']=[dict(d,reason='outside_observed_three_class_schema0_scope')for d in observed if d['name']not in CLASSES or d['schema']!=0]
    if parsed is None:
        base.update(reason=error,inspection_stopped_offset=offset,uninspected_bytes=max(0,len(raw)-offset),context=context)
        return base,None
    try:
        _roundtrip(raw,parsed,True)
        if version not in (600,700)or not observed or any(d['name']not in CLASSES or d['schema']!=0 for d in observed):raise ValueError('Not an observed schema0 input')
        output=bytearray(raw);changed=[]
        for d in observed:
            p=d['schema_offset']
            if raw[p-2:p]!=b'\xff\xff'or struct.unpack_from('<H',raw,p)[0]!=0:raise ValueError('Class declaration identity changed')
            replacement=struct.pack('<H',version);output[p:p+2]=replacement
            changed.append(dict(d,before=0,after=version,before_bytes_hex=raw[p:p+2].hex(),after_bytes_hex=replacement.hex()))
        output=bytes(output);normal=read_records_bytes(output);_roundtrip(output,normal)
        for field in ('entities','block_defs','raw_trailer','version','header_end','memo','layer_names','color_names','line_type_names'):
            if not exact(parsed[field],normal[field]):raise ValueError('Normalization changed parsed field: '+field)
        positions={x['schema_offset']+j for x in changed for j in (0,1)}
        if len(raw)!=len(output)or any(a!=b and i not in positions for i,(a,b)in enumerate(zip(raw,output))):raise ValueError('Changes outside approved schema words')
        if any(x['schema']!=version for x in normal['class_declarations']):raise ValueError('Output schema is not the file version')
        base.update(status='normalize',reason='observed_schema0_only',enumeration_complete=True,changed_declarations=changed,
            expected_output_sha256=sha(output),verification=dict(original_roundtrip=True,strict_output_roundtrip=True,all_element_fields_equal=True,non_schema_bytes_equal=True))
        return base,output
    except (ValueError,UnicodeError,struct.error,OverflowError)as exc:
        base.update(reason=str(exc),enumeration_complete=True)
        return base,None

def inspect_path(source):
    path=Path(source).resolve()
    try:
        if not path.is_file():raise ValueError('Source must be a regular file')
        with path.open('rb')as stream:raw=stream.read(MAX_FILE_BYTES+1)
        if len(raw)>MAX_FILE_BYTES:raise ValueError('Source exceeds 256 MiB inspection limit')
        return inspect_bytes(raw,path)
    except (OSError,ValueError)as exc:
        return dict(source=str(path),status='error',reason=str(exc),exception_type=type(exc).__name__,
            source_sha256=None,size=None,version=None,declarations=[],changed_declarations=[],unsupported_declarations=[],
            enumeration_complete=False,inspection_stopped_offset=None,uninspected_bytes=None,expected_output_sha256=None),None
