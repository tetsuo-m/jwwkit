"""Internal boundary for the required ezjww 0.2.13 reader.

This is a transparent adapter, not a new parser or validation policy.
See docs/ezjww_adapter_contract.md for the consumed result contract.
Keep the import eager: making the dependency optional belongs to a later design.
"""
import ezjww as _ezjww


def read_native_document(path):
    """Delegate once; preserve the native result object and exception unchanged."""
    return _ezjww.read_document(str(path))
