"""Read-only JWF inspection. Never applies settings or guesses Jw_cad state."""
from dataclasses import dataclass,asdict
from importlib.resources import files
from pathlib import Path
import codecs,hashlib,json,math,re

__all__=['JwfDocument','JwfSetting','jwf_setting_catalog']


def jwf_setting_catalog():
    """Return recognized setting names and JWW storage classifications."""
    return json.loads(files('jwwkit').joinpath('resources', 'jwf_schema.json').read_text(encoding='utf-8'))['keys']


_STORAGE_DESCRIPTIONS = {
    'drawing_saved': '図面の保存欄に対応する設定です。',
    'drawing_saved_or_conditional': '図面への保存や対応が条件によって変わる設定です。',
    'environment_behavior': '作図環境や操作時の動きに関わる設定です。',
    'mixed_or_control': '複数の設定や読み込みの制御を含む項目です。',
    'unresolved': '図面の保存欄との対応を確認中の項目です。',
}


def _bad(text):return any(0xdc80<=ord(c)<=0xdcff for c in text)


@dataclass(frozen=True)
class JwfSetting:
    name:str
    raw_value:str
    line:int
    byte_offset:int
    active:bool
    known:bool
    encoding_valid:bool
    description:str
    storage:str

    def values(self):
        """Return lossless textual fields; no decimal/hex/default guessing."""
        if not self.encoding_valid:raise ValueError('Invalid encoded setting: '+self.name)
        value=self.raw_value
        if re.fullmatch(r'LAYNAM_[0-9A-F]',self.name) or self.name.startswith('GCOM_'):
            return tuple(v.strip(' \t') for v in value.split(','))
        # Font expressions begin with a quote but intentionally have no closing
        # quote in the official JWF syntax. Preserve that complete remainder.
        if '"' in value:
            left,right=value.split('"',1)
            prefix=tuple(re.split(r'[ \t]+',left.strip(' \t'))) if left.strip(' \t') else ()
            return (*prefix, '"'+right)
        return tuple(re.split(r'[ \t]+',value.strip(' \t'))) if value.strip(' \t') else ()

    def number(self,index,*,base=10):
        """Read a field as explicit decimal or hexadecimal, zero-based index."""
        if type(index) is not int or index<0:raise ValueError('Field index must be nonnegative integer')
        if base not in (10,16):raise ValueError('base must be 10 or 16')
        token=self.values()[index]
        if base==16:
            if not re.fullmatch(r'[+-]?[0-9a-fA-F]+',token):raise ValueError('Invalid hexadecimal field')
            return int(token,16)
        if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',token):raise ValueError('Invalid decimal field')
        result=float(token) if any(c in token for c in '.eE') else int(token)
        if not math.isfinite(result):raise ValueError('Nonfinite setting')
        return result


