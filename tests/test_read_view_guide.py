"""Execute the U1 guide on a synthetic input and verify the source is unchanged."""
from pathlib import Path
import hashlib,json,os,re,sys,tempfile,unittest
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'src'))
from cad_model import CadDocument

class ReadViewGuideTests(unittest.TestCase):
    def test_all_guide_code_blocks_execute(self):
        with tempfile.TemporaryDirectory()as tmp:
            folder=Path(tmp);source=folder/'input.jww'
            doc=CadDocument.open(R/'src/resources/empty_template.jww');doc.add_line((0,0),(10,20));doc.save(source)
            before=source.read_bytes();blocks=re.findall(r'```python\n(.*?)```',(R/'docs/read_view.md').read_text(encoding='utf-8'),re.S)
            self.assertEqual(len(blocks),1);old=Path.cwd()
            try:
                os.chdir(folder)
                for block in blocks:exec(compile(block,'docs/read_view.md','exec'),{})
            finally:os.chdir(old)
            result=json.loads((folder/'inspection.json').read_text(encoding='utf-8'))
            self.assertEqual(result['summary']['total'],1)
            self.assertEqual(result['same_item']['kind'],'line')
            self.assertEqual(result['reference']['source_sha256'],hashlib.sha256(before).hexdigest())
            self.assertEqual(source.read_bytes(),before)
