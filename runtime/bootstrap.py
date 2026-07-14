from __future__ import annotations

import importlib

PART_MODULES = (
    "constants",
    "text_context",
    "prompt_pack",
    "skills",
    "memory_store",
    "memory_cards",
    "portfolio",
    "search_graph",
    "branch_policy",
    "codex_cli",
    "eda",
    "validation",
    "runner",
)

_modules = [importlib.import_module(f"{__package__}.{name}") for name in PART_MODULES]
_namespace = {}
for _module in _modules:
    for _name, _value in _module.__dict__.items():
        if not _name.startswith("__"):
            _namespace[_name] = _value

# Each component was split out of a formerly single module. Updating component
# globals preserves direct function calls while keeping the code physically
# navigable by responsibility.
for _module in _modules:
    _module.__dict__.update(_namespace)

globals().update(_namespace)
__all__ = sorted(k for k in _namespace if not k.startswith("_"))
