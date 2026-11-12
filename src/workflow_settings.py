"""Explicit, read-only workflow policy. Never read by CadDocument.open."""
from pathlib import Path
import hashlib,json,tomllib

__all__=['load_workflow_settings','resolve_workflow_settings','resolve_opening_settings']
FILENAME='jww_workflow.toml'
MAX_BYTES=65536
PROFILES={'careful':{'old_group_action':'archive'},'quick':{'old_group_action':'delete'}}
_FORBIDDEN=frozenset(('safety','overwrite','in_place','force','auto_approve','skip_approval','ignore_hash',
 'ignore_dependency_changes','allow_unknown','best_effort','drop_attributes','tolerance','default_tolerance',
 'error_tolerance','settings_policy','allow_scale','allow_images','relax_structure','ignore_writing_state',
 'ignore_protection','skip_group_audit','delete_unused_definitions','skip_reload','skip_report',
 'truncate_deleted_targets','upload','remote_validation','allow_unknown_dialogs','disable_timeout'))

def _canonical(v):return json.dumps(v,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False)
def _copy(v):return json.loads(_canonical(v))
def _hash(v):return hashlib.sha256(_canonical(v).encode('utf-8')).hexdigest()
def _require(ok,message):
    if not ok:raise ValueError(message)

def _keys(value,allowed,required,path):
    _require(type(value)is dict,'INVALID_SETTING_VALUE: '+path+' must be a table')
    for key in value:
        _require(type(key)is str,'INVALID_SETTING_VALUE: non-string key')
        if key not in allowed:
            code='FORBIDDEN_SETTING'if key in _FORBIDDEN else 'UNKNOWN_SETTING'
            raise ValueError(code+': '+path+'.'+key)
    _require(required<=value.keys(),'INVALID_SETTING_VALUE: missing '+str(sorted(required-value.keys())))

def _validate(document,*,instruction=False):
    version=document.get('schema_version')if type(document)is dict else None
    allowed={'profile','building_replacement'}|({'opening'}if instruction or type(version)is int and version==2 else set())
    _keys(document,allowed if instruction else allowed|{'schema_version'},
          set()if instruction else {'schema_version'},'instruction'if instruction else 'config')
    if not instruction:_require(type(version)is int and version in (1,2),'UNSUPPORTED_SETTINGS_VERSION')
    if 'opening'in document:
        d=document['opening'];_keys(d,{'rebro_schema0'},set(),'opening')
        if 'rebro_schema0'in d:_require(type(d['rebro_schema0'])is str and d['rebro_schema0']in ('reject','normalize'),'INVALID_SETTING_VALUE: opening.rebro_schema0')
    if 'profile'in document:_require(type(document['profile'])is str and document['profile']in PROFILES,'INVALID_SETTING_VALUE: profile')
    if 'building_replacement'in document:
        d=document['building_replacement'];_keys(d,{'old_group_action','archive_group'},set(),'building_replacement')
        if 'old_group_action'in d:_require(type(d['old_group_action'])is str and d['old_group_action']in ('archive','delete'),'INVALID_SETTING_VALUE: old_group_action')
        if 'archive_group'in d:
            v=d['archive_group']
            _require(type(v)is int and 0<=v<16 or type(v)is str and v=='first_empty','INVALID_SETTING_VALUE: archive_group must be integer 0..15 or first_empty')
    return _copy(document)

def _parse(raw):
    _require(type(raw)is str,'INVALID_SETTING_VALUE: raw UTF-8 text')
    _require(len(raw.encode('utf-8'))<=MAX_BYTES,'SETTINGS_SIZE_LIMIT')
    try:return _validate(tomllib.loads(raw))
    except (tomllib.TOMLDecodeError,RecursionError)as exc:raise ValueError('INVALID_SETTINGS_TOML: '+str(exc))from exc

def load_workflow_settings(work_dir):
    """Read work_dir/jww_workflow.toml explicitly; missing file means careful."""
    folder=Path(work_dir).resolve(strict=True)
    _require(folder.is_dir(),'Work directory must exist')
    path=folder/FILENAME
    try:
        stat=path.lstat()
    except FileNotFoundError:
        return dict(schema_version=1,work_dir=str(folder),config_path=str(path),present=False,raw_utf8=None,raw_sha256=None,parsed=None)
    _require(not path.is_symlink()and not(getattr(stat,'st_file_attributes',0)&0x400),'SETTINGS_LINK_REFUSED')
    _require(path.is_file(),'INVALID_SETTINGS_FILE')
    with path.open('rb')as f:data=f.read(MAX_BYTES+1)
    _require(len(data)<=MAX_BYTES,'SETTINGS_SIZE_LIMIT')
    try:raw=data.decode('utf-8')
    except UnicodeDecodeError as exc:raise ValueError('INVALID_SETTINGS_UTF8')from exc
    parsed=_parse(raw)
    return dict(schema_version=1,work_dir=str(folder),config_path=str(path),present=True,raw_utf8=raw,
                raw_sha256=hashlib.sha256(data).hexdigest(),parsed=parsed)

