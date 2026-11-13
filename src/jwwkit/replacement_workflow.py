"""Explicit workflow settings and a single approval plan; never execute here."""
from pathlib import Path
import hashlib
from jwwkit.cad_model import CadDocument
from jwwkit.workflow_settings import load_workflow_settings,resolve_workflow_settings,_validate,_assert_live_snapshot
from jwwkit._replacement_contract import prepare,reference_rows,require

__all__=['replacement_reference_points','plan_building_replacement']

def replacement_reference_points(source):
    """Read group3/layer0 temporary reference points with current indices and mm."""
    return reference_rows(CadDocument.open(source))

def plan_building_replacement(source,incoming,output,plan_path,*,work_dir,source_reference_indices,target_reference_indices,
                              distance_tolerance,angle_tolerance,angle_units='deg',building_group=0,settings_policy='strict',
                              archive_group=None,instruction_overrides=None,instruction_evidence=None):
    """Create a schema4 review plan only. Config reads are explicit at this boundary."""
    from jwwkit.safe_edit import write_plan
    loaded=load_workflow_settings(work_dir)
    chat=_validate({}if instruction_overrides is None else instruction_overrides,instruction=True)
    if archive_group is not None:
        require(type(chat)is dict,'Instruction overrides must be an object')
        table=chat.setdefault('building_replacement',{});require(type(table)is dict,'Invalid instruction building_replacement')
        require('archive_group'not in table or table['archive_group']==archive_group,'Conflicting explicit archive group arguments')
        table['archive_group']=archive_group
    settings=resolve_workflow_settings(loaded,instruction_overrides=chat,instruction_evidence=instruction_evidence)
    source=Path(source).resolve();incoming=Path(incoming).resolve();output=Path(output).resolve();plan_path=Path(plan_path).resolve()
    config=Path(loaded['config_path'])
    require(all(p!=config for p in (source,incoming,output,plan_path,output.with_suffix('.changes.json'))),'Workflow configuration overlaps a drawing or plan')
    for p in (output,plan_path,output.with_suffix('.changes.json')):
        if p.exists():raise FileExistsError(p)
    cad,new=CadDocument.open(source),CadDocument.open(incoming)
    context=dict(incoming=str(incoming),building_group=building_group,source_reference_indices=list(source_reference_indices),
      target_reference_indices=list(target_reference_indices),distance_tolerance=distance_tolerance,angle_tolerance=angle_tolerance,
      angle_units=angle_units,settings_policy=settings_policy)
    proof=prepare(cad,new,settings,context)
    w=dict(schema_version=1,name='building_replacement',settings=settings,context=proof['context'],review=proof['review'])
    _assert_live_snapshot(settings)
    return write_plan(cad,proof['review']['old_target_indices'],proof['actions'],output,plan_path,dependencies=[incoming],workflow=w)
