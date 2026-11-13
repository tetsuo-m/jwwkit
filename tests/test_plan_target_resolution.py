"""Large selections stay linear while original-lineage refusals stay strict."""
import unittest
from jwwkit.safe_edit import _apply_edit_actions

class Row:
    reads=0
    def __init__(self,index):self.index=index
    @property
    def source_index(self):Row.reads+=1;return self.index
class Cad:
    def __init__(self,indices):self.entities=tuple(Row(i) for i in indices)
    def delete_entities(self,indices):
        indices=set(indices);self.entities=tuple(e for i,e in enumerate(self.entities) if i not in indices)
def plan(indices,actions):return dict(targets=[dict(index=i,source_index=i) for i in indices],actions=actions)
def delete(indices):return dict(op='delete_entities',indices=indices,kwargs={})
class TargetResolutionTests(unittest.TestCase):
    def test_large_selection_does_not_rescan_for_every_target(self):
        c=Cad(range(4000));Row.reads=0
        _apply_edit_actions(c,plan(list(range(3999)),[delete(list(range(3999)))]))
        self.assertEqual([e.index for e in c.entities],[3999]);self.assertLess(Row.reads,8010)
    def test_index_is_rebuilt_after_prior_deletion(self):
        c=Cad(range(4));_apply_edit_actions(c,plan([0,2],[delete([0]),delete([2])]))
        self.assertEqual([e.index for e in c.entities],[1,3])
    def test_duplicate_and_missing_lineage_still_refused(self):
        for ids,selected in [([0,0],[0]),([1],[0])]:
            with self.subTest(ids=ids),self.assertRaisesRegex(ValueError,'Approved original target no longer available'):
                _apply_edit_actions(Cad(ids),plan(selected,[delete(selected)]))
    def test_deleted_target_cannot_be_reused(self):
        with self.assertRaisesRegex(ValueError,'Approved original target no longer available'):
            _apply_edit_actions(Cad(range(2)),plan([0],[delete([0]),delete([0])]))
