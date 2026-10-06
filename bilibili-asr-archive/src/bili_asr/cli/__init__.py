"""Public CLI entry points and command subsystem handles."""

from . import main as main
from . import signals as _signals_module
from .signals import _signals_ignored
import sys
import types


class _CliModule(types.ModuleType):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name == "_signals_ignored":
            _signals_module._signals_ignored = value


sys.modules[__name__].__class__ = _CliModule
from bili_asr.cli.parser import build_parser
from bili_asr import search_index

__all__ = ["main", "build_parser"]
