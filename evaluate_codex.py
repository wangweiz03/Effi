#!/usr/bin/env python3
"""Thin entrypoint for BSPM Codex v4.

The runtime is split under runtime/ so branch policy, prompt packing, memory,
EDA, validation, memory, branch policy, and runner logic can be inspected independently.
"""
from runtime.bootstrap import *  # re-export old public helpers for compatibility


if __name__ == "__main__":
    cli_main()
