"""Explicit, approved, schema-only normalization. Never called implicitly by open()."""
from pathlib import Path
import ctypes
import json
import os
import re
import uuid
from jwwkit._normalization_inspection import inspect_path, sha, MAX_FILES, MAX_BATCH_BYTES
from jwwkit.workflow_settings import _verify_opening_settings, _assert_live_snapshot

__all__ = ['inspect_schema_normalization', 'write_schema_normalization_plan',
           'execute_schema_normalization_plan', 'normalization_edit_dependencies']
_LIMIT = 8 * 1024 * 1024
_KIND = 'jww_schema_normalization'


class NormalizationPlanError(ValueError):
    """No plan/output published; diagnostics contains every inspected input."""
    def __init__(self, message, diagnostics):
        super().__init__(message)
        self.diagnostics = diagnostics


class NormalizationExecutionError(RuntimeError):
    """result records retained staging/published artifacts; never implies rollback."""
    def __init__(self, result):
        super().__init__(result['error'])
        self.result = result


def _json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False).encode('utf-8')


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def _load(path):
    with Path(path).open('rb') as stream:
        data = stream.read(_LIMIT + 1)
    if len(data) > _LIMIT:
        raise ValueError('Normalization JSON exceeds 8 MiB')
    return data, json.loads(data, object_pairs_hook=_pairs,
                           parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Non-finite JSON')))


def _path(value):
    p = Path(value).absolute()
    # Reject links/reparse points on the whole existing ancestry before resolving.
    for item in (p, *p.parents):
        if item.exists() or item.is_symlink():
            stat = item.lstat()
            if item.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Link/reparse path refused: ' + str(item))
    return p.resolve()


def _new(path):
    p = _path(path)
    if p.exists():
        raise FileExistsError(p)
    if not p.parent.is_dir():
        raise ValueError('Parent directory must already exist: ' + str(p.parent))
    return p


def _write(path, data):
    if len(data) > _LIMIT and Path(path).suffix == '.json':
        raise ValueError('Normalization JSON exceeds 8 MiB')
    with Path(path).open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def inspect_schema_normalization(source):
    """Read only: classify strict-standard/no-output, observed schema0, or unsupported."""
    return inspect_path(_path(source))[0]


def _entries(sources):
    if not isinstance(sources, (list, tuple)) or not 1 <= len(sources) <= MAX_FILES:
        raise ValueError('Provide 1..256 source paths')
    paths = [_path(p) for p in sources]
    if len({str(p).casefold() for p in paths}) != len(paths):
        raise ValueError('Duplicate source path')
    entries = []
    total = 0
    names = set()
    for path in paths:
        info, _ = inspect_path(path)
        total += info['size'] or 0
        name = path.stem + '.normalized.jww' if info['status'] == 'normalize' else None
        if name is not None:
            if name.casefold() in names or ':' in name or name.rstrip(' .') != name:
                raise NormalizationPlanError('Output filename collision/invalid name', entries + [info])
            names.add(name.casefold())
        entries.append(dict(info, output_name=name))
    if total > MAX_BATCH_BYTES:
        raise NormalizationPlanError('Batch exceeds 512 MiB', entries)
    if any(e['status'] not in ('normalize', 'not_needed') for e in entries):
        raise NormalizationPlanError('Unsupported/invalid input: whole batch stopped', entries)
    return entries


def _layout(output, plan, stage, result, entries, settings):
    paths = [output, plan, stage, result]
    if len({str(p).casefold() for p in paths}) != 4:
        raise ValueError('Plan/output/staging/record paths collide')
    if stage.parent != output.parent:
        raise ValueError('Staging must be a dedicated sibling of output')
    if not re.fullmatch(r'\.jww-normalize-[0-9a-f]{32}', stage.name):
        raise ValueError('Invalid staging path')
    protected = [Path(e['source']) for e in entries] + [Path(settings['config_snapshot']['config_path'])]
    for p in [plan, result, *protected]:
        if p == output or p == stage or p.is_relative_to(output) or p.is_relative_to(stage):
            raise ValueError('Protected input/plan/record is inside output/staging')
    if any(str(p).casefold() == str(q).casefold() for p in [plan, result] for q in protected):
        raise ValueError('Plan/record would overwrite an input/settings file')


def write_schema_normalization_plan(sources, output_dir, plan_path, *, opening_settings):
    """Write schema6 plan only; no JWW output. Targets AND no-ops are hash-fixed."""
    settings = _verify_opening_settings(opening_settings)
    _assert_live_snapshot(settings)
    entries = _entries(sources)
    if any(e['status'] == 'normalize' for e in entries) and settings['effective']['rebro_schema0'] != 'normalize':
        raise NormalizationPlanError('opening.rebro_schema0=reject; explicit normalize required', entries)
    output = _new(output_dir)
    plan = _new(plan_path)
    result = _new(plan.with_name(plan.stem + '.normalization-result.json'))
    stage = _new(output.parent / ('.jww-normalize-' + uuid.uuid4().hex))
    _layout(output, plan, stage, result, entries, settings)
    value = dict(schema_version=6, kind=_KIND, normalization_rule_version=1, failure_policy='all_or_nothing',
                 plan_path=str(plan), output_dir=str(output), staging_dir=str(stage), result_path=str(result),
                 opening_settings=settings, entries=entries)
    _assert_live_snapshot(settings)
    data = _json(value)
    _write(plan, data)
    return dict(plan_path=str(plan), plan_sha256=sha(data), plan=value)


def _verify_plan(path, approved):
    path = _path(path)
    raw, plan = _load(path)
    if type(approved) is not str or not re.fullmatch('[0-9a-f]{64}', approved) or sha(raw) != approved:
        raise ValueError('Approved plan SHA256 does not match')
    keys = {'schema_version', 'kind', 'normalization_rule_version', 'failure_policy', 'plan_path', 'output_dir',
            'staging_dir', 'result_path', 'opening_settings', 'entries'}
    if type(plan) is not dict or set(plan) != keys or type(plan['schema_version']) is not int or plan['schema_version'] != 6:
        raise ValueError('Expected dedicated schema6 normalization plan')
    if plan['kind'] != _KIND or type(plan['normalization_rule_version']) is not int or plan['normalization_rule_version'] != 1 or plan['failure_policy'] != 'all_or_nothing':
        raise ValueError('Unsupported normalization kind/rule/failure policy')
    if plan['plan_path'] != str(path):
        raise ValueError('Plan moved since creation')
    settings = _verify_opening_settings(plan['opening_settings'])
    if type(plan['entries']) is not list or not all(type(e) is dict and type(e.get('source')) is str for e in plan['entries']):
        raise ValueError('Invalid entries')
    output, stage, result = (_new(plan[k]) for k in ('output_dir', 'staging_dir', 'result_path'))
    if any(plan[k] != str(p) for k, p in zip(('output_dir', 'staging_dir', 'result_path'), (output, stage, result))):
        raise ValueError('Plan paths must be fixed canonical absolute paths')
    _layout(output, path, stage, result, plan['entries'], settings)
    return plan


def _revalidate(plan):
    current = _entries([e['source'] for e in plan['entries']])
    if _json(current) != _json(plan['entries']):
        raise ValueError('Input SHA/classification/declarations changed; replan and obtain approval')
    if any(e['status'] == 'normalize' for e in current) and plan['opening_settings']['effective']['rebro_schema0'] != 'normalize':
        raise ValueError('Frozen settings reject normalization')


def _publish(stage, output):
    # Windows MoveFileW fails if destination exists; no replace/cross-volume flags.
    stage, output = _path(stage), _new(output)
    if stage.parent != output.parent or not stage.is_dir():
        raise ValueError('Invalid publication paths')
    if os.name != 'nt':
        raise RuntimeError('Atomic no-replace publication currently supports Windows only')
    api = ctypes.WinDLL('kernel32', use_last_error=True).MoveFileW
    api.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    api.restype = ctypes.c_int
    if not api(str(stage), str(output)):
        raise ctypes.WinError(ctypes.get_last_error())


def _verify_artifacts(folder, plan, manifest):
    expected = {e['output_name']: e['expected_output_sha256'] for e in plan['entries'] if e['status'] == 'normalize'}
    expected['_normalization_manifest.json'] = sha(manifest)
    if {p.name for p in folder.iterdir()} != set(expected):
        raise ValueError('Staging/published inventory changed')
    for name, digest in expected.items():
        p = _path(folder / name)
        if not p.is_file() or sha(p.read_bytes()) != digest:
            raise ValueError('Output validation failed: ' + name)


def execute_schema_normalization_plan(plan_path, *, approved_sha256):
    """Execute only the approved schema6 snapshot; frozen settings are not reloaded."""
    plan = _verify_plan(plan_path, approved_sha256)
    output, stage, record = (Path(plan[k]) for k in ('output_dir', 'staging_dir', 'result_path'))
    result = dict(schema_version=6, kind=_KIND, plan_path=plan['plan_path'], plan_sha256=approved_sha256,
                  opening_settings=plan['opening_settings'], entries=plan['entries'], output_dir=str(output),
                  staging_dir=str(stage), result_path=str(record), published=False, verified=False, status='failed', error=None,
                  normalized_count=sum(e['status']=='normalize' for e in plan['entries']),
                  not_needed_count=sum(e['status']=='not_needed' for e in plan['entries']), retained_artifacts=[])
    try:
        _revalidate(plan)
        targets = [e for e in plan['entries'] if e['status'] == 'normalize']
        if targets:
            stage.mkdir()  # exclusive; retain evidence on any subsequent failure
            for entry in targets:
                info, data = inspect_path(entry['source'])
                if _json(dict(info, output_name=entry['output_name'])) != _json(entry) or data is None:
                    raise ValueError('Input changed during preparation')
                _write(stage / entry['output_name'], data)
                check, _ = inspect_path(stage / entry['output_name'])
                if check['status'] != 'not_needed' or check['source_sha256'] != entry['expected_output_sha256']:
                    raise ValueError('Prepared file is not a strict round-tripping JWW')
            manifest = _json(dict(schema_version=6, kind=_KIND, plan_path=plan['plan_path'], plan_sha256=approved_sha256,
                                  entries=plan['entries'], opening_settings=plan['opening_settings']))
            _write(stage / '_normalization_manifest.json', manifest)
            _verify_artifacts(stage, plan, manifest)
            _revalidate(plan)
            # Check owned, exact inventory again immediately before the one move.
            _verify_artifacts(stage, plan, manifest)
            _publish(stage, output)
            result['published'] = True
            _verify_artifacts(output, plan, manifest)
            _revalidate(plan)
            result['status'] = 'completed'
        else:
            result['status'] = 'nothing_to_normalize'
        result['verified'] = True
        _write(record, _json(result))
        return result
    except (OSError, ValueError, RuntimeError) as exc:
        result.update(error=type(exc).__name__ + ': ' + str(exc), status='failed')
        for folder in (stage, output):
            if folder.is_dir():
                try:
                    for item in folder.iterdir():
                        if item.is_file() and not item.is_symlink():
                            result['retained_artifacts'].append(dict(path=str(item), sha256=sha(item.read_bytes())))
                except OSError as artifact_error:
                    result['artifact_inventory_error'] = str(artifact_error)
        # Never overwrite a racing/pre-existing record. The exception always retains evidence.
        if not record.exists():
            try:
                _write(record, _json(result))
            except OSError as log_error:
                result['record_error'] = str(log_error)
        raise NormalizationExecutionError(result) from exc


def normalization_edit_dependencies(result_path, normalized_source):
    """Validate completed provenance; return dependencies for a NEW safe_edit plan."""
    record_path = _path(result_path)
    _, result = _load(record_path)
    if result.get('kind') != _KIND or result.get('status') != 'completed' or result.get('published') is not True or result.get('verified') is not True:
        raise ValueError('A verified, published normalization result is required')
    raw, plan = _load(result['plan_path'])
    if sha(raw) != result['plan_sha256'] or plan.get('schema_version') != 6 or plan.get('kind') != _KIND:
        raise ValueError('Normalization plan changed')
    for field in ('entries', 'opening_settings', 'output_dir', 'result_path'):
        if result[field] != plan[field]:
            raise ValueError('Normalization record/plan mismatch')
    if str(record_path) != plan['result_path']:
        raise ValueError('Normalization record moved')
    _verify_opening_settings(plan['opening_settings'])
    _revalidate(plan)
    folder = _path(plan['output_dir'])
    manifest_path = folder / '_normalization_manifest.json'
    manifest = _json(dict(schema_version=6, kind=_KIND, plan_path=plan['plan_path'], plan_sha256=sha(raw),
                          entries=plan['entries'], opening_settings=plan['opening_settings']))
    _verify_artifacts(folder, plan, manifest)
    source = _path(normalized_source)
    if source not in [folder / e['output_name'] for e in plan['entries'] if e['status'] == 'normalize']:
        raise ValueError('Source is not a normalized output of this plan')
    return tuple([str(_path(plan['plan_path'])), str(record_path), str(manifest_path)] + [e['source'] for e in plan['entries']])
