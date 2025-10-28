"""Pytest configuration for local imports.

Ensure the repository root is on sys.path so tests can import the local
`lobx` package when pytest changes the working directory to `tests/`.
"""
import os
import sys


def _add_project_root_to_sys_path() -> None:
    current_dir = os.path.dirname(__file__)
    project_root = os.path.abspath(os.path.join(current_dir, ".."))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


_add_project_root_to_sys_path()
