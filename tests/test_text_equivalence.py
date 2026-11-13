from importlib.resources import files
from jwwkit import template_path
"""Every approved character mapping and query/plan integration; synthetic only."""
import copy,json,unittest,tempfile,hashlib,itertools
from pathlib import Path
from unittest.mock import patch
from jwwkit.model.query_text import equivalence_table,equivalent_text,normalization_options,equivalence_rules,TABLE_SHA256
from jwwkit.cad_model import CadDocument
from jwwkit.line_document import Text,Line
from jwwkit.model.common_entities import model_entity

def query(value,**options):return dict(field='text',match='exact',value=value,normalization=options)
def doc(texts):
    d=CadDocument.open(template_path())
    d.entities=tuple(model_entity(Text((0,0),(10,0),t).record(),source_index=i)for i,t in enumerate(texts))
    return d

class EquivalenceTests(unittest.TestCase):
    def test_fixed_kana_matches_exhaustive_approved_unicode16_golden(self):
        from jwwkit.model.query_text import width_fold
        chars=[chr(x)for x in range(0xff61,0xffa0)]
        digest=hashlib.sha256()
        # All 254079 strings of 1..3 halfwidth characters, including isolated,
        # repeated and invalid dakuten/handakuten. Golden from approved U16.
        for n in (1,2,3):
            for parts in itertools.product(chars,repeat=n):
                digest.update((width_fold(''.join(parts))+'\0').encode())
        self.assertEqual(digest.hexdigest(),'599b02129e9506a8277f1e208f624603947ffb533051dd271bb882a250e131fa')

    def test_width_uses_no_runtime_unicode_and_preserves_run_boundaries(self):
        from jwwkit.model.query_text import width_fold
        options=normalization_options(dict(width=True),'exact')
        for version in ('14.0.0','15.0.0','16.0.0','17.0.0','18.0.0'):
            with patch('jwwkit.model.query_text.unicodedata.unidata_version',version),patch('jwwkit.model.query_text.unicodedata.normalize',side_effect=AssertionError('Runtime normalization forbidden')):
                self.assertEqual(equivalent_text('Ａ ｶﾞ ﾊﾟ ﾜﾞ ｳﾞ',options),'A ガ パ ヷ ヴ')
                self.assertEqual(width_fold('カﾞｶ\u3099①'),'カ\u3099カ\u3099①')
                self.assertEqual(width_fold('ｶﾞﾞﾟ'),'ガ\u3099\u309a')

    def test_kana_composition_checksum_refuses_tampering(self):
        from jwwkit.model import query_text
        query_text._kana_composition.cache_clear()
        try:
            with patch.object(query_text,'KANA_COMPOSITION_SHA256','0'*64):
                with self.assertRaisesRegex(ValueError,'checksum'):query_text.width_fold('ｶﾞ')
        finally:query_text._kana_composition.cache_clear()

    def test_resource_exactly_matches_all_approved_maps(self):
        approved=json.loads((Path(__file__).with_name('fixtures')/'approved_text_equivalence.json').read_text(encoding='utf-8'));table=equivalence_table()
        for key in approved:
            if key not in {'status', 'notice'}:
                self.assertEqual(table[key], approved[key])
        self.assertEqual(hashlib.sha256((files('jwwkit').joinpath('resources', 'text_equivalence_v1.json')).read_bytes()).hexdigest(),TABLE_SHA256)

    def test_all_width_and_case_mappings(self):
        t=equivalence_table()
        for field,option in (('width_ascii_and_space',dict(width=True)),('width_halfwidth_kana',dict(width=True)),('unicode_casefold',dict(case='unicode_casefold'))):
            o=normalization_options(option,'exact')
            for a,b in t[field].items():self.assertEqual(equivalent_text(a,o),b,(field,a))
        self.assertEqual(len(t['unicode_casefold']),1557)

    def test_all_spaces_hyphens_and_exclusions(self):
        t=equivalence_table();o=normalization_options(dict(spaces='ignore_listed'),'exact')
        self.assertEqual(len(t['ignored_whitespace']),25)
        for c in t['ignored_whitespace']:self.assertEqual(equivalent_text('a'+c+'b',o),'ab')
        for c in ('\u200b','\ufeff','\u2060'):self.assertEqual(equivalent_text(c,o),c)
        for c in t['hyphens_dash_only']:
            self.assertEqual(equivalent_text(c,normalization_options(dict(hyphens='dash_only'),'exact')),'-')
        for c in ('ー','ｰ'):
            self.assertEqual(equivalent_text(c,normalization_options(dict(hyphens='dash_only'),'exact')),c)
            self.assertEqual(equivalent_text(c,normalization_options(dict(hyphens='dash_and_prolonged'),'exact')),'-')

    def test_composition_order_and_no_general_nfkc(self):
        o=normalization_options(dict(width=True,case='unicode_casefold',spaces='ignore_listed',hyphens='dash_only'),'exact')
        self.assertEqual(equivalent_text(' ＡＷ ‐ ｶﾞ ',o),'aw-ガ')
        for text in ('①','髙','高','壹','小ゃ','か','カ','ソ','ン','カ\u3099'):
            self.assertEqual(equivalent_text(text,o),text)
        self.assertNotEqual(equivalent_text('ガ',o),equivalent_text('カ\u3099',o))

    def test_default_and_legacy_behavior_preserved(self):
        d=doc(['ＡＷ－01','aw ‐01','AW-01'])
        self.assertEqual(d.find_entities(query=dict(field='text',match='exact',value='AW-01')),(2,))
        self.assertEqual(d.find_entities(query=dict(field='text',match='exact',value='AW-01',width_fold=True)),(0,2))
        self.assertEqual(d.find_entities(query=query('AW-01')),(2,))
        self.assertEqual(d.search_entities(dict(field='text',match='exact',value='AW-01'))['query_schema_version'],1)

    def test_prefix_contains_boolean_and_detached_explanations(self):
        d=doc(['ＡＷ－01','aw ‐01','コード']);before=copy.deepcopy(d.entities)
        q=query('aw-',width=True,case='unicode_casefold',spaces='ignore_listed',hyphens='dash_only');q['match']='prefix'
        result=d.search_entities(q);self.assertEqual([h['index']for h in result['hits']],[0,1]);self.assertEqual(result['query_schema_version'],2)
        self.assertEqual(result['rules']['text_equivalence']['table_sha256'],TABLE_SHA256)
        self.assertEqual(result['text_match_details']['items'][0]['effective_text'],'aw-01')
        self.assertEqual(d.find_entities(query={'not':q}),(2,))
        self.assertEqual(d.find_entities(query={'any':[q,query('コード')]}),(0,1,2))
        self.assertEqual(d.find_entities(query={'all':[q,{'field':'layer','in':[0]}]}),(0,1))
        q['value']='01';q['match']='contains';self.assertEqual(d.find_entities(query=q),(0,1))
        self.assertEqual(before,d.entities)
        result['text_match_details']['items'][0]['normalization']['width']=False
        self.assertTrue(d.search_entities(q)['effective_query']['normalization']['width'])

    def test_prolonged_sound_warning_and_multichar_casefold(self):
        d=doc(['コード','Straße'])
        r=d.search_entities(query('コ-ド',hyphens='dash_and_prolonged'))
        self.assertEqual(r['match_count'],1);self.assertTrue(r['text_match_details']['items'][0]['warnings'])
        self.assertTrue(r['rules']['text_equivalence']['warnings'])
        self.assertEqual(d.find_entities(query=query('STRASSE',case='unicode_casefold')),(1,))

    def test_invalid_options_and_old_new_mixing_fail_even_without_hits(self):
        d=doc([])
        for o in ({'case':True},{'width':1},{'spaces':'all'},{'hyphens':'all'},{'unknown':True}):
            with self.assertRaises(ValueError):d.search_entities(query('a',**o))
        for key in ('width_fold','ignore_case'):
            q=query('a');q[key]=False
            with self.assertRaises(ValueError):d.search_entities(q)
        with self.assertRaises(ValueError):d.search_entities(query(' ',spaces='ignore_listed'))
        with self.assertRaises(ValueError):d.search_entities(query('a',case='regex_ignorecase'))

    def test_regex_subject_only_and_separate_case_semantics(self):
        d=doc(['ＡＷ ‐01','Straße','ab'])
        q=query(r'^aw-\d+$',width=True,case='regex_ignorecase',spaces='ignore_listed',hyphens='dash_only');q['match']='regex'
        self.assertEqual(d.find_entities(query=q),(0,));self.assertEqual(d.search_entities(q)['effective_query']['value'],q['value'])
        q['value']='STRASSE';self.assertEqual(d.find_entities(query=q),())
        for value in ('ＡＷ','a b','a‐b'):
            q['value']=value
            with self.assertRaises(ValueError):d.search_entities(q)
        q['value']='abc';q['normalization']['case']='unicode_casefold'
        with self.assertRaises(ValueError):d.search_entities(q)

    def test_regex_timeout_remains_fail_closed(self):
        d=doc(['a'*10000+'!']);q=query('(a+)+$',spaces='ignore_listed');q['match']='regex'
        with self.assertRaises(TimeoutError):d.search_entities(q,limits={'regex_seconds':.05})

    def test_dimension_text_is_one_subject_and_other_entities_not_applicable(self):
        from jwwkit.model.dimension import Dimension
        d=doc([]);r=Dimension(Line((0,0),(10,0)),Text((0,0),(10,0),'ＡＷ－01')).record()
        d.entities=(model_entity(r),model_entity(Line((0,0),(1,1)).record()))
        self.assertEqual(d.find_entities(query=query('AW-01',width=True)),(0,))
        self.assertEqual(d.find_entities(query={'not':query('AW-01',width=True)}),())

    def test_explanation_limit_reports_truncation(self):
        r=doc(['Ａ']*101).search_entities(query('A',width=True))
        self.assertEqual(r['match_count'],101);self.assertEqual(r['text_match_details']['returned'],100)
        self.assertTrue(r['text_match_details']['truncated']);self.assertEqual(r['text_match_details']['total'],101)

    def test_plan_records_rules_and_rejects_changed_table_identity(self):
        from jwwkit.safe_edit import write_plan,verify_plan
        with tempfile.TemporaryDirectory()as temp:
            p=Path(temp);d=CadDocument.open(template_path())
            d.add_text((0,0),content='ＡＷ－01');d.save(p/'in.jww');d=CadDocument.open(p/'in.jww')
            q=query('AW-01',width=True)
            write_plan(d,[0],[dict(op='delete_entities',indices=[0],kwargs={})],p/'out.jww',p/'plan.json',selection=q)
            h=hashlib.sha256((p/'plan.json').read_bytes()).hexdigest()
            verify_plan(p/'plan.json',approved_sha256=h)
            changed=equivalence_rules();changed['table_sha256']='0'*64
            with patch('jwwkit.model.query_text.equivalence_rules',return_value=changed):
                with self.assertRaises(ValueError):verify_plan(p/'plan.json',approved_sha256=h)
