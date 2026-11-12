"""Synthetic query tests. No real drawing is edited."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
import math
import subprocess
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from cad_model import CadDocument
from model.common_entities import model_entity
from line_document import Line,Text,Circle,Point,BlockDefinition
from model.dimension import Dimension
from model.editing import find_entities as old_find


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.doc=CadDocument.open(ROOT/'src/resources/empty_template.jww')
        self.doc.set_group_scale(0,100);self.doc.set_group_scale(1,50)
        records=[Line((0,0),(20,0),layer=3).record(),
                 Circle((0,0),10,is_full_circle=False,arc_angle=2,layer=5).record(),
                 Text((0,0),(10,0),'AW-01',layer=3).record(),
                 Line((0,0),(10,0),layer_group=1,layer=5).record()]
        self.doc.entities=tuple(model_entity(r,source_index=i) for i,r in enumerate(records))

    def indices(self,q,**kw):return tuple(h['index'] for h in self.doc.search_entities(q,**kw)['hits'])

    def test_old_scalar_filters_and_return_type_unchanged(self):
        for options in ({},{'layer':3},{'entity_type':'line'},{'text':'AW-'},
                        {'layer_group':0,'color':2},{'rect':(-1,-1,1,1)},
                        {'entity_type':'unknown'},{'linetype':1}):
            with self.subTest(options=options):
                self.assertEqual(self.doc.find_entities(**options),old_find(self.doc,**options))
        self.assertIsInstance(self.doc.find_entities(layer=3),tuple)

    def test_lists_are_or_and_filters_are_and(self):
        self.assertEqual(self.doc.find_entities(layer=[3,5],entity_type=['line','ARC'],layer_group=[0]),(0,1))
        self.assertEqual(self.doc.find_entities(layer=(3,3),color=[2,2]),(0,2))
        self.assertEqual(self.doc.find_entities(query={'field':'entity_type','in':['LINE']},layer=5),(3,))

    def test_nested_boolean_tree_and_not_keep_missing_out(self):
        q={'all':[{'any':[{'field':'entity_type','in':['LINE']},{'field':'entity_type','in':['ARC']}]},
                  {'not':{'field':'layer_group','in':[1]}}]}
        self.assertEqual(self.indices(q),(0,1))
        q={'not':{'field':'block_name','in':['anything']}}
        self.assertEqual(self.indices(q),())

    def test_full_tree_validated_even_behind_short_circuit(self):
        for q in ({'all':[]},{'not':[]},{'any':[{'field':'entity_type','in':['LINE']},{'field':'guess','in':[1]}]},
                  {'field':'layer','in':[]},{'field':'layer','in':[True]},
                  {'field':'entity_type','in':['UNKNOWN']},{'field':'layer','in':[16]},
                  {'field':'layer','in':[0],'extra':0},{'all':[{'field':'layer','in':[0]}],'extra':0}):
            with self.subTest(q=q):
                with self.assertRaises(ValueError):self.doc.search_entities(q)
        with self.assertRaises(ValueError):self.doc.find_entities(layer=[])

    def test_json_duplicate_nonfinite_depth_and_size_refused(self):
        for q in ('{"field":"layer","field":"color","in":[0]}',
                  {'field':'layer','in':[float('nan')]},{'field':'layer','in':list(range(1025))}):
            with self.assertRaises(ValueError):self.doc.search_entities(q)
        q={'field':'layer','in':[0]}
        for _ in range(18):q={'not':q}
        with self.assertRaises(ValueError):self.doc.search_entities(q)

    def test_results_are_deterministic_detached_and_readonly(self):
        before=copy.deepcopy(self.doc.__dict__);q={'field':'layer','in':[3,3]}
        result=self.doc.search_entities(q)
        self.assertTrue(result['complete']);self.assertEqual(result['effective_query']['in'],[3])
        q['in'].append(5);result['effective_query']['in'].append(15)
        self.assertEqual(self.doc.__dict__,before)

    def test_length_arc_radius_and_group_scale(self):
        q={'all':[{'field':'layer_group','in':[0]}, {'field':'entity_type','in':['LINE','ARC']},
                  {'field':'length','min':1000,'units':'real'}]}
        self.assertEqual(self.indices(q),(0,1))
        self.assertEqual(self.indices({'field':'length','min':15,'units':'paper'}),(0,1))
        self.assertEqual(self.indices({'field':'radius','min':1000,'max':1000,'units':'real'}),(1,))
        self.assertEqual(self.indices({'field':'length','min':500,'max':500,'units':'real'}),(3,))
        for bad in ({'field':'length','min':1},{'field':'length','min':2,'max':1,'units':'real'},
                    {'field':'radius','min':True,'units':'paper'},{'field':'length','min':float('inf'),'units':'real'}):
            with self.assertRaises(ValueError):self.doc.search_entities(bad)

    def test_ellipse_unknown_is_not_inverted_or_silently_selected(self):
        self.doc.entities[1].geometry['flatness']=.5
        q={'not':{'field':'length','min':1000,'units':'real'}}
        result=self.doc.search_entities(q)
        self.assertFalse(result['complete']);self.assertEqual(result['unresolved'][0]['index'],1)
        self.assertEqual(tuple(h['index'] for h in result['hits']),(3,))
        with self.assertRaisesRegex(ValueError,'incomplete'):self.doc.find_entities(query=q)
        self.assertEqual(self.doc.find_entities(query=q,entity_type='LINE'),(3,))
        # A true OR/false AND determines the result despite an irrelevant unknown.
        result=self.doc.search_entities({'any':[{'field':'entity_type','in':['ARC']},q]})
        self.assertTrue(result['complete'])

    def test_text_modes_dimensions_and_explicit_normalization(self):
        records=[Text((0,0),(1,0),x).record() for x in ('AW-01','ＡＷ－02','aw-03','①AW-04','ｶﾞ')]
        records.append(Dimension(Line((0,0),(1,0)),Text((0,0),(1,0),'AW-05')).record())
        self.doc.entities=tuple(model_entity(r,source_index=i) for i,r in enumerate(records))
        q={'field':'text','match':'prefix','value':'AW-'}
        self.assertEqual(self.indices(q),(0,5))
        self.assertEqual(self.indices(dict(q,width_fold=True,ignore_case=True)),(0,1,2,5))
        self.assertEqual(self.indices(dict(q,match='exact',value='AW-01')),(0,))
        self.assertEqual(self.indices(dict(q,match='contains',value='AW-')),(0,3,5))
        self.assertEqual(self.indices(dict(q,match='exact',value='ガ',width_fold=True)),(4,))
        self.assertEqual(self.indices({'not':dict(q,match='contains')}),(1,2,4))
        self.assertEqual(self.indices(dict(q,match='exact',value='1AW-04',width_fold=True)),())

    def test_text_size_resolves_preset_and_dimension_as_one(self):
        preset=self.doc.get_text_preset(3)
        records=[Text((0,0),(1,0),'A',size_x=99,size_y=98,text_type=3).record(),
                 Dimension(Line((0,0),(1,0)),Text((0,0),(1,0),'B',text_type=3)).record()]
        self.doc.entities=tuple(model_entity(r,source_index=i) for i,r in enumerate(records))
        q={'field':'text_width','min':preset['size_x'],'max':preset['size_x'],'units':'paper'}
        self.assertEqual(self.indices(q),(0,1))
        self.assertEqual(self.indices(dict(q,basis='stored',min=99,max=99)),(0,))
        q={'field':'text_height','min':preset['size_y'],'max':preset['size_y'],'units':'paper'}
        self.assertEqual(self.indices(q),(0,1))
        self.doc.entities[0].geometry['text_type']=11
        self.assertFalse(self.doc.search_entities(q)['complete'])

    def test_width_is_saved_value_not_implicit_mm(self):
        self.doc.entities[0].attributes['pen_width']=12
        self.assertEqual(self.indices({'field':'pen_width','min':12,'max':12,'units':'stored'}),(0,))
        with self.assertRaises(ValueError):self.doc.search_entities({'field':'pen_width','min':1,'units':'real'})

    def test_flag_bits_raw_masks_with_no_type_inference(self):
        self.doc.entities[0].attributes['flag']=0x1000
        self.doc.entities[2].attributes['flag']=0x1002
        self.assertEqual(self.indices({'field':'flag_bits','mask':4096,'mode':'all_set'}),(0,2))
        self.assertEqual(self.indices({'field':'flag_bits','mask':4098,'mode':'all_set'}),(2,))
        self.assertEqual(self.indices({'field':'flag_bits','mask':4096,'mode':'all_clear'}),(1,3))
        q={'all':[{'field':'entity_type','in':['LINE']},{'field':'flag_bits','mask':4096,'mode':'all_set'}]}
        self.assertEqual(self.indices(q),(0,))
        for mask in (0,65536,True,-1):
            with self.assertRaises(ValueError):self.doc.search_entities({'field':'flag_bits','mask':mask,'mode':'all_set'})

    def test_undirected_line_angle_tolerance_wrap_and_radians(self):
        records=[Line((0,0),p).record() for p in ((10,0),(-10,0),(0,10),(0,-10),(10,-.01),(0,0))]
        self.doc.entities=tuple(model_entity(r,source_index=i) for i,r in enumerate(records))
        q={'field':'line_angle','min':0,'max':0,'units':'deg','tolerance':.1}
        result=self.doc.search_entities(q)
        self.assertEqual(tuple(h['index'] for h in result['hits']),(0,1,4));self.assertFalse(result['complete'])
        self.assertEqual(self.indices(dict(q,min=90,max=90)),(2,3))
        self.assertEqual(self.indices(dict(q,min=175,max=5,wrap=True)),(0,1,4))
        self.assertEqual(self.indices(dict(q,min=math.pi/2,max=math.pi/2,units='rad',tolerance=0)),(2,3))
        with self.assertRaises(ValueError):self.doc.search_entities(dict(q,min=175,max=5))
        with self.assertRaises(ValueError):self.doc.search_entities({k:v for k,v in q.items() if k!='tolerance'})

    def test_saved_group_and_layer_states_do_not_filter_by_default(self):
        self.doc.header['layer_groups'][0]['state']=0
        self.doc.header['layer_groups'][0]['layers'][3]['state']=1
        self.doc.header['layer_groups'][1]['state']=3
        self.doc.header['layer_groups'][1]['layers'][5]['state']=3
        self.assertEqual(self.doc.find_entities(entity_type='LINE'),(0,3))
        self.assertEqual(self.indices({'field':'group_state','in':['hidden']}),(0,1,2))
        self.assertEqual(self.indices({'field':'layer_state','in':['display_only']}),(0,2))
        self.assertEqual(self.indices({'all':[{'field':'group_state','in':['writing']},
            {'field':'layer_state','in':[3]}]}),(3,))
        with self.assertRaises(ValueError):self.doc.search_entities({'field':'group_state','in':[True]})

    def test_regex_runs_in_worker_and_normalization_is_explicit(self):
        q={'field':'text','match':'regex','value':'^AW-[0-9]+$'}
        self.assertEqual(self.indices(q),(2,))
        self.assertEqual(self.indices(dict(q,value='^aw-',ignore_case=True)),(2,))
        for pattern in ('(', '(?i)AW-', '(?s:.*)'):
            with self.assertRaises(ValueError):self.doc.search_entities(dict(q,value=pattern))
        with self.assertRaises(ValueError):self.doc.search_entities(dict(q,value='ＡＷ－',width_fold=True))

    def test_regex_catastrophic_timeout_kills_and_reaps_worker(self):
        self.doc.entities=(model_entity(Text((0,0),(1,0),'a'*10000+'!').record()),)
        processes=[];popen=subprocess.Popen
        def track(*args,**kw):
            process=popen(*args,**kw);processes.append(process);return process
        start=time.perf_counter()
        with patch('model.query_text.subprocess.Popen',side_effect=track):
            with self.assertRaisesRegex(TimeoutError,'worker terminated'):
                self.doc.search_entities({'field':'text','match':'regex','value':'(a+)+$'},limits={'regex_seconds':.3})
        self.assertLess(time.perf_counter()-start,5)
        self.assertEqual(len(processes),1);self.assertIsNotNone(processes[0].poll())

    def test_regex_and_general_limits_fail_not_truncate(self):
        q={'field':'text','match':'regex','value':'AW-'}
        for limits in ({'regex_seconds':0},{'regex_seconds':31},{'other':1},{'total_seconds':True}):
            with self.assertRaises(ValueError):self.doc.search_entities(q,limits=limits)
        with self.assertRaises(TimeoutError):self.doc.search_entities(q,limits={'total_seconds':1e-12})
        with self.assertRaises(ValueError):self.doc.search_entities(dict(q,value='a'*513))
        with self.assertRaises(ValueError):self.doc.search_entities({'any':[q]*9})
        self.doc.entities[2].geometry['content']='a'*16385
        with self.assertRaises(ValueError):self.doc.search_entities(q)

    def test_rectangle_query_intersects_and_anchor(self):
        q={'field':'rect','bounds':[10,-1,15,1],'units':'paper','mode':'intersects'}
        self.assertEqual(self.indices({'all':[{'field':'entity_type','in':['LINE']},q]}),(0,3))
        self.assertEqual(self.indices(dict(q,mode='anchor')),())

    def test_display_name_known_marker_only_and_all_matching_definitions(self):
        a=self.doc.add_block_definition('door',[Line((0,0),(1,0))],compound_kind=4)
        b=self.doc.add_block_definition('door',[Line((0,0),(2,0))],compound_kind=1)
        c=self.doc.add_block_definition('door@@SfigorgFlag@@9',[Line((0,0),(3,0))])
        for definition in (a,b,c):self.doc.place_block(definition.number,(0,0))
        q={'field':'block_name','in':['door'],'name_kind':'display'}
        self.assertEqual(self.indices(q),(4,5))
        self.assertEqual(self.indices(dict(q,name_kind='stored')),())
        self.assertEqual(self.doc.find_entities(block_name=[a.name,b.name]),(4,5))
        self.assertEqual(self.indices(dict(q,**{'in':[c.name]})),(6,))

    def test_definitions_once_unused_included_and_identifiers_separate(self):
        a=self.doc.add_block_definition('used',[Line((0,0),(1,0)),Text((0,0),(1,0),'AW-def')])
        unused=self.doc.add_block_definition('unused',[Line((0,0),(2,0))])
        self.doc.place_block(a.number,(0,0));self.doc.place_block(a.number,(50,0),scale_x=2,scale_y=2)
        q={'field':'entity_type','in':['LINE']}
        self.assertEqual(self.doc.find_entities(query=q),(0,3))
        result=self.doc.search_entities(q,scope='definitions')
        self.assertEqual(result['hits'],[
            dict(scope='definition',definition_number=a.number,entity_path=[0]),
            dict(scope='definition',definition_number=unused.number,entity_path=[0])])
        combined=self.doc.search_entities(q,scope='drawing_and_definitions')
        self.assertEqual(combined['match_count'],4)
        self.assertEqual(self.doc.search_entities({'field':'text','match':'prefix','value':'AW-'},scope='definitions')['match_count'],1)

    def test_definition_local_units_no_world_transform_or_recursive_expansion(self):
        a=self.doc.add_block_definition('plain',[Line((0,0),(2,0))])
        self.doc.place_block(a.number,(100,100),scale_x=3,scale_y=3)
        q={'field':'length','min':2,'max':2,'units':'paper'}
        self.assertEqual(self.doc.search_entities(q,scope='definitions')['match_count'],1)
        with self.assertRaisesRegex(ValueError,'local paper'):
            self.doc.search_entities(dict(q,units='real'),scope='drawing_and_definitions')
        # Explicit saved nested reference, not a world-space recursive traversal.
        from model.common_entities import CadBlockDefinition
        from model.block_reference import BlockReference
        nested=CadBlockDefinition(99,'nested',{},(model_entity(BlockReference((0,0),a.number).record()),))
        self.doc.block_definitions=(*self.doc.block_definitions,nested)
        self.assertEqual(self.doc.search_entities({'field':'entity_type','in':['LINE']},scope='definitions')['match_count'],1)
        self.assertEqual(self.doc.search_entities({'field':'block_name','in':['plain']},scope='definitions')['match_count'],1)

    def test_invalid_scope_and_unresolved_definition_are_explicit(self):
        with self.assertRaises(ValueError):self.doc.search_entities({'field':'entity_type','in':['LINE']},scope='world')
        from model.block_reference import BlockReference
        self.doc.entities=(model_entity(BlockReference((0,0),999).record()),)
        result=self.doc.search_entities({'field':'block_name','in':['x']})
        self.assertFalse(result['complete']);self.assertIn('Unresolved',result['unresolved'][0]['reason'])


if __name__=='__main__':unittest.main()
