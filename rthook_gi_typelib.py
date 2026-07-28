# PyInstaller runtime hook — runs INSIDE the frozen app, before any user
# code (and therefore before "import pyatspi" / "import gi") executes.
#
# Purpose: tell PyGObject (gi) where to find the bundled .typelib files
# (Atspi-2.0.typelib, GLib-2.0.typelib, etc.) that drm_log_plotter_audio_
# linux.spec copies into a 'gi_typelibs' folder inside the bundle. Without
# this, gi.repository would only look in the system's default typelib
# path, which does not exist inside a onefile PyInstaller bundle at
# runtime — it must be told explicitly via GI_TYPELIB_PATH.
#
# sys._MEIPASS is the temp folder PyInstaller extracts a onefile bundle
# into at startup — only exists inside a frozen app, hence the getattr
# fallback (harmless no-op when run as plain .py during development).

import os
import sys

_meipass = getattr(sys, '_MEIPASS', None)
if _meipass:
    _typelib_dir = os.path.join(_meipass, 'gi_typelibs')
    if os.path.isdir(_typelib_dir):
        _existing = os.environ.get('GI_TYPELIB_PATH', '')
        os.environ['GI_TYPELIB_PATH'] = (
            _typelib_dir + (os.pathsep + _existing if _existing else '')
        )
