"""Run the bundled Ink/Stitch engine headless (no Inkscape, no wxPython window toolkit)."""
import os
import sys
import types
import runpy
import importlib.abc
import importlib.machinery

ENGINE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'inkstitch_engine')


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _make(name)

    def __or__(cls, other):
        return 0

    def __ror__(cls, other):
        return 0


def _make(name):
    return _Meta(name, (object,), {
        '__init__': lambda self, *a, **k: None,
        '__call__': lambda self, *a, **k: None,
        '__getattr__': lambda self, n: _make(n),
        '__class_getitem__': classmethod(lambda cls, item: cls),
    })


class _Stub(types.ModuleType):
    __path__ = []

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _make(name)


class _Finder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Ink/Stitch imports its GUI toolkit (wx) everywhere; give it an inert stand-in."""

    def find_spec(self, fullname, path, target=None):
        if fullname == 'wx' or fullname.startswith('wx.'):
            return importlib.machinery.ModuleSpec(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        return _Stub(spec.name)

    def exec_module(self, module):
        pass


if __name__ == '__main__':
    sys.meta_path.insert(0, _Finder())
    sys.path.insert(0, ENGINE)
    sys.argv[0] = os.path.join(ENGINE, 'inkstitch.py')
    runpy.run_path(sys.argv[0], run_name='__main__')
