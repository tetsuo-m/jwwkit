from jwwkit import template_path
"""Independent synthetic primitives. No answer/question drawing is read by unit tests."""
import copy,math,unittest
from jwwkit.cad_model import CadDocument
from jwwkit.line_document import Line,Circle,Text,Point
from jwwkit.model.common_entities import model_entity
from jwwkit.tategu_recognition import recognize_planar_tategu,tategu_input_fingerprint


def swing(w=930,d=80,f=40):
    return [Line((0,0),(-w,0)),Circle((0,0),w,start_angle=math.pi/2,arc_angle=math.pi/2,is_full_circle=False),
        Line((d,w+f),(d,w)),Line((0,w+f),(d,w+f)),Line((0,w),(0,w+f)),Line((d,w),(0,w)),
        Line((0,0),(0,w)),Line((d/4,0),(d/4,w)),Line((0,0),(d,0)),
        Line((0,-f),(0,0)),Line((d,-f),(0,-f)),Line((d,0),(d,-f))]


def fixed(w=1450,d=90,f=30):
    return [Line((0,0),(w,0)),Line((0,d),(w,d)),Line((0,d*.45),(w,d*.45)),
        Line((0,0),(0,d)),Line((w,0),(w,d)),Line((-f,0),(-f,d)),Line((w+f,0),(w+f,d)),
        Line((-f,0),(0,0)),Line((-f,d),(0,d)),Line((w,0),(w+f,0)),Line((w,d),(w+f,d))]


def sliding(w=1370,d=84,f=42):
    records=fixed(w,d,f);overlap=36
    records += [Line((0,d*.3),(w/2+overlap/2,d*.3)),Line((w/2-overlap/2,d*.7),(w,d*.7)),
        Line((w/2+overlap/2,d*.3),(w/2+overlap/2,d*.5)),
        Line((w/2-overlap/2,d*.5),(w/2-overlap/2,d*.7)),
        Line((w/2,-d*.3),(w/2,d*1.3))]
    return records


def sliding_profiles(w=1540,d=88,f=36):
    out=[]
    for lo,hi in ((-f,0),(w,w+f)):
        out.extend([Line((lo,0),(hi,0)),Line((lo,d),(hi,d)),Line(((lo+hi)/2,0),((lo+hi)/2,d))])
    low,high=w/2-20,w/2+20
    out.extend([Line((15,d*.35),(low,d*.35)),Line((high,d*.65),(w-15,d*.65)),
        Line((low,d*.2),(low,d*.8)),Line((high,d*.2),(high,d*.8)),
        Line((low,d*.2),(high,d*.2)),Line((low,d*.8),(high,d*.8))])
    # Tie rails to jambs geometrically, without changing the clear-facing arm ends.
    out.extend([Line((-f/2,0),(-f/2,d*.35)),Line((-f/2,d*.35),(15,d*.35)),
        Line((w-15,d*.65),(w+f/2,d*.65)),Line((w+f/2,d*.65),(w+f/2,d))])
    return out


def fold(w=1110):
    out=[Line((0,0),(0,w)),Line((-60,w/2),(60,w/2))]
    for top in (False,True):
        for offset in (0,70):
            pts=[(0,offset),(-250,70+offset),(-244,92+offset),(6,22+offset)]
            if top:pts=[(x,w-y)for x,y in pts]
            out.extend(Line(pts[i],pts[(i+1)%4])for i in range(4))
    return out


def scene(parts,*,marked=False,angle=0,mirror=False,scale=1,translation=(0,0)):
    doc=CadDocument.open(template_path());doc.set_group_scale(0,scale)
    records=[];cs=math.cos(angle);sn=math.sin(angle)
    def p(x,y):
        if mirror:y=-y
        return ((x*cs-y*sn+translation[0])/scale,(x*sn+y*cs+translation[1])/scale)
    for part in parts:
        r=part.record();kind=r['type']
        r['base']['flag']=(4096 if kind=='LINE'else 128)if marked else 0
        if kind=='LINE':
            for x,y in (('start_x','start_y'),('end_x','end_y')):r[x],r[y]=p(r[x],r[y])
        else:
            r['center_x'],r['center_y']=p(r['center_x'],r['center_y']);r['radius']/=scale
            if mirror:r['start_angle']=-r['start_angle'];r['arc_angle']=-r['arc_angle']
            r['tilt_angle']=angle
        records.append(r)
    doc.entities=tuple(model_entity(r,source_index=i)for i,r in enumerate(records))
    return doc


