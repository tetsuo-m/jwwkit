"""Explicit text normalization and killable local regex worker transport."""
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import unicodedata
import hashlib
from functools import lru_cache

TABLE_SHA256='a821077704367a49c36d4125d613c6e93c95b578bfbfec6ab5bf55d5c7f2db40'
KANA_COMPOSITION_SHA256='eb4b82da929ccc0269d5d9ebd7fbd8efd5fb1c1463af643774e590aff4b38184'

@lru_cache(maxsize=1)
def _kana_composition():
    raw=(Path(__file__).resolve().parents[1]/'resources/halfwidth_kana_composition_v1.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=KANA_COMPOSITION_SHA256:raise ValueError('Kana composition table checksum mismatch')
    table=json.loads(raw)
    if table['approved_table_sha256']!=TABLE_SHA256:raise ValueError('Kana composition approval mismatch')
    return table['pairs']

@lru_cache(maxsize=1)
def equivalence_table():
    raw=(Path(__file__).resolve().parents[1]/'resources/text_equivalence_v1.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=TABLE_SHA256:raise ValueError('Text equivalence table checksum mismatch')
    return json.loads(raw)

def normalization_options(value,match):
    if type(value)is not dict or not value.keys()<={'width','case','spaces','hyphens'}:
        raise ValueError('Invalid text normalization fields')
    result=dict(width=False,case='sensitive',spaces='preserve',hyphens='preserve');result.update(value)
    if type(result['width'])is not bool or result['case']not in ('sensitive','unicode_casefold','regex_ignorecase')or result['spaces']not in ('preserve','ignore_listed')or result['hyphens']not in ('preserve','dash_only','dash_and_prolonged'):
        raise ValueError('Invalid text normalization value')
    if match=='regex'and result['case']=='unicode_casefold' or match!='regex'and result['case']=='regex_ignorecase':
        raise ValueError('Regex uses regex_ignorecase, literals use unicode_casefold')
    equivalence_table()
    return result

def equivalent_text(text,options):
    table=equivalence_table()
    if options['width']:
        text=width_fold(text)
    if options['case']=='unicode_casefold':text=''.join(table['unicode_casefold'].get(c,c)for c in text)
    if options['spaces']=='ignore_listed':
        spaces=frozenset(table['ignored_whitespace']);text=''.join(c for c in text if c not in spaces)
    if options['hyphens']!='preserve':
        mapping=table['hyphens_dash_only']
        extra=table['hyphens_extra_prolonged']if options['hyphens']=='dash_and_prolonged'else {}
        text=''.join(mapping.get(c,extra.get(c,c))for c in text)
    return text

def equivalence_rules():
    table=equivalence_table()
    return dict(version=1,table_sha256=TABLE_SHA256,unicode_version=table['unicode_version'],order=table['order'],
                kana_composition_sha256=KANA_COMPOSITION_SHA256,
                regex_subject_only=True,regex_case_rule='re.IGNORECASE',literal_case_rule='fixed_unicode_casefold_table')


def width_fold(text):
    table=equivalence_table();pairs=_kana_composition();result=[];i=0
    while i<len(text):
        code=ord(text[i])
        if 0xff61<=code<=0xff9f:
            pair=text[i:i+2]
            if pair in pairs:result.append(pairs[pair]);i+=2;continue
            result.append(table['width_halfwidth_kana'][text[i]]);i+=1;continue
        result.append(table['width_ascii_and_space'].get(text[i],text[i]))
        i+=1
    return ''.join(result)


def normalize(text, fold, ignore_case=False):
    if fold:text=width_fold(text)
    return text.casefold() if ignore_case else text


def rules():
    return dict(engine='json-search-1',unicode_version=unicodedata.unidata_version,
        python_regex_version=sys.version.split()[0],width_rule='ascii-space-halfwidth-kana-1',
        literal_case_rule='str.casefold',regex_case_rule='re.IGNORECASE')


def regex_results(tasks, *, timeout):
    """No pattern compilation in the parent. Kill and reap the worker on every failure."""
    if not tasks:return []
    worker=Path(__file__).with_name('query_regex_worker.py')
    start=time.perf_counter()
    data=json.dumps(tasks,ensure_ascii=True,allow_nan=False).encode('ascii')
    remaining=timeout-(time.perf_counter()-start)
    if remaining<=0:raise TimeoutError('Regex search deadline exceeded before worker startup')
    process=subprocess.Popen([sys.executable,'-I',str(worker)],stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        remaining=timeout-(time.perf_counter()-start)
        if remaining<=0:raise subprocess.TimeoutExpired(process.args,timeout)
        stdout,stderr=process.communicate(data,timeout=remaining)
        if process.returncode:raise ValueError('Regex worker refused the search: '+stderr.decode('utf-8',errors='replace')[:1000])
        result=json.loads(stdout)
        if set(result)!={'matches'}:raise ValueError('Invalid regex worker response')
        matches=result['matches']
        if len(matches)!=len(tasks) or any(len(a)!=len(b['texts']) or any(type(x)is not bool for x in a) for a,b in zip(matches,tasks)):
            raise ValueError('Incomplete regex worker response')
        return matches
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError('Regex search deadline exceeded; worker terminated; no partial result') from exc
    finally:
        if process.poll() is None:process.kill()
        process.communicate()


def no_inline_flags(pattern):
    # Conservative rejection is intentional, including flag-like text in character classes.
    if re.search(r'\(\?[aiLmsux-]',pattern):raise ValueError('Inline regex flags are not permitted')
