import sys,struct,unittest,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from reader.archive import Cursor,RecordError,read_entity_sequences
from writer.mfc import records_bytes
from alignment import solve_two_point_alignment

class ExtendedCountTests(unittest.TestCase):
    def line(self):
        return dict(type='LINE',base=dict(group=0,pen_style=1,pen_color=1,pen_width=1,layer=0,layer_group=0,flag=0),start_x=0.,start_y=0.,end_x=1.,end_y=1.)
    def test_boundary_counts_and_shared_class_registry(self):
        for version in (600,700):
            for count in (0,65534,65535,65536):
                registry=dict(classes={},next_index=1)
                data=records_bytes([self.line()]*count,registry,version=version)+records_bytes([],registry,version=version)
                self.assertEqual(data[:2],struct.pack('<H',count if count<65535 else 65535))
                if count>=65535:self.assertEqual(struct.unpack_from('<I',data,2)[0],count)
                c=Cursor(data);rows,defs,_=read_entity_sequences(c,version)
                self.assertEqual(len(rows),count);self.assertFalse(defs);self.assertEqual(c.pos,len(data))
                reg=dict(classes={},next_index=1)
                self.assertEqual(records_bytes(rows,reg,version=version)+records_bytes(defs,reg,version=version),data)
    def test_nested_definition_extended_children(self):
        child=self.line()
        definition=dict(type='BLOCK_DEF',base=child['base'],number=1,is_referenced=False,timestamp=0,name='TEST',entities=[child]*65535)
        reg=dict(classes={},next_index=1)
        data=records_bytes([],reg)+records_bytes([definition],reg)
        c=Cursor(data);rows,defs,_=read_entity_sequences(c,700)
        self.assertFalse(rows);self.assertEqual(len(defs[0]['entities']),65535)
        reg=dict(classes={},next_index=1)
        self.assertEqual(records_bytes(rows,reg)+records_bytes(defs,reg),data)
    def test_old_jws_count_scope_not_expanded(self):
        for version in (230,351,420):
            with self.assertRaises(ValueError):records_bytes([self.line()]*65535,version=version)
            with self.assertRaises(RecordError):read_entity_sequences(Cursor(struct.pack('<HI',65535,65535)),version)
    def test_bad_extended_counts_fail_bounded(self):
        for data in (b'\xff\xff',b'\xff\xff\x00',struct.pack('<HI',65535,1),struct.pack('<HI',65535,0xffffffff),struct.pack('<HI',65535,1000000),b'\x01\x00'):
            with self.assertRaises(RecordError):read_entity_sequences(Cursor(data),700)
    def test_angular_tolerance_endpoint_displacement_and_no_default(self):
        r=solve_two_point_alignment([[0,0],[10000,0]],[[0,0],[10000,0]],distance_tolerance=1,angle_tolerance=.0001)
        self.assertAlmostEqual(r['reference_angle_tolerance_rad'],.0001)
        self.assertAlmostEqual(r['angle_tolerance_endpoint_displacement_mm'],2*10000*math.sin(.0001/2))
        self.assertAlmostEqual(r['angle_tolerance_lateral_mm'],10000*math.sin(.0001))
        self.assertAlmostEqual(r['reference_angle_tolerance_deg'],.005729577951308233)

if __name__=='__main__':unittest.main()