def options(doc):
    return dict(schema_version=1,binding=dict(kind='memory_model',sha256=tategu_input_fingerprint(doc,binding='memory_model')),
        coincidence_mm=.1,width_error_mm=1.,position_error_mm=1.,angle_rule='atan(epsilon/longer_length)')


class TateguTests(unittest.TestCase):
    def test_independent_unmarked_five_patterns(self):
        for make,kind,width in ((swing,'開戸',930),(fixed,'フィックス',1450),(fold,'折れ戸',1110),
                                 (sliding,'引き違い窓',1370),(sliding_profiles,'引き違い窓',1540)):
            with self.subTest(kind=kind,width=width):
                doc=scene(make());before=copy.deepcopy(doc.__dict__)
                result=recognize_planar_tategu(doc,tolerances=options(doc))
                self.assertTrue(result['complete'],result)
                self.assertEqual(len(result['recognized_candidates']),1,result)
                candidate=result['recognized_candidates'][0]
                self.assertEqual(candidate['type_candidates'],[kind]);self.assertAlmostEqual(candidate['clear_width_mm'],width,places=8)
                self.assertEqual(candidate['candidate_source'],'unmarked_geometry')
                self.assertEqual(doc.__dict__,before)

    def test_rotated_reflected_translated_and_group_scales(self):
        for make,kind,width in ((swing,'開戸',930),(fixed,'フィックス',1450),(fold,'折れ戸',1110),(sliding,'引き違い窓',1370)):
            for angle in (-135,-17,35,90,179):
                for mirror in (False,True):
                    with self.subTest(kind=kind,angle=angle,mirror=mirror):
                        doc=scene(make(),angle=math.radians(angle),mirror=mirror,scale=70,translation=(2345,-678))
                        result=recognize_planar_tategu(doc,tolerances=options(doc))
                        self.assertTrue(result['complete'],result)
                        self.assertEqual(len(result['recognized_candidates']),1,result)
                        candidate=result['recognized_candidates'][0]
                        self.assertEqual(candidate['type_candidates'],[kind]);self.assertAlmostEqual(candidate['clear_width_mm'],width,places=7)
                        origin=(40,465)if kind=='開戸'else (0,555)if kind=='折れ戸'else (width/2,45 if kind=='フィックス'else 42)
                        x,y=origin
                        if mirror:y=-y
                        a=math.radians(angle)
                        expected=(x*math.cos(a)-y*math.sin(a)+2345,x*math.sin(a)+y*math.cos(a)-678)
                        self.assertLess(math.dist(candidate['position_real_mm'],expected),1e-7)

    def test_curve_group_is_never_required_or_a_type_id(self):
        doc=scene(sliding(),marked=True);a=recognize_planar_tategu(doc,tolerances=options(doc))
        for i,e in enumerate(doc.entities):e.attributes['group']=1234 if i%2 else 9876
        b=recognize_planar_tategu(doc,tolerances=options(doc))
        for result in (a,b):
            self.assertFalse(result['group_numbers_used_for_classification'])
            self.assertEqual(result['recognized_candidates'][0]['clear_width_mm'],1370)
            self.assertEqual(result['recognized_candidates'][0]['type_candidates'],['引き違い窓'])
        self.assertEqual(a['recognized_candidates'][0]['element_indices'],b['recognized_candidates'][0]['element_indices'])

    def test_marker_bits_are_typed_and_used_through_query(self):
        doc=scene(swing(),marked=True);r=recognize_planar_tategu(doc,tolerances=options(doc))
        self.assertEqual(len(r['marked_element_indices']),len(doc.entities));self.assertIn('flag_bits',str(r['typed_flag_query']))
        self.assertEqual(r['recognized_candidates'][0]['candidate_source'],'typed_flag_bits')
        for e in doc.entities:e.attributes['flag']=0
        r=recognize_planar_tategu(doc,tolerances=options(doc),include_unmarked=False)
        self.assertEqual(r['recognized_candidates'],[])

    def test_new_input_or_changed_model_needs_its_own_binding(self):
        a=scene(fixed());b=scene(fixed(w=1460))
        with self.assertRaisesRegex(ValueError,'different input'):recognize_planar_tategu(b,tolerances=options(a))
        with self.assertRaises(ValueError):recognize_planar_tategu(a,tolerances={})
        config=options(a);config['expected_widths']=[1450]
        with self.assertRaises(ValueError):recognize_planar_tategu(a,tolerances=config)
        for invalid in (True,-1,float('nan')):
            config=options(a);config['coincidence_mm']=invalid
            with self.assertRaises(ValueError):recognize_planar_tategu(a,tolerances=config)

    def test_outer_bounds_are_not_clear_width(self):
        doc=scene(fixed(w=1437,d=90,f=47));r=recognize_planar_tategu(doc,tolerances=options(doc))
        c=r['recognized_candidates'][0]
        self.assertAlmostEqual(c['clear_width_mm'],1437);self.assertNotEqual(c['clear_width_mm'],1531)
        doc=scene(swing(w=927,d=80,f=43));r=recognize_planar_tategu(doc,tolerances=options(doc))
        self.assertAlmostEqual(r['recognized_candidates'][0]['clear_width_mm'],927)

    def test_radius_without_jambs_is_ambiguous_not_a_clear_width(self):
        doc=scene(swing()[:2]);r=recognize_planar_tategu(doc,tolerances=options(doc))
        self.assertFalse(r['complete']);c=r['recognized_candidates'][0]
        self.assertEqual(c['type_candidates'],['開戸']);self.assertIsNone(c['clear_width_mm']);self.assertTrue(c['ambiguities'])

    def test_duplicate_geometry_does_not_become_a_confident_single_symbol(self):
        parts=fixed();doc=scene(parts+parts);r=recognize_planar_tategu(doc,tolerances=options(doc))
        self.assertFalse(r['complete']);self.assertTrue(r['recognized_candidates'][0]['ambiguities'])

    def test_large_plain_rectangle_is_not_a_building_opening(self):
        pts=[(0,0),(12000,0),(12000,9000),(0,9000)]
        doc=scene([Line(pts[i],pts[(i+1)%4])for i in range(4)])
        r=recognize_planar_tategu(doc,tolerances=options(doc))
        self.assertEqual(r['recognized_candidates'],[]);self.assertEqual(len(r['excluded']),1)

    def test_unverified_ellipse_and_geometry_limits_are_explicit(self):
        parts=swing();parts[1].flatness=.8;doc=scene(parts,marked=True)
        r=recognize_planar_tategu(doc,tolerances=options(doc));self.assertFalse(r['complete']);self.assertTrue(r['unsupported'])
        doc=scene(fixed())
        with self.assertRaisesRegex(ValueError,'pair limit'):recognize_planar_tategu(doc,tolerances=options(doc),max_candidate_pairs=1)

    def test_multiple_type_hypotheses_are_preserved(self):
        from jwwkit.tategu_recognition import _deduplicate
        a=dict(type_candidates=['開戸'],position_real_mm=[0,0],clear_width_mm=900,element_indices=[1,2,3],evidence=['arc'],ambiguities=[])
        b=dict(a,type_candidates=['折れ戸'],evidence=['diagonals'],clear_width_mm=850)
        result=_deduplicate([a,b],.1,1)
        self.assertEqual(result[0]['type_candidates'],['折れ戸','開戸']);self.assertIsNone(result[0]['clear_width_mm'])
        self.assertEqual(len(result[0]['alternatives']),2);self.assertTrue(result[0]['ambiguities'])

    def test_input_model_and_file_are_not_written(self):
        from unittest.mock import patch
        doc=scene(fixed());config=options(doc)
        with patch.object(CadDocument,'save',side_effect=AssertionError('Recognition must not save')):
            self.assertTrue(recognize_planar_tategu(doc,tolerances=config)['complete'])


if __name__=='__main__':unittest.main()

