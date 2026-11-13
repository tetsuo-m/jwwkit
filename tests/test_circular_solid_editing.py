"""Circular-solid editing preserves every non-target field and refuses unknown forms."""
import copy,math,tempfile,unittest
from dataclasses import replace
from pathlib import Path
from jwwkit.cad_model import CadDocument
from jwwkit.line_document import JwwDocument
from jwwkit.safe_edit import snapshot,write_plan,execute_plan
from jwwkit.writer.preserved import entity_record

class CircularSolidEditingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.folder=Path(self.tmp.name);self.source=self.folder/'input.jww'
  new=JwwDocument();new.set_group_scale(0,50);new.set_group_scale(1,25);new.save(self.source)
  cad=CadDocument.open(self.source)
  cad.add_circle_solid((500,1000),100,units='real',flatness=.7,tilt_angle=.4,solid_mode=5,start_angle=.2,arc_angle=1.5,flag=2048,layer=3,color=7,width=2)
  cad.add_circle_solid((1500,1000),200,units='real',flatness=.6,solid_mode=100,color=10,rgb=0x123456,layer=4,width=3)
  cad.add_line((0,0),(1000,0),units='real',layer_group=1)
  self.source=self.folder/'original.jww';cad.save(self.source);self.original=self.source.read_bytes();self.cad=CadDocument.open(self.source)
 def test_move_single_and_multiple_preserve_shape_fill_and_rgb(self):
  before=[entity_record(e) for e in self.cad.entities]
  self.cad.move_entity(0,(100,-200),units='real')
  self.cad.move_entities([0,1],(50,75),units='real')
  for i,delta in [(0,(3,-2.5)),(1,(1,1.5))]:
   expected=copy.deepcopy(before[i]);expected['center_x']+=delta[0];expected['center_y']+=delta[1]
   self.assertEqual(entity_record(self.cad.entities[i]),expected)
  self.assertEqual(entity_record(self.cad.entities[2]),before[2])
 def test_group_transfer_real_preserves_world_boundary_and_all_other_fields(self):
  before=entity_record(self.cad.entities[0])
  self.cad.set_entity_attributes(0,layer_group=1,layer=8,color=6,width=4,preserve='real')
  actual=entity_record(self.cad.entities[0]);expected=copy.deepcopy(before)
  for key in ('center_x','center_y','radius'):expected[key]*=2
  expected['base'].update(layer_group=1,layer=8,pen_color=6,pen_width=4)
  self.assertEqual(actual,expected)
  for angle in (.2,.7,1.7):
   g,h=before,actual
   def point(r,scale):
    u=r['radius']*math.cos(angle);v=r['radius']*r['flatness']*math.sin(angle);t=r['tilt_angle']
    return ((r['center_x']+math.cos(t)*u-math.sin(t)*v)*scale,(r['center_y']+math.sin(t)*u+math.cos(t)*v)*scale)
   self.assertEqual(point(g,50),point(h,25))
 def test_paper_transfer_keeps_geometry_and_rgb(self):
  before=entity_record(self.cad.entities[1]);self.cad.set_entity_attributes(1,layer_group=1,layer=9,preserve='paper',linetype=101)
  expected=copy.deepcopy(before);expected['base'].update(layer_group=1,layer=9)
  self.assertEqual(entity_record(self.cad.entities[1]),expected)
 def test_invalid_style_color_or_rgb_storage_switch_is_atomic(self):
  for index,kwargs in [(0,dict(linetype=1)),(0,dict(color=10)),(1,dict(color=7)),(0,dict(color=0)),(0,dict(color=11)),(0,dict(layer_group=16)),(0,dict(width=65536))]:
   before=snapshot(self.cad)
   with self.assertRaises(ValueError):self.cad.set_entity_attributes(index,**kwargs)
   self.assertEqual(snapshot(self.cad),before)
 def test_unobserved_fill_flag_or_style_remains_preservation_only(self):
  original=self.cad.entities[0]
  for changed in [replace(original,geometry=dict(original.geometry,solid_mode=0)),replace(original,attributes=dict(original.attributes,flag=2)),replace(original,attributes=dict(original.attributes,pen_style=105))]:
   self.cad.entities=(changed,*self.cad.entities[1:]);before=snapshot(self.cad)
   for operation in [lambda:self.cad.move_entity(0,(1,0)),lambda:self.cad.set_entity_attributes(0,layer=8)]:
    with self.assertRaises(ValueError):operation()
    self.assertEqual(snapshot(self.cad),before)
  self.assertEqual(self.source.read_bytes(),self.original)
 def test_mixed_bulk_move_refusal_commits_nothing(self):
  bad=replace(self.cad.entities[1],geometry=dict(self.cad.entities[1].geometry,solid_mode=0))
  self.cad.entities=(self.cad.entities[0],bad,self.cad.entities[2]);before=snapshot(self.cad)
  with self.assertRaises(ValueError):self.cad.move_entities([0,1],(10,0))
  self.assertEqual(snapshot(self.cad),before)
 def test_plan_approval_save_reload_and_non_target(self):
  actions=[dict(op='move_entities',indices=[0,1],kwargs=dict(delta=[100,200],units='real')),
           dict(op='set_entity_attributes',indices=[0],kwargs=dict(layer_group=1,layer=8,color=6,width=4,preserve='real')),
           dict(op='set_entity_attributes',indices=[1],kwargs=dict(layer_group=1,layer=9,preserve='real'))]
  receipt=write_plan(self.cad,[0,1],actions,self.folder/'edited.jww',self.folder/'plan.json')
  self.assertEqual(self.source.read_bytes(),self.original);self.assertFalse((self.folder/'edited.jww').exists())
  report=execute_plan(receipt['path'],approved_sha256=receipt['sha256']);saved=CadDocument.open(self.folder/'edited.jww')
  self.assertEqual(report['modified_count'],2);self.assertEqual(report['added_count'],0);self.assertEqual(report['deleted_count'],0)
  self.assertEqual(entity_record(saved.entities[2]),entity_record(self.cad.entities[2]))
  self.assertEqual(saved.entities[1].geometry['color'],0x123456);self.assertEqual(self.source.read_bytes(),self.original)
 def test_plan_late_rgb_rejection_leaves_source_unchanged_and_no_output(self):
  with self.assertRaises(ValueError):write_plan(self.cad,[0,1],[dict(op='move_entities',indices=[0],kwargs=dict(delta=[10,0])),dict(op='set_entity_attributes',indices=[1],kwargs=dict(color=7))],self.folder/'refused.jww',self.folder/'refuse.json')
  self.assertFalse((self.folder/'refuse.json').exists())
  self.assertFalse((self.folder/'refused.jww').exists());self.assertEqual(self.source.read_bytes(),self.original)

if __name__=='__main__':unittest.main()