@dataclass(frozen=True)
class JwfDocument:
    source:Path
    encoding:str
    sha256:str
    raw_bytes:bytes
    settings:tuple
    diagnostics:tuple
    end_line:int|None
    auto_read_directives:tuple

    @classmethod
    def open(cls,path,*,encoding='cp932',errors='strict'):
        """Read only. errors='preserve' retains malformed CP932 with diagnostics.

        UTF-8/UTF-16 require an explicit encoding; this is inspection support,
        not a claim Jw_cad accepts those encodings. No codec auto-detection.
        """
        if errors not in ('strict','preserve'):raise ValueError('errors must be strict or preserve')
        codec=codecs.lookup(encoding).name
        if codec not in ('cp932','utf-8','utf-8-sig','utf-16','utf-16-le','utf-16-be'):raise ValueError('Unverified inspection encoding')
        if errors=='preserve' and codec!='cp932':raise ValueError('Malformed-byte preservation is CP932 only')
        path=Path(path);raw=path.read_bytes();text=raw.decode(encoding,errors='surrogateescape' if errors=='preserve' else 'strict')
        catalog=jwf_setting_catalog();settings=[];diagnostics=[];ended=None;directives=[]
        # CRCRLF occurs in actual JWF output; it does not create extra LF lines.
        lines=text.split('\n');offset=0
        for n,line in enumerate(lines,1):
            original=line;line=line.rstrip('\r');trim=line.strip(' \t')
            if n<=10 and 'A-Read' in line:directives.append(dict(line=n,text='A-Read0' if 'A-Read0' in line else 'A-Read',active=ended is None))
            if _bad(line):
                bad_offsets=[offset+len(line[:i].encode('cp932',errors='surrogateescape')) for i,c in enumerate(line) if 0xdc80<=ord(c)<=0xdcff]
                diagnostics.append(dict(code='INVALID_ENCODING_BYTES',line=n,line_byte_offset=offset,byte_offsets=bad_offsets,active=ended is None))
            if trim=='END':
                if ended is None:ended=n
            elif trim and not trim.startswith('#'):
                m=re.fullmatch(r'([A-Za-z][A-Za-z0-9_]*)[ \t]*=[ \t]*(.*)',trim)
                if m:
                    key,value=m.groups();entry=catalog.get(key,{})
                    storage = entry.get('storage', 'unresolved')
                    description = _STORAGE_DESCRIPTIONS[storage] if entry else '未確認キー'
                    settings.append(JwfSetting(
                        key, value, n, offset, ended is None, key in catalog,
                        not _bad(value), description, storage,
                    ))
                    if key not in catalog and ended is None:diagnostics.append(dict(code='UNKNOWN_KEY',key=key,line=n))
                    if '\u3000' in value and not key.startswith(('LAYNAM_','GCOM_')) and ended is None:
                        diagnostics.append(dict(code='FULLWIDTH_SEPARATOR_OR_TEXT_REQUIRES_REVIEW',key=key,line=n))
                elif ended is None:diagnostics.append(dict(code='UNRECOGNIZED_SYNTAX',line=n,byte_offset=offset))
            if codec=='cp932':offset+=len((original+('\n' if n<len(lines) else '')).encode('cp932',errors='surrogateescape'))
            else:offset=None  # No byte-offset guess for a multibyte/BOM codec.
        duplicates={s.name for s in settings if s.active and sum(t.active and t.name==s.name for t in settings)>1}
        diagnostics.extend(dict(code='DUPLICATE_ACTIVE_KEY',key=k) for k in sorted(duplicates))
        return cls(path,codec,hashlib.sha256(raw).hexdigest(),raw,tuple(settings),tuple(diagnostics),ended,tuple(directives))

    def get(self,name,*,include_inactive=False):
        """Exact key lookup; absent/END-excluded raises KeyError, duplicate refuses."""
        matches=[s for s in self.settings if s.name==name and (s.active or include_inactive)]
        if not matches:raise KeyError(name)
        if len(matches)!=1:raise ValueError('Ambiguous duplicate setting: '+name)
        return matches[0]

    def summary(self):
        """AI-facing local summary; unknowns and encoding damage stay explicit."""
        return dict(sha256=self.sha256,encoding=self.encoding,end_line=self.end_line,
            active_keys=[s.name for s in self.settings if s.active],diagnostics=list(self.diagnostics),
            settings=[asdict(s) for s in self.settings],auto_read_directives=list(self.auto_read_directives),
            note='Only declarations, not Jw_cad effective state. Missing values are not defaults. Never upload business names/paths.')

    def diff(self,other,*,include_inactive=False):
        """List declared changes/only-in-one/ambiguities; missing is unspecified."""
        if not isinstance(other,JwfDocument):raise TypeError('other must be JwfDocument')
        keys=sorted({s.name for doc in (self,other) for s in doc.settings if s.active or include_inactive});rows=[]
        for key in keys:
            values=[];states=[]
            for doc in (self,other):
                try:s=doc.get(key,include_inactive=include_inactive);values.append(s.raw_value);states.append(s)
                except KeyError:values.append(None);states.append(None)
                except ValueError:values.append(None);states.append('duplicate')
            if 'duplicate' in states:status='ambiguous_duplicate'
            elif any(s is not None and not s.encoding_valid for s in states):status='invalid_encoding'
            elif states[0] is None:status='only_right_unspecified_left'
            elif states[1] is None:status='only_left_unspecified_right'
            else:status='same' if states[0].values()==states[1].values() else 'different'
            rows.append(dict(key=key,status=status,left=values[0],right=values[1]))
        return dict(rows=rows,left_sha256=self.sha256,right_sha256=other.sha256,
            comparable_scope='Declared textual fields only; no inferred defaults or duplicate precedence')

    def compare_drawing(self,document):
        """Compare proven JWW fields only; every other declaration is unresolved.

        Does not apply JWF, simulate load priority, or mutate the document.
        Zero LAYSCALE and blank LAYNAM follow documented no-change semantics.
        """
        rows=[];keys=sorted({s.name for s in self.settings if s.active})
        for key in keys:
            try:
                s=self.get(key)
                if not s.encoding_valid:raise ValueError('Invalid encoded setting')
                fields=[]
                if key in ('MWIDE','MHIGH','MDIST','MPEN'):
                    attr={'MWIDE':'size_x','MHIGH':'size_y','MDIST':'spacing','MPEN':'color'}[key]
                    values=s.values()
                    if len(values)!=10:raise ValueError('Expected ten text preset fields')
                    fields=[dict(field=i,value=s.number(i),drawing=document.get_text_preset(i+1)[attr]) for i in range(10)]
                elif key=='LAYSCALE':
                    if len(s.values())!=16:raise ValueError('Expected sixteen group scales')
                    for i in range(16):
                        value=s.number(i)
                        if value<0:raise ValueError('Negative scale')
                        fields.append(dict(field=i,value=value,drawing=document.get_group_scale(i),
                            condition='no_change' if value==0 else 'existing_group_elements_prevent_application' if any(e.attributes['layer_group']==i for e in document.entities) else 'empty_group_candidate'))
                elif re.fullmatch(r'LCOLLOR_[1-8]',key):
                    if len(s.values())!=4:raise ValueError('Expected RGB plus screen width')
                    rgb=[s.number(i) for i in range(3)]
                    if any(type(v) is not int or not 0<=v<=255 for v in rgb):raise ValueError('Invalid RGB')
                    packed=document.header['palette']['pen_colors'][int(key[-1])]
                    fields=[dict(field=i,value=v,drawing=(packed>>(i*8))&255) for i,v in enumerate(rgb)]
                    # The known palette exposes COLORREF only, not screen width.
                    rows.append(dict(key=key,field=3,status='not_comparable',reason='Screen width mapping not verified'))
                elif re.fullmatch(r'LAYNAM_[0-9A-F]',key):
                    group=int(key[-1],16);values=s.values()
                    if len(values)>17:raise ValueError('More than group name plus sixteen layer names')
                    mode=self.get('LAYNAM_N').number(0)
                    if mode not in (0,1):raise ValueError('Unknown LAYNAM_N')
                    for i,value in enumerate(values):
                        fields.append(dict(field=i,value=value,drawing=document.get_group_name(group) if i==0 else document.get_layer_name(group,i-1),
                            condition='blank_no_change' if not value and mode==0 else 'name_candidate_protection_and_load_order_not_simulated'))
                if not fields:
                    rows.append(dict(key=key,status='not_comparable',storage=s.storage,reason='No independently verified JWF↔JWW field mapping; no guessed offset/default'));continue
                for f in fields:
                    condition=f.get('condition','stored_value_only_not_effective_state')
                    status='not_applicable' if condition in ('no_change','blank_no_change') else 'same' if f['value']==f['drawing'] else 'different'
                    rows.append(dict(key=key,status=status,**f))
            except (ValueError,KeyError,IndexError) as e:rows.append(dict(key=key,status='unresolved',reason=str(e)))
        return dict(rows=rows,jwf_sha256=self.sha256,drawing_sha256=hashlib.sha256(document._source_bytes).hexdigest(),
            note='Stored values only. Environment-only and unknown settings are not declared equal. JWF application/load priority is not simulated.')
