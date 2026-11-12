from pathlib import Path
import tempfile,re,sys,unittest
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'src'))
from cad_model import CadDocument

class GuideTests(unittest.TestCase):
    def test_all_guide_code_on_synthetic_data(self):
        codes=re.findall(r'```python\n(.*?)\n```',(R/'docs/text_equivalence.md').read_text(encoding='utf-8'),re.S)
        self.assertEqual(len(codes),1);ns={}
        for code in codes:exec(compile(code,'text_equivalence.md','exec'),ns)
        with tempfile.TemporaryDirectory()as temp:
            p=Path(temp)/'sample.jww';d=CadDocument.open(R/'src/resources/empty_template.jww')
            for t in ('ＡＷ－01','aw ‐02','BW-03'):d.add_text((0,0),content=t)
            d.save(p);raw=p.read_bytes();r=ns['find_aw'](p)
            self.assertEqual(r['match_count'],2);self.assertEqual(raw,p.read_bytes())
