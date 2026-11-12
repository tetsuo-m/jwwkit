import re,sys,tempfile,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'src'))
from cad_model import CadDocument
class GuideTests(unittest.TestCase):
    def test_all_guide_blocks_are_executed_on_synthetic_files(self):
        blocks=re.findall(r'```python\n(.*?)\n```',(R/'docs/edit_results.md').read_text(encoding='utf-8'),re.S);self.assertEqual(len(blocks),1);ns={}
        for code in blocks:exec(compile(code,'edit_results.md','exec'),ns)
        with tempfile.TemporaryDirectory()as temp:
            p=Path(temp);d=CadDocument.open(R/'src/resources/empty_template.jww');d.add_line((0,0),(10,0));d.save(p/'input.jww')
            raw=(p/'input.jww').read_bytes();r=ns['prepare_move'](p/'input.jww',p/'out.jww',p/'plan.json',[0],[10,0])
            self.assertEqual(r['status'],'planned');self.assertFalse((p/'out.jww').exists())
            preview=ns['inspect_plan'](r['plan']['path'],r['plan']['sha256']);self.assertEqual(preview['projected_counts']['modified'],1)
            done=ns['run_approved'](r['plan']['path'],r['plan']['sha256']);self.assertEqual(done['phase'],'verified');self.assertEqual(raw,(p/'input.jww').read_bytes())