def _validate_loaded(loaded):
    _keys(loaded,{'schema_version','work_dir','config_path','present','raw_utf8','raw_sha256','parsed'},
          {'schema_version','work_dir','config_path','present','raw_utf8','raw_sha256','parsed'},'snapshot')
    _require(type(loaded['schema_version'])is int and loaded['schema_version']==1,'UNSUPPORTED_SETTINGS_VERSION')
    _require(type(loaded['work_dir'])is str and Path(loaded['work_dir']).is_absolute(),'Invalid frozen work directory')
    _require(loaded['config_path']==str(Path(loaded['work_dir'])/FILENAME),'Invalid frozen config path')
    _require(type(loaded['present'])is bool,'Invalid frozen config presence')
    if loaded['present']:
        parsed=_parse(loaded['raw_utf8'])
        _require(parsed==loaded['parsed']and hashlib.sha256(loaded['raw_utf8'].encode('utf-8')).hexdigest()==loaded['raw_sha256'],'Frozen configuration content/hash mismatch')
    else:_require(all(loaded[k]is None for k in ('raw_utf8','raw_sha256','parsed')),'Absent file cannot have invented contents')
    return _copy(loaded)

def resolve_workflow_settings(loaded,*,instruction_overrides=None,instruction_evidence=None):
    """Resolve chat > file > careful; preserve all inputs and provenance in JSON."""
    loaded=_validate_loaded(loaded)
    chat=_validate({}if instruction_overrides is None else instruction_overrides,instruction=True)
    _require(instruction_evidence is None or type(instruction_evidence)is str and len(instruction_evidence)<=8192,'Invalid instruction evidence')
    file=loaded['parsed']or {};ct=chat.get('building_replacement',{});ft=file.get('building_replacement',{})
    profile=chat.get('profile',file.get('profile','careful'))
    profile_origin='instruction.profile'if 'profile'in chat else 'config.profile'if 'profile'in file else 'library.default'
    if 'old_group_action'in ct:action=ct['old_group_action'];origin='instruction.building_replacement.old_group_action'
    elif 'profile'in chat:action=PROFILES[chat['profile']]['old_group_action'];origin='instruction.profile'
    elif 'old_group_action'in ft:action=ft['old_group_action'];origin='config.building_replacement.old_group_action'
    elif 'profile'in file:action=PROFILES[file['profile']]['old_group_action'];origin='config.profile'
    else:action='archive';origin='library.default'
    archive=ct.get('archive_group',ft.get('archive_group'))
    archive_origin='instruction.building_replacement.archive_group'if 'archive_group'in ct else 'config.building_replacement.archive_group'if 'archive_group'in ft else 'plan_argument_required'
    inactive=[]
    if action=='delete'and archive is not None:
        _require('archive_group'not in ct,'Delete contradicts an explicit archive_group instruction/argument')
        inactive=[dict(field='building_replacement.archive_group',value=archive,source=archive_origin,reason='not_applicable_for_delete')]
        archive=None;archive_origin='not_applicable_for_delete'
    effective=dict(old_group_action=action,archive_group=archive)
    return dict(schema_version=1,workflow_name='building_replacement',config_snapshot=loaded,
     profile_catalog_version=1,profile_catalog=_copy(PROFILES),selected_profile=profile,profile_origin=profile_origin,
     profile_label=profile if action==PROFILES[profile]['old_group_action']else profile+' + old_group_action='+action,
     instruction_overrides=chat,instruction_evidence=instruction_evidence,effective=effective,effective_sha256=_hash(effective),
     provenance=dict(old_group_action=origin,archive_group=archive_origin),inactive_settings=inactive)

def _verify_resolved(value):
    _require(type(value)is dict,'Invalid resolved workflow settings')
    try:expected=resolve_workflow_settings(value['config_snapshot'],instruction_overrides=value['instruction_overrides'],instruction_evidence=value['instruction_evidence'])
    except KeyError as exc:raise ValueError('Incomplete resolved workflow settings')from exc
    _require(_canonical(expected)==_canonical(value),'Resolved workflow settings changed or unsupported')
    return expected

def _assert_live_snapshot(value):
    snapshot=value['config_snapshot']
    _require(load_workflow_settings(snapshot['work_dir'])==snapshot,'Configuration changed during planning; replan')

def resolve_opening_settings(loaded,*,instruction_overrides=None,instruction_evidence=None):
    """Explicit chat > file > reject; never normalize/open or inherit a quick profile."""
    loaded=_validate_loaded(loaded);chat=_validate({}if instruction_overrides is None else instruction_overrides,instruction=True)
    _require(instruction_evidence is None or type(instruction_evidence)is str and len(instruction_evidence)<=8192,'Invalid instruction evidence')
    c=chat.get('opening',{});f=(loaded['parsed']or {}).get('opening',{})
    mode=c.get('rebro_schema0',f.get('rebro_schema0','reject'))
    origin='instruction.opening.rebro_schema0'if 'rebro_schema0'in c else 'config.opening.rebro_schema0'if 'rebro_schema0'in f else 'library.default'
    effective=dict(rebro_schema0=mode)
    return dict(schema_version=2,workflow_name='opening',resolution_rule_version=1,config_snapshot=loaded,
        instruction_overrides=chat,instruction_evidence=instruction_evidence,effective=effective,effective_sha256=_hash(effective),provenance=dict(rebro_schema0=origin))

def _verify_opening_settings(value):
    _require(type(value)is dict,'Invalid opening settings')
    try:expected=resolve_opening_settings(value['config_snapshot'],instruction_overrides=value['instruction_overrides'],instruction_evidence=value['instruction_evidence'])
    except KeyError as exc:raise ValueError('Incomplete opening settings')from exc
    _require(_canonical(expected)==_canonical(value),'Opening settings snapshot changed or unsupported')
    return expected
