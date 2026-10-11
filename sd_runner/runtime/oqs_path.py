"""Points liboqs-python at the liboqs library a build bundles.

``build_exe.py --with-oqs`` ships the liboqs shared library under
``<resource root>/liboqs``, in the bin/ or lib/ layout liboqs-python searches
under ``OQS_INSTALL_PATH``. liboqs-python reads the variable when
``lib.encryptor`` imports it, and the logging setup imports that module, so
the entry points call this before any other project import. For that reason it
imports nothing from the project itself.
"""

import os

#: sd_runner/runtime/ -> sd_runner/ -> the resource root.
_RESOURCE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def point_oqs_at_bundled_library() -> None:
    bundled = os.path.join(_RESOURCE_ROOT, "liboqs")
    if os.path.isdir(bundled):
        os.environ.setdefault("OQS_INSTALL_PATH", bundled)
