"""Offline distribution integrity and executable guide checks (synthetic data only)."""
import contextlib
import hashlib
import io
import json
import math
import platform
from importlib.resources import files
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
from unittest.mock import patch

import jwwkit
from jwwkit import guide_paths, template_path
from jwwkit._commands._integrity import check_installed_files


def _run_tool(command, args, cwd):
    return subprocess.run(
        [sys.executable, "-I", "-B", "-X", "utf8", "-m", "jwwkit", command, *args],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8",
    )


def check(*, compare_command, inspect_jwf_command, summarize_command):
    if sys.flags.optimize:
        raise RuntimeError("Run without -O: executable guide assertions must remain enabled")
    count = check_installed_files()
    guides = guide_paths()["usage_guide"].parent
    template_file = template_path()
    from jwwkit.model.query_text import equivalent_text,normalization_options,_kana_composition
    width_options=normalization_options({'width':True},'exact')
    for original,expected in _kana_composition().items():
        assert equivalent_text(original,width_options)==expected
    assert equivalent_text('Ａ ｶﾞ ﾊﾟ ｳﾞ ① カ\u3099',width_options)=='A ガ パ ヴ ① カ\u3099'
    from jwwkit.cad_model import CadDocument, JwsDocument
    from jwwkit.line_document import JwwDocument, Line, Text, Circle
    from jwwkit.writer.mfc import records_bytes
    from jwwkit.reader.jws import JWS700_RESERVED
    text = (guides/'usage_guide.md').read_text(encoding='utf-8')
    blocks = re.findall(r'```python\n(.*?)\n```', text, re.S)
    if len(blocks) != 13:
        raise ValueError('Guide code inventory changed; update executable checks')
    ns = {'__name__': 'distribution_guide'}
    results = []
    with tempfile.TemporaryDirectory(prefix='jww-install-check-') as tmp, \
         patch('builtins.input', side_effect=AssertionError('No background keyboard approval')), \
         contextlib.redirect_stdout(io.StringIO()):
        for i, code in enumerate(blocks):
            with contextlib.chdir(tmp):
                exec(compile(code, f'usage_guide.md:block{i+1}', 'exec'), ns)
        folder = Path(tmp)
        source = folder/'input.jww'
        new = JwwDocument()
        new.set_group_scale(0, 50); new.set_group_scale(1, 25)
        new.add_text((10,10), content='置換前')
        new.add_line((2,2),(4,2),layer=1)
        new.add_line((10,2),(12,2),layer=2)
        new.add_line((160,120),(180,120),layer=4,layer_group=1)
        new.save(source)
        original = source.read_bytes()
        cad = CadDocument.open(source)
        if cad.diagnostics or len(cad.entities) != 4:
            raise AssertionError('Synthetic template/reader smoke failure')
        report = ns['read_report'](source,folder/'summary.json')
        assert report['entity_count']==4 and report['texts'][0]['content']=='置換前'
        assert sum(l['count'] for g in report['layer_groups'] for l in g['layers'])==4
        assert cad.convert_point((1000,0),layer_group=0,from_units='real',to_units='paper')==(20.,0.)
        assert cad.convert_point((1000,0),layer_group=1,from_units='real',to_units='paper')==(40.,0.)
        results.append('summary_and_group_units')
        before=ns['save_group_snapshot'](source,1,folder/'group_snapshot.json')
        assert ns['check_group_snapshot'](source,1,folder/'group_snapshot.json')['passed']
        changed=CadDocument.open(source);changed.set_group_name(1,'AUDIT_CHANGED');changed.save(folder/'group_changed.jww')
        assert not ns['check_group_snapshot'](folder/'group_changed.jww',1,folder/'group_snapshot.json')['passed']
        results.append('strict_group_snapshot_persist_and_difference')
        receipt = ns['plan_edit'](source,folder/'edited.jww',folder/'edit.plan.json')
        assert not (folder/'edited.jww').exists() and source.read_bytes()==original
        # Explicit synthetic test approval, never approval for a user's drawing.
        report = ns['run_approved'](receipt['path'], receipt['sha256'])
        assert (report['modified_count'],report['deleted_count'],report['added_count'])==(2,1,0)
        saved = CadDocument.open(folder/'edited.jww')
        assert saved.entities[0].geometry['content']=='置換後'
        assert saved.line_points(1,units='real')==((200.,100.),(300.,100.))
        assert ns['view'](saved.entities[-1])==ns['view'](cad.entities[-1])
        results.append('plan_edit_reload_and_non_target')
        # Build a documented-schema JWS from synthetic LINE records, not any sample.
        header = b'JwsData.'+b'.'*192+struct.pack('<I2d16d',700,0,0,*([50.]*16))+JWS700_RESERVED+struct.pack('<4d',0,0,4,4)
        registry = dict(classes={},next_index=1)
        data = header+records_bytes([Line((0,0),(4,0),layer=3).record(),Line((4,0),(4,4),layer=5,color=4).record()],registry)
        data += records_bytes([],registry)
        figure = folder/'symbol.jws'; figure.write_bytes(data)
        assert JwsDocument.open(figure).to_bytes()==data
        receipt = ns['plan_symbol'](source,figure,folder/'symbols.jww',folder/'symbol.plan.json')
        report = ns['run_approved'](receipt['path'],receipt['sha256'])
        symbols = CadDocument.open(folder/'symbols.jww')
        assert symbols.block_reference_counts()=={'SYMBOL':2} and report['added_count']==2
        assert symbols.entities[-1].geometry['scale_y']<0
        assert symbols.entities[-1].geometry['scale_x']==1.5
        assert figure.read_bytes()==data
        results.append('jws_place_copy_rotate_reflect_scale')
        groupsource = folder/'groups.jww'
        new = JwwDocument();new.set_group_scale(0,50)
        for x in (0,20):
            new.add_line((x,0),(x+4,0),layer=3,color=2,width=2)
            new.add_line((x+4,0),(x+4,4),layer=5,color=4,linetype=2,width=3)
        new.add_line((80,60),(90,60),layer=4);new.save(groupsource)
        before = CadDocument.open(groupsource)
        receipt = ns['plan_groups'](groupsource,folder/'blocks.jww',folder/'groups.plan.json')
        report = ns['run_approved'](receipt['path'],receipt['sha256'])
        saved = CadDocument.open(folder/'blocks.jww')
        assert saved.block_reference_counts()=={'MARK':2} and len(saved.block_definitions)==1
        assert [saved.get_block_layer_priority(i) for i in (0,1)]==[True,False]
        assert ns['view'](saved.entities[-1])==ns['view'](before.entities[-1])
        assert [e.attributes for e in saved.block_definitions[0].entities]==[e.attributes for e in before.entities[:2]]
        results.append('block_reuse_priority_mixed_attributes')
        rejection = ns['report_plan_refusal'](source,folder/'refuse.plan.json',folder/'refused.jww')
        assert rejection['reason']=='Mirrored glyphs cannot be represented by verified text fields'
        assert not rejection['saved'] and source.read_bytes()==original
        results.append('refusal_without_source_change')
        receipt = ns['plan_edit'](source,folder/'stale.jww',folder/'stale.plan.json')
        source.write_bytes(original+b'changed')
        try:
            ns['run_approved'](receipt['path'],receipt['sha256'])
        except ValueError:
            pass
        else:
            raise AssertionError('Changed source was accepted')
        assert not (folder/'stale.jww').exists();source.write_bytes(original)
        results.append('stale_plan_refused')
        receipt = ns['plan_add_geometry'](source,folder/'add_geometry.jww',folder/'add_geometry.plan.json')
        assert not (folder/'add_geometry.jww').exists()
        report = ns['run_approved'](receipt['path'],receipt['sha256'])
        assert report['added_count']==8 and report['modified_count']==0
        added = CadDocument.open(folder/'add_geometry.jww')
        assert [e.entity_type for e in added.entities[-8:]]==['LINE','TEXT','CIRCLE','ARC','POINT','SOLID','CIRCLE_SOLID','CIRCLE_SOLID']
        assert added.entities[-3].attributes['pen_color']==102 and added.entities[-3].attributes['pen_style']==31
        assert added.entities[-2].attributes['pen_style']==105
        assert added.entities[-2].geometry['solid_mode']*added.get_group_scale(0)==50
        filled=added.entities[-1]
        assert (filled.attributes['layer_group'],filled.attributes['layer'])==(1,7)
        assert filled.geometry['center_x']*added.get_group_scale(1)==2600
        assert filled.geometry['radius']*added.get_group_scale(1)==100
        results.append('eight_geometry_constructor_plans')
        incoming=folder/'incoming.jww';incoming.write_bytes(source.read_bytes())
        receipt=ns['plan_import_group'](source,incoming,folder/'imported.jww',folder/'import.plan.json',source_group=0,target_group=3)
        assert not (folder/'imported.jww').exists()
        report=ns['run_approved'](receipt['path'],receipt['sha256'])
        assert report['added_count']==3 and report['modified_count']==0 and report['deleted_count']==0
        imported=CadDocument.open(folder/'imported.jww')
        assert imported.line_points(5,units='real')==CadDocument.open(source).line_points(1,units='real')
        results.append('import_group_dependency_plan_and_real_coordinates')

        dimsource = folder/'dimension.jww';new = JwwDocument()
        new.add_dimension(Line((0,0),(10,0)),Text((2,1),(5,1),'10'))
        new.add_line((1,2),(3,2),layer_group=1);new.save(dimsource)
        receipt = ns['plan_names_and_dimension'](dimsource,folder/'names.jww',folder/'names.plan.json')
        assert receipt['plan']['schema_version']==2 and len(receipt['plan']['resource_targets'])==3
        report = ns['run_approved'](receipt['path'],receipt['sha256'])
        named = CadDocument.open(folder/'names.jww')
        assert named.entities[0].geometry['text']['content']=='寸法表示'
        assert named.get_group_scale(1)==100 and named.get_layer_name(0,1)=='線'
        assert named.get_group_name(1)=='配置用' and report['changed_group_count']==2
        assert named.line_points(1,units='real')==((100.,200.),(300.,200.))
        results.append('dimension_names_scales_and_resource_review')
        states=ns['read_display_states'](source)
        assert states['group']['state']=='editable'
        receipt=ns['plan_display_states'](source,folder/'states.jww',folder/'states.plan.json')
        assert not (folder/'states.jww').exists()
        report=ns['run_approved'](receipt['path'],receipt['sha256'])
        states=ns['read_display_states'](folder/'states.jww')
        assert states['group']['state']=='display_only' and states['layer']['state']=='hidden'
        assert report['changed_entity_count']==0 and report['changed_group_count']==1
        results.append('display_states_read_plan_approval_reload')
        receipt = ns['plan_definition'](source,folder/'new_definition.jww',folder/'definition.plan.json')
        report = ns['run_approved'](receipt['path'],receipt['sha256'])
        defined = CadDocument.open(folder/'new_definition.jww')
        assert report['added_count']==2 and defined.block_reference_counts()=={'CREATED':2}
        assert defined.get_block_layer_priority(4) and not defined.get_block_layer_priority(5)
        assert defined.block_definitions[0].entities[0].attributes['flag']==0
        assert [e.attributes['layer'] for e in defined.block_definitions[0].entities]==[3,5]
        assert defined.entities[-2].geometry['ref_x']==20 and defined.entities[-1].geometry['ref_x']==80
        receipt = ns['plan_existing_definition'](folder/'new_definition.jww',defined.block_definitions[0].number,
                                                  folder/'more_refs.jww',folder/'more_refs.plan.json')
        report = ns['run_approved'](receipt['path'],receipt['sha256'])
        assert report['added_count']==1 and not report['definitions_changed']
        assert CadDocument.open(folder/'more_refs.jww').block_reference_counts()=={'CREATED':3}
        results.append('new_definition_alias_priority_and_existing_placement')
        receipt=ns['plan_alignment'](source,[1],[[100,100],[200,100]],[[300,400],[300,500]],
            folder/'aligned.jww',folder/'align.plan.json',distance_tolerance=0,angle_tolerance=90,angle_units='deg')
        review=receipt['plan']['resource_targets'][0]['alignment']
        assert review['angle_input_units']=='deg' and review['angle_difference_deg']==90
        report=ns['run_approved'](receipt['path'],receipt['sha256'])
        assert report['modified_count']==1 and not report['groups_changed']
        assert CadDocument.open(folder/'aligned.jww').line_points(1,units='real')==((300.,400.),(300.,500.))
        results.append('two_point_alignment_real_degrees_and_approval')
        # Exercise the newly distributed workflow using ONLY synthetic files.
        building_paths=[]
        for name in ('current_building','new_building'):
            d=CadDocument.open(template_file)
            for g in (1,2,3):d.set_group_scale(g,100)
            d.set_group_scale(8,50)
            d.add_line((0,0),(1000,100 if name=='new_building' else 0),layer_group=1,units='real')
            d.add_line((20,20),(30,30),layer_group=2,units='real')
            for point in ((0,0),(1000,0)):d.add_point(point,layer_group=3,layer=0,units='real',is_temporary=True)
            path=folder/(name+'.jww');d.save(path);building_paths.append(path)
        current,new_building=building_paths;original_buildings=[p.read_bytes() for p in building_paths]
        refs=ns['replacement_reference_points'](current)
        assert [row['index'] for row in refs]==[2,3] and refs[1]['real_mm']==(1000.,0.)
        replacement=ns['plan_building_replacement'](current,new_building,folder/'replacement.jww',folder/'replacement.plan.json',
            archive_group=8,building_group=1,source_reference_indices=[2,3],target_reference_indices=[2,3],
            distance_tolerance=0,angle_tolerance=0,settings_policy='destination')
        assert not (folder/'replacement.jww').exists()
        assert replacement['plan']['actions'][0]['op']=='set_group_scale'
        assert next(row for row in replacement['plan']['resource_targets'] if 'settings' in row)['settings']['settings_policy']=='destination'
        report=ns['run_approved'](replacement['path'],replacement['sha256'])
        assert (report['modified_count'],report['added_count'],report['deleted_count'])==(1,1,0)
        audit=ns['check_replacement_groups'](folder/'replacement.jww',Path(replacement['path']).with_suffix('.groups.json'))
        assert audit['passed'] and audit['archive_count']==1 and audit['archive_state']['state']=='hidden'
        assert CadDocument.open(folder/'replacement.jww').get_group_scale(8)==100
        assert [p.read_bytes() for p in building_paths]==original_buildings
        results.append('building_replacement_destination_policy_and_complete_group_audits')
        for case,angle in (('translation',0.),('rotation',math.radians(5))):
            displaced=CadDocument.open(new_building)
            displaced.transform_entities([0,2,3],translation=(1000,-500),rotation=angle,units='real')
            path=folder/(case+'_source.jww');displaced.save(path);source_bytes=path.read_bytes()
            plan=folder/(case+'.plan.json');out=folder/(case+'.jww')
            receipt=ns['plan_building_replacement'](current,path,out,plan,archive_group=8,building_group=1,
                source_reference_indices=[2,3],target_reference_indices=[2,3],distance_tolerance=.001,
                angle_tolerance=5.00001 if angle else 0.,angle_units='deg',settings_policy='destination')
            assert not out.exists()
            evidence=Path(receipt['path']).with_suffix('.groups.json')
            measured=json.loads(evidence.read_text(encoding='utf-8'))['alignment']
            assert measured['applied_scale']==1 and abs(measured['angle_difference_deg']+math.degrees(angle))<1e-8
            assert 'measured_endpoint_displacement_mm' in measured
            report=ns['run_approved'](receipt['path'],receipt['sha256'])
            assert (report['modified_count'],report['added_count'],report['deleted_count'])==(1,1,0)
            assert ns['check_replacement_groups'](out,evidence)['passed']
            endpoints=CadDocument.open(out).line_points(4,units='real')
            assert all(math.dist(a,b)<1e-6 for a,b in zip(endpoints,((0.,0.),(1000.,100.))))
            assert path.read_bytes()==source_bytes and [p.read_bytes() for p in building_paths]==original_buildings
            results.append('building_replacement_'+case+'_plan_approval_and_exact_saved_attributes')
        rejected=CadDocument.open(new_building);rejected.set_group_scale(1,50)
        different_scale=folder/'different_scale.jww';rejected.save(different_scale)
        for case,path,angular in (('different_scale',different_scale,5.00001),('angle_exceeded',folder/'rotation_source.jww',4.9)):
            plan=folder/(case+'_denied.plan.json');out=folder/(case+'_denied.jww')
            try:
                ns['plan_building_replacement'](current,path,out,plan,archive_group=8,building_group=1,
                    source_reference_indices=[2,3],target_reference_indices=[2,3],distance_tolerance=.001,
                    angle_tolerance=angular,angle_units='deg',settings_policy='destination')
            except ValueError:pass
            else:raise AssertionError('Unsupported scale/tolerance accepted')
            assert not plan.exists() and not out.exists() and not plan.with_suffix('.groups.json').exists()
        results.append('building_replacement_unequal_scale_and_angle_tolerance_refused')
        cleanup=ns['plan_archive_cleanup'](folder/'replacement.jww',folder/'after_review.jww',folder/'cleanup.plan.json',archive_group=8)
        assert not (folder/'after_review.jww').exists() and len(cleanup['plan']['targets'])==1
        assert cleanup['sha256']!=replacement['sha256']
        report=ns['run_approved'](cleanup['path'],cleanup['sha256'])
        assert (report['deleted_count'],report['added_count'],report['modified_count'])==(1,0,0)
        before=CadDocument.open(folder/'replacement.jww');after=CadDocument.open(folder/'after_review.jww')
        assert [ns['view'](e) for e in before.entities if e.attributes['layer_group']!=8]==[ns['view'](e) for e in after.entities]
        results.append('separate_archive_cleanup_plan_after_synthetic_review')
        sx=ns['read_sxf_report'](source)
        assert sx['colors']==cad.get_sxf_colors() and sx['linetypes']==cad.get_sxf_linetypes()
        assert cad.get_sxf_color('red')['code']==102
        results.append('sxf_named_definition_reading')
        # Execute the actual supplemental documentation on synthetic inputs.
        from jwwkit.drawing_comparison import compare_drawings,write_comparison
        from jwwkit.jwf import JwfDocument
        supplemental={}
        for filename,expected_blocks in [('drawing_comparison.md',1),('jwf_readonly.md',1),('search_queries.md',1)]:
            codes=re.findall(r'```python\n(.*?)\n```',(guides/filename).read_text(encoding='utf-8'),re.S)
            assert len(codes)==expected_blocks
            supplemental[filename]=len(codes)
            if filename=='drawing_comparison.md':
                (folder/'before.jww').write_bytes(source.read_bytes())
                (folder/'after.jww').write_bytes((folder/'edited.jww').read_bytes())
            elif filename=='jwf_readonly.md':
                (folder/'settings.jwf').write_bytes(b'PCOLLOR_1=255 0 0 10 .4\r\n')
                (folder/'other.jwf').write_bytes(b'PCOLLOR_1=0 0 0 10 .4\r\n')
                (folder/'drawing.jww').write_bytes(source.read_bytes())
            example={}
            with contextlib.chdir(folder):
                for code in codes:exec(compile(code,filename,'exec'),example)
            if filename=='drawing_comparison.md':
                assert example['result']['complete'] and (folder/'comparison.json').is_file()
                assert example['result']['element_accounting']['left_selected']==3
            elif filename=='jwf_readonly.md':
                assert example['red']==255 and example['changes']['rows'][0]['status']=='different'
                assert example['stored']['rows'][0]['status']=='not_comparable'
            else:
                from jwwkit.safe_edit import execute_plan
                querydoc=CadDocument.open(template_file);querydoc.set_group_scale(0,100)
                querydoc.add_line((0,0),(20,0),layer=3)
                querydoc.add_arc((0,0),10,0,2,layer=5)
                querydoc.add_text((0,0),content='AW-01')
                querysource=folder/'query_input.jww';querydoc.save(querysource)
                assert example['inspect_drawing'](querysource)['long_shapes']==(0,1)
                assert example['inspect_drawing'](querysource)['aw_texts']==(2,)
                receipt=example['plan_search_move'](querysource,folder/'query_output.jww',folder/'query_review.json')
                assert receipt['plan']['schema_version']==3
                execution=execute_plan(receipt['path'],approved_sha256=receipt['sha256'])
                assert execution['modified_count']==2 and execution['saved_all_fields_match']
                assert querydoc.search_entities({'field':'text','match':'regex','value':'^AW-'})['match_count']==1
                results.append('json_query_documented_plan_and_isolated_regex')
        scoped=compare_drawings(current,folder/'replacement.jww',left_scope={'groups':[1]},right_scope={'groups':[1]})
        assert scoped['complete'] and (scoped['summary']['added'],scoped['summary']['deleted'])==(1,1)
        execution=json.loads((folder/'replacement.changes.json').read_text(encoding='utf-8'))
        assert (execution['modified_count'],execution['added_count'],execution['deleted_count'])==(1,1,0)
        assert execution['saved_all_fields_match'] and execution['approved_plan_sha256']==replacement['sha256']
        results.append('independent_comparison_docs_group_scope_versus_execution_record')
        compound=CadDocument.open(dimsource)
        compound.add_solid(((20,0),(30,10),(30,0),(20,10)))
        compound.add_circle_solid((40,0),5)
        definition=compound.add_block_definition('CHECK',[Line((0,0),(10,0))])
        compound.place_block(definition.number,(60,0))
        compound_path=folder/'compound.jww';compound.save(compound_path)
        compound_bytes=compound_path.read_bytes();r=compare_drawings(compound_path,compound_path)
        assert r['complete'] and r['summary']['unchanged']==len(compound.entities)
        assert {x['type'] for x in r['left_entities']}>={'DIMENSION','BLOCK','SOLID','CIRCLE_SOLID'}
        assert compound_path.read_bytes()==compound_bytes and r['definitions']['matches'][0]['semantic_equal']
        results.append('compound_comparison_dimensions_blocks_solids')
        # Fully synthetic compatibility fixtures: no manufacturer DXF/JWW is packaged.
        from jwwkit.reader.archive import read_records_bytes,RecordError
        from jwwkit.writer.preserved import serialize_body
        template=(template_file).read_bytes()
        end=read_records_bytes(template)['header_end']
        for version in (600,700):
            header=bytearray(template[:end]);struct.pack_into('<I',header,8,version)
            records=[Line((0,0),(10,0)).record(),Text((0,0),(5,0),'synthetic').record(),
                     Circle((5,5),2).record(),Circle((10,10),3,is_full_circle=False,arc_angle=1).record()]
            raw=bytes(header)+serialize_body(records,[],version)
            declarations=read_records_bytes(raw)['class_declarations']
            fixture=bytearray(raw)
            for declaration in declarations:struct.pack_into('<H',fixture,declaration['offset']+2,0)
            source0=folder/f'schema0_{version}.jww';source0.write_bytes(fixture)
            try:CadDocument.open(source0)
            except RecordError as exc:assert 'schema_profile="rebro_schema0"' in str(exc)
            else:raise AssertionError('Default reader accepted schema0')
            readonly=CadDocument.open(source0,schema_profile='rebro_schema0')
            target0=folder/f'schema0_{version}_copy.jww';readonly.save(target0)
            again=CadDocument.open(target0,schema_profile='rebro_schema0')
            assert target0.read_bytes()==source0.read_bytes()
            assert again.entities==readonly.entities
            assert again._source_records['class_declarations']==readonly._source_records['class_declarations']
            try:readonly.add_line((0,0),(1,0))
            except ValueError as exc:assert 'read-only' in str(exc)
            else:raise AssertionError('Schema0 editing was accepted')
        results.append('explicit_schema0_readonly_file_roundtrip_v600_v700')
        results.append('jwf_documentation_read_diff_no_settings_application')
        verified=folder/'verified.jwf'
        widths=' '.join(str(cad.get_text_preset(i)['size_x']) for i in range(1,11))
        palette=cad.header['palette']['pen_colors'][1]
        verified.write_bytes(('MWIDE='+widths+'\nLCOLLOR_1='+f'{palette&255} {(palette>>8)&255} {(palette>>16)&255} 1\nKEY_A=5 1\n').encode('cp932'))
        declaration=JwfDocument.open(verified);compared=declaration.compare_drawing(cad)
        assert sum(x['status']=='same' for x in compared['rows'])==13
        assert next(x for x in compared['rows'] if x['key']=='KEY_A')['status']=='not_comparable'
        assert cad._source_bytes==original and not any(hasattr(declaration,n) for n in ('save','write','apply'))
        results.append('jwf_proven_drawing_fields_only')
        for tool,args,output in [(compare_command,['--left',str(current),'--right',str(folder/'replacement.jww'),'--left-groups','1','--right-groups','1'],'comparison_cli.json'),
                                 (inspect_jwf_command,['--source',str(folder/'settings.jwf'),'--other',str(folder/'other.jwf'),'--drawing',str(source)],'jwf_cli.json')]:
            proc=_run_tool(tool, [*args, '--output', str(folder/output)], folder)
            assert proc.returncode==0,proc.stderr
            assert (folder/output).is_file()
        results.append('standalone_comparison_and_jwf_clis')
        cli = _run_tool(summarize_command, ['--source', str(source), '--output', str(folder/'cli.json')], folder)
        assert cli.returncode==0,cli.stderr
        assert json.loads((folder/'cli.json').read_text(encoding='utf-8'))['entity_count']==4
        assert source.read_bytes()==original
        # Execute newer guides without relying on an original checkout or CAD.
        new_guides={};workflow_checks=[]
        for filename in ('read_view.md','geometry_view.md','spatial_search.md','workflow_settings.md','text_equivalence.md','edit_results.md','schema_normalization.md','reading_to_editing.md'):
            codes=re.findall(r'```python\n(.*?)\n```',(guides/filename).read_text(encoding='utf-8'),re.S)
            assert len(codes)==1;new_guides[filename]=len(codes);new_ns={}
            with contextlib.chdir(folder):
                for code in codes:exec(compile(code,filename,'exec'),new_ns)
            if filename=='workflow_settings.md':workflow_ns=new_ns
            if filename=='text_equivalence.md':equivalence_ns=new_ns
            if filename=='edit_results.md':edit_ns=new_ns
            if filename=='schema_normalization.md':normalization_ns=new_ns
            if filename=='reading_to_editing.md':pipeline_ns=new_ns
        policy_folder=folder/'job';policy_folder.mkdir();config=policy_folder/'jww_workflow.toml'
        config.write_text('schema_version=1\n[building_replacement]\narchive_group="first_empty"\n',encoding='utf-8')
        assert workflow_ns['read_policy'](policy_folder)['effective']['archive_group']=='first_empty'
        kw=dict(work_dir=policy_folder,building_group=1,source_reference_indices=[2,3],target_reference_indices=[2,3],distance_tolerance=0,angle_tolerance=0,settings_policy='destination')
        rec=workflow_ns['plan_replacement'](current,new_building,folder/'wf_archive.jww',folder/'wf_archive.json',**kw)
        assert rec['plan']['schema_version']==4 and rec['plan']['workflow']['context']['archive_group']==4
        config.write_text('schema_version=1\nprofile="quick"\n',encoding='utf-8')
        report=workflow_ns['run_replacement_approved'](rec['path'],rec['sha256'])
        assert report['workflow_audit']['passed'] and report['deleted_count']==0
        workflow_checks.append('first_empty_fixed_and_changed_config_ignored')
        rec=workflow_ns['plan_replacement'](current,new_building,folder/'wf_delete.jww',folder/'wf_delete.json',**kw)
        config.unlink();report=workflow_ns['run_replacement_approved'](rec['path'],rec['sha256'])
        assert report['workflow_audit']['passed'] and report['deleted_count']==1 and report['added_count']==1
        assert report['workflow']['settings']['effective']['old_group_action']=='delete'
        workflow_checks.append('quick_deletion_approved_plan_and_saved_group_audit')
        config.write_text('schema_version=1\n[open]\nnormalize=true\n',encoding='utf-8')
        try:workflow_ns['read_policy'](policy_folder)
        except ValueError:pass
        else:raise AssertionError('Future opening setting must be rejected')
        assert len(CadDocument.open(current).entities)==4
        assert [p.read_bytes()for p in building_paths]==original_buildings and source.read_bytes()==original
        workflow_checks.append('unknown_open_settings_refused_no_implicit_read_originals_unchanged')
        assert equivalence_ns['find_aw'](source)['complete']
        common_plan=edit_ns['prepare_move'](source,folder/'common.jww',folder/'common.plan.json',[0],[10,0])
        assert common_plan['status']=='planned'
        common_preview=edit_ns['inspect_plan'](common_plan['plan']['path'],common_plan['plan']['sha256'])
        assert common_preview['projected_counts']['modified']==1
        common_saved=edit_ns['run_approved'](common_plan['plan']['path'],common_plan['plan']['sha256'])
        assert common_saved['phase']=='verified'and common_saved['counts']['modified']==1 and source.read_bytes()==original
        # Synthetic schema0 only; never normalize a user/manufacturer drawing here.
        from jwwkit.reader.archive import read_records_bytes
        from jwwkit.writer.preserved import serialize_body
        normalization_checks=[]
        config.write_text('schema_version=2\n[opening]\nrebro_schema0="normalize"\n',encoding='utf-8')
        raw=source.read_bytes();header=raw[:read_records_bytes(raw)['header_end']]
        normal=header+serialize_body([Line((0,0),(1,1)).record(),Text((0,0),(5,0),'合成').record(),Circle((2,2),3).record()],[],700,encoding='utf-16le')
        data=bytearray(normal)
        for declaration in read_records_bytes(normal)['class_declarations']:
            struct.pack_into('<H',data,declaration['offset']+2,0)
        schema0=folder/'schema0.jww';schema0.write_bytes(data)
        standard=folder/'standard.jww';standard.write_bytes(normal)
        planned=normalization_ns['prepare_normalization'](policy_folder,[schema0,standard],folder/'normalized',folder/'normalize.plan.json')
        assert planned['plan']['schema_version']==6 and [e['status']for e in planned['plan']['entries']]==['normalize','not_needed']
        config.write_text('schema_version=2\n[opening]\nrebro_schema0="reject"\n',encoding='utf-8')
        if platform.system() == 'Windows':
            completed=normalization_ns['run_normalization_approved'](planned['plan_path'],planned['plan_sha256'])
            normalized=Path(completed['output_dir'])/completed['entries'][0]['output_name']
            assert completed['verified'] and normalized.read_bytes()==normal and schema0.read_bytes()==bytes(data)
            assert len(list(normalized.parent.glob('*.jww')))==1
            normalization_checks.append('synthetic_schema_only_mixed_noop_frozen_settings')
            edit=normalization_ns['prepare_separate_edit'](completed['result_path'],normalized,folder/'separate_edit.jww',folder/'separate_edit.plan.json',[0],[1,0])
            assert edit['plan']['schema_version']in (1,2,3,4,5) and len(edit['plan']['dependencies'])>=4
            assert not (folder/'separate_edit.jww').exists()
            normalization_checks.append('separate_edit_plan_only_with_provenance_dependencies')
        else:
            normalization_checks.append('正規化の一括確定と確定結果に基づく編集計画: 対象外（Windows専用）')
        # One synthetic workflow connects views, shape/point queries, U4 and U5.
        pipeline_checks=[]
        pipe=CadDocument.open(template_file)
        pipe.set_group_scale(0,50);pipe.set_group_scale(1,25)
        pipe.add_text((0,0),content='ＡＷ－01',units='real')
        pipe.add_text((200,0),content='aw ‐02',units='real')
        pipe.add_text((0,0),content='OTHER',layer_group=1,units='real')
        pipe.add_line((0,100),(100,100),units='real')
        pipe_source=folder/'pipeline.jww';pipe.save(pipe_source);pipe_before=pipe_source.read_bytes()
        inspection=pipeline_ns['inspect_local'](pipe_source,[0,0],group=0,tie_tolerance=0,detail_limit=1)
        assert inspection['text_match_count']==2 and inspection['text_search_complete']
        assert inspection['details']['truncated'] and inspection['closest']['complete']
        assert pipe_source.read_bytes()==pipe_before
        pipeline_checks.append('views_geometry_text_frame_and_scoped_nearest_read_only')
        planned=pipeline_ns['prepare_change'](pipe_source,folder/'pipeline_edited.jww',folder/'pipeline.plan.json',group=0,delta_real_mm=[10,0])
        assert planned['status']=='planned'and planned['projected_counts']['modified']==2
        plan_value=json.loads(Path(planned['plan']['path']).read_text(encoding='utf-8'))
        assert plan_value['schema_version']==5 and plan_value['selection']is not None
        assert not (folder/'pipeline_edited.jww').exists()
        pipeline_checks.append('explicit_equivalence_query_fixed_in_schema5_plan')
        saved=pipeline_ns['run_approved_change'](planned['plan']['path'],planned['plan']['sha256'])
        assert saved['phase']=='verified'and saved['counts']['modified']==2 and saved['counts']['unchanged']==2
        after=CadDocument.open(folder/'pipeline_edited.jww');before=CadDocument.open(pipe_source)
        assert [e.geometry['content']for e in after.entities[:2]]==['ＡＷ－01','aw ‐02']
        assert [e.raw for e in before.entities[2:]]==[e.raw for e in after.entities[2:]]
        assert pipe_source.read_bytes()==pipe_before
        pipeline_checks.append('approved_common_result_reload_original_text_and_non_targets_unchanged')
        example=folder/'example_job';example.mkdir()
        (example/'jww_workflow.toml').write_bytes(files('jwwkit').joinpath('resources', 'jww_workflow.example.toml').read_bytes())
        from jwwkit.workflow_settings import load_workflow_settings,resolve_opening_settings
        explicit=resolve_opening_settings(load_workflow_settings(example))
        assert explicit['config_snapshot']['parsed']['schema_version']==2 and explicit['effective']['rebro_schema0']=='reject'
        pipeline_checks.append('generic_settings_v2_example_defaults_to_reject')
        # Loaded project modules must come from this distribution, never another checkout.
        package_root = Path(jwwkit.__file__).resolve().parent
        for name, module in tuple(sys.modules.items()):
            path = getattr(module, "__file__", None)
            if name.startswith("jwwkit.") and path:
                assert Path(path).resolve().is_relative_to(package_root), path
        results.append('standalone_summary_cli_and_module_origins')
    return {'passed': True, 'python': platform.python_version(), 'guide_blocks_executed': len(blocks),
            'supplemental_guide_blocks_executed': supplemental,
            'new_guide_blocks_executed':new_guides,'workflow_checks':workflow_checks,'normalization_checks':normalization_checks,'pipeline_checks':pipeline_checks,'common_result_checks':['explicit_equivalence_query','schema5_preview_and_verified_common_result'],
            'checks': results, 'package_files_checked': count, 'gui_executed': False, 'business_data_used': False}
