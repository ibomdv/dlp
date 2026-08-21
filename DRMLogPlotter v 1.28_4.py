#!/usr/bin/env python3
"""
DRM-Log Plotter - Python Rebuild
Code Base is 100% rebuild and created by CLAUDE.AI
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import csv, os, re, json, math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib
matplotlib.use('TkAgg')
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np

# ══════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════
APP_TITLE       = "DRMLogPlotter rebuild - Version 1.28"
VERSION         = "Based on Original DRM-Log Plotter v. 22.1 (Python Rebuild by CLAUDE.AI)"

# ── Absolute base directory — works for .py, compiled .exe/.bin, AppImage ──
# sys.frozen is set by PyInstaller/auto-py-to-exe when running as .exe/.bin
import sys as _sys
if os.environ.get('APPIMAGE'):
    # Running as AppImage — mount point is read-only.
    # Use ~/.local/share/drm_log_plotter/ for all user data.
    BASE_DIR = os.path.join(os.path.expanduser('~'),
                            '.local', 'share', 'drm_log_plotter')
    os.makedirs(BASE_DIR, exist_ok=True)
elif getattr(_sys, 'frozen', False):
    # Running as compiled .exe (Windows) or .bin (Linux).
    # sys.executable points to temp dir on Windows onefile builds!
    # sys.argv[0] always points to the real executable location.
    BASE_DIR = os.path.dirname(os.path.abspath(_sys.argv[0]))
else:
    # Running as .py script.
    # __file__ can be wrong under Thonny on Windows (points to Thonny dir).
    # Check if __file__ actually exists — if not, fall back to sys.argv[0].
    try:
        _file_abs = os.path.abspath(__file__)
        if os.path.isfile(_file_abs):
            BASE_DIR = os.path.dirname(_file_abs)
        else:
            BASE_DIR = os.path.dirname(os.path.abspath(_sys.argv[0]))
    except Exception:
        BASE_DIR = os.path.dirname(os.path.abspath(_sys.argv[0]))

CONFIG_FILE     = os.path.join(BASE_DIR, "drmplotter_cfg.json")
TX_SITES_FILE   = os.path.join(BASE_DIR, "drmtransmittersites.txt")
LOGFILES_DIR    = os.path.join(BASE_DIR, "logfiles")
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "screenshots")

MAX_AUDIO_FRAMES = 1500
SNR_MAX  = 45
DOPPLER_MAX  = 1.0   # 1 Hz maps to 20 dB height on the plot

import subprocess as _subprocess
import platform as _platform

DREAM_AUDIO_JSON = 'DreamAudio.json'   # filename — written alongside DreamLog.txt
DREAM_AUDIO_MAX  = 300                 # max entries — prune oldest beyond this

def _dream_audio_json_path(log_dir):
    """Full path to DreamAudio.json in the same folder as DreamLog.txt."""
    return os.path.join(log_dir, DREAM_AUDIO_JSON)

def _load_dream_audio_json(log_dir):
    """Load DreamAudio.json and return list of dicts (empty list on error)."""
    path = _dream_audio_json_path(log_dir)
    try:
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []

def _save_dream_audio_json(log_dir, entry):
    """
    Append or update one entry in DreamAudio.json.
    Key: (start_time, freq_khz) — updated if already exists.
    Prunes to DREAM_AUDIO_MAX entries (oldest first).

    MERGE, NOT OVERWRITE (added July 2026): if an entry for this
    (start_time, freq_khz) already exists, fields that were already
    successfully found ('codec'/'protection'/'audio_mode' not '—', or
    'sbr' == 'On') are preserved even if this newer read came back
    empty for that field. Confirmed necessary by testing: if the user
    covers/minimises Dream's window after codec+mode were already found,
    a later poll attempt can fail and — without this merge — would
    silently erase the already-correct values from both DreamAudio.json
    and the GUI. Each individual field can still be UPGRADED by a later,
    more complete read; only a field regressing from a real value back
    to '—'/'Off' is what gets blocked.
    """
    path  = _dream_audio_json_path(log_dir)
    data  = _load_dream_audio_json(log_dir)
    key   = (entry.get('start_time',''), entry.get('freq_khz',''))

    def _merge(old, new):
        merged = dict(new)
        for field, empty_val in (('codec', '—'), ('protection', '—'),
                                  ('audio_mode', '—'), ('sbr', 'Off')):
            if new.get(field, empty_val) == empty_val and \
               old.get(field, empty_val) != empty_val:
                merged[field] = old[field]
        return merged

    # Update existing or append new
    final_entry = entry
    for i, e in enumerate(data):
        if (e.get('start_time',''), e.get('freq_khz','')) == key:
            final_entry = _merge(e, entry)
            data[i] = final_entry
            break
    else:
        data.append(entry)
    # Prune oldest
    if len(data) > DREAM_AUDIO_MAX:
        data = data[-DREAM_AUDIO_MAX:]
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
    return final_entry

def _find_dream_audio_entry(log_dir, start_time_str, freq_khz_str):
    """
    Find matching entry in DreamAudio.json.
    Returns dict with codec/sbr/audio_mode/sample_rate or None.
    """
    data = _load_dream_audio_json(log_dir)
    for e in data:
        if (e.get('start_time','') == start_time_str and
                e.get('freq_khz','') == freq_khz_str):
            return e
    return None

def _is_dream_window(title):
    """True if title belongs to Dream — not to the plotter or other tools."""
    t = title.lower()
    return ('dream' in t and 'log plotter' not in t and
            'diagnose' not in t and 'thonny' not in t)

def _is_bitrate_protection_label(text):
    """e.g. '8.08 kbps EEP' or '11.64 kbps UEP'"""
    t = text.upper().strip()
    return 'KBPS' in t and ('EEP' in t or 'UEP' in t)

def _is_codec_label(text):
    """e.g. 'aac' or 'aac+' or 'xHE-AAC'"""
    import re as _re
    t = text.upper().strip()
    return bool(_re.search(r'\bAAC\b|XHE[\s\-]*AAC|AAC\+', t)) and \
           'KBPS' not in t

def _is_mode_label(text):
    """e.g. 'Mono' or 'Stereo'"""
    import re as _re
    t = text.upper().strip()
    return t in ('MONO', 'STEREO') or \
           bool(_re.search(r'P[\-\s]*STEREO|PARAMETRIC', t))

def _is_sbr_label(text):
    """e.g. '/ sbr' or 'sbr'"""
    import re as _re
    t = text.upper().strip()
    return bool(_re.search(r'^/?[\s]*SBR$', t))

def _assemble_dream_audio(label_list):
    """
    Combine Dream's three separate Qt labels into one result dict.
    Dream uses THREE labels not one:
      Label 1: '8.08 kbps EEP'  → bitrate + protection
      Label 2: 'aac'            → codec
      Label 3: 'Mono'           → audio mode
      Optional: '/ sbr'         → SBR active
    Returns dict or None if insufficient data.
    """
    import re as _re
    protection = '—'; codec = '—'; audio_mode = '—'; sbr = 'Off'

    for text in label_list:
        t = text.strip()
        if not t:
            continue
        if _is_bitrate_protection_label(t):
            tu = t.upper()
            protection = 'UEP' if 'UEP' in tu else 'EEP'
        elif _is_codec_label(t):
            tu = t.upper()
            if _re.search(r'XHE[\s\-]*AAC', tu): codec = 'xHE-AAC'
            elif 'AAC+' in tu:                    codec = 'AAC+'
            elif 'AAC'  in tu:                    codec = 'AAC'
        elif _is_mode_label(t):
            tu = t.upper()
            if _re.search(r'P[\-\s]*STEREO|PARAMETRIC', tu):
                audio_mode = 'P-Stereo'
            elif 'STEREO' in tu: audio_mode = 'Stereo'
            elif 'MONO'   in tu: audio_mode = 'Mono'
        elif _is_sbr_label(t):
            sbr = 'On'

    # Tab bar fallback: "TDF DRM | aac Mono (8.08 kbps) + MM ..."
    for text in label_list:
        tu = text.upper()
        if '|' in text and 'AAC' in tu and 'KBPS' in tu:
            if codec == '—':
                if _re.search(r'XHE[\s\-]*AAC', tu): codec = 'xHE-AAC'
                elif 'AAC+' in tu: codec = 'AAC+'
                elif 'AAC'  in tu: codec = 'AAC'
            if audio_mode == '—':
                if 'STEREO' in tu: audio_mode = 'Stereo'
                elif 'MONO' in tu:  audio_mode = 'Mono'
            if 'SBR' in tu:
                sbr = 'On'

    if codec == '—' and protection == '—':
        return None
    return {'codec': codec, 'protection': protection,
            'sbr': sbr, 'audio_mode': audio_mode}


def _read_dream_audio_info():
    """
    Read audio codec info from Dream's Qt window.

    Strategy:
    1. If a compiled DRMLogPlotter_Audio exists alongside this program
       (DRMLogPlotter_Audio.exe on Windows, DRMLogPlotter_Audio with no
       extension on Linux — PyInstaller default), call it as a subprocess.
       It handles QT_ACCESSIBILITY / comtypes / pyatspi in its own process
       space (avoids PyInstaller import conflicts in the main binary).
    2. Fallback: DRMLogPlotter_Audio.py via the current interpreter (works
       when running as .py, or when only the main program was compiled).
    3. Fallback: call the platform-specific functions directly (works
       when running as .py but may fail in a compiled main .exe/.bin).

    Returns dict with codec/protection/sbr/audio_mode or None on failure.
    """
    import platform as _pl
    import subprocess as _sp
    import json as _json

    # ── Try external Audio tool first ─────────────────────────────────────
    # Look for the compiled Audio helper (DRMLogPlotter_Audio.exe on
    # Windows, DRMLogPlotter_Audio with no extension on Linux), then fall
    # back to the .py source.
    #
    # Search folder — NOT simply BASE_DIR:
    #   - Running as AppImage: BASE_DIR is ~/.local/share/drm_log_plotter/
    #     (the writable data dir — see top of file), NOT the folder the
    #     .AppImage file itself sits in. DRMLogPlotter_Audio is placed next
    #     to the .AppImage file (per build.sh instructions), so we must
    #     resolve that folder separately. AppImages set the 'APPIMAGE' env
    #     var to the full path of the .AppImage file itself at runtime —
    #     use its folder instead of BASE_DIR in that case.
    #   - Everything else (plain .exe/.bin, .py): BASE_DIR is already the
    #     correct program folder.
    _audio_exe = None
    _appimage_path = os.environ.get('APPIMAGE', '').strip()
    if _appimage_path:
        _base = os.path.dirname(os.path.abspath(_appimage_path))
    else:
        _base = BASE_DIR

    if _pl.system() == 'Windows':
        _candidate = os.path.join(_base, 'DRMLogPlotter_Audio.exe')
        if os.path.isfile(_candidate):
            _audio_exe = [_candidate]
    else:
        # Linux (and other non-Windows): PyInstaller onefile binaries have
        # no extension by default — matches BUILD_NAME in
        # drm_log_plotter_audio_linux.spec.
        _candidate = os.path.join(_base, 'DRMLogPlotter_Audio')
        if os.path.isfile(_candidate):
            if not os.access(_candidate, os.X_OK):
                # Executable bit often gets lost after copying via USB
                # stick, browser download, or a network share — the user
                # rarely notices because DRMLogPlotter_Audio is never
                # launched by hand, only DRMLogPlotter itself. Try to
                # self-heal instead of silently failing every time.
                try:
                    _st = os.stat(_candidate)
                    os.chmod(_candidate, _st.st_mode | 0o111)
                except Exception:
                    pass
            if os.access(_candidate, os.X_OK):
                _audio_exe = [_candidate]
    if not _audio_exe:
        _candidate_py = os.path.join(_base, 'DRMLogPlotter_Audio.py')
        if os.path.isfile(_candidate_py):
            import sys as _sys
            _audio_exe = [_sys.executable, _candidate_py]

    if _audio_exe:
        try:
            env = os.environ.copy()
            env['QT_ACCESSIBILITY'] = '1'
            flags = 0x08000000 if _pl.system() == 'Windows' else 0
            r = _sp.run(_audio_exe, capture_output=True, text=True,
                        timeout=40, env=env,
                        creationflags=flags if _pl.system() == 'Windows' else 0)
            if r.returncode == 0 and r.stdout.strip():
                data = _json.loads(r.stdout.strip())
                if data.get('codec', '—') != '—' or \
                        data.get('protection', '—') != '—':
                    return data
                # Parsed OK but no usable codec/protection — fall through
                # to the in-process fallback below.
        except Exception:
            pass

    # ── Fallback: direct call (works under .py, may not work in .exe) ────
    if _pl.system() == 'Windows':
        return _win_read_dream_audio()
    elif _pl.system() == 'Linux':
        return _linux_read_dream_audio()
    return None


def _win_read_dream_audio():
    """Windows: UIA comtypes → pywinauto → GetWindowTextW."""
    import ctypes, ctypes.wintypes

    # ── Method A: UIA via comtypes (works with Qt5 + QT_ACCESSIBILITY=1) ──
    try:
        import comtypes.client
        try:
            from comtypes.gen import UIAutomationClient as UIA
        except ImportError:
            comtypes.client.GetModule(
                r'C:\Windows\System32\UIAutomationCore.dll')
            from comtypes.gen import UIAutomationClient as UIA
        uia  = comtypes.client.CreateObject(
            '{ff48dba4-60ef-4201-aa87-54103eef594e}',
            interface=UIA.IUIAutomation)
        cond = uia.CreateTrueCondition()
        root = uia.GetRootElement()
        tops = root.FindAll(UIA.TreeScope_Children, cond)
        dream_el = None
        for i in range(tops.Length):
            el = tops.GetElement(i)
            try:
                if _is_dream_window(el.CurrentName or ''):
                    dream_el = el
                    break
            except Exception:
                pass
        if dream_el:
            els    = dream_el.FindAll(UIA.TreeScope_Descendants, cond)
            labels = []
            for i in range(els.Length):
                el = els.GetElement(i)
                try:
                    name = el.CurrentName or ''
                    if name:
                        labels.append(name)
                    try:
                        vp  = el.GetCurrentPattern(10002)
                        val = vp.CurrentValue or ''
                        if val and val not in labels:
                            labels.append(val)
                    except Exception:
                        pass
                except Exception:
                    pass
            result = _assemble_dream_audio(labels)
            if result:
                return result
    except ImportError:
        pass
    except Exception:
        pass

    # ── Method B: pywinauto ────────────────────────────────────────────
    try:
        from pywinauto import Desktop
        for win in Desktop(backend='uia').windows():
            try:
                if not _is_dream_window(win.window_text()):
                    continue
                labels = []
                for ctrl in win.descendants():
                    try:
                        t = ctrl.window_text()
                        if t:
                            labels.append(t)
                    except Exception:
                        pass
                result = _assemble_dream_audio(labels)
                if result:
                    return result
            except Exception:
                pass
    except ImportError:
        pass
    except Exception:
        pass

    # ── Method C: GetWindowTextW (fallback — rarely works with Qt5) ───
    try:
        user32  = ctypes.windll.user32
        GetText = user32.GetWindowTextW
        GetLen  = user32.GetWindowTextLengthW
        PROC    = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                      ctypes.wintypes.HWND,
                                      ctypes.wintypes.LPARAM)
        def _get(hwnd):
            n = GetLen(hwnd)
            if n == 0: return ''
            b = ctypes.create_unicode_buffer(n + 1)
            GetText(hwnd, b, n + 1)
            return b.value

        dream_hwnd = [None]
        def _top(hwnd, _):
            if _is_dream_window(_get(hwnd)):
                dream_hwnd[0] = hwnd
                return False
            return True
        user32.EnumWindows(PROC(_top), 0)
        if dream_hwnd[0]:
            labels = []
            def _child(hwnd, _):
                t = _get(hwnd)
                if t:
                    labels.append(t)
                return True
            user32.EnumChildWindows(dream_hwnd[0], PROC(_child), 0)
            result = _assemble_dream_audio(labels)
            if result:
                return result
    except Exception:
        pass
    return None


def _linux_read_dream_audio():
    """Linux: AT-SPI → wmctrl → xdotool."""
    import subprocess as _sp

    # ── Method A: AT-SPI via pyatspi (proven by diagnose report) ──────
    try:
        import pyatspi
        desktop = pyatspi.Registry.getDesktop(0)
        for i in range(desktop.childCount):
            app = desktop.getChildAtIndex(i)
            try:
                if 'dream' not in (app.name or '').lower():
                    continue
                if not _is_dream_window(app.name or ''):
                    continue
                labels = []
                def _walk(obj):
                    try:
                        name = obj.name or ''
                        if name:
                            labels.append(name)
                        try:
                            ti   = obj.queryText()
                            text = ti.getText(0, ti.characterCount)
                            if text and text not in labels:
                                labels.append(text)
                        except Exception:
                            pass
                        for j in range(obj.childCount):
                            _walk(obj.getChildAtIndex(j))
                    except Exception:
                        pass
                _walk(app)
                result = _assemble_dream_audio(labels)
                if result:
                    return result
            except Exception:
                pass
    except ImportError:
        pass
    except Exception:
        pass

    # ── Method B: wmctrl ───────────────────────────────────────────────
    try:
        out = _sp.run(['wmctrl', '-l'], capture_output=True,
                      text=True, timeout=3).stdout
        labels = []
        for line in out.splitlines():
            if 'dream' in line.lower() and \
                    'log plotter' not in line.lower():
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    labels.append(parts[-1])
        result = _assemble_dream_audio(labels)
        if result:
            return result
    except Exception:
        pass

    # ── Method C: xdotool ──────────────────────────────────────────────
    try:
        ids = _sp.run(['xdotool', 'search', '--name', 'dream'],
                      capture_output=True, text=True, timeout=3).stdout
        labels = []
        for wid in ids.strip().splitlines():
            name = _sp.run(['xdotool', 'getwindowname', wid.strip()],
                           capture_output=True, text=True,
                           timeout=3).stdout.strip()
            if name and _is_dream_window(name):
                labels.append(name)
        result = _assemble_dream_audio(labels)
        if result:
            return result
    except Exception:
        pass
    return None

class ToolTip:
    """
    Simple tooltip for tkinter widgets.
    Shows a small yellow popup window when the mouse hovers over a widget.
    Usage: ToolTip(widget, text='your tooltip text')
    """
    def __init__(self, widget, text=''):
        self.widget  = widget
        self.text    = text
        self.tip_win = None
        widget.bind('<Enter>',  self._show)
        widget.bind('<Leave>',  self._hide)
        widget.bind('<Button>', self._hide)

    def _show(self, event=None):
        if self.tip_win or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip_win = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)   # no window border/title bar
        tw.wm_geometry(f'+{x}+{y}')
        tw.wm_attributes('-topmost', True)
        tk.Label(tw, text=self.text, justify=tk.LEFT,
                 background='#ffffe0', relief=tk.SOLID, borderwidth=1,
                 font=('Arial', 9)).pack(ipadx=4, ipady=2)

    def _hide(self, event=None):
        if self.tip_win:
            self.tip_win.destroy()
            self.tip_win = None


def _subprocess_run(cmd, **kwargs):
    """
    Wrapper around subprocess.run that adds CREATE_NO_WINDOW on Windows
    to prevent console windows flashing in compiled .exe builds.
    creationflags is a Windows-only parameter — never passed on Linux/macOS.
    """
    if _platform.system() == 'Windows':
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | 0x08000000
    return _subprocess.run(cmd, **kwargs)

def _subprocess_call(cmd, **kwargs):
    """Same as _subprocess_run but for subprocess.call."""
    if _platform.system() == 'Windows':
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | 0x08000000
    return _subprocess.call(cmd, **kwargs)


def _is_linux_wayland_session():
    """
    True only on Linux, and only when the current desktop session is
    actually Wayland (not X11). Windows and macOS always return False,
    as does Linux running a plain X11 session — the X11/xWayland setup
    frame and the related info-window hint are meant to appear ONLY in
    this one specific situation (confirmed via 'xlsclients' testing on
    Raspberry Pi OS Bookworm, 2026-07: Dream itself runs fine via
    XWayland once QT_QPA_PLATFORM=xcb is set for its process).
    """
    if _platform.system() != 'Linux':
        return False
    session_type = os.environ.get('XDG_SESSION_TYPE', '').strip().lower()
    if session_type == 'wayland':
        return True
    if session_type == '':
        # XDG_SESSION_TYPE not set on some minimal setups — fall back to
        # checking for a Wayland display socket as the next-best signal.
        return bool(os.environ.get('WAYLAND_DISPLAY', '').strip())
    return False


def _xwayland_available():
    """
    Checks whether an 'Xwayland' binary is on PATH. Used to warn the user
    BEFORE starting Dream with QT_QPA_PLATFORM=xcb, instead of letting
    Dream fail to start with no clear explanation.
    """
    import shutil
    return shutil.which('Xwayland') is not None

def _stop_dream_process(proc):
    """
    Stop the given Dream subprocess, trying a regular window-close first
    on Linux before falling back to terminate() (SIGTERM).

    Added July 2026: Dream, started standalone, opens centred on screen —
    but Dream started via DRMLogPlotter's own Timer-Event/AutoPlot always
    reappeared top-left instead, and audio-codec screenshot-OCR detection
    worked noticeably worse in that position (likely partially covered by
    a desktop panel at the very top-left corner). Root cause: this
    program only ever stopped Dream via terminate() (SIGTERM) — most Qt
    apps only save their window geometry on a REGULAR window-close event
    (as triggered by the window's own close button / window-manager close
    request), not on SIGTERM. Requesting a normal close first via xdotool
    (Linux only — matches the same tool already used elsewhere in this
    project) lets Dream save its real, centred position for next time;
    terminate() remains the fallback if that doesn't work or takes too
    long, so behaviour is unchanged wherever this doesn't apply (Windows,
    macOS, or if xdotool isn't available).
    """
    if proc is None:
        return
    if _platform.system() == 'Linux':
        try:
            import shutil, time
            if shutil.which('xdotool'):
                ids = _subprocess.run(
                    ['xdotool', 'search', '--pid', str(proc.pid)],
                    capture_output=True, text=True, timeout=3
                ).stdout.strip().splitlines()
                for wid in ids:
                    wid = wid.strip()
                    if wid:
                        _subprocess.run(['xdotool', 'windowclose', wid],
                                        capture_output=True, text=True, timeout=3)
                # Give Dream a brief moment to close itself and save its
                # window geometry before falling back to a hard terminate.
                for _ in range(10):   # up to ~1s
                    if proc.poll() is not None:
                        return   # closed cleanly — done
                    time.sleep(0.1)
        except Exception:
            pass   # any problem here — fall through to terminate() below
    try:
        proc.terminate()
    except Exception:
        pass

def _grab_screenshot(bbox):
    """
    Grab a screenshot cropped to bbox=(x0,y0,x1,y1), choosing the capture
    method based on the current session — same reasoning already used
    for Dream's own Audio-Codec detection:

    - Windows / macOS / Linux+X11 (e.g. Linux Mint currently): unchanged,
      PIL.ImageGrab.grab(bbox=...) — confirmed working there already.
    - Linux+Wayland (e.g. Raspberry Pi OS): use 'grim' instead. Confirmed
      by testing (July 2026) that PIL's own ImageGrab() on this
      combination silently invokes the visible 'Bildschirmfoto'
      (gnome-screenshot) GUI app instead of a silent capture, produces an
      empty result, and can leave the DRMLogPlotter window partially
      unresponsive afterwards. 'grim' captures the whole screen directly
      via the Wayland compositor (no X11 pixmap-read involved), which we
      then crop down to bbox ourselves with PIL — this check is
      re-evaluated live each time (not cached), so it keeps working
      correctly if the session type ever changes (e.g. Linux Mint moving
      to Wayland by default, expected around December 2026).

    Returns a PIL Image, or None if the capture failed.
    """
    from PIL import Image
    if _platform.system() == 'Linux' and _is_linux_wayland_session():
        import shutil, tempfile
        if not shutil.which('grim'):
            return None
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
                tmp_path = tf.name
            result = _subprocess.run(['grim', tmp_path],
                                     capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return None
            img = Image.open(tmp_path)
            img.load()   # force-read pixel data before the temp file is removed
            return img.crop(bbox)
        except Exception:
            return None
        finally:
            if tmp_path:
                try: os.remove(tmp_path)
                except OSError: pass
    else:
        from PIL import ImageGrab
        return ImageGrab.grab(bbox=bbox)

COL_AUDIO   = "#1ec8e0"  # brighter, turquoise-leaning blue (Aug 2026, user-chosen "Option B", was "#2f6fdd")
COL_SNR     = "#ff3333"
COL_DOPPLER      = "#00cc44"   # plot line  — bright for dark background
COL_DOPPLER_TEXT = "#007722"   # GUI text   — dark for light GUI background
COL_DELAY   = "#cc8833"
GUI_BG      = "#d4d0c8"

# ══════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════
def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a  = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    dist = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    y = math.sin(dl)*math.cos(p2)
    x = math.cos(p1)*math.sin(p2) - math.sin(p1)*math.cos(p2)*math.cos(dl)
    az = (math.degrees(math.atan2(y, x)) + 360) % 360
    return round(dist, 1), round(az, 1)

def _is_float(s):
    try: float(s); return True
    except: return False

def parse_dt(date_str, time_str):
    """Parse DATE + TIME from CSV. TIME may have decimal seconds: '15:59:03.0'"""
    ts = time_str.strip()
    ds = date_str.strip()
    # Remove decimal seconds fraction for strptime compatibility
    if '.' in ts:
        ts = ts.split('.')[0]
    return datetime.strptime(f"{ds} {ts}", "%Y-%m-%d %H:%M:%S")

def center_dialog(dlg, parent, w, h):
    """
    Position a Toplevel dialog centred over its parent window — without flashing.

    Technique:
      1. withdraw()  — hide the window before it is ever drawn on screen
      2. Calculate the correct position relative to the parent
      3. Set geometry with position in one call
      4. deiconify() — make the window visible, already in the right place

    This completely prevents the brief flash at position (0,0) or at the
    top-left corner of the screen that Tkinter shows when a Toplevel is
    created and then moved.
    """
    dlg.withdraw()                        # hide immediately — before any drawing
    parent.update_idletasks()             # make sure parent geometry is current
    px = parent.winfo_x()
    py = parent.winfo_y()
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    cx = px + (pw - w) // 2
    cy = py + (ph - h) // 2
    dlg.geometry(f'{w}x{h}+{cx}+{cy}')   # size AND position in one call
    dlg.deiconify()                       # now show — already in the right place

# ══════════════════════════════════════════════════════
# PARSERS
# ══════════════════════════════════════════════════════
class DreamLog:
    def __init__(self):
        self.label = self.frequency = self.mode = self.bandwidth = ""
        self.bitrate = self.sw_version = ""
        self.start_time = None
        self.active = False   # True = log still running (no <<<< yet)
        self.max_audio_frames = 0   # max AUDIO value from minute lines
    def display_name(self):
        freq   = self.frequency.replace(" kHz","").strip().rjust(5)
        date   = self.start_time.strftime("%Y-%m-%d") if self.start_time else "?"
        time   = self.start_time.strftime("%H:%M")    if self.start_time else "?"
        return f"{freq} kHz  {date}  {time}"

def _read_file_robust(filepath):
    """
    Read a text file trying multiple encodings in order:
    1. UTF-8 (Dream 2.2.1+)
    2. Windows-1252 / Latin-1 (Dream up to 2.1.1, older logs)
    3. Raw bytes with replacement (fallback, always works)
    This makes the parser version-independent regardless of
    how Dream wrote the degree symbol (° = 0xB0 in cp1252,
    0xC2 0xB0 in UTF-8).
    """
    for enc in ('utf-8', 'cp1252', 'latin-1'):
        try:
            with open(filepath, 'r', encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, LookupError):
            continue
    # Ultimate fallback: read as bytes, decode with replacement
    with open(filepath, 'rb') as f:
        return f.read().decode('utf-8', errors='replace')


def parse_dreamlog_txt(filepath):
    """
    Parse DreamLog.txt — works for both:
    - Completed logs:  block starts with >>>> and ends with <<<<
    - Active logs:     block starts with >>>> but has NO <<<< yet
                       (Dream is still logging — used for AutoPlot)
    """
    logs = []
    content = _read_file_robust(filepath)

    for block in re.split(r'>>>>', content):
        block = block.strip()
        if not block:
            continue

        # Check BEFORE removing closing marker
        is_active = '<<<<' not in block   # True = log still running in Dream

        # Remove closing markers if present (completed log)
        if '<<<<' in block:
            block = block.split('<<<<')[0].strip()

        dl = DreamLog()
        dl.active = is_active

        for line in block.splitlines():
            line = line.strip()
            if   line.startswith("Software Version"):
                dl.sw_version = " ".join(line.split()[2:])
            elif line.startswith("Starttime (UTC)"):
                ts = " ".join(line.split()[2:])
                try: dl.start_time = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                except: pass
            elif line.startswith("Frequency"):  dl.frequency = " ".join(line.split()[1:])
            elif line.startswith("Label"):      dl.label     = " ".join(line.split()[1:])
            elif line.startswith("Bitrate"):    dl.bitrate   = " ".join(line.split()[1:])
            elif line.startswith("Mode"):       dl.mode      = " ".join(line.split()[1:])
            elif line.startswith("Bandwidth"):  dl.bandwidth = " ".join(line.split()[1:])
            else:
                # Try to parse minute data line: "  0001   18   150   755/00   0"
                parts = line.split()
                if len(parts) >= 4 and parts[0].isdigit():
                    audio_field = parts[3]   # e.g. "755/00"
                    if '/' in audio_field:
                        try:
                            audio_val = int(audio_field.split('/')[0])
                            if audio_val > dl.max_audio_frames:
                                dl.max_audio_frames = audio_val
                        except ValueError:
                            pass

        if dl.start_time:
            # Label fallback — shown when Dream could not sync
            if not dl.label:
                dl.label = '(no label at log start)'
            logs.append(dl)
    return logs

def load_csv_rows(filepath):
    """Load CSV with automatic encoding detection (UTF-8, cp1252, latin-1)."""
    rows = []
    for enc in ('utf-8', 'cp1252', 'latin-1'):
        try:
            with open(filepath, 'r', encoding=enc) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append({k.strip(): v.strip() for k, v in row.items()})
            return rows
        except (UnicodeDecodeError, LookupError):
            rows = []
            continue
    # Fallback
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k.strip(): v.strip() for k, v in row.items()})
    return rows

def filter_csv_for_log(all_rows, log_start, next_start):
    result = []
    for r in all_rows:
        try:
            dt = parse_dt(r['DATE'], r['TIME'])
            if dt < log_start - timedelta(seconds=5): continue
            if next_start and dt >= next_start - timedelta(seconds=5): break
            result.append(r)
        except: continue
    return result

def parse_tx_sites(filepath):
    """Load TX sites from drmtransmittersites.txt file."""
    sites = []
    if not os.path.exists(filepath):
        return sites
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        raw = [l.strip().strip('"') for l in f]
    i = 1 if (raw and re.match(r'\d{2}-\d{2}-\d{2}', raw[0])) else 0
    while i < len(raw):
        if not raw[i]: i += 1; continue
        freq_service = raw[i]; i += 1
        try:
            lon_deg=int(raw[i]);i+=1; lon_min=int(raw[i]);i+=1
            lat_deg=int(raw[i]);i+=1; lat_min=int(raw[i]);i+=1
            location=raw[i];i+=1
        except: i+=1; continue
        m = re.match(r'(\d+)\s+kHz\s+(.*)', freq_service)
        if not m: continue
        # Minutes are arc-minutes (0-59), convert to decimal degrees
        # Note: some entries store the sign on the minutes (e.g. lon_deg=4, lon_min=-9
        # means lon = -4°09' West). Handle both cases.
        lat_sign = -1 if (lat_deg < 0 or lat_min < 0) else 1
        lon_sign = -1 if (lon_deg < 0 or lon_min < 0) else 1
        lat = (abs(lat_deg) + abs(lat_min)/60.0) * lat_sign
        lon = (abs(lon_deg) + abs(lon_min)/60.0) * lon_sign
        sites.append({'freq_khz':int(m.group(1)),'service':m.group(2),
                      'freq_service':freq_service,'location':location,
                      'lat':lat,'lon':lon})
    return sites

def find_tx_for_freq(sites, freq_str):
    m = re.search(r'\d+', freq_str)
    if not m: return []
    try: khz = int(m.group())
    except: return []
    return [s for s in sites if s['freq_khz']==khz]

def compute_stats(rows, key):
    vals = [float(r[key]) for r in rows if _is_float(r.get(key,''))]
    if not vals: return None, None, None
    return min(vals), max(vals), round(sum(vals)/len(vals), 2)

# ══════════════════════════════════════════════════════
# DRM-RADIO-LIST  (DRM Consortium schedule .ini file)
# ══════════════════════════════════════════════════════
def _split_hhmm(s):
    """'900' -> (9,0)  '1800' -> (18,0)  '2400' -> (24,0). None on bad input."""
    s = str(s).strip().zfill(4)
    try:
        h, m = int(s[:2]), int(s[2:])
        return h, m
    except ValueError:
        return None, None

def parse_drm_schedule(path):
    """
    Parse a DRM Consortium schedule file (e.g. 'DRMSchedule.ini').

    NOTE: despite the .ini extension this is NOT a standard configparser
    file — there is only one '[DRMSchedule]' header, followed by many
    repeated blocks that all reuse the same key names (Frequency=,
    Programme=, ...). configparser would silently keep only the last one.
    So this is parsed as repeated blocks instead, split on every
    'StartStopTimeUTC=' line (each transmission starts with that key,
    regardless of how blank lines are used around it).

    Malformed / incomplete blocks are skipped silently rather than
    raising — a broken line in a large real-world schedule file must
    never prevent the rest of the list from loading.

    Returns a list of dicts with keys:
        start_h, start_m, stop_h, stop_m   (ints, UTC)
        days        (7-char '0'/'1' string, index 0=Sunday .. 6=Saturday)
        freq_khz    (int)
        target, power, programme, language, site, country   (strings)
    """
    entries = []
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            text = f.read()
    except Exception:
        return entries

    raw_blocks = re.split(r'(?=^\s*StartStopTimeUTC\s*=)', text, flags=re.MULTILINE)
    for block in raw_blocks:
        block = block.strip()
        if not block.lower().startswith('startstoptimeutc'):
            continue
        fields = {}
        for line in block.splitlines():
            line = line.strip()
            if not line or '=' not in line:
                continue
            k, _, v = line.partition('=')
            fields[k.strip()] = v.strip()
        try:
            sst = fields.get('StartStopTimeUTC', '')
            m = re.match(r'^(\d{1,4})\s*-\s*(\d{1,4})$', sst)
            if not m:
                continue
            sh, sm = _split_hhmm(m.group(1))
            eh, em = _split_hhmm(m.group(2))
            if sh is None or eh is None:
                continue
            days = fields.get('Days[SMTWTFS]', '')
            if len(days) != 7 or not all(c in '01' for c in days):
                # Unknown/garbled day pattern — be permissive rather than
                # silently dropping a real transmission from the list.
                days = '1111111'
            freq_str = fields.get('Frequency', '').strip()
            if not freq_str.isdigit():
                continue
            entries.append({
                'start_h': sh, 'start_m': sm, 'stop_h': eh, 'stop_m': em,
                'days': days,
                'freq_khz': int(freq_str),
                'target':    fields.get('Target', ''),
                'power':     fields.get('Power', ''),
                'programme': fields.get('Programme', ''),
                'language':  fields.get('Language', ''),
                'site':      fields.get('Site', ''),
                'country':   fields.get('Country', ''),
            })
        except Exception:
            continue   # never let one broken block abort the whole load
    return entries

def save_drm_schedule(path, entries):
    """
    Write the in-memory DRM-Radio-List back out to disk, in the same
    repeated-block .ini format parse_drm_schedule() reads (one
    '[DRMSchedule]' header, followed by blank-line-separated blocks).
    Entries are written sorted by frequency, then programme name.
    """
    lines = ['[DRMSchedule]\n']
    for e in sorted(entries, key=lambda x: (x['freq_khz'], x['programme'].lower())):
        sst = f"{e['start_h']:02d}{e['start_m']:02d}-{e['stop_h']:02d}{e['stop_m']:02d}"
        lines.append('\n')
        lines.append(f"StartStopTimeUTC={sst}\n")
        lines.append(f"Days[SMTWTFS]={e['days']}\n")
        lines.append(f"Frequency={e['freq_khz']}\n")
        lines.append(f"Target={e['target']}\n")
        lines.append(f"Power={e['power']}\n")
        lines.append(f"Programme={e['programme']}\n")
        lines.append(f"Language={e['language']}\n")
        lines.append(f"Site={e['site']}\n")
        lines.append(f"Country={e['country']}\n")
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(lines)

def drm_entry_is_active(entry, now_utc):
    """
    True if 'entry' is on air at 'now_utc' (a UTC datetime).

    Handles transmissions that cross UTC midnight (start > stop, e.g.
    '2000-1800' for stations in a very different time zone — start
    20:00 UTC, stop 18:00 UTC the *next* day). In that case the weekday
    check is applied against the day the transmission STARTED, not
    necessarily today's date — see inline comments.
    """
    now_min   = now_utc.hour * 60 + now_utc.minute
    start_min = entry['start_h'] * 60 + entry['start_m']
    stop_min  = entry['stop_h']  * 60 + entry['stop_m']
    days = entry['days']
    # Days[SMTWTFS]: index 0=Sunday .. 6=Saturday.
    # Python weekday(): Monday=0 .. Sunday=6  ->  (weekday+1) % 7 = SMTWTFS index.
    dow_today = (now_utc.weekday() + 1) % 7

    if start_min <= stop_min:
        # Normal same-UTC-day window (includes the 0000-2400 full-day case).
        active = start_min <= now_min < stop_min
        return active and days[dow_today] == '1'

    # ── Crosses UTC midnight ────────────────────────────────────────
    if now_min >= start_min:
        # We're in the part of the window that started earlier today.
        return days[dow_today] == '1'
    elif now_min < stop_min:
        # We're in the early-morning tail end of a window that actually
        # started YESTERDAY (UTC) — check yesterday's day-bit instead.
        dow_yesterday = (dow_today - 1) % 7
        return days[dow_yesterday] == '1'
    return False

def drm_entry_starts_soon(entry, now_utc, window_min=15):
    """
    True if 'entry' has NOT started yet, but its start time falls within
    the next window_min minutes from now_utc (a UTC datetime). Aug 2026,
    user request — 'red' pre-alert row colour in the DRM-Radio-List /
    Radio-List for Timer-Event, 15 minutes ahead of a station's start.

    Mirrors drm_entry_is_active()'s own day-of-week and UTC-midnight
    handling, so a station starting at e.g. 00:05 UTC still correctly
    turns red a few minutes before midnight (UTC) the previous day, not
    only once the calendar date has already rolled over.
    """
    now_min   = now_utc.hour * 60 + now_utc.minute
    start_min = entry['start_h'] * 60 + entry['start_m']
    days = entry['days']
    dow_today = (now_utc.weekday() + 1) % 7   # SMTWTFS index, 0=Sunday

    window_start = start_min - window_min
    if window_start >= 0:
        # Normal case: the whole lead-in window is on the same UTC day
        # as the start itself.
        if not (window_start <= now_min < start_min):
            return False
        return days[dow_today] == '1'
    else:
        # Start is within the first window_min minutes of the UTC day
        # (e.g. start 00:05) — part of the lead-in window falls on the
        # PREVIOUS UTC day (e.g. 23:50-23:59).
        wrapped_window_start = window_start % 1440   # e.g. -10 -> 1430
        if now_min >= wrapped_window_start:
            # Late-evening part of the lead-in, still "yesterday" —
            # the start itself belongs to TODAY's day-bit (the day the
            # transmission actually occurs on).
            return days[dow_today] == '1'
        elif now_min < start_min:
            # Early-morning part of the lead-in, same UTC day the
            # start also falls on.
            return days[dow_today] == '1'
        return False

# ══════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════
class Config:
    DEFAULTS = {
        'unit':'kilometer', 'screenshot_alerts':True, 'multiple_sites_alert':True,
        'plot_bg':'darkblue',
        'frame_bg':'darkblue',
        'rx_lat_deg':46,'rx_lat_min':57,'rx_lat_ns':'N',
        'rx_lon_deg':7, 'rx_lon_min':26,'rx_lon_ew':'E',
        'nickname':'Nickname', 'location_name':'',
        'header_text':'Click Button RX+Ant Info to write information about your Receiver and Antenna etc.',
        'profiles':[], 'last_log_dir':'',
        'web_links': ['https://www.drmrx.org/forum/', '', '', '', ''],
        'dream_log_path': '',   # folder where Dream writes DreamLog.txt / DreamLogLong.csv
        'switch_rx_to_freq': False,  # checkbox: switch RX to log-frequency on manual start
        'set_event_info_shown': True,  # show Dream info window on first Set Event click
        'dream_display_mode': 'xwayland',  # 'xwayland' (covers X11 + xWayland — both force the xcb Qt plugin) or 'wayland'
        'sdr_usb_lsb_enabled': False,  # USB/LSB offset trick for SDR receivers without a native DRM mode
        'sdr_usb_lsb_offset': 0,       # kHz, added to the RX/tuning frequency to get Dream's Log-Frequency; range -10..+10
        'drmschedule_path': '',        # last DRM-Radio-List (.ini) loaded via "Load DRMSchedule"
        'drm_radio_presets': ['', '', '', '', ''],  # 5 user-defined preset frequencies (kHz), empty by default
        'drm_radio_list_last_choice': '',  # last frequency picked in the DRM-Radio-List (list click or preset)
        'radio_list_autoplot_flag': False,  # 'Start with AutoPlot (10s)' checkbox in DRM-Radio-List — remembered across sessions per user request (Aug 2026)
        'ap_last_interval': 30,  # last-chosen Refresh Rate in 'Auto Plot Settings' — remembered across sessions per user request (Aug 2026)
        'ap_last_scroll': 'Full',  # last-chosen Scroll range in 'Auto Plot Settings' — remembered across sessions per user request (Aug 2026)
        'sdr_usb_lsb_sideband': 'USB', # 'USB' or 'LSB' — sign of the SDR offset (USB=+, LSB=-); default USB
        'drm_radio_list_sort': 'active',  # persisted Sort-by choice for the DRM-Radio-List window
        'drm_radio_list_col_widths': {},  # persisted column widths (user drag-resize) for the DRM-Radio-List table
        'drm_radio_list_geometry': '',    # persisted window size+position ("WxH+X+Y") for the DRM-Radio-List window
        'help_window_geometry': '',       # persisted window size+position ("WxH+X+Y") for the Help window
        'add_comments_geometry': '',      # persisted window position ("WxH+X+Y") for the Add Comments window (size is fixed, not resizable)
        'tx_sites_geometry': '',          # persisted window size+position ("WxH+X+Y") for the Manage Transmitter Sites window
        'radio_list_timer_geometry': '',        # persisted window size+position for 'Radio-List for Timer-Event'
        'radio_list_timer_sort': 'active',      # persisted Sort-by choice for 'Radio-List for Timer-Event'
        'radio_list_timer_col_widths': {},      # persisted column widths for 'Radio-List for Timer-Event'
        'radio_list_timer_confirm_geometry': '', # persisted position of its 'Copy to Timer-Event-List?' confirm dialog
        'set_event_geometry': '',         # persisted window position for 'Dream — Start & Schedule' (size is fixed, not resizable)
        'setup_geometry': '',             # persisted window size+position ("WxH+X+Y") for the Basic Setup Parameters window
        'rx_config_geometry': '',         # persisted window size+position ("WxH+X+Y") for the Dream and Receiver Configuration window
        'profile_config_geometry': '',    # persisted window size+position ("WxH+X+Y") for the Receiver and Antenna Configurations window (profiles list — a DIFFERENT dialog from rx_config_geometry above)
    }
    def __init__(self):
        self.data = dict(self.DEFAULTS)
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE) as f: self.data.update(json.load(f))
            except: pass
    def save(self):
        try:
            with open(CONFIG_FILE,'w',encoding='utf-8') as f: json.dump(self.data,f,indent=2)
        except: pass
    def get(self,k,d=None): return self.data.get(k, d if d is not None else self.DEFAULTS.get(k))
    def set(self,k,v): self.data[k]=v; self.save()
    def rx_lat(self):
        v = self.get('rx_lat_deg',46)+self.get('rx_lat_min',57)/60.0
        return -v if self.get('rx_lat_ns')=='S' else v
    def rx_lon(self):
        v = self.get('rx_lon_deg',7)+self.get('rx_lon_min',26)/60.0
        return -v if self.get('rx_lon_ew')=='W' else v

# ══════════════════════════════════════════════════════
# MAIN APPLICATION
# ══════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════
# RECEIVER AND ANTENNA CONFIGURATIONS WINDOW
# ══════════════════════════════════════════════════════
class RXConfigWindow:
    """Standalone window for managing receiver/antenna profile texts."""

    HINT = 'Write your Receiver Profile here and click on "Add Profile"'

    def __init__(self, parent, cfg, header_var):
        self.cfg        = cfg
        self.header_var = header_var
        self.profiles   = list(cfg.get('profiles', []))
        self.edit_idx   = -1

        self.win = tk.Toplevel(parent)
        self.win.title('Receiver and Antenna Configurations')
        self.win.configure(bg='#d4d0c8')
        # Widened 620 -> 760 (Aug 2026, user request) — the 'Edit a
        # Profile' frame now holds 5 buttons (Edit, Save, Add Profile,
        # Remove, Cancel) instead of 2, and the separate 'Add a New
        # Entry' frame was dissolved into it. Also now resizable, with
        # size AND position remembered across sessions — same proven
        # pattern already used for the 'Dream and Receiver
        # Configuration' dialog (_open_rx_config), just under its own
        # config key so the two dialogs' geometries don't collide.
        self.win.resizable(True, True)
        self.win.minsize(700, 360)
        _saved_geom = self.cfg.get('profile_config_geometry', '')
        if _saved_geom:
            try:
                self.win.geometry(_saved_geom)
            except Exception:
                center_dialog(self.win, parent, 760, 400)
        else:
            center_dialog(self.win, parent, 760, 400)
        self.win.grab_set()
        self.win.transient(parent)   # v_rig_test_06: keep dialog above its parent
        self.win.lift()
        self.win.focus_force()
        self.win.focus_set()

        def _save_geometry(event=None):
            if event is not None and event.widget is not self.win:
                return
            try:
                self.cfg.set('profile_config_geometry', self.win.geometry())
            except Exception:
                pass
        self.win.bind('<Configure>', _save_geometry, add='+')

        self._build()
        self.win.wait_window()

    def _build(self):
        w = self.win
        bg = '#d4d0c8'

        # ── Entry row ──────────────────────────────────────────────────
        self.entry_var = tk.StringVar(value=self.HINT)
        self.entry = tk.Entry(w, textvariable=self.entry_var,
                              font=('Arial', 9), bg='white', fg='#333333',
                              relief=tk.SUNKEN, bd=2)
        self.entry.pack(fill=tk.X, padx=8, pady=(8,3), ipady=4)
        self.entry.bind('<FocusIn>', self._clear_hint)

        # ── Middle row ─────────────────────────────────────────────────
        mid = tk.Frame(w, bg=bg)
        mid.pack(fill=tk.X, padx=8, pady=2)

        # Nickname frame — stays fixed on the left, no longer directly
        # touching 'Edit a Profile' (Aug 2026, user request): the two
        # are unrelated processes and should look visually separated.
        fn = tk.LabelFrame(mid, text='Enter your Nickname',
                           bg=bg, font=('Arial',8), padx=4, pady=2)
        fn.pack(side=tk.LEFT, padx=(0,4))
        self.nick_var = tk.StringVar(value=self.cfg.get('nickname',''))
        tk.Entry(fn, textvariable=self.nick_var, width=10,
                 font=('Arial',9), bg='white').pack(side=tk.LEFT, padx=(0,2))
        tk.Button(fn, text='OK', width=3,
                  command=self._save_nick).pack(side=tk.LEFT)

        # Edit a Profile frame — now holds all 5 editing actions in the
        # order requested (Aug 2026): Edit, Save, Add Profile, Remove,
        # Cancel. 'Add a New Entry' as a separate frame is dissolved —
        # its one button ('Add Profile') moved in here. 'Remove' and
        # 'Edit' moved up here from the bottom row.
        # Centred (Aug 2026, user request): packed with expand=True and
        # no fill, so pack's default centre-anchor places the frame in
        # the middle of the space left over after the fixed-width
        # Nickname frame — clearly separated from it, and stays centred
        # even as the (now resizable) dialog is stretched wider.
        fe = tk.LabelFrame(mid, text='Edit a Profile',
                           bg=bg, font=('Arial',8), padx=4, pady=2)
        fe.pack(side=tk.LEFT, expand=True)
        tk.Button(fe, text='Edit',        width=5,
                  command=self._edit_sel  ).pack(side=tk.LEFT, padx=2)
        tk.Button(fe, text='Save',        width=5,
                  command=self._save_edit ).pack(side=tk.LEFT, padx=2)
        tk.Button(fe, text='Add Profile', width=10,
                  command=self._add_profile).pack(side=tk.LEFT, padx=2)
        tk.Button(fe, text='Remove',      width=7,
                  command=self._remove    ).pack(side=tk.LEFT, padx=2)
        tk.Button(fe, text='Cancel',      width=6,
                  command=self._cancel_edit).pack(side=tk.LEFT, padx=2)

        # ── List row ───────────────────────────────────────────────────
        lf = tk.Frame(w, bg=bg)
        lf.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        sb = ttk.Scrollbar(lf)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.lb = tk.Listbox(lf, font=('Arial',9), bg='white',
                             selectbackground='#000080', selectforeground='white',
                             yscrollcommand=sb.set, relief=tk.SUNKEN, bd=1,
                             exportselection=False)
        self.lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.lb.yview)
        self.lb.bind('<Double-Button-1>', self._on_dbl_click)

        # ── Bottom button row ──────────────────────────────────────────
        # Layout (Aug 2026, user request): 'Delete All' keeps its exact
        # spot on the left, deliberately isolated from the other buttons
        # since it is a destructive/dangerous action — no other button
        # should ever end up next to it by accident. 'Edit' and 'Remove'
        # moved up to the 'Edit a Profile' frame above, leaving a large
        # gap here by design; the entry-count label now expands to fill
        # that gap and sits centred in it. 'Select' and 'Close' keep
        # their original left-to-right order but are now anchored to
        # the right edge of the window (side=tk.RIGHT), so they stay in
        # place even as the now-resizable dialog is stretched wider.
        bot = tk.Frame(w, bg=bg)
        bot.pack(fill=tk.X, padx=8, pady=(0,8))
        self.count_var = tk.StringVar()
        tk.Button(bot, text='Delete All', width=9,
                  command=self._delete_all).pack(side=tk.LEFT, padx=(0,3))
        tk.Button(bot, text='Close',      width=7,
                  command=self.win.destroy).pack(side=tk.RIGHT, padx=(3,0))
        tk.Button(bot, text='Select',     width=7,
                  command=self._select    ).pack(side=tk.RIGHT, padx=3)
        tk.Label(bot, textvariable=self.count_var, anchor='center',
                 bg=bg, font=('Arial',8)).pack(side=tk.LEFT,
                 expand=True, fill=tk.X, padx=8)

        self._refresh()

    # ── helpers ────────────────────────────────────────────────────────
    def _refresh(self):
        self.lb.delete(0, tk.END)
        for p in self.profiles:
            self.lb.insert(tk.END, p)
        self.count_var.set(f'{len(self.profiles)} Entries')

    def _save_profiles(self):
        self.cfg.set('profiles', self.profiles)

    def _clear_hint(self, event=None):
        if self.entry_var.get().startswith('Write your'):
            self.entry_var.set('')

    def _save_nick(self):
        self.cfg.set('nickname', self.nick_var.get().strip())

    def _add_profile(self):
        txt = self.entry_var.get().strip()
        if txt and not txt.startswith('Write your'):
            self.profiles.append(txt)
            self._refresh()
            self._save_profiles()
            self.entry_var.set(self.HINT)

    def _save_edit(self):
        txt = self.entry_var.get().strip()
        if self.edit_idx >= 0 and txt and not txt.startswith('Write your'):
            self.profiles[self.edit_idx] = txt
            self.edit_idx = -1
            self._refresh()
            self._save_profiles()
            self.entry_var.set(self.HINT)

    def _cancel_edit(self):
        self.edit_idx = -1
        self.entry_var.set(self.HINT)

    def _on_dbl_click(self, event=None):
        s = self.lb.curselection()
        if s:
            self.edit_idx = s[0]
            self.entry_var.set(self.profiles[s[0]])

    def _delete_all(self):
        if messagebox.askyesno('Delete All',
                               'Delete ALL profiles?', parent=self.win):
            self.profiles.clear()
            self._refresh()
            self._save_profiles()

    def _remove(self):
        s = self.lb.curselection()
        if s:
            self.profiles.pop(s[0])
            self._refresh()
            self._save_profiles()

    def _edit_sel(self):
        s = self.lb.curselection()
        if s:
            self.edit_idx = s[0]
            self.entry_var.set(self.profiles[s[0]])
            self.entry.focus_set()
            self.entry.selection_range(0, tk.END)

    def _select(self):
        # Bugfix (Aug 2026): used to call self.win.destroy() unconditionally,
        # even with nothing selected — so the button always closed the
        # dialog regardless of whether it actually did its job. Now only
        # closes when a row was really transferred to the Main-GUI header.
        s = self.lb.curselection()
        if s:
            self.header_var.set(self.profiles[s[0]])
            self.cfg.set('header_text', self.profiles[s[0]])
            self.win.destroy()
        else:
            messagebox.showinfo(
                'Select', 'Please select a profile line first.',
                parent=self.win)


class DRMPlotter:
    def __init__(self, root):
        self.root = root
        self.root.configure(bg=GUI_BG)
        self.root.resizable(True, True)
        # Aug 2026, user request ("DRMLogPlotter - UTC in GUI"): alive
        # flag for the small UTC clock in the Main-GUI's 'TX Sites and
        # UTC' frame — same [True]/[False]-list pattern already used by
        # the two Radio-List dialogs' own clocks, just scoped to the
        # whole app lifetime instead of one Toplevel. Flipped to False
        # in _on_close() so the clock's 1s tick loop stops itself.
        self._main_clock_alive = [True]
        # Windows-only title centring (Aug 2026, user request): the
        # native OS title bar is drawn by Windows itself — Tkinter has
        # no portable API to set its text alignment, unlike some Linux
        # window managers, which already centre it by default (left
        # unchanged there). This is a well-known, low-risk approximation
        # used for exactly this limitation: pad the title with leading
        # spaces so it visually shifts toward the centre of the window.
        # Not pixel-perfect (title-bar font metrics aren't queryable),
        # but noticeably closer to centred than flush-left. Recomputed
        # on every resize so it stays roughly centred as the window
        # width changes.
        if _platform.system() == 'Windows':
            self._APP_TITLE_AVG_CHAR_PX = 8   # rough system title-font width estimate
            def _update_win_title(event=None):
                if event is not None and event.widget is not self.root:
                    return
                try:
                    w = self.root.winfo_width()
                    title_px = len(APP_TITLE) * self._APP_TITLE_AVG_CHAR_PX
                    pad_chars = max(0, int(
                        (w - title_px) / 2 / self._APP_TITLE_AVG_CHAR_PX))
                    self.root.title(' ' * pad_chars + APP_TITLE)
                except Exception:
                    self.root.title(APP_TITLE)
            self.root.bind('<Configure>', _update_win_title, add='+')
            _update_win_title()
        else:
            self.root.title(APP_TITLE)

        self.cfg      = Config()
        # Load TX sites from saved path (if user loaded one before) or default file
        tx_path = self.cfg.get('tx_sites_path', TX_SITES_FILE)
        self.tx_sites = parse_tx_sites(tx_path)
        if not self.tx_sites and tx_path != TX_SITES_FILE:
            # Fallback to default if saved path no longer exists
            self.tx_sites = parse_tx_sites(TX_SITES_FILE)

        # DRM-Radio-List: load the last-used DRMSchedule.ini, if any.
        # Completely separate list from self.tx_sites — never mixed.
        self.drm_schedule = []
        drmsched_path = self.cfg.get('drmschedule_path', '')
        if drmsched_path and os.path.isfile(drmsched_path):
            self.drm_schedule = parse_drm_schedule(drmsched_path)


        # Restore the window position saved on last close (July 2026).
        # Safety check: if the stored position no longer fits on the
        # CURRENT screen (e.g. a second monitor was disconnected since
        # last time), fall back to the default placement instead of
        # risking an off-screen/invisible window.
        try:
            _wx = self.cfg.get('window_x', None)
            _wy = self.cfg.get('window_y', None)
            if _wx is not None and _wy is not None:
                _sw = self.root.winfo_screenwidth()
                _sh = self.root.winfo_screenheight()
                _wx, _wy = int(_wx), int(_wy)
                if -50 <= _wx < _sw - 50 and -50 <= _wy < _sh - 50:
                    self.root.geometry(f'+{_wx}+{_wy}')
        except Exception:
            pass

        self.all_logs  = []
        self.all_csv   = []
        self.sel_log   = None
        self.plot_rows = []
        self.comp_rows = []
        self.comp_log_meta = None
        self.sel_tx    = None
        self.txt_path  = self.csv_path = ""

        self.opt_smooth  = tk.IntVar(value=1)
        self.opt_thick   = tk.IntVar(value=0)
        self.opt_doppler = tk.IntVar(value=1)
        self.opt_delay   = tk.IntVar(value=1)
        self.opt_snr     = tk.IntVar(value=1)
        self.opt_audio   = tk.IntVar(value=1)

        self.zoom_start_var = tk.StringVar()
        self.zoom_stop_var  = tk.StringVar()
        self.zoom_active    = False
        self.zoom_t0 = self.zoom_t1 = None

        self.ap_active    = False
        self.ap_countdown = 0
        # Load the user's last-chosen Refresh Rate / Scroll from the
        # persisted config (Aug 2026, user request) — previously these
        # always reset to the hardcoded defaults (30 / 'Full') on every
        # programme start, even though the in-memory value stayed
        # correct for the rest of that session. Falls back to the same
        # defaults as before if nothing was ever saved, or if a saved
        # value somehow doesn't parse — behaviour for a fresh install is
        # unchanged.
        try:
            self.ap_interval = int(self.cfg.get('ap_last_interval', 30))
        except (TypeError, ValueError):
            self.ap_interval = 30
        self.ap_scroll   = self.cfg.get('ap_last_scroll', 'Full') or 'Full'
        self._ap_after_id = None
        # Handle window close — cancel any pending timers
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

        # SNR Max/Min dot markers on plot
        self._show_snr_max_dot = False
        self._show_snr_min_dot = False
        self._show_snr_avg_line = False

        # Annotations from Add Text dialog
        self._annotations      = []   # list of {time, text, pos}
        self._annotation_free  = ''
        self._show_vlines      = True

        self.header_var = tk.StringVar(value=self.cfg.get('header_text'))

        # ── Persistent Schedule State ─────────────────────────────────────
        # Survives dialog close/reopen. Each slot:
        #   sh,sm,eh,em = start/stop times, freq, log-flag, led-colour
        # led colours: grey=empty, yellow=waiting, green=active,
        #              blue=done, red=error
        self._sched_timers       = [[None,None],[None,None],[None,None],[None,None]]
        # Separate from _sched_timers on purpose (Aug 2026) — tracks the
        # new 'pre-stop' background Timer per slot (fires ~60s before
        # that slot's own start time, auto-stopping a manually-running
        # Dream so it doesn't collide with the scheduled start). Kept in
        # its own list rather than adding a 3rd element to _sched_timers'
        # existing [start, stop] pairs, since many places elsewhere
        # already index/unpack that list assuming exactly 2 entries.
        self._sched_prestop_timers = [None, None, None, None]
        self._sched_state        = [
            {'sh':'','sm':'','eh':'','em':'','freq':'','log':0,'autoplot':0,'led':'grey'}
            for _ in range(4)]
        # (AutoPlot is now configured per slot in _sched_state['autoplot'])
        # Dream process state — lives in self, survives dialog close
        self._dream_proc          = [None]  # running Dream subprocess
        self._monitor_stop        = [False] # signal to stop process monitor
        self._autoplot_enabled    = [False] # AutoPlot checkbox state at accept
        # Text-countdown state — survives dialog close
        self._dream_start_time    = None    # datetime of last Dream start
        self._ap_start_time       = None    # datetime of last AutoPlot start
        self._dream_log_flag      = False   # True if started with Log
        # Status LED colours for the 5 Status-frame LEDs — survive close
        self._sched_led_status = {
            'led1': 'grey',   # RX Connected
            'led2': 'grey',   # Frequency Set
            'led3': 'grey',   # Dream
            'led4': 'grey',   # Dream Log
            'led5': 'grey',   # Timer
        }
        # v_rig_test_03: action-based RX-connect state, used ONLY for
        # Network mode + "Hamlib NET rigctl" (model 2). Some rigctl-server
        # emulations (e.g. SDR++) respond inconsistently to the artificial
        # periodic 'f' ping used for all other rig types, while genuine
        # user-triggered actions (Set Freq, Set TRX to Log Frequency,
        # Autostart) get a reliable RPRT response. For this one specific
        # combination, the LED reflects the outcome of the last real
        # action instead of the last periodic ping — see
        # _is_netrigctl_mode() / _netrigctl_socket_set_freq() / _probe_trx_connection.
        self._netrigctl_led_state = None   # None=grey, 'green', or 'red'

        self._build_gui()

    # ─────────────────────────────────────────────────
    # GUI BUILD
    # ─────────────────────────────────────────────────
    def _build_gui(self):
        """
        Exact layout matching original screenshot:

        ROW 0 (top info):
          [Main Log frame ............] [DRM Modes Used] [right_col: Plot Audio/Plot/Zoom/Buttons]

        ROW 1 (header bar):
          [grey editable text, spans left+centre columns only]

        ROW 2 (plot):
          [matplotlib canvas, spans left+centre] | [right_col continues]

        ROW 3 (bottom bar):
          [Misc][AutoPlot][TX Site][Select Log][4btns][Update Files]

        The right_col is a single tk.Frame that spans rows 0-2.
        """
        self.root.columnconfigure(0, weight=1)   # left+centre: expands
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        self.root.columnconfigure(1, weight=0)   # right col: fixed width
        self.root.rowconfigure(0, weight=1)       # top row: expands
        self.root.rowconfigure(2, weight=1)       # plot row: expands

        # ── TOP INFO ROW (col 0) ─────────────────
        top = tk.Frame(self.root, bg=GUI_BG)
        top.grid(row=0, column=0, sticky='ew', padx=2, pady=2)
        self._build_top_info(top)

        # ── HEADER BAR (col 0) ───────────────────
        self._build_header_bar()

        # ── PLOT CANVAS (col 0) ──────────────────
        self._build_plot_area()

        # ── RIGHT COLUMN — uses pack not grid so it gets full window height ─
        right = tk.Frame(self.root, bg=GUI_BG)
        right.grid(row=0, column=1, rowspan=4, sticky='nsew', padx=(0,2), pady=2)
        self.root.rowconfigure(3, weight=0)   # bottom bar: fixed
        self._build_right_col(right)

        # ── BOTTOM BAR (spans col 0 only) ────────
        bot = tk.Frame(self.root, bg=GUI_BG)
        bot.grid(row=3, column=0, sticky='ew', padx=2, pady=2)
        self._build_bottom_bar(bot)

        # ── Start Timer-LED polling loop ─────────
        # Runs every 2s independently of the Schedule dialog.
        self._timer_led_after_id = None
        self.root.after(2000, self._timer_led_tick)

        # ── Auto-probe TRX connection 3s after start ─────────────────
        # Runs in background thread — no GUI freeze.
        # Updates _sched_led_status['led1/2'] for the Schedule dialog LED.
        self.root.after(3000, self._probe_trx_connection)

        # ── RX connection health loop — every 15s ─────────────────────
        # First tick at 16s (after the initial probe at 3s has completed).
        # Completely independent of _refresh_loop.
        self._rigctl_health_after_id = None
        self.root.after(16000, self._rigctl_health_tick)

    # ── TOP INFO ──────────────────────────────────
    def _build_top_info(self, parent):
        """
        Top row layout (left → right):
          [Main Log frame] [Stats frame (Decoded Audio / SNR / Delay / Doppler)] [DRM Modes Used]

        DRM Modes Used sits directly left of the right controls column (Plot Audio / Zoom etc.)
        Stats block floats freely in the centre — not inside Main Log.
        """

        # ── 1) Main Log frame (ganz links) ───────────────────────────────
        ml = tk.LabelFrame(parent, text='Main Log', bg=GUI_BG,
                           font=('Arial', 9, 'bold'), padx=4, pady=2)
        ml.pack(side=tk.LEFT, fill=tk.Y, padx=(0,3))

        # Small horizontal gap between the label and value columns —
        # Linux only (July 2026): confirmed by testing that under Linux's
        # substituted font (see note below), long static labels like
        # "Main Service Channel:" can end up visually touching/crowding
        # the value column right next to them with zero gap. Windows is
        # untouched (padx stays 0, exactly as before).
        _label_gap = (0, 8) if _platform.system() == 'Linux' else 0

        # Value-field width in the LEFT sub-column, widened on Linux only
        # (July 2026): confirmed by testing that "(no label at log start)"
        # (24 chars) was clipped to "...sta" at the old width=16. Windows
        # keeps width=16 unchanged.
        _lc_val_width = 20 if _platform.system() == 'Linux' else 16

        # Left sub-column: Label / Frequency / TX Location / Date / Audio Codec
        lc = tk.Frame(ml, bg=GUI_BG)
        lc.grid(row=0, column=0, sticky='nw')
        self.v_label  = tk.StringVar(value='label')
        self.v_freq   = tk.StringVar(value='freq')
        self.v_txloc  = tk.StringVar(value='site')
        self.v_date   = tk.StringVar(value='date')
        self.v_audio_codec = tk.StringVar(value='—')
        for i,(txt,var) in enumerate([('Label:',self.v_label),('Frequency:',self.v_freq),
                                       ('TX Location:',self.v_txloc),('Date:',self.v_date),
                                       ('Audio Codec:',self.v_audio_codec)]):
            tk.Label(lc,text=txt,bg=GUI_BG,font=('Arial',10),anchor='w',width=11).grid(row=i,column=0,sticky='w',pady=1,padx=_label_gap)
            tk.Label(lc,textvariable=var,bg=GUI_BG,font=('Arial',10,'bold'),
                     fg='#000080',anchor='w',width=_lc_val_width).grid(row=i,column=1,sticky='w',pady=1)

        # Separator padding and value-field width are widened slightly on
        # Linux only (July 2026): Tkinter's 'width=' for Labels is in
        # CHARACTERS, not pixels, so the same character count renders at
        # different actual pixel widths depending on the font actually
        # used. 'Arial' (hardcoded below) is not installed on Linux, so
        # Tk silently substitutes a wider font (typically DejaVu Sans) —
        # confirmed by testing to clip the last character of "EEP ·
        # Stereo" (exactly 12 chars, same as the old width=12) under
        # Linux, while fitting fine under Windows' real Arial. Windows
        # keeps its original values unchanged (padx=5 / width=12) since
        # its layout was already confirmed to look correct there.
        _sep_padx   = (2, 2)  if _platform.system() == 'Linux' else 5
        _val_width  = 15      if _platform.system() == 'Linux' else 12
        ttk.Separator(ml,orient='vertical').grid(row=0,column=1,sticky='ns',padx=_sep_padx)

        # Label-column width in the RIGHT sub-column, widened on Linux
        # only (July 2026): "Main Service Channel:" is 21 characters —
        # confirmed by testing still getting visually crowded by the
        # value column at the previous width=16 under Linux's substituted
        # font. Windows keeps width=16 unchanged (already confirmed fine
        # there).
        _rc_label_width = 22 if _platform.system() == 'Linux' else 16

        # Right sub-column: Mode / Bitrate / MSC / PL / Audio Mode
        rc = tk.Frame(ml, bg=GUI_BG)
        rc.grid(row=0, column=2, sticky='nw')
        self.v_mode    = tk.StringVar(value='bw')
        self.v_bitrate = tk.StringVar(value='kbps')
        self.v_msc     = tk.StringVar(value='qam')
        self.v_pl      = tk.StringVar(value='PL')
        self.v_audio_mode = tk.StringVar(value='—')
        for i,(txt,var) in enumerate([('Mode / Bandwidth:',self.v_mode),
                                       ('Bitrate (at log start):',self.v_bitrate),
                                       ('Main Service Channel:',self.v_msc),
                                       ('Protection Level:',self.v_pl),
                                       ('Prot. / Audio:',self.v_audio_mode)]):
            tk.Label(rc,text=txt,bg=GUI_BG,font=('Arial',10),anchor='w',width=_rc_label_width).grid(row=i,column=0,sticky='w',pady=1,padx=_label_gap)
            tk.Label(rc,textvariable=var,bg=GUI_BG,font=('Arial',10,'bold'),
                     fg='#000080',anchor='w',width=_val_width).grid(row=i,column=1,sticky='w',pady=1)

        # ── 2) Stats block (centre) — with frame, font Arial 8 ──────────
        sf_outer = tk.LabelFrame(parent, text='Data evaluation result', bg=GUI_BG,
                                 font=('Arial',9,'bold'), relief=tk.GROOVE, bd=2, padx=4, pady=2)
        sf_outer.pack(side=tk.LEFT, fill=tk.Y, padx=(6,6))
        sf = sf_outer   # all widgets directly in the frame

        self.v_audio_pct = tk.StringVar(value='audio')
        self.v_fac       = tk.StringVar(value='sfm')
        self.v_audio_max = tk.StringVar(value='---')

        # Row 0: Decoded Audio (blau)  |  spacer  |  FAC CRC (grau)
        # Fixed to the old blue (Aug 2026, user request) — kept
        # independent of COL_AUDIO on purpose: COL_AUDIO is now a
        # brighter turquoise-blue tuned for the dark plot background,
        # but on this frame's light GUI background that same color is
        # hard to read. This label color intentionally does NOT follow
        # future COL_AUDIO (plot line) changes any more.
        COL_AUDIO_LABEL = '#2f6fdd'
        tk.Label(sf, text='Decoded Audio:', bg=GUI_BG, font=('Arial',10),
                 fg=COL_AUDIO_LABEL).grid(row=0, column=0, sticky='w', padx=(4,1))
        tk.Label(sf, textvariable=self.v_audio_pct, bg=GUI_BG, font=('Arial',10,'bold'),
                 fg=COL_AUDIO_LABEL).grid(row=0, column=1, sticky='w', padx=(1,8))
        tk.Label(sf, text='FAC CRC:', bg=GUI_BG, font=('Arial',10),
                 fg='#000000').grid(row=0, column=3, sticky='w', padx=(4,1))
        tk.Label(sf, textvariable=self.v_fac, bg=GUI_BG, font=('Arial',10,'bold'),
                 fg='#000000').grid(row=0, column=4, sticky='w', padx=(1,8))
        tk.Label(sf, text='Audio Frames max.:', bg=GUI_BG, font=('Arial',10),
                 fg=COL_AUDIO_LABEL).grid(row=0, column=6, sticky='w', padx=(4,1))
        tk.Label(sf, textvariable=self.v_audio_max, bg=GUI_BG, font=('Arial',10,'bold'),
                 fg=COL_AUDIO_LABEL).grid(row=0, column=7, sticky='w', padx=(1,4))

        # Row 1: thin spacer between row-0 and stats block
        tk.Label(sf, text='', bg=GUI_BG, font=('Arial',4)).grid(row=1, column=0)

        # ── SNR / Delay / Doppler in a SEPARATE inner frame ──────────────
        # This isolates the stats grid from row-0 column widths,
        # so "Audio Frames max." no longer pushes Doppler values far right.
        self.v_snr_max=tk.StringVar(value='sma'); self.v_snr_min=tk.StringVar(value='smi'); self.v_snr_avg=tk.StringVar(value='avg')
        self.v_del_max=tk.StringVar(value='dma'); self.v_del_min=tk.StringVar(value='dmi'); self.v_del_avg=tk.StringVar(value='dev')
        self.v_dop_max=tk.StringVar(value='dma'); self.v_dop_min=tk.StringVar(value='dmi'); self.v_dop_avg=tk.StringVar(value='dav')
        self.v_runtime = tk.StringVar(value='0 h 0 m')

        # Inner frame spans all columns of row 2 — own independent grid
        sf_stats = tk.Frame(sf, bg=GUI_BG)
        sf_stats.grid(row=2, column=0, columnspan=8, sticky='w', padx=(0,0))

        # Pin column widths so values don't shift when numbers change length.
        # col 0 = label (e.g. "SNR Max.:"), col 1 = value, col 2 = unit + gap
        for _grp in range(3):
            sf_stats.columnconfigure(_grp * 3 + 0, minsize=78)  # label col
            sf_stats.columnconfigure(_grp * 3 + 1, minsize=40)  # value col
            sf_stats.columnconfigure(_grp * 3 + 2, minsize=30)  # unit col

        stat_col = 0
        for (mlbl, vmax, vmin, vavg, unit, color) in [
            ('SNR',     self.v_snr_max, self.v_snr_min, self.v_snr_avg, 'dB', COL_SNR),
            ('Delay',   self.v_del_max, self.v_del_min, self.v_del_avg, 'ms', COL_DELAY),
            ('Doppler', self.v_dop_max, self.v_dop_min, self.v_dop_avg, 'Hz', COL_DOPPLER_TEXT),
        ]:
            for ri, (row_lbl, var) in enumerate([
                (f'{mlbl} Max.:',  vmax),
                (f'{mlbl} Min.:',  vmin),
                ('Average:',       vavg),
            ]):
                is_snr = (mlbl == 'SNR')
                lbl = tk.Label(sf_stats, text=row_lbl, bg=GUI_BG,
                               font=('Arial',10), fg=color, anchor='w')
                lbl.grid(row=ri, column=stat_col, sticky='w', padx=(4,1), pady=2)
                if is_snr:
                    if ri == 0:
                        lbl.config(cursor='hand2')
                        lbl.bind('<Button-1>', lambda e: self._toggle_snr_dot('max'))
                        ToolTip(lbl, 'Click for plot On / Off')
                    elif ri == 1:
                        lbl.config(cursor='hand2')
                        lbl.bind('<Button-1>', lambda e: self._toggle_snr_dot('min'))
                        ToolTip(lbl, 'Click for plot On / Off')
                    elif ri == 2:
                        lbl.config(cursor='hand2')
                        lbl.bind('<Button-1>', lambda e: self._toggle_snr_dot('avg'))
                        ToolTip(lbl, 'Click for plot On / Off')
                tk.Label(sf_stats, textvariable=var, bg=GUI_BG,
                         font=('Arial',10,'bold'), fg=color,
                         anchor='e').grid(row=ri, column=stat_col+1,
                                          sticky='e', padx=(1,0), pady=2)
                tk.Label(sf_stats, text=unit, bg=GUI_BG, font=('Arial',10),
                         fg=color).grid(row=ri, column=stat_col+2,
                                        sticky='w', padx=(1,10), pady=2)
            stat_col += 3

        # Runtime is shown in the DRM Modes Used frame (not here)

        # ── 3) Right wrapper — stacks "DRM Modes Used" and "Scheduled Event"
        #       vertically on the right side of the top row
        right_wrapper = tk.Frame(parent, bg=GUI_BG)
        right_wrapper.pack(side=tk.RIGHT, fill=tk.Y, padx=(0,2))

        # ── 3a) DRM Modes Used ───────────────────────────────────────────
        mf = tk.LabelFrame(right_wrapper, text='DRM Modes Used', bg=GUI_BG,
                           font=('Arial',9,'bold'), padx=3, pady=2)
        mf.pack(side=tk.TOP, fill=tk.X)
        self.modes_text = tk.Text(mf, width=17, height=2, font=('Courier',11),
                                  bg='white', state=tk.DISABLED, relief=tk.SUNKEN, bd=1)
        self.modes_text.pack()
        # Runtime directly below the text widget
        rt_row = tk.Frame(mf, bg=GUI_BG)
        rt_row.pack(fill=tk.X, pady=(4,0))
        rt_inner = tk.Frame(rt_row, bg=GUI_BG)
        rt_inner.pack(anchor='center')
        tk.Label(rt_inner, text='Runtime:', bg=GUI_BG,
                 font=('Arial',10)).pack(side=tk.LEFT)
        tk.Label(rt_inner, textvariable=self.v_runtime, bg=GUI_BG,
                 font=('Arial',10,'bold'), fg='#000080').pack(side=tk.LEFT, padx=(3,0))

        # ── 3b) Timer / Log / RX activ — separate frame, below DRM Modes Used ─
        tf = tk.LabelFrame(right_wrapper, text='', bg=GUI_BG,
                           font=('Arial',8,'bold'), padx=4, pady=4)
        tf.pack(side=tk.TOP, fill=tk.X, pady=(4,0))

        # ── Left: Timer ───────────────────────────────────────────────────────
        tf_left = tk.Frame(tf, bg=GUI_BG)
        tf_left.pack(side=tk.LEFT, fill=tk.Y, padx=(0,2))
        tk.Label(tf_left, text='Timer', bg=GUI_BG,
                 font=('Arial',8,'bold')).pack(anchor='w')
        tf_left_row = tk.Frame(tf_left, bg=GUI_BG)
        tf_left_row.pack(anchor='w')
        self._timer_led_canvas = tk.Canvas(tf_left_row, width=14, height=14,
                                           bg=GUI_BG, highlightthickness=0)
        self._timer_led_canvas.pack(side=tk.LEFT, padx=(0,3))
        self._timer_led_oval = self._timer_led_canvas.create_oval(
            2, 2, 12, 12, fill='#888888', outline='#555555')
        self._timer_led_var = tk.StringVar(value='Off')
        tk.Label(tf_left_row, textvariable=self._timer_led_var,
                 bg=GUI_BG, font=('Arial',8), width=5,
                 anchor='w').pack(side=tk.LEFT)

        # ── Separator ─────────────────────────────────────────────────────────
        tk.Frame(tf, width=1, bg='#888888').pack(
            side=tk.LEFT, fill=tk.Y, padx=(2,4))

        # ── Middle: Log ───────────────────────────────────────────────────────
        tf_mid = tk.Frame(tf, bg=GUI_BG)
        tf_mid.pack(side=tk.LEFT, fill=tk.Y, padx=(0,2))
        tk.Label(tf_mid, text='Log', bg=GUI_BG,
                 font=('Arial',8,'bold')).pack(anchor='w')
        tf_mid_row = tk.Frame(tf_mid, bg=GUI_BG)
        tf_mid_row.pack(anchor='w')
        self._log_led_canvas = tk.Canvas(tf_mid_row, width=14, height=14,
                                         bg=GUI_BG, highlightthickness=0)
        self._log_led_canvas.pack(side=tk.LEFT, padx=(0,3))
        self._log_led_oval = self._log_led_canvas.create_oval(
            2, 2, 12, 12, fill='#888888', outline='#555555')
        self._log_led_var = tk.StringVar(value='Off')
        tk.Label(tf_mid_row, textvariable=self._log_led_var,
                 bg=GUI_BG, font=('Arial',8), width=4,
                 anchor='w').pack(side=tk.LEFT)

        # ── Separator ─────────────────────────────────────────────────────────
        tk.Frame(tf, width=1, bg='#888888').pack(
            side=tk.LEFT, fill=tk.Y, padx=(4,4))

        # ── Right: RX activ ───────────────────────────────────────────────────
        tf_right = tk.Frame(tf, bg=GUI_BG)
        tf_right.pack(side=tk.LEFT, fill=tk.Y, padx=(0,0))
        tk.Label(tf_right, text='RX activ', bg=GUI_BG,
                 font=('Arial',8,'bold')).pack(anchor='w')
        tf_right_row = tk.Frame(tf_right, bg=GUI_BG)
        tf_right_row.pack(anchor='w')
        self._trx_led_canvas = tk.Canvas(tf_right_row, width=14, height=14,
                                         bg=GUI_BG, highlightthickness=0)
        self._trx_led_canvas.pack(side=tk.LEFT, padx=(0,3))
        self._trx_led_oval = self._trx_led_canvas.create_oval(
            2, 2, 12, 12, fill='#888888', outline='#555555')
        self._trx_led_var = tk.StringVar(value='Off')
        tk.Label(tf_right_row, textvariable=self._trx_led_var,
                 bg=GUI_BG, font=('Arial',8), width=4,
                 anchor='w').pack(side=tk.LEFT)

    # ── HEADER BAR ───────────────────────────────
    def _build_header_bar(self):
        bar = tk.Frame(self.root, bg='#b0b0b0', relief=tk.SUNKEN, bd=1)
        bar.grid(row=1, column=0, sticky='ew', padx=2, pady=0)
        lbl = tk.Label(bar, textvariable=self.header_var, bg='#c8c8c8',
                       fg='#000080', font=('Arial',11,'bold'),
                       anchor='center', cursor='', pady=6)
        lbl.pack(fill=tk.X)

    # ── PLOT AREA ────────────────────────────────
    def _build_plot_area(self):
        """
        The matplotlib figure goes in column 0, row 2.
        The figure itself draws:
          - left Y-axis  : SNR 0-45 dB (red labels)
          - right content: Frames + Doppler labels (drawn as ax.text, inside figure margins)
        """
        self.plot_frame = tk.Frame(self.root, bg='#0a0a1a', relief=tk.SUNKEN, bd=1)
        self.plot_frame.grid(row=2, column=0, sticky='nsew', padx=(2,0), pady=0)
        plot_frame = self.plot_frame

        # Figure: relatively wide, moderate height
        # ── DPI-aware width ───────────────────────────────────────────────
        # winfo_fpixels('1i') returns the real screen DPI (pixels per inch).
        # On a standard 96-DPI screen (Linux/Windows 100%) → scale = 1.0
        # On Windows 125% scaling → DPI ≈ 120 → scale = 1.25 → fig narrower
        # On Windows 150% scaling → DPI ≈ 144 → scale = 1.50 → fig narrower
        # Clamped to [0.9 … 1.0] so the plot never shrinks below 85% of
        # the base width on very high-DPI displays (e.g. 4K monitors).
        try:
            _screen_dpi = self.root.winfo_fpixels('1i')
            _scale      = max(0.9, min(1.0, 96.0 / _screen_dpi))
        except Exception:
            _scale = 1.0   # fallback — use base size unchanged
        _fig_w = round(8.5 * _scale, 2)

        _frame_init = '#0a0a1a' if self.cfg.get('frame_bg','darkblue') in ('darkblue','black') else ('#555555' if self.cfg.get('frame_bg') == 'gray' else '#ffffff')
        self.fig = Figure(figsize=(_fig_w, 4.0), dpi=96, facecolor=_frame_init)
        # Leave room on right for Frames/Doppler labels inside figure
        self.ax  = self.fig.add_subplot(111)
        self.fig.subplots_adjust(left=0.045, right=0.925, top=0.97, bottom=0.12)
        self._style_axes()

        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        cw = self.canvas.get_tk_widget()
        cw.pack(fill=tk.BOTH, expand=True)
        # Set canvas widget background at init — prevents dark blue bleeding through
        _ax_init = {'darkblue':'#0a0a1a','black':'#0a0a1a',
                    'navy2':'#0a1628','dpurple':'#160a1e','dteal':'#0a1a1a',
                    'lightblue':'#1e304a','gray':'#3a3a3a','white':'#ffffff'}
        cw.configure(bg=_ax_init.get(self.cfg.get('plot_bg','darkblue'), '#0a0a1a'))

    def _style_axes(self):
        ax = self.ax
        # Plot Field Background — Axes area only
        _ax_map = {
            'darkblue':  '#0a0a1a',
            'black':     '#0a0a1a',
            'navy2':     '#0a1628',
            'dpurple':   '#160a1e',
            'dteal':     '#0a1a1a',
            'white':     '#ffffff',
        }
        bg = _ax_map.get(self.cfg.get('plot_bg','darkblue'), '#0a0a1a')
        ax.set_facecolor(bg)
        ax.patch.set_facecolor(bg)
        ax.patch.set_alpha(1.0)

        # Plot Frame Color — Figure margins (scales, time axis, outer area)
        _frame_map = {'darkblue':'#0a0a1a','black':'#0a0a1a',
                      'navy2':'#0a1628','dpurple':'#160a1e','dteal':'#0a1a1a',
                      'gray':'#555555','white':'#ffffff'}
        frame_bg = _frame_map.get(self.cfg.get('frame_bg','darkblue'), '#0a0a1a')
        self.fig.set_facecolor(frame_bg)

        # Text/tick color based on frame color

        # Grid colors based on plot background
        if bg == '#ffffff':
            grid_minor = '#cccccc'
            grid_major = '#bbbbbb'
            grid_green = '#007700'
            spine_col  = '#aaaaaa'
            tick_col   = '#666666'
        else:  # darkblue
            grid_minor = '#2a2a2a'
            grid_major = '#3a3a3a'
            grid_green = '#00aa00'
            spine_col  = '#333333'
            tick_col   = '#666666'
        ax.set_ylim(0, SNR_MAX)
        ax.set_xlim(0, 1)

        # Major ticks every 5 dB
        ax.set_yticks(range(0, SNR_MAX+1, 5))
        # Minor ticks every 1 dB — small tick marks on the axis
        ax.set_yticks(range(0, SNR_MAX+1, 1), minor=True)
        ax.tick_params(axis='y', which='minor', length=3, width=0.6,
                       color=tick_col, left=True, labelleft=False)
        ax.tick_params(axis='y', which='major', length=5, width=1.0, left=True)

        # Y-axis labels: 0,5,10 in ochre (ms/Delay scale), 15-45 in red (SNR)
        tick_labels = []
        tick_colors = []
        for v in range(0, SNR_MAX+1, 5):
            tick_labels.append(str(v))
            tick_colors.append(COL_DELAY if v <= 10 else COL_SNR)

        ax.set_yticklabels(tick_labels, fontsize=9)
        for label, color in zip(ax.get_yticklabels(), tick_colors):
            label.set_color(color)

        ax.set_ylabel('SNR (dB)', color=COL_SNR, fontsize=10)

        ax.set_xticks([])
        for spine in ax.spines.values():
            spine.set_edgecolor(spine_col)

        # Fine grey horizontal grid lines every 1 dB (minor) — loosely dotted
        ax.grid(True, which='minor', axis='y',
                color=grid_minor, linestyle=(0, (2, 6)), linewidth=0.6, alpha=0.9)
        # Slightly brighter grey every 5 dB (major)
        ax.grid(True, which='major', axis='y',
                color=grid_major, linestyle='--', linewidth=0.5, alpha=0.7)

        # Vertical green dashed grid lines (time axis)
        ax.grid(True, which='major', axis='x',
                color='#006600', linestyle='--', linewidth=0.8, alpha=0.8)

        # Green horizontal reference lines — color adapts to background
        for y_db in [0, 45]:
            ax.axhline(y_db, color=grid_green, linestyle='-',
                       linewidth=0.8, alpha=0.9, zorder=1)
        for y_db in [10, 20, 30, 40]:
            ax.axhline(y_db, color=grid_green, linestyle='--',
                       linewidth=0.8, alpha=0.9, zorder=1, dashes=(6, 4))

    # ── RIGHT COLUMN ─────────────────────────────
    def _build_right_col(self, parent):
        """
        Exact right column from original (top to bottom):
        - LabelFrame 'Plot Audio'  → Smooth / Rough
        - LabelFrame 'Plot Audio'  → Thin / Thick
        - LabelFrame 'Plot'        → Doppler / Delay / SNR / Audio checkboxes
        - LabelFrame 'Zoom'        → Start, Stop entries + Zoom in / Restore / Trim Ends
        - Nameless frame           → Add Text, Help, Set Event,
                                     Summary, Print Plot, Set-Up
        - Button 'Close'
        """
        # Plot Audio — one frame with separator between Smooth/Rough and Thin/Thick
        f1 = tk.LabelFrame(parent,text='Plot Audio',bg=GUI_BG,font=('Arial',9,'bold'),padx=3,pady=3)
        f1.pack(fill=tk.X, pady=1, padx=1)
        # Smooth / Rough — stacked vertically
        tk.Radiobutton(f1,text='Smooth',variable=self.opt_smooth,value=1,
                       bg=GUI_BG,font=('Arial',10),command=self._replot).pack(anchor='w')
        tk.Radiobutton(f1,text='Rough', variable=self.opt_smooth,value=0,
                       bg=GUI_BG,font=('Arial',10),command=self._replot).pack(anchor='w')
        # Separator
        ttk.Separator(f1, orient='horizontal').pack(fill=tk.X, pady=3)
        # Thin / Thick — stacked vertically
        tk.Radiobutton(f1,text='Thin', variable=self.opt_thick,value=0,
                       bg=GUI_BG,font=('Arial',10),command=self._replot).pack(anchor='w')
        tk.Radiobutton(f1,text='Thick',variable=self.opt_thick,value=1,
                       bg=GUI_BG,font=('Arial',10),command=self._replot).pack(anchor='w')

        # Spacer — pushes Plot+Zoom frames down to Action buttons
        tk.Frame(parent, bg=GUI_BG).pack(fill=tk.BOTH, expand=True)

        # Plot checkboxes — centred in frame
        f3 = tk.LabelFrame(parent,text='Plot',bg=GUI_BG,font=('Arial',9,'bold'),padx=3,pady=3)
        f3.pack(fill=tk.X, pady=1, padx=1)
        f3_inner = tk.Frame(f3, bg=GUI_BG)
        f3_inner.pack(anchor='center')
        for txt,var,color in [('Doppler',self.opt_doppler,COL_DOPPLER),
                               ('Delay',  self.opt_delay,  COL_DELAY),
                               ('SNR',    self.opt_snr,    COL_SNR),
                               ('Audio',  self.opt_audio,  COL_AUDIO)]:
            cb = tk.Checkbutton(f3_inner, text=txt, variable=var,
                                bg=GUI_BG, font=('Arial', 10), fg=color,
                                activebackground=GUI_BG, activeforeground=color,
                                command=self._replot)
            cb.pack(anchor='w', pady=1)

        # Zoom
        fz = tk.LabelFrame(parent,text='Zoom',bg=GUI_BG,font=('Arial',9,'bold'),padx=3,pady=1)
        fz.pack(fill=tk.X, pady=1, padx=1)
        # Inner frame — centred inside fz
        fz_inner = tk.Frame(fz, bg=GUI_BG)
        fz_inner.pack(anchor='center')

        # Validate: max 4 digits only (HHMM format)
        def _val_4dig(val):
            return len(val) <= 4 and (val == '' or val.isdigit())
        vcmd4 = (fz_inner.register(_val_4dig), '%P')

        tk.Label(fz_inner,text='Start:',bg=GUI_BG,font=('Arial',10)).grid(row=0,column=0,sticky='w')
        e_zoom_start = tk.Entry(fz_inner, textvariable=self.zoom_start_var,
                                width=5, font=('Arial',10),
                                validate='key', validatecommand=vcmd4)
        e_zoom_start.grid(row=0, column=1, sticky='w', pady=2)

        tk.Label(fz_inner,text='Stop:',bg=GUI_BG,font=('Arial',10)).grid(row=1,column=0,sticky='w')
        e_zoom_stop = tk.Entry(fz_inner, textvariable=self.zoom_stop_var,
                               width=5, font=('Arial',10),
                               validate='key', validatecommand=vcmd4)
        e_zoom_stop.grid(row=1, column=1, sticky='w', pady=2)

        # Select-all-on-focus (Aug 2026) — same mechanism as the RX
        # Coordinates fields in Basic Setup Parameters: without this, a
        # user clicking directly into either field to edit an existing
        # zoom range had to manually clear the old HHMM value first,
        # since new digits were simply appended to it instead of
        # replacing it.
        def _zoom_select_all_on_focus(event):
            event.widget.select_range(0, tk.END)
            event.widget.icursor(tk.END)
        e_zoom_start.bind('<FocusIn>', _zoom_select_all_on_focus)
        e_zoom_stop.bind('<FocusIn>', _zoom_select_all_on_focus)

        # Auto-tab: jump to Stop when 4 digits entered in Start
        def _zoom_autotab(*_):
            if len(self.zoom_start_var.get()) == 4:
                e_zoom_stop.focus_set()
                e_zoom_stop.select_range(0, tk.END)
        self.zoom_start_var.trace_add('write', _zoom_autotab)
        tk.Button(fz_inner,text='Zoom in',  font=('Arial',8),width=10,
                  command=self._do_zoom).grid(row=2,column=0,columnspan=2,pady=(3,1))
        tk.Button(fz_inner,text='Trim Ends',font=('Arial',8),width=10,
                  command=self._trim_ends).grid(row=3,column=0,columnspan=2,pady=1)
        tk.Button(fz_inner,text='Restore',  font=('Arial',8),width=10,
                  command=self._do_restore).grid(row=4,column=0,columnspan=2,pady=(1,3))

        # ── Bottom buttons in a GROOVE frame (no title) ─────────────────
        fb_bottom = tk.Frame(parent, bg=GUI_BG, relief=tk.GROOVE, bd=2)
        fb_bottom.pack(side=tk.BOTTOM, fill=tk.X, pady=2, padx=1)
        tk.Button(fb_bottom, text='RX+Ant Info', font=('Arial',8), bg='#aaddff', width=10,
                  command=self._edit_header).pack(pady=(1,1), padx=3)
        tk.Button(fb_bottom, text='Close', font=('Arial',8,'bold'), bg='#ffaaaa', width=10,
                  command=self._on_close).pack(pady=(1,2), padx=3)

        # Action buttons — packed BOTTOM after Close/RX+Ant
        fa = tk.Frame(parent, bg=GUI_BG, relief=tk.GROOVE, bd=2)
        fa.pack(side=tk.BOTTOM, fill=tk.X, pady=2, padx=1)
        for txt,cmd in [('Add Text',  self._add_text),
                         ('Print Plot',self._print_plot),
                         ('Summary',  self._show_summary),
                         ('Set Event',self._set_event),
                         ('About',    self._about),
                         ('Help',     self._show_help),
                         ('Set-Up',   self._open_setup)]:
            tk.Button(fa,text=txt,font=('Arial',8),width=10,command=cmd).pack(pady=1,padx=3)

    # ── BOTTOM BAR ───────────────────────────────
    def _build_bottom_bar(self, parent):
        # 1) Miscellaneous
        fm = tk.LabelFrame(parent,text='Miscellaneous',bg=GUI_BG,
                           font=('Arial',9,'bold'),padx=3,pady=2)
        fm.pack(side=tk.LEFT, padx=2, fill=tk.Y)
        _loc_name = self.cfg.get('location_name', '').strip()
        self.v_location = tk.StringVar(value=_loc_name if _loc_name else 'RX Location')
        self.v_lat_disp = tk.StringVar(value=f"{self.cfg.get('rx_lat_deg')}°{self.cfg.get('rx_lat_min'):02d}'{self.cfg.get('rx_lat_ns')}")
        self.v_lon_disp = tk.StringVar(value=f"{self.cfg.get('rx_lon_deg')}°{self.cfg.get('rx_lon_min'):02d}'{self.cfg.get('rx_lon_ew')}")
        self.v_software = tk.StringVar(value='s/w')
        self.v_dist     = tk.StringVar(value='km')
        self.v_az       = tk.StringVar(value='?')
        for r,(lbl,var) in enumerate([('Location:',self.v_location),('Latitude:',self.v_lat_disp),
                                       ('Longitude:',self.v_lon_disp),('Software:',self.v_software)]):
            tk.Label(fm,text=lbl,bg=GUI_BG,font=('Arial',10),anchor='w',width=9).grid(row=r,column=0,sticky='w',pady=2)
            tk.Label(fm,textvariable=var,bg=GUI_BG,font=('Arial',10,'bold'),
                     fg='#000080',anchor='w',width=16).grid(row=r,column=1,sticky='w',pady=2)
        tk.Label(fm,text='Distance to TX site:',bg=GUI_BG,font=('Arial',10)).grid(row=0,column=2,sticky='w',padx=(10,0))
        tk.Label(fm,textvariable=self.v_dist,bg=GUI_BG,font=('Arial',10,'bold'),fg='#000080').grid(row=1,column=2,sticky='w',padx=(10,0))
        tk.Label(fm,text='Az. to / from TX site:',bg=GUI_BG,font=('Arial',10)).grid(row=2,column=2,sticky='w',padx=(10,0))
        tk.Label(fm,textvariable=self.v_az,bg=GUI_BG,font=('Arial',10,'bold'),fg='#000080').grid(row=3,column=2,sticky='w',padx=(10,0))

        # 2) Auto Plot
        fap = tk.LabelFrame(parent,text='Auto Plot',bg=GUI_BG,
                            font=('Arial',9,'bold'),padx=3,pady=4)
        fap.pack(side=tk.LEFT, padx=2, fill=tk.Y)
        self.v_ap_interval=tk.StringVar(value='Interval:')
        self.v_ap_refresh =tk.StringVar(value='Refresh:')
        self.v_ap_scroll  =tk.StringVar(value='Scroll:   Off')
        for var in [self.v_ap_interval,self.v_ap_refresh,self.v_ap_scroll]:
            tk.Label(fap,textvariable=var,bg=GUI_BG,font=('Arial',9),anchor='w',width=16).pack(anchor='w',pady=2)
        ap_row = tk.Frame(fap, bg=GUI_BG)
        ap_row.pack(anchor='w', pady=(6,2))
        # LED indicator — grey=inactive, green=active (like Headers/LogLong)
        self.ap_led = tk.Canvas(ap_row, width=14, height=14, bg=GUI_BG,
                                highlightthickness=0)
        self.ap_led.pack(side=tk.LEFT, padx=(0, 4))
        self._ap_oval = self.ap_led.create_oval(2, 2, 12, 12,
                                                fill='#888888', outline='#555555')
        # Windows-only (Aug 2026): frame width is governed by the 16-char
        # labels above (Interval:/Refresh:/Scroll:), confirmed to leave
        # visible slack around this button on Windows 10/11 — Linux stays
        # exactly as before.
        _is_win_ap = _platform.system() == 'Windows'
        _ap_btn_width = 9 if _is_win_ap else None
        _ap_btn_padx  = (6,0) if _is_win_ap else (0,0)
        self.ap_btn = tk.Button(ap_row, text='Auto Plot', font=('Arial',9),
                                width=_ap_btn_width,
                                command=self._toggle_autoplot)
        self.ap_btn.pack(side=tk.LEFT, padx=_ap_btn_padx)

        # 3) Transmitter Site — taller text area, button aligned with Auto Plot button
        # Aug 2026, user request ("DRMLogPlotter - UTC in GUI"): renamed
        # to 'TX Sites and UTC' and given a small live UTC clock of its
        # own, squeezed into the frame WITHOUT changing the frame's
        # width or height by a single pixel. The room for the clock is
        # taken from the site Listbox below (3 visible lines -> 2) —
        # nothing else in the frame (buttons, their size/position) is
        # touched. The clock itself reuses the same shared
        # _build_text_clock() helper as the two Radio-List dialogs (same
        # Arial family, bold, green #008800), just at a much smaller
        # font size (10 instead of 14) and WITHOUT the bordered
        # GROOVE box those dialogs use, since there is no vertical
        # budget here for a border/padding — confirmed OK by user.
        fts = tk.LabelFrame(parent, text='Transmitter Site', bg=GUI_BG,
                            font=('Arial',9,'bold'), padx=3, pady=2)
        fts.pack(side=tk.LEFT, padx=2, fill=tk.Y)
        self.v_tx_display = tk.StringVar(value='')
        # Small UTC clock row — plain (no relief/border), packed FIRST so
        # it sits directly under the frame's title border, above the
        # hint line and the site Listbox. Reuses the app-wide alive flag
        # set in _on_close() so its 1s tick loop stops when the app
        # closes, same pattern as the Radio-List clocks.
        #
        # Aug 2026, user feedback round 2:
        #  - centred horizontally: NOT packed with fill=tk.X any more —
        #    left without fill, so the row shrink-wraps to the width of
        #    its two labels and pack()'s default anchor='center' then
        #    centres that whole (shrunk) row within the frame's actual
        #    width (which is still driven by the Listbox below, fill=X
        #    there, completely unchanged).
        #  - 'UTC:' label is now Arial 12 BOLD, same size/weight as the
        #    digits (was 8, not bold) — user request, also fixes the
        #    two texts not sharing a visual baseline.
        #  - anchor='s' on both labels bottom-aligns them within the
        #    row's height so 'UTC:' and the digits sit on one shared
        #    (invisible) baseline instead of each being independently
        #    centred.
        # Aug 2026, user feedback round 3: the gap seen between the
        # clock's baseline and the red hint line below it is NOT an
        # intentional pady of mine — it's Tk's own default per-Label
        # padding + highlightthickness (reserved even when the label
        # never gets keyboard focus) plus the font's own descender
        # space (room reserved below the glyphs for letters like 'g'/
        # 'y', even though 'UTC: 19:45:58' has none). Zeroing bd/
        # highlightthickness/pady on every Label here is a genuine net
        # height reduction (not a redistribution like the centring fix
        # was), which is what's needed since the TX Sites/Radio List
        # buttons are still sitting a touch lower than the Auto
        # Plot / Select Main Log buttons.
        tx_clock_row = tk.Frame(fts, bg=GUI_BG, bd=0, highlightthickness=0)
        tx_clock_row.pack(pady=0)
        # Aug 2026, user feedback (Windows 11 build test, round 2): the
        # previous +2px TOP pady on the digits had no visible effect —
        # both labels use anchor='s' (bottom-anchored) with 0 pady, so
        # the row's height simply grows to fit the now-taller digit
        # cell while the digits themselves stay glued to its bottom
        # edge; nothing shifts relative to 'UTC:'. Reversed logic: since
        # 'UTC:' is the reference and the digits are already correctly
        # bottom-anchored, 'UTC:' itself gets a tiny Windows-only BOTTOM
        # pady instead — that nudges 'UTC:' up by that amount within the
        # row, so the (unmoved) digits now sit visibly lower by
        # comparison. Digits label is back to pady=0 (Linux, which is
        # already pixel-perfect, was and remains completely unaffected
        # either way since it never got this padding).
        _is_win_clock = _platform.system() == 'Windows'
        tk.Label(tx_clock_row, text='UTC:', bg=GUI_BG,
                 font=('Arial',11), fg='black',
                 bd=0, highlightthickness=0, pady=0).pack(
                 side=tk.LEFT, anchor='s', padx=(0,3),
                 pady=(0, 1 if _is_win_clock else 0))
        self._build_text_clock(tx_clock_row, self._main_clock_alive,
                                font=('Arial',11,'bold'), tight=True).pack(
                                side=tk.LEFT, anchor='s')
        # Listbox — click to select site directly
        # Same zeroing as above on the (usually empty) hint label —
        # its text/colour/visibility logic is completely untouched,
        # only its own invisible default border/padding is removed.
        self._tx_hint_lbl = tk.Label(fts, text='', bg=GUI_BG,
                                     font=('Arial',8,'italic'), fg='#cc2200',
                                     bd=0, highlightthickness=0, pady=0)
        self._tx_hint_lbl.pack(pady=0)
        tx_lb_frame = tk.Frame(fts, bg='white', relief=tk.SUNKEN, bd=1)
        tx_lb_frame.pack(fill=tk.X, pady=2)
        # height=2 (was 3) — the one line given up here is exactly the
        # room the UTC clock row above now uses. In the rare case of
        # more than 2 TX sites listed for one frequency, the Listbox
        # simply scrolls/truncates like any other short Listbox — user
        # confirmed this trade-off is acceptable, no scrollbar added.
        self.tx_lb = tk.Listbox(tx_lb_frame, font=('Arial',9), height=2,
                                bg='white', fg='#000080',
                                selectbackground='#000080',
                                selectforeground='white',
                                activestyle='none',
                                relief=tk.FLAT, bd=0)
        self.tx_lb.pack(fill=tk.X, padx=2, pady=1)
        self.tx_lb.bind('<<ListboxSelect>>', self._on_tx_lb_select)
        # Two buttons side by side, same row, same height — narrower than
        # the previous single button so the frame's own width (driven by
        # the listbox above, not by this row) never has to grow.
        #
        # Aug 2026, user feedback (Windows 11 build test): on Windows the
        # 'TX Sites' / 'Radio List' buttons sit a couple of pixels too
        # HIGH relative to their neighbours (Auto Plot / Select Main
        # Log) — the opposite direction of the earlier Linux fix, and
        # confirmed Linux/Raspberry Pi are pixel-perfect as-is. Same
        # platform-only pattern as _is_win_tx just below: only the TOP
        # gap above this button row grows on Windows (4px -> 6px,
        # +2px probe value), bottom gap and everything else stays
        # untouched, Linux/Pi keep the original pady=(4,2) exactly.
        _is_win_tx_gap = _platform.system() == 'Windows'
        _tx_btn_row_top_pad = 7 if _is_win_tx_gap else 4
        tx_btn_row = tk.Frame(fts, bg=GUI_BG)
        tx_btn_row.pack(pady=(_tx_btn_row_top_pad,2))
        # Windows-only (Aug 2026): these two buttons render visibly more
        # cramped/clipped-looking on Windows 10/11 than on Linux — same
        # kind of platform rendering difference as the Linux font-width
        # fix elsewhere (there Linux needed more room; here it's the
        # other way round). platform.system() only distinguishes
        # "Windows" from "Linux"/"Darwin" in general, not individual
        # Windows versions — this applies to any Windows version, but
        # confirmed wanted for Windows 10/11 specifically; Linux/
        # Raspberry Pi are completely unaffected either way.
        #
        # Widths chosen to make better use of the fixed listbox's width
        # above (that listbox itself is never touched) — measured from a
        # real Windows 11 screenshot: listbox content ≈150px, previous
        # combined button width only ≈119px, confirming visible slack.
        _is_win_tx = _platform.system() == 'Windows'
        _tx_sites_width  = 8  if _is_win_tx else 6
        _radio_list_width = 10 if _is_win_tx else 8
        _tx_btn_gap = 6 if _is_win_tx else 2
        tk.Button(tx_btn_row, text='TX Sites', font=('Arial',9), width=_tx_sites_width,
                  command=self._open_tx_sites).pack(side=tk.LEFT, padx=(0,_tx_btn_gap))
        # Opens the same DRM-Radio-List window used inside 'Dream — Start
        # & Schedule' (self._open_drm_radio_list_window()) — fully
        # self-sufficient here: no freq_var/parent given, so it creates
        # its own, initialised from the same persisted last-used
        # frequency, and reports its own status without needing that
        # other dialog to be open.
        # Toggle behaviour (Aug 2026, user request): a 2nd click while
        # the window is already open closes it instead of opening a
        # further copy — see self._toggle_drm_radio_list_window().
        tk.Button(tx_btn_row, text='Radio List', font=('Arial',9), width=_radio_list_width,
                  command=lambda: self._toggle_drm_radio_list_window()
                  ).pack(side=tk.LEFT)

        # 4) Select Main Log — wider listbox, bigger buttons
        fsl = tk.LabelFrame(parent,text='Select Main Log',bg=GUI_BG,
                            font=('Arial',9,'bold'),padx=3,pady=2)
        fsl.pack(side=tk.LEFT, padx=2, fill=tk.Y)
        # Listbox + scrollbar — 3 lines height
        lb_frame = tk.Frame(fsl, bg=GUI_BG)
        lb_frame.pack(fill=tk.X)
        self.log_lb=tk.Listbox(lb_frame,font=('Courier',11),width=30,height=4,
                               selectmode=tk.SINGLE,bg='white',
                               selectbackground='#000080',selectforeground='white')
        sb=ttk.Scrollbar(lb_frame,command=self.log_lb.yview)
        self.log_lb.configure(yscrollcommand=sb.set)
        self.log_lb.pack(side=tk.LEFT)
        sb.pack(side=tk.LEFT,fill=tk.Y)
        self.log_lb.bind('<<ListboxSelect>>',self._on_log_select)
        # 4 buttons in a row below the listbox
        # Order: Publish | Screenshot | PNG | Load Log
        # expand=True + fill=X — buttons share available width equally,
        # no fixed width= so text never gets clipped on Windows.
        btn_row = tk.Frame(fsl, bg=GUI_BG)
        btn_row.pack(fill=tk.X, pady=(6,6))
        tk.Button(btn_row, text='Publish',
                  font=('Arial',9),
                  command=self._publish).pack(
                  side=tk.LEFT, padx=1, expand=True, fill=tk.X)
        self.ss_btn = tk.Button(btn_row, text='Screenshot',
                                font=('Arial',9),
                                command=self._screenshot, state=tk.DISABLED)
        self.ss_btn.pack(side=tk.LEFT, padx=1, expand=True, fill=tk.X)
        tk.Button(btn_row, text='PNG',
                  font=('Arial',9),
                  command=self._show_logs).pack(
                  side=tk.LEFT, padx=1, expand=True, fill=tk.X)
        tk.Button(btn_row, text='Show Logs',
                  font=('Arial',9),
                  command=self._select_main).pack(
                  side=tk.LEFT, padx=1, expand=True, fill=tk.X)

        # 6) Update Files — packed RIGHT so it sits directly below Close button
        fuf=tk.LabelFrame(parent,text='Update Files',bg=GUI_BG,
                          font=('Arial',9,'bold'),padx=2,pady=1)
        fuf.pack(side=tk.LEFT,padx=4,fill=tk.Y)
        tk.Label(fuf,text='Headers',bg=GUI_BG,font=('Arial',9),anchor='w').grid(row=0,column=0,sticky='w')
        self.led_h=tk.Canvas(fuf,width=14,height=14,bg=GUI_BG,highlightthickness=0)
        self.led_h.grid(row=0,column=1,padx=4)
        self._led_h=self.led_h.create_oval(2,2,12,12,fill='#cc0000',outline='#880000')
        tk.Label(fuf,text='LogLong',bg=GUI_BG,font=('Arial',9),anchor='w').grid(row=1,column=0,sticky='w')
        self.led_l=tk.Canvas(fuf,width=14,height=14,bg=GUI_BG,highlightthickness=0)
        self.led_l.grid(row=1,column=1,padx=4)
        self._led_l=self.led_l.create_oval(2,2,12,12,fill='#cc0000',outline='#880000')
        self.v_logs_count=tk.StringVar(value='No')
        self.v_logs_size =tk.StringVar(value='')
        tk.Label(fuf,text='Logs:',bg=GUI_BG,font=('Arial',9)).grid(row=2,column=0,sticky='w')
        tk.Label(fuf,textvariable=self.v_logs_count,bg=GUI_BG,font=('Arial',9,'bold')).grid(row=2,column=1,sticky='w')
        tk.Label(fuf,text='Size:',bg=GUI_BG,font=('Arial',9)).grid(row=3,column=0,sticky='w')
        tk.Label(fuf,textvariable=self.v_logs_size,bg=GUI_BG,font=('Arial',9,'bold')).grid(row=3,column=1,sticky='w')
        uf_btn_row = tk.Frame(fuf, bg=GUI_BG)
        uf_btn_row.grid(row=4, column=0, columnspan=2, pady=1, sticky='w')
        # Windows-only (Aug 2026) — same rationale as the TX Sites / Radio
        # List row above: these two buttons look visibly more cramped on
        # Windows 10/11 than on Linux/Raspberry Pi, which stays completely
        # unaffected. A tiny bit more width + gap fixes it without the
        # "Update Files" frame itself changing size (it's sized by the
        # LED/label rows above, not by this button row).
        _is_win = _platform.system() == 'Windows'
        _uf_update_width = 7 if _is_win else 6
        _uf_stop_width   = 6 if _is_win else 5
        _uf_btn_gap      = 3 if _is_win else 1
        tk.Button(uf_btn_row, text='Update', font=('Arial',8,'bold'),
                  bg='#aaddaa', width=_uf_update_width,
                  command=self._update_files).pack(side=tk.LEFT, padx=(0,_uf_btn_gap))
        self._stop_dream_btn = tk.Button(
            uf_btn_row, text='Stop\nDream',
            font=('Arial', 7), fg='#cc0000',
            width=_uf_stop_width,
            state=tk.DISABLED,
            command=self._stop_dream_from_main)
        self._stop_dream_btn.pack(side=tk.LEFT)

        # 5) 4 stacked buttons — next to Update Files (also RIGHT side)
        fb4=tk.Frame(parent,bg=GUI_BG, relief=tk.GROOVE, bd=2)
        fb4.pack(side=tk.LEFT,padx=2,pady=2)
        for txt,cmd in [('Load Log',  self._load_log),
                        ('Save Log',  self._save_log),
                        ('Main Log',  self._select_main),
                        ('Comp. Log', self._compare_log)]:
            tk.Button(fb4,text=txt,font=('Arial',9),width=10,
                      command=cmd).pack(fill=tk.X,pady=1)

    # ─────────────────────────────────────────────────
    # LED helper
    # ─────────────────────────────────────────────────
    def _toggle_snr_dot(self, which):
        """Toggle SNR max/min dot or avg line on the plot."""
        if which == 'max':
            self._show_snr_max_dot  = not self._show_snr_max_dot
        elif which == 'min':
            self._show_snr_min_dot  = not self._show_snr_min_dot
        elif which == 'avg':
            self._show_snr_avg_line = not self._show_snr_avg_line
        self._replot()

    def _set_led(self, canvas, oval_id, green):
        c,o = ('#00cc00','#008800') if green else ('#cc0000','#880000')
        canvas.itemconfig(oval_id,fill=c,outline=o)

    # ─────────────────────────────────────────────────
    # FILE LOADING
    # ─────────────────────────────────────────────────
    def _update_files(self):
        """Step 1: choose DreamLog.txt  Step 2: choose DreamLogLong.csv"""
        init = self.cfg.get("last_log_dir", os.path.expanduser("~"))
        txt = filedialog.askopenfilename(
            title="Step 1 of 2 - Select DreamLog.txt",
            initialdir=init,
            filetypes=[("Dream Log","DreamLog.txt"),("Text","*.txt"),("All","*.*")]
        )
        if not txt: return
        d = os.path.dirname(txt)
        csv_p = filedialog.askopenfilename(
            title="Step 2 of 2 - Select DreamLogLong.csv",
            initialdir=d,
            filetypes=[("CSV","DreamLogLong.csv"),("CSV","*.csv"),("All","*.*")]
        )
        if not csv_p: return
        self.cfg.set("last_log_dir", d)
        self._load_files(txt, csv_p)

    def _load_files(self, txt_path, csv_path):
        # ── Reset ALL old data first ──────────────────────────────────
        self.all_logs  = []
        self.all_csv   = []
        self.plot_rows = []
        self.comp_rows = []
        self.sel_log   = None
        self.sel_tx    = None
        self.zoom_active = False
        self.zoom_t0 = self.zoom_t1 = None

        # Reset all display fields to defaults
        self.log_lb.delete(0, tk.END)
        self.v_label.set('label');   self.v_freq.set('freq')
        self.v_txloc.set('site');    self.v_date.set('date')
        self.v_mode.set('bw');       self.v_bitrate.set('kbps')
        self.v_msc.set('qam');       self.v_pl.set('PL')
        self.v_audio_codec.set('—'); self.v_audio_mode.set('—')
        self.v_audio_pct.set('audio'); self.v_fac.set('sfm')
        self.v_snr_max.set('sma'); self.v_snr_min.set('smi'); self.v_snr_avg.set('avg')
        self.v_del_max.set('dma'); self.v_del_min.set('dmi'); self.v_del_avg.set('dev')
        self.v_dop_max.set('dma'); self.v_dop_min.set('dmi'); self.v_dop_avg.set('dav')
        self.v_runtime.set('0 h 0 m')
        self.v_tx_display.set('')
        self.v_dist.set(''); self.v_az.set('?')
        self.v_software.set('s/w')
        self.v_logs_count.set('No'); self.v_logs_size.set('')
        self._set_led(self.led_h, self._led_h, False)
        self._set_led(self.led_l, self._led_l, False)
        self.modes_text.configure(state=tk.NORMAL)
        self.modes_text.delete('1.0', tk.END)
        self.modes_text.configure(state=tk.DISABLED)
        self.ax.cla(); self._style_axes(); self.canvas.draw()

        # ── Load new files ────────────────────────────────────────────
        self.txt_path = txt_path
        self.csv_path = csv_path
        txt_ok = csv_ok = False

        try:
            self.all_logs = parse_dreamlog_txt(txt_path)
            txt_ok = bool(self.all_logs)
        except Exception as e:
            messagebox.showerror('Error', f'DreamLog.txt:\n{e}')

        try:
            self.all_csv = load_csv_rows(csv_path)
            csv_ok = bool(self.all_csv)
        except Exception as e:
            messagebox.showerror('Error', f'DreamLogLong.csv:\n{e}')

        self._set_led(self.led_h, self._led_h, txt_ok)
        self._set_led(self.led_l, self._led_l, csv_ok)
        size_kb = sum(os.path.getsize(p) // 1024
                      for p in [txt_path, csv_path] if os.path.exists(p))
        self.v_logs_count.set(str(len(self.all_logs)))
        self.v_logs_size.set(f'{max(1, size_kb)} kB')
        self.v_software.set(
            f'Dream {self.all_logs[0].sw_version}' if self.all_logs else 's/w')
        for log in reversed(self.all_logs):
            self.log_lb.insert(tk.END, log.display_name())
        if self.all_logs:
            self.log_lb.select_set(0)
            self._on_log_select(None)
        self.ss_btn.configure(state=tk.NORMAL if self.all_logs else tk.DISABLED)

    # ─────────────────────────────────────────────────
    # LOG SELECTION
    # ─────────────────────────────────────────────────
    def _on_log_select(self,event):
        sel=self.log_lb.curselection()
        if not sel: return
        lb_idx = sel[0]
        # Listbox shows logs newest-first (reversed), but all_logs is
        # stored oldest-first. Convert listbox position to all_logs index.
        idx = len(self.all_logs) - 1 - lb_idx
        self.sel_log=self.all_logs[idx]
        self.zoom_active=False; self.zoom_t0=self.zoom_t1=None
        # Clear annotations when a new log is selected
        self._annotations     = []
        self._annotation_free = ''
        self._show_vlines     = True
        self._free_x          = 0.50
        self._free_y          = 0.50
        next_start=(self.all_logs[idx+1].start_time if idx+1<len(self.all_logs)
                    else self.sel_log.start_time+timedelta(hours=6))
        self.plot_rows=filter_csv_for_log(self.all_csv,self.sel_log.start_time,next_start)
        self._update_meta()
        self._update_tx_site()
        self._update_stats()
        self._replot()
        # Load audio codec info for this log from DreamAudio.json
        self._load_dream_audio_for_log(self.sel_log)

    def _update_meta(self):
        log=self.sel_log
        self.v_label.set(log.label); self.v_freq.set(log.frequency)
        self.v_date.set(log.start_time.strftime('%Y-%m-%d') if log.start_time else '')
        self.v_mode.set(f'{log.mode} / {log.bandwidth}')
        self.v_bitrate.set(log.bitrate)
        if self.plot_rows:
            r0  = self.plot_rows[0]
            fmq = r0.get('FREQ/MODE/QAM PL:ABH', '').strip()
            # Format: FREQ/ModeQAMplABH  e.g. "13690/B3010"
            # digit 1 after Mode = QAM index: 0,1=16-QAM  2,3=64-QAM
            # digit 2 = Protection Level high part
            # digit 3 = Protection Level low part
            parts = fmq.split('/')
            if len(parts) >= 2:
                code = parts[1]   # e.g. "B3010"
                if len(code) >= 4:
                    qam_idx = code[1]
                    pl_a    = code[2]   # Protection Level A (Stelle 3)
                    pl_b    = code[3]   # Protection Level B (Stelle 4)
                    # DRM QAM + Protection Level — algorithmic decode
                    # Code format after Mode letter: Q P_A P_B R
                    #   Q   = MSC modulation: 0 → 64-QAM, 3 → 16-QAM
                    #   P_A = Protection Level A (Stelle 3): 0 or 1
                    #   P_B = Protection Level B (Stelle 4): 0 or 1
                    #   R   = reserved (always 0, ignored)
                    # Display order: P_B / P_A  (matches original DRM-Log Plotter)
                    # Examples: B0000→64QAM 0/0  B3000→16QAM 0/0  B3010→16QAM 1/0
                    qam_map = {'0': '64 QAM', '3': '16 QAM'}
                    qam_str = qam_map.get(qam_idx, f'{qam_idx} QAM')
                    pl_str  = f'{pl_b} / {pl_a}'
                    self.v_msc.set(qam_str)
                    self.v_pl.set(pl_str)
                else:
                    self.v_msc.set('-'); self.v_pl.set('-')
            else:
                self.v_msc.set('-'); self.v_pl.set('-')

    def _update_tx_site(self, silent=False):
        """Update TX site display.
        silent=True  — no messagebox (used by AutoPlot / Timer-started logs).
        silent=False — show dialog if site not found (used by manual log select).
        """
        if not self.sel_log: return
        freq_str = self.sel_log.frequency
        matches  = find_tx_for_freq(self.tx_sites, freq_str)

        # Clear listbox
        self.tx_lb.delete(0, tk.END)
        self._tx_hint_lbl.config(text='')

        if not matches:
            self.sel_tx = None
            self.v_txloc.set('? No TX site found')
            self.v_tx_display.set(f'No site for {freq_str}')
            self.v_dist.set('')
            self.v_az.set('?')
            self.tx_lb.insert(tk.END, f'No site for {freq_str}')
            if not silent:
                if messagebox.askyesno(
                    'TX Site not found',
                    f'No transmitter site found for {freq_str}\n\n'
                    f'Open "Manage the Transmitter Sites List"\n'
                    f'to add or edit a site for this frequency?'
                ):
                    self._manage_tx_sites()
            return

        # Fill listbox with all matches
        self._tx_matches = matches
        for s in matches:
            self.tx_lb.insert(tk.END, s['location'])

        if len(matches) == 1:
            # Only one site — select automatically
            self.tx_lb.select_set(0)
            self.sel_tx = matches[0]
            self._apply_tx_site()
        else:
            # Multiple sites
            if self.cfg.get('multiple_sites_alert', True):
                # Alert ON — show hint, wait for user click
                self._tx_hint_lbl.config(text='↑ Choose Transmitter Site')
                self.sel_tx = None
                self.v_txloc.set('?')
                self.v_dist.set('')
                self.v_az.set('?')
            else:
                # Alert OFF — select first site automatically
                self.tx_lb.select_set(0)
                self.sel_tx = matches[0]
                self._apply_tx_site()

    def _on_tx_lb_select(self, event):
        # pylint: disable=unused-argument
        """User clicked a TX site — show only the selected site in the listbox."""
        sel = self.tx_lb.curselection()
        if sel and hasattr(self, '_tx_matches'):
            self.sel_tx = self._tx_matches[sel[0]]
            self._tx_hint_lbl.config(text='')
            # Show only the selected site in the listbox
            selected_loc = self.sel_tx['location']
            self.tx_lb.delete(0, tk.END)
            self.tx_lb.insert(tk.END, selected_loc)
            self.tx_lb.select_set(0)
            self._apply_tx_site()

    def _apply_tx_site(self):
        """Apply the selected TX site: show name, calculate distance and azimuth."""
        if not self.sel_tx: return
        loc = self.sel_tx['location']
        self.v_txloc.set(loc)
        self.v_tx_display.set(loc)
        # Highlight selected in listbox
        if hasattr(self, '_tx_matches'):
            for i, s in enumerate(self._tx_matches):
                if s is self.sel_tx:
                    self.tx_lb.select_clear(0, tk.END)
                    self.tx_lb.select_set(i)
                    break

        # Distance and azimuth using Haversine formula
        rx_lat = self.cfg.rx_lat()
        rx_lon = self.cfg.rx_lon()
        tx_lat = self.sel_tx['lat']
        tx_lon = self.sel_tx['lon']

        dist, az = haversine(rx_lat, rx_lon, tx_lat, tx_lon)
        # True back-azimuth (bearing from TX back to RX) — NOT simply
        # az+180. That shortcut is only exact for a rhumb line (constant
        # compass course); on a great-circle path (which we already use
        # for distance and the forward azimuth above) the bearing changes
        # continuously along the path, so the reverse bearing must be
        # calculated independently, with start/end swapped. Confirmed via
        # a side-by-side comparison against the original drmlogplotter
        # (Munich -> transmitter): forward azimuth matched exactly (266°),
        # but az+180 gave 86° back-azimuth vs. the original's correct 79°.
        _, az_back_f = haversine(tx_lat, tx_lon, rx_lat, rx_lon)

        if self.cfg.get('unit') == 'miles':
            dist = round(dist * 0.621371, 1)
            unit = 'miles'
        else:
            unit = 'km'

        az_back = int(round(az_back_f))
        dist_int = int(round(dist))
        az_int   = int(round(az))
        self.v_dist.set(f'{dist_int} {unit}')
        self.v_az.set(f'{az_int} / {az_back} deg.')


    def _get_active_rows(self):
        """Return plot_rows filtered by current zoom — same data as the plot."""
        if not self.plot_rows:
            return []
        if self.zoom_active and self.zoom_t0 and self.zoom_t1:
            return [r for r in self.plot_rows
                    if _is_float(r.get('SNR','')) and
                    self.zoom_t0 <= parse_dt(r['DATE'], r['TIME']) <= self.zoom_t1]
        return self.plot_rows

    def _update_stats(self, rows=None):
        if rows is None:
            rows = self._get_active_rows()
        if not rows: return
        def fmt(v): return f'{v:.2f}' if v is not None else '-'
        sn_min,sn_max,sn_avg=compute_stats(rows,'SNR')
        dl_min,dl_max,dl_avg=compute_stats(rows,'DELAY')
        dp_min,dp_max,dp_avg=compute_stats(rows,'DOPPLER')
        self.v_snr_max.set(fmt(sn_max));self.v_snr_min.set(fmt(sn_min));self.v_snr_avg.set(fmt(sn_avg))
        self.v_del_max.set(fmt(dl_max));self.v_del_min.set(fmt(dl_min));self.v_del_avg.set(fmt(dl_avg))
        self.v_dop_max.set(fmt(dp_max));self.v_dop_min.set(fmt(dp_min));self.v_dop_avg.set(fmt(dp_avg))
        # AUDIOOK / AUDIO ratio = decoded audio percentage
        ao_sum = sum(float(r.get('AUDIOOK', 0)) for r in rows if _is_float(r.get('AUDIOOK','')))
        at_sum = sum(float(r.get('AUDIO',   0)) for r in rows if _is_float(r.get('AUDIO','')))
        pct = round(ao_sum / at_sum * 100, 2) if at_sum > 0 else 0.0
        self.v_audio_pct.set(f'{pct:.2f} %')
        # FAC=1 means successful decode, FAC=0 means error
        # We want: how many seconds had FAC=1 (successful) out of total
        fac_ok = sum(1 for r in rows if r.get('FAC','').strip() == '1')

        # Max audio frames — from drmlog.txt minute lines (already parsed)
        if self.sel_log and self.sel_log.max_audio_frames > 0:
            self.v_audio_max.set(str(self.sel_log.max_audio_frames))
        else:
            self.v_audio_max.set('---')
        fac_pct = round(fac_ok / len(rows) * 100, 2) if rows else 0.0
        self.v_fac.set(f'{fac_pct:.2f} %')
        if rows:
            try:
                t0 = parse_dt(rows[0]['DATE'], rows[0]['TIME'])
                t1 = parse_dt(rows[-1]['DATE'], rows[-1]['TIME'])
                mins = int((t1 - t0).total_seconds() // 60)
                self.v_runtime.set(f'{mins//60} h {mins%60} m')
            except: self.v_runtime.set('0 h 0 m')
        # modes — use same filtered rows as stats
        self.modes_text.configure(state=tk.NORMAL)
        self.modes_text.delete('1.0', tk.END)
        prev_real = None   # tracks last REAL mode (ignores unconfirmed glitches)

        # ── Pre-scan: count consecutive occurrences of each mode ──────────
        # A mode is only accepted as REAL if it appears for at least
        # MIN_MODE_SECS consecutive seconds AND has MSC=1 on first entry.
        # This filters out single-entry glitches like B1010 at signal loss.
        MIN_MODE_SECS = 5

        # Dream fills the log with e.g. "B0000" when it has no valid QAM/
        # Protection-Level reading yet (so the line isn't left empty) — this
        # does NOT necessarily mean "no signal". Gegenprüfung: if a genuine,
        # SUSTAINED SNR + SYNC + MSC reading shows up, the "...0000" entry is
        # treated as a real, valid reception period starting at that recovery
        # moment. Note: this never distinguishes by the mode CODE itself — a
        # genuine transmission that happens to actually use "...0000" (e.g.
        # 64-QAM, Protection 0/0) is confirmed exactly the same way as any
        # other mode, purely via MSC — never treated worse just because its
        # code ends in "0000".
        SNR_VALID_DB = 5.0   # minimum SNR (dB) counted as real reception

        def _row_snr(r):
            try:
                return float(r.get('SNR', '').strip())
            except Exception:
                return None

        def _row_sync_ok(r):
            try:
                return int(r.get('SYNC', 0)) == 1
            except Exception:
                return False

        def _row_msc_ok(r):
            # MSC=1 is the one signal that distinguishes genuine, decoded
            # reception from a placeholder/glitch — regardless of the mode
            # code itself. Used both here (for "...0000" recovery) and
            # below (for normal mode confirmation), so both are held to
            # exactly the same standard.
            try:
                return int(r.get('MSC', 0)) == 1
            except Exception:
                return False

        def _window_sustained_ok(valid_rows, k, run_end):
            """
            True if rows [k, k+MIN_MODE_SECS) all lie within this run AND
            all show SNR >= SNR_VALID_DB, SYNC == 1 and MSC == 1 —
            SUSTAINED for the full minimum duration, not just a single
            sample row. This is what actually tells apart a brief
            fading/multipath flicker (a row or two of good-looking values
            in the middle of an otherwise bad patch) from real, stable
            reception — a short flicker will always fail this check
            somewhere in the window, a genuine signal will not.
            """
            end_needed = k + MIN_MODE_SECS
            if end_needed > run_end:
                return False
            for idx in range(k, end_needed):
                rr = valid_rows[idx][1]
                snr = _row_snr(rr)
                if snr is None or snr < SNR_VALID_DB:
                    return False
                if not (_row_sync_ok(rr) and _row_msc_ok(rr)):
                    return False
            return True

        # Build list of (mode_code, row)
        valid_rows = []
        for r in rows:
            fmq   = r.get('FREQ/MODE/QAM PL:ABH', '').strip()
            parts = fmq.split('/')
            mc    = parts[1].strip() if len(parts) > 1 else fmq.strip()
            valid_rows.append((mc, r))

        n = len(valid_rows)

        # Collect confirmed real modes with their first-occurrence rows
        confirmed = []   # list of (mode_code, first_row)
        i = 0
        while i < n:
            mc, r = valid_rows[i]
            # Find the extent of this consecutive run of the same mode code
            j = i
            while j < n and valid_rows[j][0] == mc:
                j += 1
            run_start, run_end = i, j   # rows [run_start, run_end)

            if mc.endswith('0000'):
                # "...0000" placeholder — search forward INSIDE this run for
                # the first row from which SNR/SYNC/MSC all hold for the
                # full MIN_MODE_SECS window (see _window_sustained_ok()).
                # Scanning row-by-row through the whole run (rather than a
                # single fixed check at the run's start) behaves exactly like
                # a rolling ~2-minute forward window that is re-evaluated
                # every second: it never gives up early, so a genuine
                # recovery even 20-30 minutes into a long bad-reception
                # block is still found and reported at its real (actual)
                # recovery timestamp — not backdated to the start of the
                # "...0000" run.
                recovery_idx = None
                for k in range(run_start, run_end):
                    if _window_sustained_ok(valid_rows, k, run_end):
                        recovery_idx = k
                        break
                if recovery_idx is not None:
                    confirmed.append((mc, valid_rows[recovery_idx][1]))
                # else: no sustained SNR/SYNC/MSC recovery found anywhere in
                # this run — genuine no-signal gap, same as before.
            else:
                count  = run_end - run_start
                msc_ok = False
                try:
                    msc_ok = int(valid_rows[run_start][1].get('MSC', 0)) == 1
                except Exception:
                    msc_ok = False
                # Accept mode only if it lasted >= MIN_MODE_SECS AND MSC was OK
                if count >= MIN_MODE_SECS and msc_ok:
                    confirmed.append((mc, r))

            i = j

        # Display confirmed mode changes
        for mc, r in confirmed:
            if mc != prev_real:
                time_str = r.get('TIME', '?').strip()
                if '.' in time_str:
                    time_str = time_str.split('.')[0]
                time_hhmm = time_str[:5]
                self.modes_text.insert(tk.END, mc + ' from ' + time_hhmm + '\n')
                prev_real = mc
        self.modes_text.configure(state=tk.DISABLED)



    # ─────────────────────────────────────────────────
    # PLOTTING
    # ─────────────────────────────────────────────────
    def _replot(self):
        try:
            self._replot_inner()
        except Exception as e:
            import traceback
            print(f"_replot ERROR: {e}")
            traceback.print_exc()

    def _replot_inner(self):
        ax=self.ax; ax.cla(); self._style_axes()
        _bg_val    = self.cfg.get('plot_bg','darkblue')
        _frame_val = self.cfg.get('frame_bg','darkblue')
        # fg for x-axis labels depends on FRAME color (labels sit in figure margin)
        # 'gray' switched from black to white text (Aug 2026, user request,
        # "Option B" #555555) — the frame is now dark enough that black
        # text would no longer be readable; white matches every other
        # dark frame color's behaviour.
        fg = 'black' if _frame_val == 'white' else 'white'
        # Ensure figure background is also updated on every replot
        _frame_map = {'darkblue':'#0a0a1a','black':'#0a0a1a',
                      'navy2':'#0a1628','dpurple':'#160a1e','dteal':'#0a1a1a',
                      'gray':'#555555','white':'#ffffff'}
        self.fig.set_facecolor(_frame_map.get(_frame_val, '#0a0a1a'))
        # Third layer: Tkinter canvas widget background
        # Must match axes background to prevent dark blue bleeding through
        _ax_map = {'darkblue':'#0a0a1a','black':'#0a0a1a',
                   'navy2':'#0a1628','dpurple':'#160a1e','dteal':'#0a1a1a',
                   'white':'#ffffff'}
        canvas_bg = _ax_map.get(_bg_val, '#0a0a1a')
        try:
            self.canvas.get_tk_widget().configure(bg=canvas_bg)
        except Exception:
            pass

        rows=self.plot_rows
        if not rows:
            ax.set_xticks(np.linspace(0,1,16))
            ax.set_xticklabels([f't({i})' for i in range(16)],fontsize=9,color=fg)
            self._draw_right_labels(ax)
            self.canvas.draw(); return

        # Parse data
        # AUDIO   = frames needed per second (alternates e.g. 10/15 or 20/30)
        # AUDIOOK = frames actually decoded  (same as AUDIO if OK, less if errors, 0 if none)
        # Ratio AUDIOOK/AUDIO = 1.0 → perfect audio (line at top = 45 dB)
        # Ratio = 0.0 → no audio decoded (line at zero-line = 35 dB)
        def _safe_float(s, default=float('nan')):
            """
            Parse a single CSV numeric field defensively.
            Dream.exe (Windows build) occasionally writes '-nan(ind)' into the
            DOPPLER column when its internal Doppler estimate is briefly
            indeterminate (e.g. a very short signal dip on weak/DX signals
            such as BBC WS) — that string is not a valid float.
            Returns NaN on any bad value — NaN is the honest representation
            of "no valid measurement here" (a gap in the line), as opposed
            to fabricating a 0.0 that would look like a real zero reading.
            Matplotlib simply skips NaN points, leaving a small gap instead
            of breaking the whole curve.
            """
            try:
                return float(s)
            except (TypeError, ValueError):
                return default

        times,snr,audio,doppler,delay,sync=[],[],[],[],[],[]
        for r in rows:
            try:
                dt=parse_dt(r['DATE'], r['TIME'])
            except Exception:
                continue   # no valid timestamp → this row cannot be placed on the x-axis at all
            times.append(dt)
            # From here on, every field is parsed independently with a NaN
            # fallback — one bad value (e.g. '-nan(ind)' in DOPPLER) must
            # never cause the other fields for this same row (or any later
            # row) to be skipped, or the data lists (times/snr/audio/
            # doppler/delay) would end up different lengths and crash the
            # ax.plot(...) calls further down — which is exactly what
            # silently emptied the whole plot before this fix.
            raw_snr = _safe_float(r.get('SNR', 0), default=0.0)
            fac_val = int(r.get('FAC', '1')) if r.get('FAC','').strip().isdigit() else 1
            # Only set SNR=0 when FAC=0 AND SNR is genuinely low (real signal loss)
            # A single FAC=0 glitch from the TX encoder must NOT zero the SNR
            # Threshold: if SNR > 5 dB with FAC=0 → TX encoder glitch → keep real SNR
            if fac_val == 0 and raw_snr <= 5.0:
                snr.append(0.0)   # real signal loss
            else:
                snr.append(raw_snr)   # valid signal or TX encoder glitch
            ao = _safe_float(r.get('AUDIOOK', 0), default=0.0)
            at = _safe_float(r.get('AUDIO', 0), default=0.0)
            # ratio 0.0–1.0 regardless of absolute frame counts
            ratio = (ao / at) if at > 0 else 0.0
            ratio = max(0.0, min(1.0, ratio))
            audio.append(ratio)
            doppler.append(_safe_float(r.get('DOPPLER', 0)))
            delay.append(_safe_float(r.get('DELAY', 0)))
            # SYNC — default to 1 (assume "locked") on any parse issue, so a
            # missing/garbled value can never falsely trigger the SNR
            # correction below. Only an explicit, unambiguous '0' does.
            try:
                sync.append(int(r.get('SYNC', 1)))
            except (TypeError, ValueError):
                sync.append(1)
        if not times: self.canvas.draw(); return

        # ── "Frozen SNR" correction (Aug 2026) ───────────────────────────
        # Dream can hold the last-known SNR reading unchanged for as long
        # as sync stays lost — confirmed against real logs (e.g. a value
        # stuck at 23.21 dB for 2.5 minutes with SYNC=0 the whole time).
        # The FAC/low-SNR correction above only catches this when the
        # frozen value happens to already be low (<=5 dB); it completely
        # misses a frozen value that happens to be high, which is exactly
        # what happened here. This second pass closes that gap: any
        # CONTINUOUS run of SYNC=0 lasting at least 10 seconds is treated
        # as confirmed genuine signal loss (empirically, ~90% of all
        # sync dropouts in real logs last under 10s and are normal
        # fading/multipath blips, not real loss — see analysis), and the
        # entire run (not just the part after the 10s mark) is zeroed —
        # the frozen reading was never valid to begin with, from its very
        # first second.
        MIN_DROPOUT_SECS = 10.0
        i = 0
        n = len(times)
        while i < n:
            if sync[i] == 0:
                j = i
                while j < n and sync[j] == 0:
                    j += 1
                run_duration = (times[j-1] - times[i]).total_seconds()
                if run_duration >= MIN_DROPOUT_SECS:
                    for k in range(i, j):
                        snr[k] = 0.0
                i = j
            else:
                i += 1

        t0=times[0]
        xs=[(t-t0).total_seconds()/60.0 for t in times]

        # Apply zoom — filter all data to selected time range
        active_rows = self.plot_rows  # default: all rows
        if self.zoom_active and self.zoom_t0 and self.zoom_t1:
            mask=[self.zoom_t0<=t<=self.zoom_t1 for t in times]
            if any(mask):
                active_rows = [r for r,m in zip(self.plot_rows,mask) if m]
                times   =[t for t,m in zip(times,mask)   if m]
                xs      =[x for x,m in zip(xs,mask)      if m]
                snr     =[v for v,m in zip(snr,mask)     if m]
                audio   =[v for v,m in zip(audio,mask)  if m]
                doppler =[v for v,m in zip(doppler,mask) if m]
                delay   =[v for v,m in zip(delay,mask)   if m]
        # Update stats with the same rows that are plotted
        self._update_stats(rows=active_rows)

        ax.set_xlim(xs[0],xs[-1]); ax.set_ylim(0,SNR_MAX)

        # Audio (blue):
        #   ratio = AUDIOOK / AUDIO  (0.0 = no audio, 1.0 = perfect)
        #   ratio 1.0  → 45 dB (top,  = 750 Frames on right scale)
        #   ratio 0.0  → 35 dB (base, = 0 Frames  on right scale)
        AUDIO_BASE  = 35.0   # dB = 0 Frames
        AUDIO_TOP   = 44.5   # dB = 750 Frames (0.5 dB margin so thick line is fully visible)
        AUDIO_RANGE = AUDIO_TOP - AUDIO_BASE   # 9.5 dB

        # ── SNR Max / Min dots and Average line ─────────────────────
        if snr and times:
            if getattr(self, '_show_snr_max_dot', False):
                max_val = max(snr)
                max_idx = snr.index(max_val)
                ax.plot(xs[max_idx], max_val, 'o',
                        color=COL_SNR, markersize=8, zorder=9,
                        markeredgecolor='white', markeredgewidth=1)
                ax.annotate(f'{max_val:.1f}',
                            xy=(xs[max_idx], max_val),
                            xytext=(6, 4),
                            textcoords='offset points',
                            color=COL_SNR, fontsize=9,
                            va='bottom', zorder=9)
            if getattr(self, '_show_snr_min_dot', False):
                # Ignore zero values (signal loss) for min dot
                nonzero = [(v, i) for i,v in enumerate(snr) if v > 0]
                if nonzero:
                    min_val, min_idx = min(nonzero, key=lambda x: x[0])
                    ax.plot(xs[min_idx], min_val, 'o',
                            color=COL_SNR, markersize=8, zorder=9,
                            markeredgecolor='white', markeredgewidth=1)
                    ax.annotate(f'{min_val:.1f}',
                                xy=(xs[min_idx], min_val),
                                xytext=(6, -4),
                                textcoords='offset points',
                                color=COL_SNR, fontsize=9,
                                va='top', zorder=9)
            if getattr(self, '_show_snr_avg_line', False) and snr:
                avg_val = sum(v for v in snr if v > 0) / max(1, sum(1 for v in snr if v > 0))
                ax.axhline(avg_val, color=COL_SNR, linestyle=':',
                           linewidth=1.2, alpha=0.8, zorder=4)
                ax.annotate(f'avg {avg_val:.1f}',
                            xy=(xs[-1], avg_val),
                            xytext=(6, 0),
                            textcoords='offset points',
                            color=COL_SNR, fontsize=9,
                            va='center', zorder=9,
                            annotation_clip=False)

        # Blue dotted zero-line at 35 dB — always visible
        ax.axhline(AUDIO_BASE, color=COL_AUDIO, linestyle=(0, (2, 4)),
                   linewidth=0.8, alpha=0.95, zorder=2)

        # Audio curve — only when checkbox is ON
        if self.opt_audio.get() and audio:
            lw = 2 if self.opt_thick.get() else 1
            ya = [AUDIO_BASE + r * AUDIO_RANGE for r in audio]
            if self.opt_smooth.get():
                win = min(10, max(1, len(ya)//50))
                pad = win // 2
                ya_arr = np.array(ya)
                ya_padded = np.concatenate([
                    np.full(pad, ya_arr[0]),
                    ya_arr,
                    np.full(pad, ya_arr[-1])
                ])
                kernel = np.ones(win) / win
                ya_conv = np.convolve(ya_padded, kernel, mode='valid')
                ya_smooth = ya_conv[:len(ya)].tolist()
                ya_smooth = [max(AUDIO_BASE, min(AUDIO_TOP, v)) for v in ya_smooth]
                ax.plot(xs, ya_smooth, color=COL_AUDIO, linewidth=lw, zorder=6)
            else:
                ax.plot(xs, ya, color=COL_AUDIO, linewidth=lw, zorder=6)

        # SNR (red)
        if self.opt_snr.get() and snr:
            ax.plot(xs,snr,color=COL_SNR,linewidth=1.2,zorder=8)

        # Doppler (green): logarithmic scale
        # Formula: y_dB = 20.959 * log10(Hz) + 20
        # → 1 Hz = 20 dB, 3 Hz = 30 dB, 0.1 Hz ≈ 0 dB
        def _dop_to_db(v):
            if math.isnan(v): return v   # keep gap as a gap — NOT clamp to top of scale
            if v <= 0: return 0.0
            y = 20.959 * math.log10(max(v, 0.05)) + 20.0
            return max(0.0, min(SNR_MAX, y))
        if self.opt_doppler.get() and doppler:
            yd = [_dop_to_db(v) for v in doppler]
            # Smooth doppler to remove staircase effect — rolling average.
            # NaN gaps (see _dop_to_db) are excluded from the window instead
            # of poisoning the whole averaging window with NaN — this keeps
            # a single bad Dream.exe sample (e.g. '-nan(ind)') a one-point
            # gap instead of smearing it across ~half a minute either side.
            win = 3  # window size — small on purpose: just enough to break
                     # up the log-scale staircase without smearing the
                     # curve away from the original data (was up to 30)
            yd_s = []
            for i in range(len(yd)):
                s = max(0, i-win); e = min(len(yd), i+win+1)
                window_vals = [v for v in yd[s:e] if not math.isnan(v)]
                yd_s.append(sum(window_vals)/len(window_vals) if window_vals else float('nan'))
            ax.plot(xs, yd_s, color=COL_DOPPLER, linewidth=0.8, zorder=4)

        # Delay (ochre): 0-10 ms → 0-10 dB scale
        # NaN values (see _safe_float) pass straight through as a genuine
        # gap in the line rather than a fabricated reading.
        if self.opt_delay.get() and delay:
            ax.plot(xs,[v if math.isnan(v) else min(v,10.0) for v in delay],color=COL_DELAY,linewidth=0.6,zorder=3)

        # X-axis time labels
        n=min(16,max(5,int((xs[-1]-xs[0])/4)))
        ticks=np.linspace(xs[0],xs[-1],n)
        ax.set_xticks(ticks)
        ax.set_xticklabels(
            [(t0 + timedelta(minutes=float(tx))).strftime('%H:%M') for tx in ticks],
            fontsize=9, color=fg)

        # ── Compare overlay — absolute UTC clock + Zoom support ─────────
        # Both logs sit on a shared time axis (minutes since common ref).
        # Midnight-safe: uses datetime arithmetic, not hour*60 arithmetic.
        # When Zoom is active the view is clipped to [zoom_start, zoom_end].
        if self.comp_rows:

            # ── Collect compare datetime objects first (needed for ref) ──
            comp_dts_full, cs_full, ca_full = [], [], []
            for r in self.comp_rows:
                try:
                    dt = parse_dt(r['DATE'], r['TIME'])
                except Exception:
                    continue   # no valid timestamp — row cannot be placed on the axis
                comp_dts_full.append(dt)
                cs_full.append(_safe_float(r.get('SNR', 0), default=0.0))
                ao = _safe_float(r.get('AUDIOOK', 0), default=0.0)
                at = _safe_float(r.get('AUDIO',   0), default=0.0)
                ratio = (ao / at) if at > 0 else 0.0
                ca_full.append(max(0.0, min(1.0, ratio)))

            # ── Time axis: pure UTC clock minutes, date is irrelevant ────
            # Logs can never exceed 24 hours, so date is always ignored.
            # Midnight crossing (e.g. 22:00->01:57) is handled per log:
            # if a timestamp is earlier than the first value of that log,
            # +1440 minutes is added (= same log, next calendar day).

            def _time_min(dt_obj):
                """Pure UTC clock minutes since 00:00 — date ignored."""
                return dt_obj.hour * 60.0 + dt_obj.minute + dt_obj.second / 60.0

            def _midnight_safe(dt_list):
                """Convert list of datetimes to clock-minutes.
                Adds +1440 for any value that wraps past the first value
                (30 min tolerance to avoid false triggers)."""
                if not dt_list:
                    return []
                result = []
                base = _time_min(dt_list[0])
                for dt in dt_list:
                    m = _time_min(dt)
                    if m < base - 30:
                        m += 1440
                    result.append(m)
                return result

            # ── Convert zoom boundaries (pure clock minutes) ──────────────
            zoom_abs_start = None
            zoom_abs_end   = None
            if self.zoom_active and self.zoom_t0 and self.zoom_t1:
                zoom_abs_start = _time_min(self.zoom_t0)
                zoom_abs_end   = _time_min(self.zoom_t1)
                if zoom_abs_end < zoom_abs_start - 30:
                    zoom_abs_end += 1440

            # ── Main log: clock minutes, midnight-safe ────────────────────
            main_abs_full = _midnight_safe(times)
            main_abs      = main_abs_full   # already zoom-filtered via times[]

            # ── Compare log: clock minutes, midnight-safe ─────────────────
            ct_abs_full = _midnight_safe(comp_dts_full)

            if zoom_abs_start is not None and ct_abs_full:
                ct_abs = [x for x in ct_abs_full
                          if zoom_abs_start <= x <= zoom_abs_end]
                cs     = [v for x, v in zip(ct_abs_full, cs_full)
                          if zoom_abs_start <= x <= zoom_abs_end]
                ca     = [v for x, v in zip(ct_abs_full, ca_full)
                          if zoom_abs_start <= x <= zoom_abs_end]
            else:
                ct_abs = ct_abs_full
                cs     = cs_full
                ca     = ca_full

            if ct_abs or main_abs:
                # X range: union of whatever is visible after zoom
                all_visible = (main_abs or []) + (ct_abs or [])
                if zoom_abs_start is not None:
                    x_min = zoom_abs_start
                    x_max = zoom_abs_end
                else:
                    x_min = min(all_visible)
                    x_max = max(all_visible)

                ax.set_xlim(x_min, x_max)
                ax.set_ylim(0, SNR_MAX)

                # Redraw main curves with relative x
                if self.opt_snr.get() and snr:
                    ax.plot(main_abs, snr, color=COL_SNR,
                            linewidth=1.2, zorder=8)
                if self.opt_doppler.get() and doppler:
                    yd2 = [_dop_to_db(v) for v in doppler]
                    w2  = min(30, max(5, len(yd2)//20))
                    yd2s = [sum(yd2[max(0,i-w2):min(len(yd2),i+w2+1)]) /
                            (min(len(yd2),i+w2+1)-max(0,i-w2))
                            for i in range(len(yd2))]
                    ax.plot(main_abs, yd2s, color=COL_DOPPLER,
                            linewidth=0.8, zorder=4)
                if self.opt_delay.get() and delay:
                    ax.plot(main_abs, [min(v, 10.0) for v in delay],
                            color=COL_DELAY, linewidth=0.6, zorder=3)
                if self.opt_audio.get() and audio:
                    lw2 = 2 if self.opt_thick.get() else 1
                    ya2 = [AUDIO_BASE + rv * AUDIO_RANGE for rv in audio]
                    if self.opt_smooth.get():
                        w2  = min(10, max(1, len(ya2)//50))
                        p2  = w2 // 2
                        arr = np.array(ya2)
                        pad = np.concatenate([np.full(p2,arr[0]),
                                              arr,
                                              np.full(p2,arr[-1])])
                        smt = np.convolve(pad,np.ones(w2)/w2,
                                          mode='valid')[:len(ya2)].tolist()
                        ya2 = [max(AUDIO_BASE,min(AUDIO_TOP,v)) for v in smt]
                    ax.plot(main_abs, ya2, color=COL_AUDIO,
                            linewidth=lw2, zorder=6)

                # ── Compare SNR (amber) — only if data in window ───────────
                if ct_abs:
                    ax.plot(ct_abs, cs, color='#ff9900',  # Compare SNR: amber/ocher (Aug 2026, user request, was "#00cccc")
                            linewidth=1.4, linestyle='-', zorder=6)

                # ── Compare Audio (yellow) — respects Smooth/Rough + Thick ─
                # Shifted -1.0 dB below Main Audio so both lines remain
                # visible even when both logs have perfect audio decoding.
                if self.opt_audio.get() and ct_abs and ca:
                    COMP_AUDIO_OFFSET = -1.0   # dB shift downward
                    lw_c = 2 if self.opt_thick.get() else 1
                    yac  = [AUDIO_BASE + rv * AUDIO_RANGE + COMP_AUDIO_OFFSET
                            for rv in ca]
                    if self.opt_smooth.get():
                        wc  = min(10, max(1, len(yac)//50))
                        pc  = wc // 2
                        arc = np.array(yac)
                        pad = np.concatenate([np.full(pc, arc[0]),
                                              arc,
                                              np.full(pc, arc[-1])])
                        smt = np.convolve(pad, np.ones(wc)/wc,
                                          mode='valid')[:len(yac)].tolist()
                        yac = [max(AUDIO_BASE + COMP_AUDIO_OFFSET,
                                   min(AUDIO_TOP  + COMP_AUDIO_OFFSET, v))
                               for v in smt]
                    ax.plot(ct_abs, yac, color='#99e6ef',  # Compare Audio: bright cyan (Aug 2026, user-chosen "Option C2", was "#ddcc00")
                            linewidth=lw_c, zorder=7)

                # UTC time-axis labels
                span = max(1, x_max - x_min)
                n2   = min(16, max(5, int(span / 4)))
                ticks2 = np.linspace(x_min, x_max, n2)
                ax.set_xticks(ticks2)
                ax.set_xticklabels(
                    [f'{int(tx//60):02d}:{int(tx%60):02d}' for tx in ticks2],
                    fontsize=9, color=fg)

                # Overlap shading (only meaningful without zoom)
                if not zoom_abs_start and ct_abs and main_abs:
                    ol_s = max(min(main_abs), min(ct_abs))
                    ol_e = min(max(main_abs), max(ct_abs))
                    if ol_e > ol_s:
                        ax.axvspan(ol_s, ol_e, alpha=0.02,
                                   color='#ffffff', zorder=1)

                # Info label
                def fmt(m): return f'{int(m//60):02d}:{int(m%60):02d}'
                m_all = main_abs_full
                c_all = ct_abs_full
                zoom_tag = f'  [Zoom {fmt(zoom_abs_start)}–{fmt(zoom_abs_end)}]'                            if zoom_abs_start is not None else ''
                if c_all:
                    overlap_min = 0
                    if not zoom_abs_start:
                        ol_s2 = max(min(m_all), min(c_all))
                        ol_e2 = min(max(m_all), max(c_all))
                        overlap_min = max(0, ol_e2 - ol_s2) if ol_e2 > ol_s2 else 0
                    info = (f'Main {fmt(min(m_all))}–{fmt(max(m_all))}'
                            f'   Comp {fmt(min(c_all))}–{fmt(max(c_all))} UTC'
                            + (f'   overlap {int(overlap_min)} min'
                               if overlap_min > 0 else '   no overlap')
                            + zoom_tag)
                else:
                    info = f'Compare log empty in this window{zoom_tag}'
                # Position/size (Aug 2026, user request): moved from near
                # the top (y=0.97) down to just above the time axis
                # (y=0.09, va='bottom' — leaves a visible gap above the
                # axis, not flush against it), and enlarged by 2pt
                # (8 -> 10) for better readability.
                ax.text(0.01, 0.09, info,
                        transform=ax.transAxes, color='#00cccc',
                        fontsize=10, va='bottom', ha='left',
                        clip_on=False, zorder=9)

        # "ms" label on left for Delay scale
        # "ms" label: outside left axis, just below the "10" tick label
        ax.text(-0.01, 7.5/SNR_MAX, 'ms', transform=ax.transAxes,
                color=COL_DELAY, fontsize=10, va='center', ha='right',
                clip_on=False, fontweight='bold')

        self._draw_right_labels(ax)

        # ── Draw annotations from Add Text dialog ────────────────────
        # Block 1: timed annotations (6 rows) — only if any are set
        if hasattr(self, '_annotations') and self._annotations and times:
            t0_dt = times[0]
            for ann in self._annotations:
                t_str = ann['time'].replace(':','')
                if len(t_str) == 4 and t_str.isdigit():
                    try:
                        hh = int(t_str[:2]); mm = int(t_str[2:])
                        base = t0_dt.replace(hour=hh, minute=mm, second=0)
                        x_pos = (base - t0_dt).total_seconds() / 60.0
                        # Handle midnight crossover: if negative, try next day
                        if x_pos < -1:
                            base += timedelta(days=1)
                            x_pos = (base - t0_dt).total_seconds() / 60.0
                        if xs[0] <= x_pos <= xs[-1]:
                            # Shared Y position — driven by pos% spinbox
                            # so both time label and text move together
                            pos    = ann.get('pos', 50)
                            y_frac = pos / 100.0
                            y_db   = y_frac * SNR_MAX

                            # Vertical dashed line — only if flag set
                            if getattr(self, '_show_vlines', True):
                                ax.axvline(x_pos, color='#ff8800',
                                           linestyle='--', linewidth=0.8,
                                           alpha=0.8, zorder=7)

                            # Time label — LEFT of the marker point
                            time_lbl = f"{ann['time'][:2]}:{ann['time'][2:4]}" \
                                       if len(ann['time']) >= 4 else ann['time']
                            ax.text(x_pos - 0.3, y_db,
                                    time_lbl,
                                    color='#dddddd', fontsize=8,
                                    va='center', ha='right',
                                    bbox=dict(boxstyle='round,pad=0.1',
                                              facecolor='#222222',
                                              alpha=0.6, edgecolor='none'),
                                    zorder=9, clip_on=True)

                            # Text annotation — RIGHT of the marker point
                            # (only if text is not empty)
                            if ann.get('text', '').strip():
                                ax.text(x_pos + 0.3, y_db, ann['text'],
                                        color='white', fontsize=10,
                                        va='center', ha='left',
                                        bbox=dict(boxstyle='round,pad=0.2',
                                                  facecolor='#333333',
                                                  alpha=0.7, edgecolor='none'),
                                        zorder=8, clip_on=True)
                    except Exception:
                        pass

        # Block 2: Free comment — independent of Block 1, always shown if set
        if getattr(self, '_annotation_free', ''):
            fx = getattr(self, '_free_x', 0.50)
            fy = getattr(self, '_free_y', 0.50)
            ax.text(fx, fy, self._annotation_free,
                    transform=ax.transAxes,
                    color='#dddddd', fontsize=10,
                    va='center', ha='center', clip_on=False,
                    bbox=dict(boxstyle='round,pad=0.2',
                              facecolor='#222222',
                              alpha=0.5, edgecolor='none'),
                    zorder=8)

        self.canvas.draw()

    def _draw_right_labels(self, ax):
        """
        Draw inside the figure, right of the plot area:
        - Blue: 'Frames', 1500, 750, 0
        - Green: Doppler Hz scale (2 Hz at mid-height down to 0.1)
        """
        # Audio scale (blue) right side:
        #   'Audio 100%' at top  (45 dB = axes y 1.0)
        #   'Dropouts'   at 40 dB = 40/45 = 0.889  (on the green dashed line)
        #   '0'          at 35 dB = 35/45 = 0.778  (audio zero-line)
        ax.text(1.01, 1.00,  'Audio 100%', transform=ax.transAxes,
                color=COL_AUDIO, fontsize=9, va='top',    ha='left', clip_on=False)
        ax.text(1.01, 40/45, 'Dropouts',   transform=ax.transAxes,
                color=COL_AUDIO, fontsize=9, va='center', ha='left', clip_on=False)
        ax.text(1.01, 35/45, '0',          transform=ax.transAxes,
                color=COL_AUDIO, fontsize=9, va='center', ha='left', clip_on=False)

        # Doppler Hz scale (green): logarithmic — same formula as plot
        # y_dB = 20.959 * log10(Hz) + 20  →  3Hz=30dB, 1Hz=20dB, 0.1Hz≈0dB
        def _dop_y(hz):
            return (20.959 * math.log10(hz) + 20.0) / SNR_MAX
        # Readability fix (superseded Aug 2026): this used to switch to
        # the darker green (COL_DOPPLER_TEXT) specifically because bright
        # green was hard to read against the light Gray frame (#aaaaaa).
        # Now that 'gray' is a dark frame color (#555555, "Option B",
        # user request), it behaves like every other dark frame — the
        # bright green (COL_DOPPLER) is readable again, so no special
        # case is needed any more.
        dop_scale_color = COL_DOPPLER
        dop_ticks = [(3.0,'3'), (2.0,'2'), (1.5,'1.5'), (1.0,'1 Hz'),
                     (0.5,'0.5'), (0.4,'0.4'), (0.3,'0.3'),
                     (0.2,'0.2'), (0.15,'0.15'), (0.1,'0.1')]
        for hz, label in dop_ticks:
            y = _dop_y(hz)
            if y < 0 or y > 1.0: continue
            ax.annotate('', xy=(1.0, y), xytext=(1.008, y),
                        xycoords='axes fraction', textcoords='axes fraction',
                        arrowprops=dict(arrowstyle='-', color=dop_scale_color,
                                        lw=1.0),
                        annotation_clip=False)
            ax.text(1.012, y, label, transform=ax.transAxes,
                    color=dop_scale_color, fontsize=9, va='center', ha='left',
                    clip_on=False)

    # ─────────────────────────────────────────────────
    # ZOOM / TRIM
    # ─────────────────────────────────────────────────
    def _parse_time_str(self,s):
        s=s.strip().replace(':','')
        if len(s)==4 and s.isdigit() and self.plot_rows:
            try:
                base=datetime.strptime(self.plot_rows[0]['DATE'],'%Y-%m-%d')
                return base.replace(hour=int(s[:2]),minute=int(s[2:]),second=0)
            except: pass
        return None

    def _do_zoom(self):
        t0=self._parse_time_str(self.zoom_start_var.get())
        t1=self._parse_time_str(self.zoom_stop_var.get())
        if t0 and t1 and t1>t0:
            self.zoom_active=True; self.zoom_t0=t0; self.zoom_t1=t1; self._replot()

    def _do_restore(self):
        """Reset zoom and trim — reload full original CSV data for current log."""
        self.zoom_active = False
        self.zoom_t0     = None
        self.zoom_t1     = None
        self.zoom_start_var.set('')
        self.zoom_stop_var.set('')
        if self.sel_log and self.all_csv:
            # Reload plot_rows directly from full CSV — bypasses any trim
            idx = self.all_logs.index(self.sel_log)
            next_start = (self.all_logs[idx+1].start_time
                          if idx+1 < len(self.all_logs)
                          else self.sel_log.start_time + timedelta(hours=6))
            self.plot_rows = filter_csv_for_log(
                self.all_csv, self.sel_log.start_time, next_start)
            self._update_stats()
            self._replot()

    def _trim_ends(self):
        if len(self.plot_rows) < 10: return
        try:
            # Use parse_dt() — handles decimal seconds and encoding
            # differences between Windows and Linux correctly
            d0 = parse_dt(self.plot_rows[0]['DATE'], self.plot_rows[0]['TIME'])
            d1 = parse_dt(self.plot_rows[1]['DATE'], self.plot_rows[1]['TIME'])
            gap = (d1 - d0).total_seconds()
            skip = max(1, int(60 / max(1, gap)))
        except Exception:
            skip = 10
        self.plot_rows = self.plot_rows[skip:-skip]
        self._replot()

    # ─────────────────────────────────────────────────
    # AUTOPLOT
    # ─────────────────────────────────────────────────
    def _on_close(self):
        """Cancel all pending timers before closing."""
        self._main_clock_alive[0] = False
        self.ap_active = False
        if hasattr(self, '_ap_after_id') and self._ap_after_id:
            try: self.root.after_cancel(self._ap_after_id)
            except Exception: pass
        if hasattr(self, '_timer_led_after_id') and self._timer_led_after_id:
            try: self.root.after_cancel(self._timer_led_after_id)
            except Exception: pass
        if hasattr(self, '_rigctl_health_after_id') and self._rigctl_health_after_id:
            try: self.root.after_cancel(self._rigctl_health_after_id)
            except Exception: pass
        # Save the window position so it reopens in the same spot next
        # time (July 2026). Position only — not size, per user request.
        try:
            self.cfg.set('window_x', self.root.winfo_x())
            self.cfg.set('window_y', self.root.winfo_y())
        except Exception:
            pass
        self.root.destroy()

    def _toggle_autoplot(self):
        if self.ap_active:
            self.ap_active = False
            self.ap_btn.configure(text='Auto Plot')
            self.ap_led.itemconfig(self._ap_oval, fill='#888888', outline='#555555')
            self.v_ap_refresh.set('Refresh:')
            # Cancel pending countdown timer
            if hasattr(self, '_ap_after_id') and self._ap_after_id:
                try: self.root.after_cancel(self._ap_after_id)
                except Exception: pass
                self._ap_after_id = None
        else:
            if not self.txt_path:
                messagebox.showwarning('Auto Plot', 'Load log files first.')
                return
            # ── CSV age check — warn if log is not from a live Dream session ──
            # Dream writes one row per second → an active CSV is at most a few
            # seconds old. If the file is older than 10 minutes it is likely
            # a historical log, not the current Dream output.
            # The user may have Dream installed in a non-standard location;
            # in that case they need to load the correct log files first.
            try:
                import time as _time
                _mtime     = os.path.getmtime(self.csv_path)
                _age_min   = (_time.time() - _mtime) / 60.0
                if _age_min >= 10:
                    from datetime import datetime as _dt
                    _mtime_str = _dt.fromtimestamp(_mtime).strftime('%Y-%m-%d  %H:%M:%S')
                    _proceed = messagebox.askyesno(
                        'Auto Plot — Log may be outdated',
                        f'The loaded log file was last written:\n'
                        f'  {_mtime_str}\n'
                        f'  ({int(_age_min)} minutes ago)\n\n'
                        f'Dream may be writing to a different folder.\n'
                        f'If so, please load the current log files first\n'
                        f'(Update button) before starting Auto Plot.\n\n'
                        f'Start Auto Plot with this log anyway?',
                        icon='warning')
                    if not _proceed:
                        return
            except Exception:
                pass   # mtime check failed — proceed silently
            self._autoplot_dialog()

    def _autoplot_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title('Auto Plot Settings')
        dlg.configure(bg=GUI_BG)
        dlg.resizable(False, False)
        center_dialog(dlg, self.root, 300, 160)
        dlg.grab_set()
        dlg.transient(self.root)   # v_rig_test_06: keep dialog above its parent
        dlg.lift()
        dlg.focus_force()

        tk.Label(dlg, text='Refresh Rate:', bg=GUI_BG,
                 font=('Arial', 10)).grid(row=0, column=0, padx=15, pady=12, sticky='w')
        # Pre-select the last-used value (Aug 2026, user request) instead
        # of always defaulting to '30' — self.ap_interval is now loaded
        # from the persisted config at programme start (see __init__).
        # Guard against a persisted value that isn't one of the valid
        # OptionMenu choices (e.g. an old/foreign config file) by falling
        # back to '30' in that case only.
        _ap_interval_choices = ('5', '10', '30', '60', '120', '240')
        _rv_default = (str(self.ap_interval)
                        if str(self.ap_interval) in _ap_interval_choices
                        else '30')
        rv = tk.StringVar(value=_rv_default)
        tk.OptionMenu(dlg, rv, *_ap_interval_choices).grid(
            row=0, column=1, padx=5)
        tk.Label(dlg, text='seconds', bg=GUI_BG,
                 font=('Arial', 10)).grid(row=0, column=2, padx=5)

        tk.Label(dlg, text='Scroll:', bg=GUI_BG,
                 font=('Arial', 10)).grid(row=1, column=0, padx=15, pady=12, sticky='w')
        # Same pre-selection for Scroll — see rationale above.
        _ap_scroll_choices = ('Full', '5 min', '10 min', '20 min',
                               '30 min', '60 min')
        _sv_default = (self.ap_scroll
                        if self.ap_scroll in _ap_scroll_choices else 'Full')
        sv = tk.StringVar(value=_sv_default)
        tk.OptionMenu(dlg, sv, 'Full', '5 min', '10 min', '20 min',
                      '30 min', '60 min').grid(row=1, column=1, padx=5)

        def start():
            chosen_interval = int(rv.get())
            # ── 5s warning — only if ap_5s_alert is enabled ──────────────
            if chosen_interval == 5 and self.cfg.get('ap_5s_alert', True):
                warn_dlg = tk.Toplevel(dlg)
                warn_dlg.title('Autoplot 5 Sec. Alert')
                warn_dlg.configure(bg=GUI_BG)
                warn_dlg.resizable(False, False)
                center_dialog(warn_dlg, self.root, 400, 160)
                warn_dlg.grab_set()
                warn_dlg.transient(dlg)   # v_rig_test_06: keep dialog above its parent
                warn_dlg.lift()
                warn_dlg.focus_force()
                tk.Label(warn_dlg,
                         text='Not recommended if total time of\n'
                              'Dream-Logfile is more than 6 hours\n'
                              'or CSV > 5 MB.',
                         bg=GUI_BG, font=('Arial', 9),
                         justify=tk.LEFT).pack(padx=15, pady=10)
                dont_show = tk.BooleanVar(value=False)
                tk.Checkbutton(warn_dlg, text="Don't show this again",
                               variable=dont_show,
                               bg=GUI_BG).pack(anchor='w', padx=15)
                def warn_ok():
                    if dont_show.get():
                        self.cfg.set('ap_5s_alert', False)
                    warn_dlg.destroy()
                    dlg.destroy()
                    _do_start(chosen_interval, sv.get())
                def warn_cancel():
                    warn_dlg.destroy()
                bf = tk.Frame(warn_dlg, bg=GUI_BG)
                bf.pack(pady=8)
                tk.Button(bf, text='OK',     command=warn_ok,     width=8).pack(side=tk.LEFT, padx=5)
                tk.Button(bf, text='Cancel', command=warn_cancel, width=8).pack(side=tk.LEFT, padx=5)
            else:
                dlg.destroy()
                _do_start(chosen_interval, sv.get())

        def _do_start(interval, scroll):
            self.ap_interval = interval
            self.ap_scroll   = scroll
            # Persist the user's choice (Aug 2026, user request) — so the
            # next 'Auto Plot Settings' dialog, even after a full
            # programme restart, opens pre-selected with these same
            # values instead of always falling back to 30 / 'Full'.
            self.cfg.set('ap_last_interval', interval)
            self.cfg.set('ap_last_scroll', scroll)
            self.ap_active   = True
            self._ap_start_time = datetime.now()
            self.ap_led.itemconfig(self._ap_oval, fill='#00cc00', outline='#008800')
            self.ap_btn.configure(text='Stop')
            self.v_ap_interval.set(f'Interval: {self.ap_interval}s')
            self.v_ap_scroll.set(f'Scroll:   {self.ap_scroll}')
            self._autoplot_tick()

        tk.Button(dlg, text='OK', command=start, width=10,
                  font=('Arial', 10)).grid(row=2, column=0, columnspan=3, pady=12)

    def _start_autoplot_silent(self, interval=10):
        """
        Start AutoPlot without opening the settings dialog.
        Originally used exclusively by the Set Event timer after the
        65-second delay; also reused (Aug 2026, unchanged) by the
        DRM-Radio-List's 'Start with AutoPlot (10s)' checkbox via
        self._radio_list_start_autoplot_after_log() — same proven
        behaviour, no changes made here for that.
        - interval  : fixed at 10 seconds (caller passes 10)
        - ap_scroll : kept exactly as the user last set it manually
        The AutoPlot LED and button caption are updated just like the
        manual start path so the user can see AutoPlot is running and
        can stop it with the [Stop] button in the main window if needed.
        """
        if self.ap_active:
            return   # already running — do nothing
        if not self.txt_path:
            return   # no log files loaded — cannot start
        self.ap_interval = interval
        # ap_scroll is NOT touched — keeps whatever the user set last
        self.ap_active      = True
        self._ap_start_time = datetime.now()   # warmup anchor
        self.ap_led.itemconfig(self._ap_oval, fill='#00cc00', outline='#008800')
        self.ap_btn.configure(text='Stop')
        self.v_ap_interval.set(f'Interval: {self.ap_interval}s')
        self.v_ap_scroll.set(f'Scroll:   {self.ap_scroll}')
        self._autoplot_tick()

    def _radio_list_start_autoplot_after_log(self, log_dir, delay_ms=20000):
        """
        NEW (Aug 2026) — 'Start with AutoPlot (10s)' checkbox in the
        DRM-Radio-List window.

        Deliberately a SEPARATE, self-contained method — does NOT touch,
        share, or call into any Set Event / Timer-Event code. It only
        reuses the two already-proven, general-purpose building blocks
        that Timer-Events also happen to use: the module-level log
        parsing helpers and self._start_autoplot_silent() above. Timer-
        Event's own internal countdown/loading code is left completely
        untouched, per explicit user requirement.

        Mirrors the same ~20s wait Timer-Events already use before their
        own silent AutoPlot start — enough time for DreamLog.txt /
        DreamLogLong.csv to actually contain the first written data.

        Aborts quietly (no popup, no error) if, by the time this fires,
        Dream Log is no longer running (e.g. the user stopped it in the
        meantime) — same 'don't act on stale state' principle used
        throughout the programme.

        Aug 2026, user request: while this 20s wait is pending, the
        Main-GUI's 'AutoPlot' LED (self.ap_led) should show YELLOW —
        'AutoPlot armed, waiting for Dream to log'. That yellow display
        logic already existed (added earlier for Timer-Events) and reads
        the shared self._ap_countdown_active flag on its own 2-second
        tick — it was simply never armed from this method. Setting/
        clearing that one flag here is the ONLY change; the Timer-Event
        code that flag was originally built for is not touched at all.
        """
        countdown_active = [True]
        self._ap_countdown_active = countdown_active
        def _fire():
            # Log was stopped (manually or otherwise) before this fired
            # — nothing to load, nothing to plot. Silent, no error.
            if not (hasattr(self, '_dream_log_flag') and self._dream_log_flag):
                countdown_active[0] = False   # LED back to grey
                return
            if self.ap_active:
                countdown_active[0] = False
                return   # already running (e.g. started manually meanwhile)
            derived_txt = os.path.join(log_dir, 'DreamLog.txt')
            derived_csv = os.path.join(log_dir, 'DreamLogLong.csv')
            if not os.path.exists(derived_txt):
                countdown_active[0] = False   # nothing written — LED to grey
                return   # nothing written yet — silently give up, as designed
            try:
                self.txt_path = derived_txt
                self.csv_path = derived_csv
                self.all_logs = parse_dreamlog_txt(derived_txt)
                self.all_csv  = (load_csv_rows(derived_csv)
                                 if os.path.exists(derived_csv) else [])
                if not self.all_logs:
                    countdown_active[0] = False
                    return
                self.ss_btn.configure(state=tk.NORMAL)
                self.log_lb.delete(0, tk.END)
                for log in self.all_logs:
                    self.log_lb.insert(tk.END, log.display_name())
                idx = len(self.all_logs) - 1   # newest = just-started log
                self.log_lb.select_set(idx)
                self.sel_log = self.all_logs[idx]
                self.zoom_active = False
                self.zoom_t0 = self.zoom_t1 = None
                self._annotations     = []
                self._annotation_free = ''
                self._show_vlines     = True
                self._free_x          = 0.50
                self._free_y          = 0.50
                next_start = (self.all_logs[idx + 1].start_time
                              if idx + 1 < len(self.all_logs)
                              else self.sel_log.start_time + timedelta(hours=6))
                self.plot_rows = filter_csv_for_log(
                    self.all_csv, self.sel_log.start_time, next_start)
                self._update_meta()
                self._update_tx_site(silent=True)
                self._update_stats()
                self._replot()
                self._set_led(self.led_h, self._led_h, True)
                self._set_led(self.led_l, self._led_l, bool(self.all_csv))
                self.v_logs_count.set(str(len(self.all_logs)))
            except Exception:
                countdown_active[0] = False   # hiccup — LED back to grey
                return   # any load hiccup — silently give up, never crash
            # ── Same proven silent AutoPlot start Timer-Events use ──────
            countdown_active[0] = False   # waiting is over either way —
            # self._start_autoplot_silent() below sets self.ap_active,
            # which alone already makes the shared display show green;
            # clearing this here too is just tidy bookkeeping so no
            # stale 'waiting' flag is left behind for next time.
            self._start_autoplot_silent(10)
        try:
            self.root.after(delay_ms, _fire)
        except Exception:
            countdown_active[0] = False
            pass

    def _stop_autoplot_silent(self):
        """
        Stop AutoPlot without any dialog or user interaction.
        Used exclusively by the Set Event stop-timer so AutoPlot is
        cleanly shut down before Dream is terminated.
        Mirrors exactly what _toggle_autoplot() does when stopping.
        """
        if not self.ap_active:
            return   # already stopped — do nothing
        self.ap_active      = False
        self._ap_start_time = None
        self.ap_btn.configure(text='Auto Plot')
        self.ap_led.itemconfig(self._ap_oval, fill='#888888', outline='#555555')
        self.v_ap_refresh.set('Refresh:')
        if hasattr(self, '_ap_after_id') and self._ap_after_id:
            try:
                self.root.after_cancel(self._ap_after_id)
            except Exception:
                pass
            self._ap_after_id = None

    # ─────────────────────────────────────────────────
    # TRX CONNECTION PROBE  (runs in background thread)
    # ─────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────────
    # STOP DREAM — callable from Main-GUI without Schedule dialog open
    # ─────────────────────────────────────────────────────────────────────
    def _stop_dream_from_main(self):
        """
        Stop Dream from the Main-GUI Stop Dream button.
        Identical logic to stop_dream() in _set_event() but uses
        self._dream_proc instead of the local dream_proc variable.
        Dialog-specific LEDs are updated via self._sched_led_status
        so they reflect correctly whether the Schedule dialog is open
        or closed.
        """
        import platform as _plt

        # ── Step 1: Cancel stop-timers → orange immediately ──────────────
        any_cancelled = False
        for i, pair in enumerate(self._sched_timers):
            t_e = pair[1]
            if t_e is not None and t_e.is_alive():
                t_e.cancel()
                self._sched_timers[i][1] = None
                self._sched_state[i]['led'] = 'orange'
                any_cancelled = True

        # ── Cancel AutoPlot countdown ─────────────────────────────────────
        if hasattr(self, '_ap_countdown_active') and \
                self._ap_countdown_active[0]:
            self._ap_countdown_active[0] = False
            self._ap_countdown_cancelled = True
            self._ap_countdown_start     = None
            # Bugfix (Aug 2026): was hardcoded range(3), silently
            # excluding slot 4 (added later) from this AutoPlot-cancel
            # bookkeeping. len(self._sched_state) always matches however
            # many Timer-Event rows actually exist — see __init__.
            for i in range(len(self._sched_state)):
                if self._sched_state[i].get('autoplot', 0):
                    self._sched_state[i]['led'] = 'orange'

        if any_cancelled:
            self._sched_led_status['led5'] = 'orange'

            def _orange_to_blue():
                # Bugfix (Aug 2026): same range(3) -> len(...) fix as
                # above — slot 4 must transition orange -> blue too.
                for i in range(len(self._sched_state)):
                    if self._sched_state[i].get('led') == 'orange':
                        self._sched_state[i]['led'] = 'blue'
                self._sched_led_status['led5'] = 'grey'
                self._ap_countdown_cancelled = False
            try:
                self.root.after(10000, _orange_to_blue)
            except Exception:
                pass

        # ── Step 2: Terminate Dream ───────────────────────────────────────
        def _do_stop():
            if self._dream_proc[0]:
                try:
                    _stop_dream_process(self._dream_proc[0])
                    self._dream_proc[0] = None
                except Exception:
                    pass
            else:
                if _plt.system() == 'Windows':
                    _subprocess_call(
                        ['taskkill', '/IM', 'Dream.exe'],
                        stdout=_subprocess.DEVNULL,
                        stderr=_subprocess.DEVNULL)
                else:
                    _subprocess_call(
                        ['pkill', '-TERM', 'dream'],
                        stdout=_subprocess.DEVNULL,
                        stderr=_subprocess.DEVNULL)

            # Reset flags
            self._dream_log_flag   = False
            self._dream_start_time = None

            # Update LED status — picked up by _timer_led_tick
            self._sched_led_status['led3'] = 'grey'
            self._sched_led_status['led4'] = 'grey'
            if not any_cancelled:
                self._sched_led_status['led5'] = 'grey'

            # Reset dream.ini — enablelog=0, delay=0
            dream_ini = self._resolve_dream_ini_path()
            if dream_ini:
                try:
                    import configparser, re as _re
                    with open(dream_ini, encoding='utf-8',
                              errors='replace') as f:
                        lines = f.readlines()
                    new_lines = []
                    for line in lines:
                        key_raw = line.split('=')[0].strip().lower()
                        if key_raw == 'enablelog':
                            new_lines.append(
                                'enablelog = 0\n' if ' = ' in line
                                else 'enablelog=0\n')
                        elif key_raw == 'delay':
                            new_lines.append(
                                'delay = 0\n' if ' = ' in line
                                else 'delay=0\n')
                        else:
                            new_lines.append(line)
                    with open(dream_ini, 'w', encoding='utf-8') as f:
                        f.writelines(new_lines)
                except Exception:
                    pass

            # Grey out the Stop Dream button
            try:
                self._stop_dream_btn.configure(state=tk.DISABLED)
            except Exception:
                pass

        self.root.after(500, _do_stop)

    # ─────────────────────────────────────────────────────────────────────
    def _is_netrigctl_mode(self, conn_mode=None, model_id=None):
        """
        True only for Network mode + Hamlib model 2 ("Hamlib NET rigctl").
        v_rig_test_03: this one specific combination gets the new
        action-based LED logic (see _netrigctl_led_state). Every other
        rig/connection type (USB serial, or Network with a real rigctld
        talking to an actual transceiver) keeps the original, unchanged
        exit-code-based logic — nothing else is affected.
        Pass conn_mode/model_id explicitly to check *live* dialog values
        (before Save & Close); omit them to check the saved cfg instead.
        """
        cm = conn_mode if conn_mode is not None else self.cfg.get('trx_conn_mode', 'usb')
        mid = model_id if model_id is not None else self.cfg.get('trx_model_id', None)
        try:
            mid = int(mid) if mid is not None else None
        except (TypeError, ValueError):
            mid = None
        return cm == 'network' and mid == 2

    # ─────────────────────────────────────────────────────────────────────
    def _netrigctl_socket_set_freq(self, host, port, freq_hz, timeout=3):
        """
        v_rig_test_05: talk directly to a rigctl-server (e.g. SDR++) over a
        raw TCP socket, bypassing the 'rigctl' command-line program
        entirely. Confirmed by an isolated test (5/5 rounds, 0.1–0.5 ms
        replies) that SDR++'s server itself is fast and reliable — the
        unreliability traced back to what 'rigctl' does internally before
        it even sends the actual command (cache setup, poll thread,
        capability negotiation — visible in the Hamlib 4.7.1 debug log as
        'rig_open returning2(-1) Invalid parameter'). A minimal, direct
        conversation avoids all of that:
            connect -> send "F <hz>\\n" -> read reply (expect "RPRT 0")
                    -> send "f\\n"      -> read reply (expect the frequency)
        Only ever used for Network mode + Hamlib model 2 ("Hamlib NET
        rigctl") — every other rig/connection type keeps using rigctl.

        Returns (ok: bool, info: str) — info is a short human-readable
        summary for the status line (raw replies or the error).
        """
        import socket as _socket
        try:
            with _socket.create_connection((host, int(port)), timeout=timeout) as s:
                s.settimeout(timeout)

                s.sendall(f"F {freq_hz}\n".encode('ascii'))
                set_reply = s.recv(200).decode('ascii', errors='replace').strip()
                if not set_reply.startswith('RPRT 0'):
                    return False, f'set failed — server replied: {set_reply!r}'

                s.sendall(b"f\n")
                read_reply = s.recv(200).decode('ascii', errors='replace').strip()
                if not read_reply.isdigit():
                    return False, f'set OK but read-back invalid: {read_reply!r}'
                if int(read_reply) != int(freq_hz):
                    return False, (f'set OK but read-back mismatch: '
                                    f'requested {freq_hz}, got {read_reply}')
                return True, f'confirmed at {read_reply} Hz'

        except _socket.timeout:
            return False, f'timeout after {timeout}s waiting for server reply'
        except ConnectionRefusedError:
            return False, 'connection refused — is the rigctl server running?'
        except Exception as ex:
            return False, f'{type(ex).__name__}: {ex}'

    # ─────────────────────────────────────────────────────────────────────
    def _rigctl_setconf_args(self):
        """
        Build the optional '--set-conf' argument for rigctl from the
        Serial Port Parameters saved in cfg.json (Data Bits, Stop Bits,
        Handshake, Force DTR, Force RTS).

        Only used for USB/Serial connections — Network mode talks to an
        already-open rigctld, whose serial line was configured by
        whoever started that daemon, so these settings do not apply there.

        Any parameter left on 'Default' is omitted entirely, so existing
        working profiles (e.g. ICOM CI-V) are completely unaffected unless
        the user explicitly changes a value away from 'Default'.

        Returns: [] or ['--set-conf', 'token1=val1,token2=val2,...']
        """
        tokens = []

        databits = self.cfg.get('trx_databits', 'Default')
        if databits == 'Seven':
            tokens.append('data_bits=7')
        elif databits == 'Eight':
            tokens.append('data_bits=8')

        stopbits = self.cfg.get('trx_stopbits', 'Default')
        if stopbits == 'One':
            tokens.append('stop_bits=1')
        elif stopbits == 'Two':
            tokens.append('stop_bits=2')

        handshake = self.cfg.get('trx_handshake', 'Default')
        if handshake == 'None':
            tokens.append('serial_handshake=None')
        elif handshake == 'XON/XOFF':
            tokens.append('serial_handshake=XONXOFF')
        elif handshake == 'Hardware':
            tokens.append('serial_handshake=Hardware')

        dtr = self.cfg.get('trx_dtr', 'Default')
        if dtr == 'On':
            tokens.append('dtr_state=ON')
        elif dtr == 'Off':
            tokens.append('dtr_state=OFF')

        rts = self.cfg.get('trx_rts', 'Default')
        if rts == 'On':
            tokens.append('rts_state=ON')
        elif rts == 'Off':
            tokens.append('rts_state=OFF')

        if not tokens:
            return []
        return ['--set-conf', ','.join(tokens)]

    # ─────────────────────────────────────────────────────────────────────
    def _probe_trx_connection(self):
        """
        Test the configured TRX connection silently in a background thread.
        Reads all parameters from self.cfg — no dialog needed.
        Updates self._sched_led_status['led1'] and ['led2'] with the result.
        Called:
          (a) 3 seconds after program start (via root.after → thread)
          (b) immediately after RX-Config Save & Close (via thread)
        Never blocks the Tkinter main loop.
        """
        import subprocess, shutil as _shutil, platform

        def _run():
            result_color = 'grey'   # default — no connection or not configured
            try:
                # ── Read config ───────────────────────────────────────
                if not self.cfg.get('trx_enable', 0):
                    # TRX control disabled — grey, no test needed
                    _apply('grey')
                    return

                model_id = self.cfg.get('trx_model_id', None)
                if not model_id:
                    _apply('grey')
                    return

                # v_rig_test_03: for Network + Hamlib NET rigctl, the
                # periodic artificial 'f' ping has proven unreliable with
                # some rigctl-server emulations (e.g. SDR++) — it must no
                # longer drive the LED for this mode. Skip the ping
                # entirely and just re-assert the last real, action-based
                # result instead (grey until the first real action happens).
                if self._is_netrigctl_mode():
                    _apply(self._netrigctl_led_state or 'grey')
                    return

                # ── Find rigctl ───────────────────────────────────────
                rigctl_p = self.cfg.get('trx_rigctl', '').strip()
                if rigctl_p and os.path.isfile(rigctl_p):
                    rigctl = rigctl_p
                else:
                    rigctl = _shutil.which('rigctl')
                if not rigctl:
                    _apply('grey')
                    return

                # ── Build command ─────────────────────────────────────
                conn = self.cfg.get('trx_conn_mode', 'usb')
                cmd  = [rigctl, '-m', str(model_id)]
                if conn == 'network':
                    host  = self.cfg.get('trx_net_host', '127.0.0.1')
                    nport = self.cfg.get('trx_net_port', '4532')
                    cmd  += ['-r', f'{host}:{nport}']
                else:
                    port = self.cfg.get('trx_port', '')
                    baud = self.cfg.get('trx_baud', '9600')
                    cmd += ['-r', port, '-s', baud]
                    cmd += self._rigctl_setconf_args()
                cmd.append('f')   # query current frequency — lightest command

                # ── Run test ──────────────────────────────────────────
                # creationflags is Windows-only — never pass it on Linux
                # stdin=DEVNULL (v_rig_test_02): confirmed fix — rigctl can
                # hang indefinitely waiting on stdin when launched by Python
                # instead of an interactive shell (no controlling-terminal
                # job control). drmlogplotter never sends anything after the
                # single command, so stdin is explicitly closed/empty.
                if platform.system() == 'Windows':
                    res = subprocess.run(cmd, capture_output=True,
                                         text=True, timeout=5,
                                         encoding='utf-8', errors='replace',
                                         stdin=subprocess.DEVNULL,
                                         creationflags=0x08000000)
                else:
                    res = subprocess.run(cmd, capture_output=True,
                                         text=True, timeout=5,
                                         encoding='utf-8', errors='replace',
                                         stdin=subprocess.DEVNULL)
                result_color = 'green' if res.returncode == 0 else 'grey'

            except Exception:
                result_color = 'grey'

            _apply(result_color)

        def _apply(color):
            """Apply result safely on the Tkinter main thread."""
            def _ui():
                self._sched_led_status['led1'] = color
                # Also update Main-GUI RX Connect LED directly —
                # _timer_led_tick only runs when Schedule dialog is open,
                # so we must update the canvas here too.
                try:
                    if color == 'green':
                        fill, outline, text = '#22cc22', '#116611', 'OK'
                    elif color == 'red':
                        fill, outline, text = '#cc2222', '#881111', 'Failed'
                    else:
                        fill, outline, text = '#888888', '#555555', 'Off'
                    self._trx_led_canvas.itemconfig(
                        self._trx_led_oval, fill=fill, outline=outline)
                    self._trx_led_var.set(text)
                except Exception:
                    pass   # widget not yet created or already destroyed
            try:
                self.root.after(0, _ui)
            except Exception:
                pass   # root already destroyed — ignore

        import threading
        t = threading.Thread(target=_run, daemon=True)
        t.start()

    # ─────────────────────────────────────────────────
    # DREAM AUDIO INFO — read window + store JSON
    # ─────────────────────────────────────────────────
    def _schedule_dream_audio_read(self, log_dir, start_time_str, freq_khz_str,
                                   delay_ms=30000, repeat_ms=30000,
                                   max_attempts=6):
        """
        Periodically read Dream's audio info, starting 30s after Dream
        start, then every further 30s (repeat_ms) for as long as Dream is
        still running AND no COMPLETE result has been found yet (both
        codec and protection — see below), up to max_attempts tries
        (default 6 — a 3-minute window in total, matching the 30s/30s
        timing already used elsewhere and confirmed sufficient by testing,
        July 2026, for reception to stabilise after a Timer-Event start).
        Stores each result in DreamAudio.json using the start_time from
        DreamLog.txt (not from Dream-start moment) so
        _load_dream_audio_for_log can match it exactly — even for short
        logs of 3-5 minutes.

        Why periodic instead of a single early check (previous design):
        DRM sync/decoding can take longer than the original 30-45s window,
        or reception can be intermittent — a one-shot check right after
        Dream starts can miss a signal that only becomes decodable later.
        Repeating regularly, and updating the file each time, also makes
        the AutoPlot display "live" instead of frozen at whatever the
        very first check happened to find (confirmed necessary by testing,
        July 2026).

        Why require BOTH codec AND protection before stopping (changed
        July 2026 — previously stopped as soon as EITHER was found):
        on Linux, screenshot-OCR detection can briefly pick up Dream's
        service-selector line ("1 | ServiceName | aac Mono (11.64 kbps)")
        instead of the actual coloured Audio-Codec label — that line
        never contains protection (EEP/UEP), so the old looser condition
        stopped polling permanently on an incomplete result before the
        real label ever appeared. Windows (UIA) and Linux Mint/Ubuntu
        (AT-SPI) read the real label directly and are not affected by
        this ambiguity — they already return both values together on the
        first successful attempt in practice, so this stricter condition
        should not change behaviour there, only make the Linux/OCR path
        more robust. The max_attempts cap exists as a safety net for the
        (currently unconfirmed) case where protection is genuinely never
        shown for some signal — without it, polling would otherwise
        continue every 30s for as long as Dream keeps running.

        The loop also stops automatically once Dream itself has ended.

        THREADING (added after Windows 11 testing, July 2026):
        _read_dream_audio_info() calls subprocess.run() on the external
        DRMLogPlotter_Audio helper, which blocks for however long the
        comtypes/UIA window search takes (confirmed on Windows: sometimes
        15-20+ seconds shortly after Dream starts, while Windows still
        sets up the UI Automation connection to the freshly started Dream
        process). Since Tkinter is single-threaded, running that blocking
        call directly in a self.root.after() callback froze the ENTIRE
        GUI for that whole duration — Windows then shows "Not Responding",
        even though the program recovers fully once the call returns (no
        crash, no restart needed — confirmed by testing). The detection
        itself does not need to be fast (25-30s would be completely fine)
        — it just must not block the GUI while it runs.
        Fix: the blocking call now runs in a background thread; only the
        final result is handed back to the main thread (via
        self.root.after(0, ...)), which is the only safe way to touch
        Tkinter widgets or reschedule further self.root.after() calls.
        """
        import threading
        attempts = [0]   # mutable closure counter — one shared instance
                        # across all _check_once/_on_worker_done calls for
                        # THIS particular _schedule_dream_audio_read() call
                        # (i.e. this one Dream-start event); unrelated to
                        # any other log's own independent polling.

        def _check_once():
            # ── Stop the loop if Dream is no longer running ────────────
            proc = self._dream_proc[0]
            if proc is not None:
                try:
                    if proc.poll() is not None:
                        return   # Dream process has ended — stop polling
                except Exception:
                    pass

            def _worker():
                # Runs in a background thread — deliberately does NOT touch
                # any Tkinter widget directly (not thread-safe in Tkinter).
                # File I/O (parse_dreamlog_txt, _read_dream_audio_info's
                # subprocess call, _save_dream_audio_json) is safe here.

                # ── Read actual start_time from DreamLog.txt ────────────
                # Dream writes the log entry ~15s after start (log delay).
                # We use this time as key — matches log.start_time exactly.
                txt_path = os.path.join(log_dir, 'DreamLog.txt')
                actual_start_str = start_time_str   # fallback
                actual_freq_str  = freq_khz_str     # fallback
                try:
                    logs = parse_dreamlog_txt(txt_path)
                    if logs:
                        newest = logs[-1]
                        if newest.start_time:
                            actual_start_str = newest.start_time.strftime(
                                '%Y-%m-%d %H:%M:%S')
                        if newest.frequency:
                            actual_freq_str = newest.frequency.replace(
                                ' kHz', '').strip()
                except Exception:
                    pass   # fallback to Dream-start time

                # ── Read audio info from Dream window (the slow, blocking
                #    part — now safely off the GUI thread) ───────────────
                info = _read_dream_audio_info()
                if not info:
                    # Complete detection failure (e.g. weak reception, no
                    # Dream window found) — still write a placeholder entry
                    # so DreamAudio.json always exists, then try again later.
                    info = {'codec': '—', 'protection': '—',
                             'sbr': 'Off', 'audio_mode': '—'}

                entry = {
                    'start_time':  actual_start_str,
                    'freq_khz':    actual_freq_str,
                    'codec':       info['codec'],
                    'protection':  info['protection'],
                    'sbr':         info['sbr'],
                    'audio_mode':  info['audio_mode'],
                }
                # merged_entry reflects the FINAL state after combining with
                # any previously-found values for this same log — see the
                # "MERGE, NOT OVERWRITE" note on _save_dream_audio_json().
                merged_entry = _save_dream_audio_json(log_dir, entry)

                # Hand off everything that touches Tkinter/self.root back
                # to the main thread — the only safe way to do this.
                self.root.after(0, lambda: _on_worker_done(merged_entry))

            def _on_worker_done(entry):
                # Runs back on the main thread.
                #
                # Only push this into the GUI if the log CURRENTLY shown
                # is actually the same log this poll was started for.
                # Fixed July 2026: previously applied unconditionally
                # whenever any log was selected, which could show one
                # log's audio info while a different (not yet updated)
                # log was on screen — confirmed by testing.
                if (self.sel_log
                        and self.sel_log.start_time
                        and self.sel_log.start_time.strftime('%Y-%m-%d %H:%M:%S')
                            == entry.get('start_time', '')
                        and self.sel_log.frequency.replace(' kHz', '').strip()
                            == entry.get('freq_khz', '')):
                    self._apply_dream_audio_to_gui(entry)
                attempts[0] += 1
                complete = (entry['codec'] != '—' and entry['protection'] != '—')
                # ── Keep polling if still incomplete AND attempts remain ──
                if not complete and attempts[0] < max_attempts:
                    try:
                        self.root.after(repeat_ms, _check_once)
                    except Exception:
                        pass
                # else: complete result found, or max_attempts reached —
                # stop, no further rescheduling. Whatever was last saved
                # to DreamAudio.json (even if still partial) remains as
                # the final answer for this log.

            threading.Thread(target=_worker, daemon=True).start()

        try:
            self.root.after(delay_ms, _check_once)
        except Exception:
            pass

    def _apply_dream_audio_to_gui(self, entry):
        """Update the 5th row in Main Log from a DreamAudio entry dict."""
        if not entry:
            self.v_audio_codec.set('—')
            self.v_audio_mode.set('—')
            return
        codec      = entry.get('codec',      '—')
        protection = entry.get('protection', '—')
        sbr        = entry.get('sbr',        '')
        mode       = entry.get('audio_mode', '—')
        # Left: codec  e.g. "AAC" / "AAC+" / "xHE-AAC"
        self.v_audio_codec.set(codec)
        # Right: e.g. "EEP · Stereo · SBR On"
        parts = []
        if protection and protection != '—':
            parts.append(protection)
        if mode and mode != '—':
            parts.append(mode)
        if sbr == 'On':
            parts.append('SBR On')
        self.v_audio_mode.set('  ·  '.join(parts) if parts else '—')

    def _load_dream_audio_for_log(self, log):
        """
        Try to load and display audio info for the given DreamLog entry.
        Called from _on_log_select and AutoPlot tick (when 5th row is empty).
        """
        if not self.txt_path:
            return
        log_dir = os.path.dirname(self.txt_path)
        start_str = (log.start_time.strftime('%Y-%m-%d %H:%M:%S')
                     if log.start_time else '')
        freq_str  = log.frequency.replace(' kHz', '').strip()
        entry = _find_dream_audio_entry(log_dir, start_str, freq_str)
        self._apply_dream_audio_to_gui(entry)   # None → shows '—'


    def _rigctl_health_tick(self):
        """
        Periodic RX connection health check — runs every 30 seconds.
        Completely independent of _refresh_loop (which runs every 2s
        in the Schedule dialog and only reads _sched_led_status['led1']).

        If trx_enable=0 → led1 = grey immediately (no rigctl call).
        If trx_enable=1 → calls _probe_trx_connection() in background thread.
          returncode=0  → led1 = green  (RX connected)
          returncode≠0  → led1 = grey   (IO error / timeout / port gone)

        rigctl error messages that all produce returncode≠0:
          rigctl: error = IO error
          rigctl: error = Connection timed out
          rigctl: error = No such file or directory
          rigctl: error = Permission denied
        """
        if not self.cfg.get('trx_enable', 0):
            # TRX control disabled — ensure LED is grey
            self._sched_led_status['led1'] = 'grey'
        else:
            # Run probe in background thread — never blocks GUI
            self._probe_trx_connection()

        # Reschedule — stop only when root is destroyed
        try:
            self._rigctl_health_after_id = self.root.after(
                15000, self._rigctl_health_tick)
        except Exception:
            pass   # root destroyed — loop ends silently

    def _timer_led_tick(self):
        """
        Polling loop — runs every 2 seconds regardless of whether the
        Dream-Start & Schedule dialog is open or closed.

        Derives the timer state directly from self._sched_timers and
        self._sched_state — the same persistent data the dialog uses —
        so the LED is always accurate.

        LED colours and text:
          grey   / 'Off'     — no schedule accepted or all cleared
          yellow / 'Wait'     — at least one start-timer is counting down
          green  / 'Active'  — at least one stop-timer is counting down
                               (event is running right now)
          blue   / 'Done'    — all timers finished, at least one slot done
        """
        # ── Derive state from live timer threads ──────────────────────
        any_waiting   = False   # start-timer alive  → yellow
        any_active    = False   # stop-timer  alive  → green
        any_cancelled = False   # manually stopped   → orange
        any_done      = False   # slot led == 'blue'  → blue (after green)

        # Bugfix (Aug 2026): was hardcoded range(3), so an event running
        # ONLY in slot 4 (added later) was invisible to this aggregate
        # LED — it stayed grey/Off even though slot 4's own row LED
        # correctly showed yellow. len(self._sched_state) always matches
        # the real number of Timer-Event rows.
        for i in range(len(self._sched_state)):
            pair = self._sched_timers[i]
            t_s  = pair[0]   # start-timer thread
            t_e  = pair[1]   # stop-timer  thread

            # FIX (Aug 2026): check t_s (start-timer) FIRST, not t_e. Both
            # timers are alive simultaneously for the whole time between
            # 'Accept Schedule' and their own individual fire time — t_e
            # (stop-timer) is already alive long before the event even
            # starts, since it was armed at the same moment as t_s. Only
            # t_s reliably dies exactly when the event actually begins,
            # so it must be checked first to correctly distinguish
            # "still waiting to start" (yellow) from "actually running"
            # (green) — matches the dialog's own (already correct) LED5
            # logic in _refresh_status().
            if t_s is not None and t_s.is_alive():
                any_waiting = True
            elif t_e is not None and t_e.is_alive():
                any_active = True
            elif self._sched_state[i].get('led') == 'orange':
                any_cancelled = True
            elif self._sched_state[i].get('led') == 'blue':
                any_done = True

        # ── Choose colour + text (priority: active > waiting > cancelled > done > off) ──
        if any_active:
            fill, outline, text = '#22cc22', '#116611', 'Active'
        elif any_waiting:
            fill, outline, text = '#ffee00', '#ccaa00', 'Wait'
        elif any_cancelled:
            fill, outline, text = '#ff8800', '#cc5500', 'Stop'
        elif any_done:
            fill, outline, text = '#2277ff', '#0044bb', 'Done'
        else:
            fill, outline, text = '#888888', '#555555', 'Off'

        # ── Update Timer LED ──────────────────────────────────────────────
        try:
            self._timer_led_canvas.itemconfig(
                self._timer_led_oval, fill=fill, outline=outline)
            self._timer_led_var.set(text)
        except Exception:
            pass

        # ── Update RX activ LED ───────────────────────────────────────────
        # Reads self._sched_led_status['led1'] — same source as Schedule dialog.
        try:
            trx_color = self._sched_led_status.get('led1', 'grey')
            if trx_color == 'green':
                trx_fill, trx_outline, trx_text = '#22cc22', '#116611', 'OK'
            elif trx_color == 'red':
                trx_fill, trx_outline, trx_text = '#cc2222', '#881111', 'Failed'
            else:
                trx_fill, trx_outline, trx_text = '#888888', '#555555', 'Off'
            self._trx_led_canvas.itemconfig(
                self._trx_led_oval, fill=trx_fill, outline=trx_outline)
            self._trx_led_var.set(trx_text)
        except Exception:
            pass

        # ── Update Log LED ────────────────────────────────────────────────
        # Green when Dream is actively logging (dream_proc running + log flag).
        # Grey otherwise — manuell or timer start, log flag must be True.
        try:
            log_active = (
                hasattr(self, '_dream_log_flag') and
                self._dream_log_flag and
                hasattr(self, '_dream_start_time') and
                self._dream_start_time is not None
            )
            if log_active:
                log_fill, log_outline, log_text = '#22cc22', '#116611', 'On'
            else:
                log_fill, log_outline, log_text = '#888888', '#555555', 'Off'
            self._log_led_canvas.itemconfig(
                self._log_led_oval, fill=log_fill, outline=log_outline)
            self._log_led_var.set(log_text)
        except Exception:
            pass

        # ── Update AutoPlot LED (Aug 2026) ──────────────────────────────
        # Was previously only ever grey (off) or green (active) — the
        # dialog's own LED6 already has a third, yellow "waiting for
        # DreamLog.txt" state (_ap_countdown_active), but that was never
        # reflected here. Same condition as the dialog uses, piggy-backed
        # onto this same reliable 2-second tick so it works whether or
        # not the Schedule dialog is open.
        try:
            ap_waiting = (hasattr(self, '_ap_countdown_active') and
                          bool(self._ap_countdown_active[0]) and
                          not self.ap_active)
            if self.ap_active:
                ap_fill, ap_outline = '#00cc00', '#008800'
            elif ap_waiting:
                ap_fill, ap_outline = '#ffee00', '#ccaa00'
            else:
                ap_fill, ap_outline = '#888888', '#555555'
            self.ap_led.itemconfig(self._ap_oval, fill=ap_fill, outline=ap_outline)
        except Exception:
            pass

        # ── Reschedule — stop only when root is destroyed ─────────────
        try:
            self._timer_led_after_id = self.root.after(2000, self._timer_led_tick)
        except Exception:
            pass   # root destroyed — loop ends silently

    def _autoplot_tick(self):
        if not self.ap_active: return
        try:
            self.all_logs=parse_dreamlog_txt(self.txt_path); self.all_csv=load_csv_rows(self.csv_path)
            # Update Software version display — not set by _update_stats(),
            # so must be refreshed here each AutoPlot tick.
            if self.all_logs:
                self.v_software.set(f'Dream {self.all_logs[0].sw_version}')
            # ── Refresh listbox so newest log always appears at top ───────
            # all_logs is oldest-first; listbox shows newest-first (reversed).
            # Must be kept in sync so the _on_log_select index conversion
            # (len-1-lb_idx) remains correct when new logs are added.
            self.log_lb.delete(0, tk.END)
            for log in reversed(self.all_logs):
                self.log_lb.insert(tk.END, log.display_name())
            # Re-select the currently active log in the listbox
            if self.sel_log:
                for i, log in enumerate(reversed(self.all_logs)):
                    if log.start_time == self.sel_log.start_time:
                        self.log_lb.select_set(i)
                        self.log_lb.see(i)
                        break
            if self.sel_log:
                # Fallback: len-1 = newest log (all_logs is oldest-first).
                # On Windows 11 .exe the start_time match can fail on the
                # first tick (encoding/parse difference) — without this fix
                # idx would fall back to 0 (oldest log) and show stale data.
                _fallback = len(self.all_logs) - 1
                idx=next((i for i,l in enumerate(self.all_logs) if l.start_time==self.sel_log.start_time),_fallback)
                self.sel_log = self.all_logs[idx]   # refresh — picks up updated max_audio_frames
                ns=(self.all_logs[idx+1].start_time if idx+1<len(self.all_logs)
                    else self.sel_log.start_time+timedelta(hours=6))
                self.plot_rows=filter_csv_for_log(self.all_csv,self.sel_log.start_time,ns)
                # Reload audio info if 5th row still empty (JSON may have
                # been written since the last tick — check once per tick)
                if self.v_audio_codec.get() in ('—', '', 'audio_codec'):
                    self._load_dream_audio_for_log(self.sel_log)

                # ── Dream/Log stop detection — CSV age check ─────────────
                # Dream writes one CSV row per second.
                # If the last row is older than (ap_interval + 10)s, Dream
                # has stopped or the user removed the Log flag.
                # Only active after a 30s warm-up so the first tick after
                # AutoPlot start does not trigger a false stop.
                if self.plot_rows:
                    try:
                        _last_t = parse_dt(
                            self.plot_rows[-1]['DATE'],
                            self.plot_rows[-1]['TIME'])
                        # _last_t from CSV is UTC (Dream logs in UTC).
                        # Compare against UTC now — never local time —
                        # to avoid false stops in non-UTC timezones.
                        from datetime import timezone as _tz
                        _now_utc = datetime.now(_tz.utc).replace(tzinfo=None)
                        _age    = (_now_utc - _last_t).total_seconds()
                        _threshold = self.ap_interval + 10   # dynamic: e.g. 10+10=20s
                        # Warmup: suppress stop-check for 30s after AutoPlot start.
                        # Uses _ap_start_time (set at AutoPlot start — manual or timer).
                        # This prevents false stops when the CSV contains old log data.
                        _warmup_ok = (
                            hasattr(self, '_ap_start_time') and
                            self._ap_start_time is not None and
                            (datetime.now() - self._ap_start_time
                             ).total_seconds() > 30
                        )
                        if _warmup_ok and _age > _threshold:
                            self._stop_autoplot_silent()
                            return
                    except Exception:
                        pass   # parse error — don't stop, just skip check
                # ── End of Dream/Log stop detection ──────────────────────

                # Apply scroll — show only last N minutes if not 'Full'
                scroll = getattr(self, 'ap_scroll', 'Full')
                if scroll != 'Full' and self.plot_rows:
                    try:
                        mins = int(scroll.split()[0])  # e.g. '5 min' → 5
                        last_t = parse_dt(self.plot_rows[-1]['DATE'], self.plot_rows[-1]['TIME'])
                        cutoff = last_t - timedelta(minutes=mins)
                        self.zoom_active = True
                        self.zoom_t0 = cutoff
                        self.zoom_t1 = last_t + timedelta(seconds=30)
                    except Exception:
                        self.zoom_active = False
                else:
                    self.zoom_active = False
                    self.zoom_t0 = self.zoom_t1 = None
                self._update_stats(); self._replot()
        except: pass
        # Echtzeit-Basis setzen — verhindert Drift in .exe/.bin/.AppImage
        self.ap_countdown       = self.ap_interval
        self._cd_start          = datetime.now()
        self._cd_total          = float(self.ap_interval)
        self._countdown()

    def _countdown(self):
        """Refresh-Countdown auf Basis echter PC-Systemzeit.
        Verhindert Drift in kompilierten Versionen (.exe/.bin/.AppImage)
        wo root.after(1000) teils deutlich kuerzer als 1 s feuert.
        Tick-Rate 500 ms — Anzeige bleibt trotzdem sekundengenau."""
        if not self.ap_active:
            self.v_ap_refresh.set('Refresh:')
            return
        # Verbleibende Zeit aus echter Systemzeit berechnen
        elapsed  = (datetime.now() - self._cd_start).total_seconds()
        remaining = max(0, int(self._cd_total - elapsed))
        self.ap_countdown = remaining          # Anzeige-Variable aktuell halten
        self.v_ap_refresh.set(f'Refresh: {remaining}s')
        if elapsed >= self._cd_total:
            self._autoplot_tick()
        else:
            # 500 ms Tick — genug Aufloesung, kein spuerbarer CPU-Load
            self._ap_after_id = self.root.after(500, self._countdown)

    # ─────────────────────────────────────────────────
    # TX SITES
    # ─────────────────────────────────────────────────
    def _open_tx_sites(self):
        # Toggle behaviour (Aug 2026, user request): a 2nd click while
        # the window is already open closes it instead of opening a
        # further copy. self._tx_sites_dlg tracks the currently open
        # instance (or None) across calls, persisting on the DRMPlotter
        # object itself since _manage_tx_sites() creates a fresh local
        # 'dlg' every call.
        win = getattr(self, '_tx_sites_dlg', None)
        if win is not None and win.winfo_exists():
            win.destroy()
            return
        self._manage_tx_sites()

    def _pick_tx_site(self,matches):
        dlg=tk.Toplevel(self.root); dlg.title('Select Transmitter Site'); dlg.configure(bg=GUI_BG)
        center_dialog(dlg, self.root, 420, 200)
        dlg.grab_set()
        dlg.transient(self.root)   # v_rig_test_06: keep dialog above its parent
        dlg.lift()
        dlg.focus_force()
        tk.Label(dlg,text='Multiple TX sites found.\nSelect one:',bg=GUI_BG,font=('Arial',9)).pack(padx=10,pady=5)
        lb=tk.Listbox(dlg,font=('Arial',9),width=48,height=min(8,len(matches)))
        for m in matches: lb.insert(tk.END,f"{m['freq_khz']} kHz  {m['service']}  –  {m['location']}")
        lb.pack(padx=10,pady=5)
        def sel():
            s=lb.curselection()
            if s:
                self.sel_tx=matches[s[0]]; loc=self.sel_tx['location']
                self.v_txloc.set(loc); self.v_tx_display.set(loc)
                dist,az=haversine(self.cfg.rx_lat(),self.cfg.rx_lon(),self.sel_tx['lat'],self.sel_tx['lon'])
                _,az_back=haversine(self.sel_tx['lat'],self.sel_tx['lon'],self.cfg.rx_lat(),self.cfg.rx_lon())
                self.v_dist.set(f'{int(round(dist))} km'); self.v_az.set(f'{int(round(az))} / {int(round(az_back))} deg.')
            dlg.destroy()
        tk.Button(dlg,text='Select',command=sel).pack(pady=5)

    def _manage_tx_sites(self):
        dlg = tk.Toplevel(self.root)
        dlg.title('Manage the Transmitter Sites List')
        dlg.configure(bg=GUI_BG)
        # Toggle behaviour (Aug 2026, user request) — track this window so
        # _open_tx_sites() can close it on a 2nd click instead of opening
        # another one. Cleared on <Destroy> so it works no matter how the
        # window actually closes (its own Close button, the OS X button,
        # or the toggle itself calling destroy()).
        self._tx_sites_dlg = dlg
        def _clear_tx_sites_ref(event=None):
            if event is not None and event.widget is not dlg:
                return
            self._tx_sites_dlg = None
        dlg.bind('<Destroy>', _clear_tx_sites_ref, add='+')
        _saved_tx_geom = self.cfg.get('tx_sites_geometry', '')
        if _saved_tx_geom:
            try:
                dlg.geometry(_saved_tx_geom)
            except Exception:
                center_dialog(dlg, self.root, 800, 520)
        else:
            center_dialog(dlg, self.root, 800, 520)

        def _save_tx_geometry(event=None):
            # Live while dragging/resizing, same as the DRM-Radio-List,
            # Help and Add Comments windows — only reacts to events on
            # dlg itself, not on any child widget bubbling one up.
            if event is not None and event.widget is not dlg:
                return
            try:
                self.cfg.set('tx_sites_geometry', dlg.geometry())
            except Exception:
                pass
        dlg.bind('<Configure>', _save_tx_geometry, add='+')

        # load_tx_file defined first so btn_row can reference it
        def load_tx_file():
            p = filedialog.askopenfilename(
                title='Load drmtransmittersites.txt',
                filetypes=[('TX Sites','drmtransmittersites.txt'),
                           ('Text','*.txt'),('All','*.*')]
            )
            if not p: return
            loaded = parse_tx_sites(p)
            loaded.sort(key=lambda s: (s['freq_khz'], s['service']))
            if loaded:
                self.tx_sites = loaded
                self.cfg.set('tx_sites_path', p)
                site_lb.delete(0, tk.END)
                for s in self.tx_sites:
                    site_lb.insert(tk.END, s['freq_service'])
                count_lbl.config(text=f'{len(self.tx_sites)} sites in the list')
                messagebox.showinfo('TX Sites loaded',
                    f'{len(loaded)} sites loaded from:\n{p}')
            else:
                messagebox.showwarning('Load TX Sites',
                    'No sites found in the selected file.')

        # Button row packed BOTTOM first — guarantees visibility
        btn_row = tk.Frame(dlg, bg=GUI_BG)
        btn_row.pack(side=tk.BOTTOM, pady=6)
        def save_tx_file():
            """Save all TX sites (including newly added) to transmittersites.txt."""
            p = self.cfg.get('tx_sites_path', '')
            if not p:
                p = filedialog.asksaveasfilename(
                    title='Save TX Sites as...',
                    defaultextension='.txt',
                    initialfile='drmtransmittersites.txt',
                    filetypes=[('Text files','*.txt'),('All files','*.*')]
                )
            if not p: return
            try:
                from datetime import date
                today = date.today().strftime('%y-%m-%d')
                lines = [f'"{today}"\n']
                for s in sorted(self.tx_sites, key=lambda s: (s['freq_khz'], s['service'])):
                    # Convert decimal degrees back to integer degrees + minutes
                    # lat/lon stored as decimal: e.g. 46.75 = 46 deg 45 min
                    lat_abs = abs(s['lat'])
                    lat_deg = int(lat_abs)
                    lat_min = int(round((lat_abs - lat_deg) * 60))
                    lon_abs = abs(s['lon'])
                    lon_deg = int(lon_abs)
                    lon_min = int(round((lon_abs - lon_deg) * 60))
                    # Negative sign for S/W stored on the degree value
                    if s['lat'] < 0: lat_deg = -lat_deg
                    if s['lon'] < 0: lon_deg = -lon_deg
                    lines.append('""\n')
                    lines.append(f'"{s["freq_khz"]} kHz {s["service"]}"\n')
                    lines.append(f'"{lon_deg}"\n')
                    lines.append(f'"{lon_min}"\n')
                    lines.append(f'"{lat_deg}"\n')
                    lines.append(f'"{lat_min}"\n')
                    lines.append(f'"{s["location"]}"\n')
                with open(p, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                self.cfg.set('tx_sites_path', p)
                messagebox.showinfo('Saved',
                    f'{len(self.tx_sites)} TX sites saved to:\n{p}')
            except Exception as e:
                messagebox.showerror('Save Error', str(e))

        def sort_list():
            self.tx_sites.sort(key=lambda s: (s['freq_khz'], s['service']))
            refresh_list()
            status_lbl.config(text=f'List sorted by frequency ({len(self.tx_sites)} sites).',
                              fg='#008800')

        tk.Button(btn_row, text='Load TX-Sites', font=('Arial',9),
                  bg='#aaddff', width=14,
                  command=load_tx_file).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text='Save TX-Sites', font=('Arial',9),
                  bg='#aaddaa', width=14,
                  command=save_tx_file).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text='Sort List', font=('Arial',9),
                  bg='#ffddaa', width=10,
                  command=sort_list).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text='Close', font=('Arial',9),
                  width=8, command=dlg.destroy).pack(side=tk.LEFT, padx=6)

        # Left frame: Add/Edit/Delete
        lf = tk.LabelFrame(dlg, text='Add, Edit or Delete a Transmitter Site',
                           bg=GUI_BG, font=('Arial',10,'bold'))
        lf.pack(side=tk.LEFT, fill=tk.BOTH, padx=5, pady=5)
        entries = {}
        # Max 5 digits for Frequency (Aug 2026, user request) — shortwave
        # never exceeds 30000 kHz. Same proven validator already used
        # for the Log-Frequency field in 'Dream — Start & Schedule'.
        def _val_freq_5dig_tx(val):
            return len(val) <= 5 and (val == '' or val.isdigit())
        vcmd_freq5_tx = (lf.register(_val_freq_5dig_tx), '%P')
        for r, lbl in enumerate(['Service Name','TX Location','Frequency (kHz)']):
            tk.Label(lf, text=lbl, bg=GUI_BG, font=('Arial',10)).grid(row=r, column=0, sticky='w', pady=3)
            if lbl == 'Frequency (kHz)':
                e = tk.Entry(lf, width=24, font=('Arial',10),
                             validate='key', validatecommand=vcmd_freq5_tx)
            else:
                e = tk.Entry(lf, width=24, font=('Arial',10))
            e.grid(row=r, column=1, padx=3, pady=3)
            entries[lbl] = e
        # Max 2 digits for Lat degrees+minutes and Lon minutes (Aug 2026,
        # user request) — same proven validator already used in Setup ->
        # Receiver Coordinates.
        def _val_2dig_coord_tx(val):
            return len(val) <= 2 and (val == '' or val.isdigit())
        vcmd_coord_tx = (lf.register(_val_2dig_coord_tx), '%P')
        # Aug 2026, user bug report (with screenshot: Rangitaiki/NZL,
        # 176°E — Lon-degree field showed up completely EMPTY after
        # clicking the site, and saving would have silently corrupted
        # it to ~0°E): a Longitude DEGREE can be up to 180, so the same
        # 3-digit validator already used in Setup -> Receiver
        # Coordinates is needed here too. Longitude degrees only —
        # Latitude degrees (max 90) and both Minutes fields (max 59)
        # are intentionally left on the 2-digit validator above.
        def _val_3dig_lon_coord_tx(val):
            return len(val) <= 3 and (val == '' or val.isdigit())
        vcmd_coord_lon_tx = (lf.register(_val_3dig_lon_coord_tx), '%P')
        tk.Label(lf, text='Lat:', bg=GUI_BG, font=('Arial',10)).grid(row=3, column=0, sticky='w')
        lat_d = tk.Entry(lf, width=5, font=('Arial',10),
                          validate='key', validatecommand=vcmd_coord_tx)
        lat_d.grid(row=3, column=1, sticky='w')
        lat_m = tk.Entry(lf, width=5, font=('Arial',10),
                          validate='key', validatecommand=vcmd_coord_tx)
        lat_m.grid(row=3, column=2, sticky='w')
        lat_ns = tk.StringVar(value='N')
        lat_ns_menu = tk.OptionMenu(lf, lat_ns, 'N','S')
        lat_ns_menu.grid(row=3, column=3)
        tk.Label(lf, text='Lon:', bg=GUI_BG, font=('Arial',10)).grid(row=4, column=0, sticky='w')
        lon_d = tk.Entry(lf, width=5, font=('Arial',10),
                          validate='key', validatecommand=vcmd_coord_lon_tx)
        lon_d.grid(row=4, column=1, sticky='w')
        lon_m = tk.Entry(lf, width=5, font=('Arial',10),
                          validate='key', validatecommand=vcmd_coord_tx)
        lon_m.grid(row=4, column=2, sticky='w')
        lon_ew = tk.StringVar(value='E')
        lon_ew_menu = tk.OptionMenu(lf, lon_ew, 'E','W')
        lon_ew_menu.grid(row=4, column=3)

        # Auto-tab (Aug 2026, user request) — Coordinates ONLY, not
        # Frequency. Same proven helper already used in Setup -> Receiver
        # Coordinates: jumps to the next field as soon as 2 digits have
        # been typed, so the user never has to press Tab manually while
        # entering Lat/Lon degrees and minutes.
        # Aug 2026, user feedback round 2: Auto-tab REMOVED specifically
        # from the Longitude-degree field (lon_d) — waiting for a 3rd
        # digit before jumping felt awkward for the (common) 2-digit
        # case. User now Tabs/clicks to the Minutes field manually for
        # Longitude; every other field (Latitude degrees/minutes,
        # Longitude minutes) keeps its normal 2-digit auto-tab.
        def _make_autotab_tx(src, dst, maxlen=2):
            def _check(event, s=src, d=dst, m=maxlen):
                if len(s.get()) >= m:
                    d.focus_set()
            src.bind('<KeyRelease>', _check)
        _make_autotab_tx(lat_d, lat_m)
        _make_autotab_tx(lat_m, lat_ns_menu)
        _make_autotab_tx(lon_m, lon_ew_menu)

        # helper: clear all entry fields
        def clear_fields():
            for e in entries.values(): e.delete(0, tk.END)
            lat_d.delete(0, tk.END); lat_m.delete(0, tk.END)
            lon_d.delete(0, tk.END); lon_m.delete(0, tk.END)
            lat_ns.set('N'); lon_ew.set('E')
            status_lbl.config(text='')

        # helper: fill entry fields from a site dict
        def fill_fields(s):
            clear_fields()
            entries['Service Name'].insert(0, s['service'])
            entries['TX Location'].insert(0, s['location'])
            entries['Frequency (kHz)'].insert(0, str(s['freq_khz']))
            # Reconstruct lat deg/min and N/S
            lat_abs = abs(s['lat'])
            lat_deg_v = int(lat_abs)
            lat_min_v = int(round((lat_abs - lat_deg_v) * 60))
            lat_d.insert(0, str(lat_deg_v))
            lat_m.insert(0, str(lat_min_v))
            lat_ns.set('S' if s['lat'] < 0 else 'N')
            # Reconstruct lon deg/min and E/W
            lon_abs = abs(s['lon'])
            lon_deg_v = int(lon_abs)
            lon_min_v = int(round((lon_abs - lon_deg_v) * 60))
            lon_d.insert(0, str(lon_deg_v))
            lon_m.insert(0, str(lon_min_v))
            lon_ew.set('W' if s['lon'] < 0 else 'E')

        def refresh_list():
            site_lb.delete(0, tk.END)
            for s in self.tx_sites:
                site_lb.insert(tk.END, s['freq_service'])
            count_lbl.config(text=f'{len(self.tx_sites)} sites in the list')

        def add_site():
            """Add new site OR update existing selected site."""
            try:
                freq = int(entries['Frequency (kHz)'].get())
                svc  = entries['Service Name'].get().strip()
                loc  = entries['TX Location'].get().strip()
                if not svc or not loc:
                    messagebox.showwarning('Add Site', 'Please fill in Service Name and TX Location.')
                    return
                lat_deg_v = int(lat_d.get() or 0)
                lat_min_v = int(lat_m.get() or 0)
                lon_deg_v = int(lon_d.get() or 0)
                lon_min_v = int(lon_m.get() or 0)
                lat = (lat_deg_v + lat_min_v/60.0) * (-1 if lat_ns.get()=='S' else 1)
                lon = (lon_deg_v + lon_min_v/60.0) * (-1 if lon_ew.get()=='W' else 1)
                new_site = {'freq_khz':freq,'service':svc,'location':loc,
                            'freq_service':f'{freq} kHz {svc}','lat':lat,'lon':lon}
                sel = site_lb.curselection()
                if sel:
                    # Update existing site
                    self.tx_sites[sel[0]] = new_site
                    status_lbl.config(text=f'Updated: {freq} kHz {svc}', fg='#008800')
                else:
                    # Add new site — insert in frequency order
                    self.tx_sites.append(new_site)
                    self.tx_sites.sort(key=lambda s: (s['freq_khz'], s['service']))
                    status_lbl.config(text=f'Added: {freq} kHz {svc}', fg='#008800')
                refresh_list()
                clear_fields()
            except Exception as e:
                messagebox.showerror('Error', str(e))

        def del_site():
            sel = site_lb.curselection()
            if not sel:
                messagebox.showwarning('Delete', 'Please select a site from the list first.')
                return
            s = self.tx_sites[sel[0]]
            if messagebox.askyesno('Delete Site',
                    f"Delete '{s['freq_service']}'?"):
                self.tx_sites.pop(sel[0])
                refresh_list()
                clear_fields()
                status_lbl.config(text='Site deleted.', fg='#cc0000')

        # Status label
        status_lbl = tk.Label(lf, text='', bg=GUI_BG, font=('Arial',10), fg='#008800')
        status_lbl.grid(row=6, column=0, columnspan=4, sticky='w', pady=2)

        tk.Button(lf, text='Add / Save Site', command=add_site,
                  bg='#aaddaa', font=('Arial',10,'bold')).grid(row=5, column=0, pady=5, padx=2)
        tk.Button(lf, text='Delete Site', command=del_site,
                  bg='#ffaaaa', font=('Arial',10)).grid(row=5, column=1, pady=5, padx=2)
        tk.Button(lf, text='Clear Fields', font=('Arial',10),
                  command=clear_fields).grid(row=5, column=2, pady=5, padx=2)

        # Right frame: site list
        rf = tk.LabelFrame(dlg, text='DRM Transmitter Sites',
                           bg=GUI_BG, font=('Arial',10,'bold'))
        rf.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        site_lb = tk.Listbox(rf, font=('Courier',10), width=28, height=14,
                             selectbackground='#000080', selectforeground='white')
        sb = ttk.Scrollbar(rf, command=site_lb.yview)
        site_lb.configure(yscrollcommand=sb.set)
        site_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        for s in self.tx_sites: site_lb.insert(tk.END, s['freq_service'])
        count_lbl = tk.Label(rf, text=f'{len(self.tx_sites)} sites in the list',
                             bg=GUI_BG, font=('Arial',10))
        count_lbl.pack()

        # Click on list → fill fields for editing
        def on_select(event):
            sel = site_lb.curselection()
            if sel:
                fill_fields(self.tx_sites[sel[0]])
                status_lbl.config(
                    text=f'Selected: {self.tx_sites[sel[0]]["freq_service"]}',
                    fg='#000080')
        site_lb.bind('<<ListboxSelect>>', on_select)

    # ─────────────────────────────────────────────────
    # DRM-RADIO-LIST — Manage / Edit the DRM Schedule (.ini)
    #
    # Deliberately a fully separate, independent copy of the same
    # Add/Edit/Delete pattern used above in _manage_tx_sites(). It never
    # touches self.tx_sites, TX_SITES_FILE, or any TX-Site code — it
    # works exclusively on self.drm_schedule / drmschedule_path.
    # ─────────────────────────────────────────────────
    def _manage_drm_schedule(self, on_change=None, parent=None):
        """
        Add, edit or delete entries of the DRM-Radio-List (DRMSchedule.ini).
        on_change: optional no-arg callback, called after any Load / Add /
        Save / Delete, so an already-open 'DRM-Radio-List' browser window
        can refresh itself immediately instead of waiting for its own
        once-a-minute auto-refresh.
        parent: the window this dialog should be created under. MUST be
        the actual calling window (e.g. the DRM-Radio-List Toplevel) when
        called from inside a modal dialog chain — Tk's local grab_set()
        (used by the Set-Event dialog) restricts all input to the
        grabbing widget AND ITS DESCENDANTS ONLY. A Toplevel created
        under self.root while some other Toplevel holds the grab is a
        SIBLING of the grab-holder, not a descendant, and therefore
        receives no mouse/keyboard events at all — visible but frozen,
        except for the OS window-manager's own close button (which
        bypasses Tk entirely). Defaults to self.root for callers outside
        any modal chain.
        """
        if parent is None:
            parent = self.root
        dlg = tk.Toplevel(parent)
        dlg.title('Manage the DRM-Radio-List (DRM Schedule)')
        dlg.configure(bg=GUI_BG)
        center_dialog(dlg, self.root, 860, 560)

        def _notify():
            if on_change:
                try: on_change()
                except Exception: pass

        # load_schedule_file defined first so btn_row can reference it
        def load_schedule_file():
            p = filedialog.askopenfilename(
                title='Load DRM Schedule (.ini)',
                filetypes=[('DRM Schedule','*.ini'),('All','*.*')]
            )
            if not p: return
            loaded = parse_drm_schedule(p)
            if loaded:
                self.drm_schedule = loaded
                self.cfg.set('drmschedule_path', p)
                refresh_list()
                messagebox.showinfo('DRM Schedule loaded',
                    f'{len(loaded)} entries loaded from:\n{p}')
                _notify()
            else:
                messagebox.showwarning('Load DRM Schedule',
                    'No valid entries found in the selected file.')

        # Button row packed BOTTOM first — guarantees visibility
        btn_row = tk.Frame(dlg, bg=GUI_BG)
        btn_row.pack(side=tk.BOTTOM, pady=6)

        def save_schedule_file():
            """Save all DRM-Radio-List entries (including new ones) to disk."""
            p = self.cfg.get('drmschedule_path', '')
            if not p:
                p = filedialog.asksaveasfilename(
                    title='Save DRM Schedule as...',
                    defaultextension='.ini',
                    initialfile='DRMSchedule.ini',
                    filetypes=[('DRM Schedule','*.ini'),('All files','*.*')]
                )
            if not p: return
            try:
                save_drm_schedule(p, self.drm_schedule)
                self.cfg.set('drmschedule_path', p)
                messagebox.showinfo('Saved',
                    f'{len(self.drm_schedule)} entries saved to:\n{p}')
                _notify()
            except Exception as e:
                messagebox.showerror('Save Error', str(e))

        def sort_list():
            self.drm_schedule.sort(key=lambda e: (e['freq_khz'], e['programme'].lower()))
            refresh_list()
            status_lbl.config(
                text=f'List sorted by frequency ({len(self.drm_schedule)} entries).',
                fg='#008800')

        tk.Button(btn_row, text='Load DRM-Schedule', font=('Arial',9),
                  bg='#aaddff', width=16,
                  command=load_schedule_file).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text='Save DRM-Schedule', font=('Arial',9),
                  bg='#aaddaa', width=16,
                  command=save_schedule_file).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text='Sort List', font=('Arial',9),
                  bg='#ffddaa', width=10,
                  command=sort_list).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text='Close', font=('Arial',9),
                  width=8, command=dlg.destroy).pack(side=tk.LEFT, padx=6)

        # Left frame: Add/Edit/Delete
        lf = tk.LabelFrame(dlg, text='Add, Edit or Delete a DRM Schedule Entry',
                           bg=GUI_BG, font=('Arial',10,'bold'))
        lf.pack(side=tk.LEFT, fill=tk.BOTH, padx=5, pady=5)

        # Max 5 digits for Frequency (Aug 2026, user request) — shortwave
        # never exceeds 30000 kHz. Same proven validator already used for
        # the Log-Frequency field in 'Dream — Start & Schedule' and for
        # the TX-Sites 'Add, Edit or Delete a Transmitter Site' frame.
        # This dialog is the ONE shared function opened from both
        # 'DRM-Radio-List' and 'Radio-List for Timer-Event' (via the
        # 'Edit DRM-Schedule' button in each) — fixing it here therefore
        # applies identically and automatically to both, by design.
        def _val_freq_5dig_sched(val):
            return len(val) <= 5 and (val == '' or val.isdigit())
        vcmd_freq5_sched = (lf.register(_val_freq_5dig_sched), '%P')

        entries_w = {}
        for r, lbl in enumerate(['Programme','Frequency (kHz)','Target',
                                  'Power (kW)','Site','Country','Language']):
            tk.Label(lf, text=lbl, bg=GUI_BG, font=('Arial',10)).grid(
                row=r, column=0, sticky='w', pady=3)
            if lbl == 'Frequency (kHz)':
                e = tk.Entry(lf, width=24, font=('Arial',10),
                             validate='key', validatecommand=vcmd_freq5_sched)
            else:
                e = tk.Entry(lf, width=24, font=('Arial',10))
            e.grid(row=r, column=1, columnspan=3, padx=3, pady=3, sticky='w')
            entries_w[lbl] = e

        # Start / Stop time (UTC, HHMM — same convention as the .ini file)
        def _val_hhmm(val):
            return len(val) <= 4 and (val == '' or val.isdigit())
        vcmd_hhmm = (lf.register(_val_hhmm), '%P')

        r_time = 7
        tk.Label(lf, text='Start (UTC, HHMM)', bg=GUI_BG, font=('Arial',10)).grid(
            row=r_time, column=0, sticky='w', pady=3)
        start_e = tk.Entry(lf, width=6, font=('Arial',10), validate='key',
                           validatecommand=vcmd_hhmm)
        start_e.grid(row=r_time, column=1, sticky='w')
        tk.Label(lf, text='Stop (UTC, HHMM)', bg=GUI_BG, font=('Arial',10)).grid(
            row=r_time+1, column=0, sticky='w', pady=3)
        stop_e = tk.Entry(lf, width=6, font=('Arial',10), validate='key',
                          validatecommand=vcmd_hhmm)
        stop_e.grid(row=r_time+1, column=1, sticky='w')

        # Auto-tab (Aug 2026, user request) — Start time ONLY: jumps to
        # the Stop field as soon as all 4 digits (HHMM) have been typed.
        # Deliberately one-directional — no auto-tab away from Stop.
        def _autotab_start_to_stop(event=None):
            if len(start_e.get()) >= 4:
                stop_e.focus_set()
        start_e.bind('<KeyRelease>', _autotab_start_to_stop)

        # Days[SMTWTFS] — 7 checkboxes, index 0=Sunday .. 6=Saturday
        r_days = r_time + 2
        tk.Label(lf, text='Days', bg=GUI_BG, font=('Arial',10)).grid(
            row=r_days, column=0, sticky='w', pady=3)
        day_vars = [tk.BooleanVar(value=True) for _ in range(7)]
        day_frame = tk.Frame(lf, bg=GUI_BG)
        day_frame.grid(row=r_days, column=1, columnspan=3, sticky='w')
        for i, lbl in enumerate('SMTWTFS'):
            tk.Checkbutton(day_frame, text=lbl, variable=day_vars[i],
                           bg=GUI_BG, font=('Arial',9)).pack(side=tk.LEFT)

        # helper: clear all entry fields back to a sensible "new entry" state
        def clear_fields():
            for e in entries_w.values(): e.delete(0, tk.END)
            start_e.delete(0, tk.END)
            stop_e.delete(0, tk.END)
            for v in day_vars: v.set(True)   # default: every day, like most real entries
            status_lbl.config(text='')

        # helper: fill entry fields from a schedule entry dict
        def fill_fields(e):
            clear_fields()
            entries_w['Programme'].insert(0, e['programme'])
            entries_w['Frequency (kHz)'].insert(0, str(e['freq_khz']))
            entries_w['Target'].insert(0, e['target'])
            entries_w['Power (kW)'].insert(0, e['power'])
            entries_w['Site'].insert(0, e['site'])
            entries_w['Country'].insert(0, e['country'])
            entries_w['Language'].insert(0, e['language'])
            start_e.insert(0, f"{e['start_h']:02d}{e['start_m']:02d}")
            stop_e.insert(0, f"{e['stop_h']:02d}{e['stop_m']:02d}")
            for i, v in enumerate(day_vars):
                v.set(e['days'][i] == '1')

        def refresh_list():
            sched_lb.delete(0, tk.END)
            for e in self.drm_schedule:
                sst = f"{e['start_h']:02d}{e['start_m']:02d}-{e['stop_h']:02d}{e['stop_m']:02d}"
                sched_lb.insert(tk.END, f"{e['freq_khz']} kHz  {sst}  {e['programme']}")
            count_lbl.config(text=f'{len(self.drm_schedule)} entries in the list')

        def add_entry():
            """Add new entry OR update the currently selected one."""
            try:
                programme = entries_w['Programme'].get().strip()
                freq_str  = entries_w['Frequency (kHz)'].get().strip()
                if not programme or not freq_str.isdigit():
                    messagebox.showwarning(
                        'Add Entry',
                        'Please fill in at least Programme and a numeric Frequency (kHz).')
                    return
                sh, sm = _split_hhmm(start_e.get() or '0000')
                eh, em = _split_hhmm(stop_e.get() or '0000')
                if sh is None or eh is None:
                    messagebox.showwarning(
                        'Add Entry', 'Start/Stop time must be 4 digits (HHMM), e.g. 1800.')
                    return
                days = ''.join('1' if v.get() else '0' for v in day_vars)
                new_entry = {
                    'start_h': sh, 'start_m': sm, 'stop_h': eh, 'stop_m': em,
                    'days': days,
                    'freq_khz': int(freq_str),
                    'target':    entries_w['Target'].get().strip(),
                    'power':     entries_w['Power (kW)'].get().strip(),
                    'programme': programme,
                    'language':  entries_w['Language'].get().strip(),
                    'site':      entries_w['Site'].get().strip(),
                    'country':   entries_w['Country'].get().strip(),
                }
                sel = sched_lb.curselection()
                if sel:
                    self.drm_schedule[sel[0]] = new_entry
                    status_lbl.config(
                        text=f'Updated: {freq_str} kHz {programme}', fg='#008800')
                else:
                    self.drm_schedule.append(new_entry)
                    self.drm_schedule.sort(
                        key=lambda e: (e['freq_khz'], e['programme'].lower()))
                    status_lbl.config(
                        text=f'Added: {freq_str} kHz {programme}', fg='#008800')
                refresh_list()
                clear_fields()
                _notify()
            except Exception as e:
                messagebox.showerror('Error', str(e))

        def del_entry():
            sel = sched_lb.curselection()
            if not sel:
                messagebox.showwarning(
                    'Delete', 'Please select an entry from the list first.')
                return
            e = self.drm_schedule[sel[0]]
            if messagebox.askyesno(
                    'Delete Entry', f"Delete '{e['freq_khz']} kHz {e['programme']}'?"):
                self.drm_schedule.pop(sel[0])
                refresh_list()
                clear_fields()
                status_lbl.config(text='Entry deleted.', fg='#cc0000')
                _notify()

        # Status label
        status_lbl = tk.Label(lf, text='', bg=GUI_BG, font=('Arial',10), fg='#008800')
        status_lbl.grid(row=r_days+1, column=0, columnspan=4, sticky='w', pady=2)

        tk.Button(lf, text='Add / Save Entry', command=add_entry,
                  bg='#aaddaa', font=('Arial',10,'bold')).grid(
                  row=r_days+2, column=0, pady=5, padx=2)
        tk.Button(lf, text='Delete Entry', command=del_entry,
                  bg='#ffaaaa', font=('Arial',10)).grid(
                  row=r_days+2, column=1, pady=5, padx=2)
        tk.Button(lf, text='Clear Fields', font=('Arial',10),
                  command=clear_fields).grid(row=r_days+2, column=2, pady=5, padx=2)

        # Right frame: schedule list
        rf = tk.LabelFrame(dlg, text='DRM-Radio-List Entries',
                           bg=GUI_BG, font=('Arial',10,'bold'))
        rf.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        sched_lb = tk.Listbox(rf, font=('Courier',9), width=40, height=18,
                              selectbackground='#000080', selectforeground='white')
        sb = ttk.Scrollbar(rf, command=sched_lb.yview)
        sched_lb.configure(yscrollcommand=sb.set)
        sched_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        count_lbl = tk.Label(rf, text=f'{len(self.drm_schedule)} entries in the list',
                             bg=GUI_BG, font=('Arial',10))
        count_lbl.pack()
        refresh_list()

        # Click on list → fill fields for editing
        def on_select(event):
            sel = sched_lb.curselection()
            if sel:
                fill_fields(self.drm_schedule[sel[0]])
                e = self.drm_schedule[sel[0]]
                status_lbl.config(
                    text=f'Selected: {e["freq_khz"]} kHz {e["programme"]}',
                    fg='#000080')
        sched_lb.bind('<<ListboxSelect>>', on_select)

    # ─────────────────────────────────────────────────
    # COMPARE / SAVE / LOAD
    # ─────────────────────────────────────────────────
    def _compare_log(self):
        if not self.sel_log:
            messagebox.showwarning('Compare', 'Select a main log first.')
            return

        # ── Step 1: choose source — saved log or file from PC ────────
        src_dlg = tk.Toplevel(self.root)
        src_dlg.title('Compare Log — Select Source')
        src_dlg.configure(bg=GUI_BG)
        center_dialog(src_dlg, self.root, 420, 200)
        src_dlg.grab_set()
        src_dlg.transient(self.root)   # v_rig_test_06: keep dialog above its parent
        src_dlg.lift()
        src_dlg.focus_force()

        tk.Label(src_dlg, text='Where is the log to compare?',
                 bg=GUI_BG, font=('Arial',10,'bold')).pack(pady=(14,8))

        source = [None]   # 'saved' or 'file'

        def pick_saved():
            source[0] = 'saved'
            src_dlg.destroy()

        def pick_file():
            source[0] = 'file'
            src_dlg.destroy()

        def cancel_src():
            src_dlg.destroy()

        btn_f = tk.Frame(src_dlg, bg=GUI_BG)
        btn_f.pack(pady=4)
        tk.Button(btn_f, text='Saved Log (drmlogplotter)',
                  font=('Arial',10), bg='#aaddff', width=20,
                  command=pick_saved).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_f, text='Load from PC (CSV file)',
                  font=('Arial',10), bg='#aaddaa', width=20,
                  command=pick_file).pack(side=tk.LEFT, padx=10)
        tk.Button(src_dlg, text='Cancel', font=('Arial',9), width=10,
                  command=cancel_src).pack(pady=(8,4))

        src_dlg.wait_window()

        if source[0] is None:
            return   # cancelled

        # ── Step 2a: pick from LOGFILES_DIR ──────────────────────────
        if source[0] == 'saved':
            os.makedirs(LOGFILES_DIR, exist_ok=True)
            saved_files = sorted(
                [f for f in os.listdir(LOGFILES_DIR) if f.endswith('.csv')],
                reverse=True)
            if not saved_files:
                messagebox.showwarning('Compare',
                    f'No saved logs found in:\n{LOGFILES_DIR}')

            pick_dlg2 = tk.Toplevel(self.root)
            pick_dlg2.title('Compare — Select Saved Log')
            pick_dlg2.configure(bg=GUI_BG)
            center_dialog(pick_dlg2, self.root, 520, 300)
            pick_dlg2.grab_set()
            pick_dlg2.transient(self.root)   # v_rig_test_06: keep dialog above its parent
            pick_dlg2.lift()
            pick_dlg2.focus_force()

            tk.Label(pick_dlg2,
                     text=f'Saved logs in:  {LOGFILES_DIR}',
                     bg=GUI_BG, font=('Arial',8,'italic'),
                     fg='#555555').pack(anchor='w', padx=8, pady=(6,2))

            frm2 = tk.Frame(pick_dlg2, bg=GUI_BG)
            frm2.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
            lb2 = tk.Listbox(frm2, font=('Courier',9), width=60, height=10,
                             selectbackground='#000080',
                             selectforeground='white')
            sb2 = ttk.Scrollbar(frm2, command=lb2.yview)
            lb2.configure(yscrollcommand=sb2.set)
            sb2.pack(side=tk.RIGHT, fill=tk.Y)
            lb2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            for f in saved_files:
                lb2.insert(tk.END, f)
            if saved_files:
                lb2.select_set(0)

            chosen_file = [None]

            def do_pick2():
                sel = lb2.curselection()
                if not sel:
                    messagebox.showwarning('Select', 'Please select a log.')
                    return
                chosen_file[0] = os.path.join(LOGFILES_DIR, saved_files[sel[0]])
                pick_dlg2.destroy()

            br2 = tk.Frame(pick_dlg2, bg=GUI_BG)
            br2.pack(pady=6)
            tk.Button(br2, text='Compare', font=('Arial',10,'bold'),
                      bg='#aaddaa', width=10,
                      command=do_pick2).pack(side=tk.LEFT, padx=8)
            tk.Button(br2, text='Cancel', font=('Arial',10),
                      width=8,
                      command=pick_dlg2.destroy).pack(side=tk.LEFT, padx=8)
            pick_dlg2.wait_window()

            if chosen_file[0] is None:
                return
            p = chosen_file[0]

        # ── Step 2b: open file dialog for any CSV ────────────────────
        else:
            p = filedialog.askopenfilename(
                title='Select Compare Log CSV',
                filetypes=[('CSV', '*.csv'), ('All', '*.*')])
            if not p:
                return

        # ── Step 3: load chosen CSV ───────────────────────────────────
        try:
            all_comp_csv = load_csv_rows(p)
        except Exception as e:
            messagebox.showerror('Error', str(e))
            return

        # ── Step 4: try to find DreamLog.txt next to the CSV ─────────
        import pathlib
        csv_dir  = pathlib.Path(p).parent
        txt_path = csv_dir / 'DreamLog.txt'
        comp_logs = []
        if txt_path.exists():
            try:
                comp_logs = parse_dreamlog_txt(str(txt_path))
            except Exception:
                comp_logs = []

        if not comp_logs:
            # No txt found — use whole CSV as one block
            self.comp_rows     = all_comp_csv
            self.comp_log_meta = None
            self._replot()
            return

        # ── Step 3: let user pick which log entry to compare ─────────
        pick_dlg = tk.Toplevel(self.root)
        pick_dlg.title('Select Compare Log Entry')
        pick_dlg.configure(bg=GUI_BG)
        center_dialog(pick_dlg, self.root, 520, 300)
        pick_dlg.grab_set()
        pick_dlg.transient(self.root)   # v_rig_test_06: keep dialog above its parent
        pick_dlg.lift()
        pick_dlg.focus_force()

        tk.Label(pick_dlg,
                 text='Select the log entry to compare:',
                 bg=GUI_BG, font=('Arial', 10, 'bold')).pack(pady=(10, 4))

        frame = tk.Frame(pick_dlg, bg=GUI_BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        lb = tk.Listbox(frame, font=('Courier', 9), width=60, height=10,
                        selectbackground='#000080', selectforeground='white')
        sb = ttk.Scrollbar(frame, command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Show logs newest-first (same as main list)
        display_logs = list(reversed(comp_logs))
        for log in display_logs:
            lb.insert(tk.END, log.display_name())
        if display_logs:
            lb.select_set(0)

        selected = [None]

        def do_select():
            sel = lb.curselection()
            if not sel:
                messagebox.showwarning('Select', 'Please select a log entry.')
                return
            selected[0] = display_logs[sel[0]]
            pick_dlg.destroy()

        def do_cancel():
            pick_dlg.destroy()

        br = tk.Frame(pick_dlg, bg=GUI_BG)
        br.pack(pady=6)
        tk.Button(br, text='Compare', font=('Arial', 10, 'bold'),
                  bg='#aaddaa', width=10, command=do_select).pack(side=tk.LEFT, padx=8)
        tk.Button(br, text='Cancel',  font=('Arial', 10),
                  width=8, command=do_cancel).pack(side=tk.LEFT, padx=8)

        pick_dlg.wait_window()

        if selected[0] is None:
            return   # user cancelled

        # ── Step 4: filter CSV to the chosen log's time range ────────
        chosen = selected[0]
        idx = comp_logs.index(chosen)
        next_start = (comp_logs[idx + 1].start_time
                      if idx + 1 < len(comp_logs)
                      else chosen.start_time + timedelta(hours=6))
        self.comp_rows     = filter_csv_for_log(all_comp_csv,
                                                chosen.start_time, next_start)
        self.comp_log_meta = chosen   # keep for legend / overlap info
        self._replot()

    def _clear_compare(self):
        """Remove the compare log and replot the main log alone."""
        self.comp_rows     = []
        self.comp_log_meta = None
        self._replot()

    def _select_main(self):
        """Restore the original log list from DreamLog.txt / DreamLogLong.csv."""
        if not self.all_logs:
            messagebox.showwarning('Main Log',
                'No main logs loaded yet.\nClick [Update] to load DreamLog.txt first.')
            return
        # Clear compare
        self.comp_rows = []
        self.comp_log_meta = None
        # Repopulate listbox with original logs
        self.log_lb.delete(0, tk.END)
        for log in reversed(self.all_logs):
            self.log_lb.insert(tk.END, log.display_name())
        # Select and plot the first (most recent) log
        self.log_lb.select_set(0)
        self.log_lb.event_generate('<<ListboxSelect>>')

    def _save_log(self):
        if not self.plot_rows: messagebox.showwarning('Save','No log data.'); return
        os.makedirs(LOGFILES_DIR,exist_ok=True)
        # Filename now matches the same "Select Main Log" display format
        # (Aug 2026, user request) — was previously Label_YYYYMMDD_HHMM
        # using the moment Save was clicked (datetime.now()), which had
        # no frequency and didn't match the log's actual recorded time.
        # Now: "{freq} kHz  {date}  {time}", using the log's own
        # start_time — same convention as DreamLogEntry.display_name().
        # Colon is replaced with a hyphen (HH-MM) since ':' is not a
        # valid filename character on Windows.
        if self.sel_log and self.sel_log.frequency:
            freq = self.sel_log.frequency.replace(' kHz', '').strip()
        else:
            freq = '?'
        if self.sel_log and self.sel_log.start_time:
            date_s = self.sel_log.start_time.strftime('%Y-%m-%d')
            time_s = self.sel_log.start_time.strftime('%H-%M')
        else:
            date_s = datetime.now().strftime('%Y-%m-%d')
            time_s = datetime.now().strftime('%H-%M')
        p=filedialog.asksaveasfilename(initialdir=LOGFILES_DIR,
            initialfile=f'{freq} kHz  {date_s}  {time_s}.csv',
            defaultextension='.csv',filetypes=[('CSV','*.csv')])
        if not p: return
        try:
            with open(p,'w',newline='',encoding='utf-8') as f:
                w=csv.DictWriter(f,fieldnames=self.plot_rows[0].keys())
                w.writeheader(); w.writerows(self.plot_rows)
            messagebox.showinfo('Saved',f'Saved:\n{p}')
        except Exception as e: messagebox.showerror('Error',str(e))

    def _load_log(self):
        """Load a previously saved log CSV from the logfiles/ folder."""
        os.makedirs(LOGFILES_DIR, exist_ok=True)
        p = filedialog.askopenfilename(
            title='Load Saved Log',
            initialdir=LOGFILES_DIR,
            filetypes=[('CSV files', '*.csv'), ('All files', '*.*')]
        )
        if not p:
            return
        try:
            self.plot_rows = load_csv_rows(p)
            # Reset Audio Codec info — archived logs have no DreamAudio.json
            self.v_audio_codec.set('—')
            self.v_audio_mode.set('—')
            self._update_stats()
            self._replot()
        except Exception as e:
            messagebox.showerror('Error', str(e))

    def _show_logs(self):
        """Show contents of the screenshots folder."""
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
        files = sorted(Path(SCREENSHOTS_DIR).glob('*.png'), reverse=True)

        dlg = tk.Toplevel(self.root)
        dlg.title('Screenshots')
        dlg.configure(bg=GUI_BG)
        center_dialog(dlg, self.root, 520, 320)

        tk.Label(dlg, text=f'Screenshots folder:  {os.path.abspath(SCREENSHOTS_DIR)}',
                 bg=GUI_BG, font=('Arial',8,'italic'), fg='#555555').pack(anchor='w', padx=8, pady=(6,2))

        # Listbox with scrollbar
        frame = tk.Frame(dlg, bg=GUI_BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=2)
        lb = tk.Listbox(frame, font=('Courier',9), width=60, height=12,
                        selectbackground='#000080', selectforeground='white')
        sb = ttk.Scrollbar(frame, command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for f in files:
            size_kb = f.stat().st_size // 1024
            lb.insert(tk.END, f'{f.name}  ({size_kb} kB)')
        if not files:
            lb.insert(tk.END, '(no screenshots yet)')

        # Open folder button
        btn_row = tk.Frame(dlg, bg=GUI_BG)
        btn_row.pack(pady=6)
        def open_folder():
            import subprocess, platform
            path = os.path.abspath(SCREENSHOTS_DIR)
            if platform.system() == 'Windows':
                if platform.system() == 'Windows':
                    os.startfile(path)
                else:
                    import subprocess as _sp
                    _sp.call(['xdg-open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        tk.Button(btn_row, text='Open Folder', font=('Arial',9), width=12,
                  command=open_folder).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_row, text='Close', font=('Arial',9), width=8,
                  command=dlg.destroy).pack(side=tk.LEFT, padx=5)

    def _edit_header(self, event=None):
        # pylint: disable=unused-argument
        """Open Receiver and Antenna Configurations — via button or grey bar click."""
        RXConfigWindow(self.root, self.cfg, self.header_var)


    # SCREENSHOT
    # ─────────────────────────────────────────────────
    def _screenshot(self):
        """
        Save a screenshot — Full GUI or Limited (plot area only).
        If screenshot_alerts is OFF: saves Plot only directly (no dialog).
        If screenshot_alerts is ON:  user chooses via a small dialog.
        """
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
        if not self.cfg.get('screenshot_alerts', True):
            # Alert off — save Plot only immediately, no dialog
            self._do_screenshot('limited')
            return
        # Ask user: Full or Limited
        choice_dlg = tk.Toplevel(self.root)
        choice_dlg.title('Screenshot')
        choice_dlg.configure(bg=GUI_BG)
        choice_dlg.resizable(False, False)
        center_dialog(choice_dlg, self.root, 320, 140)
        choice_dlg.grab_set()
        choice_dlg.transient(self.root)   # v_rig_test_06: keep dialog above its parent
        choice_dlg.lift()
        choice_dlg.focus_force()

        tk.Label(choice_dlg, text='Select Screenshot Type:',
                 bg=GUI_BG, font=('Arial',10,'bold')).pack(pady=(12,6))
        mode_var = tk.StringVar(value='limited')
        tk.Radiobutton(choice_dlg, text='Plot only  (without controls)',
                       variable=mode_var, value='limited',
                       bg=GUI_BG, font=('Arial',10)).pack(anchor='w', padx=30)
        tk.Radiobutton(choice_dlg, text='Full GUI',
                       variable=mode_var, value='full',
                       bg=GUI_BG, font=('Arial',10)).pack(anchor='w', padx=30)

        chosen = [None]
        def ok():
            chosen[0] = mode_var.get()
            choice_dlg.destroy()
        def cancel():
            choice_dlg.destroy()

        br = tk.Frame(choice_dlg, bg=GUI_BG)
        br.pack(pady=8)
        tk.Button(br, text='OK',     font=('Arial',9), width=8, command=ok).pack(side=tk.LEFT, padx=5)
        tk.Button(br, text='Cancel', font=('Arial',9), width=8, command=cancel).pack(side=tk.LEFT, padx=5)
        choice_dlg.wait_window()

        if chosen[0] is None:
            return   # cancelled

        self._do_screenshot(chosen[0])

    def _do_screenshot(self, mode='full'):
        """Perform the actual screenshot — full GUI or limited (plot area only)."""
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
        # Build filename: Frequency-YYMMDD-StartUTC-EndUTC-Nickname.png
        # Date format changed DDMMYYYY -> YYMMDD (Aug 2026, user request):
        # 2-digit year first, then month, then day — no separators within
        # the date group, same as before, just reordered/shortened.
        def safe(s):
            for c in r'\/:*?"<>|': s = s.replace(c, '')
            return s.strip()
        nickname = safe(self.cfg.get('nickname', '').strip())
        if self.sel_log:
            freq  = self.sel_log.frequency.replace(' ','').replace('kHz','')
            if self.sel_log.start_time:
                date_s  = self.sel_log.start_time.strftime('%y%m%d')
                start_s = self.sel_log.start_time.strftime('%H%M')
            else:
                date_s  = datetime.now().strftime('%y%m%d')
                start_s = '0000'
            # End time from last plot row
            if self.plot_rows:
                try:
                    last = self.plot_rows[-1]
                    end_dt = parse_dt(last['DATE'], last['TIME'])
                    end_s = end_dt.strftime('%H%M')
                except Exception:
                    end_s = start_s
            else:
                end_s = start_s
        else:
            freq    = 'DRM'
            date_s  = datetime.now().strftime('%y%m%d')
            start_s = datetime.now().strftime('%H%M')
            end_s   = start_s
        parts = [p for p in [freq, date_s, start_s, end_s, nickname] if p]
        fname = os.path.join(SCREENSHOTS_DIR, '-'.join(parts) + '.png')
        if self.cfg.get('screenshot_alerts', True):
            if mode == 'limited':
                confirm_text = f'Save plot only (without controls) to:\n{fname}?'
            else:
                confirm_text = f'Save complete GUI window to:\n{fname}?'
            if not messagebox.askyesno('Screenshot', confirm_text):
                return
        # Overwrite check — always active, even if screenshot_alerts is off
        if os.path.exists(fname):
            if not messagebox.askyesno(
                    'Overwrite Screenshot?',
                    f'This file already exists:\n{fname}\n\nOverwrite?'):
                return
        try:
            import time
            # Get window geometry BEFORE any dialog appears
            self.root.update_idletasks()
            x      = self.root.winfo_rootx()
            y      = self.root.winfo_rooty()
            width  = self.root.winfo_width()
            height = self.root.winfo_height()
            # Wait for dialog to fully disappear from screen
            self.root.update_idletasks()
            self.root.update()
            time.sleep(0.3)   # 300ms — enough for dialog to vanish
            self.root.update_idletasks()
            self.root.update()
            # Capture exactly the window area
            img = _grab_screenshot((x, y, x + width, y + height))
            if img is None:
                messagebox.showerror(
                    'Screenshot',
                    'Screenshot capture failed on this system.')
                return

            # Limited mode: crop to right edge of plot frame
            if mode == 'limited':
                self.root.update_idletasks()
                pf_right = (self.plot_frame.winfo_rootx()
                            + self.plot_frame.winfo_width()
                            - self.root.winfo_rootx())
                img = img.crop((0, 0, pf_right, img.height))

            # Scale to 20% larger than forum standard (993x618 * 1.2)
            # Keep aspect ratio — fit within target without cropping
            TARGET_W, TARGET_H = 1192, 742
            ratio_w = TARGET_W / img.width
            ratio_h = TARGET_H / img.height
            ratio   = min(ratio_w, ratio_h)   # fit inside target box
            new_w   = int(img.width  * ratio)
            new_h   = int(img.height * ratio)
            if new_w != img.width or new_h != img.height:
                from PIL import Image
                img = img.resize((new_w, new_h), Image.LANCZOS)

            # Optimise file size — 3 methods combined:
            # 1) Quantize to 256 colours (palette PNG — much smaller)
            # 2) Maximum PNG compression level 9
            # 3) optimize=True (extra pass for smallest file)
            try:
                img_opt = img.quantize(colors=256, method=2)
                img_opt.save(fname, 'PNG', compress_level=9, optimize=True)
            except Exception:
                img.save(fname, 'PNG', compress_level=9, optimize=True)
            actual_kb = os.path.getsize(fname) // 1024
            messagebox.showinfo('Screenshot saved',
                f'Saved to:\n{fname}\n'
                f'{new_w}x{new_h} px  —  {actual_kb} kB')
        except ImportError:
            # Fallback: save plot area only
            try:
                self.fig.savefig(fname, dpi=100, bbox_inches='tight',
                                 facecolor=self.fig.get_facecolor())
                messagebox.showinfo('Screenshot saved (plot only)',
                    f'Note: Install Pillow for full GUI screenshot.\n{fname}')
            except Exception as e:
                messagebox.showerror('Error', str(e))
        except Exception as e:
            messagebox.showerror('Screenshot Error', str(e))

    # ─────────────────────────────────────────────────
    # SUMMARY
    # ─────────────────────────────────────────────────
    def _show_summary(self):
        if not self.sel_log: messagebox.showwarning('Summary','No log selected.'); return
        log=self.sel_log; rows=self.plot_rows
        sn_min,sn_max,sn_avg=compute_stats(rows,'SNR')
        dl_min,dl_max,dl_avg=compute_stats(rows,'DELAY')
        dp_min,dp_max,dp_avg=compute_stats(rows,'DOPPLER')
        def fmt(v): return f'{v:.2f}' if v is not None else '-'
        rt_min=0; t0s=t1s='-'
        if rows:
            try:
                d0 = parse_dt(rows[0]['DATE'], rows[0]['TIME'])
                d1 = parse_dt(rows[-1]['DATE'], rows[-1]['TIME'])
                rt_min=int((d1-d0).total_seconds()//60); t0s=d0.strftime('%H:%M'); t1s=d1.strftime('%H:%M')
            except: pass
        dlg=tk.Toplevel(self.root); dlg.title('Main Log Summary  (Dream Format Logs)')
        dlg.configure(bg=GUI_BG)
        center_dialog(dlg, self.root, 680, 640)
        m=tk.Frame(dlg,bg=GUI_BG); m.pack(fill=tk.BOTH,expand=True,padx=5,pady=5)
        def lf(title,r,c,rs=1,cs=1):
            f=tk.LabelFrame(m,text=title,bg=GUI_BG,font=('Arial',10,'bold'),padx=5,pady=3)
            f.grid(row=r,column=c,rowspan=rs,columnspan=cs,sticky='nsew',padx=3,pady=3); return f
        def ar(frame,r,label,value,fg='#000080'):
            tk.Label(frame,text=label,bg=GUI_BG,font=('Arial',10),anchor='w',width=18).grid(row=r,column=0,sticky='w',pady=1)
            tk.Label(frame,text=value,bg=GUI_BG,font=('Arial',10,'bold'),fg=fg,anchor='w').grid(row=r,column=1,sticky='w',pady=1)
        ft=lf('Transmission',0,0)
        for i,(l,v) in enumerate([('Label:',log.label),('Date:',log.start_time.strftime('%Y-%m-%d') if log.start_time else '-'),
                                    ('Frequency:',log.frequency),('TX Location:',self.sel_tx['location'] if self.sel_tx else '-'),
                                    ('Log start time:',t0s),('Log end time:',t1s),('Runtime:',f'{rt_min} min')]): ar(ft,i,l,v)
        fsnr=lf('SNR, Delay, Doppler Data',0,1)
        for i,(l,v,u) in enumerate([('SNR, dB (max.):',fmt(sn_max),'dB'),('SNR, dB (min.):',fmt(sn_min),'dB'),
                                      ('SNR, dB (avg.):',fmt(sn_avg),'dB'),('Delay, ms (max.):',fmt(dl_max),'ms'),
                                      ('Delay, ms (min.):',fmt(dl_min),'ms'),('Delay, ms (avg.):',fmt(dl_avg),'ms'),
                                      ('Doppler, Hz (max.):',fmt(dp_max),'Hz'),('Doppler, Hz (min.):',fmt(dp_min),'Hz'),
                                      ('Doppler, Hz (avg.):',fmt(dp_avg),'Hz')]):
            tk.Label(fsnr,text=l,bg=GUI_BG,font=('Arial',10),anchor='w',width=20).grid(row=i,column=0,sticky='w',pady=1)
            tk.Label(fsnr,text=v,bg=GUI_BG,font=('Arial',10,'bold'),fg='#000080',width=7).grid(row=i,column=1,pady=1)
            tk.Label(fsnr,text=u,bg=GUI_BG,font=('Arial',10)).grid(row=i,column=2,sticky='w')
        frx=lf('Receiver',1,0)
        for i,(l,v) in enumerate([('RX Longitude:',f"{self.cfg.get('rx_lon_deg')}°{self.cfg.get('rx_lon_min')}'{self.cfg.get('rx_lon_ew')}"),
                                    ('RX Latitude:',f"{self.cfg.get('rx_lat_deg')}°{self.cfg.get('rx_lat_min')}'{self.cfg.get('rx_lat_ns')}"),
                                    ('Distance to TX:',self.v_dist.get()),('Azimuth to TX:',self.v_az.get())]): ar(frx,i,l,v)
        # RX Config — separate treatment with wraplength for long strings
        rx_cfg_text = self.header_var.get()
        tk.Label(frx, text='RX Config:', bg=GUI_BG, font=('Arial',10),
                 anchor='w').grid(row=4, column=0, sticky='w', pady=1)
        tk.Label(frx, text=rx_cfg_text, bg=GUI_BG, font=('Arial',10,'bold'),
                 fg='#000080', anchor='w', wraplength=220,
                 justify=tk.LEFT).grid(row=4, column=1, sticky='w', pady=1)
        fdrm=lf('General DRM Data',1,1)
        for i,(l,v) in enumerate([('Bitrate at start:',log.bitrate),('Mode / Bandwidth:',f'{log.mode} / {log.bandwidth}'),
                                    ('Main Service Channel:',self.v_msc.get()),('Protection Level:',self.v_pl.get()),
                                    ('Audio Codec:',self.v_audio_codec.get()),('Prot. / Audio:',self.v_audio_mode.get()),
                                    ('Decoded Audio:',self.v_audio_pct.get()),('FAC CRC:',self.v_fac.get())]): ar(fdrm,i,l,v)
        fsw=lf('Software Radio',2,0); ar(fsw,0,'DRM Software:','Dream'); ar(fsw,1,'S/W Version:',log.sw_version)
        br=tk.Frame(dlg,bg=GUI_BG); br.pack(pady=5)
        def save_txt():
            p=filedialog.asksaveasfilename(defaultextension='.txt',filetypes=[('Text','*.txt')])
            if not p:
                return
            with open(p,'w',encoding='utf-8') as f:
                f.write('DRM Log Summary\n')
                f.write('='*40 + '\n\n')

                f.write('-- Transmission --\n')
                f.write(f'Label: {log.label}\n')
                f.write(f"Date: {log.start_time.strftime('%Y-%m-%d') if log.start_time else '-'}\n")
                f.write(f'Frequency: {log.frequency}\n')
                f.write(f"TX Location: {self.sel_tx['location'] if self.sel_tx else '-'}\n")
                f.write(f'Log start time: {t0s}\n')
                f.write(f'Log end time: {t1s}\n')
                f.write(f'Runtime: {rt_min} min\n\n')

                f.write('-- SNR, Delay, Doppler Data --\n')
                f.write(f'SNR (max/min/avg), dB: {fmt(sn_max)} / {fmt(sn_min)} / {fmt(sn_avg)}\n')
                f.write(f'Delay (max/min/avg), ms: {fmt(dl_max)} / {fmt(dl_min)} / {fmt(dl_avg)}\n')
                f.write(f'Doppler (max/min/avg), Hz: {fmt(dp_max)} / {fmt(dp_min)} / {fmt(dp_avg)}\n\n')

                f.write('-- Receiver --\n')
                f.write(f"RX Longitude: {self.cfg.get('rx_lon_deg')}\u00b0{self.cfg.get('rx_lon_min')}'{self.cfg.get('rx_lon_ew')}\n")
                f.write(f"RX Latitude: {self.cfg.get('rx_lat_deg')}\u00b0{self.cfg.get('rx_lat_min')}'{self.cfg.get('rx_lat_ns')}\n")
                f.write(f'Distance to TX: {self.v_dist.get()}\n')
                f.write(f'Azimuth to TX: {self.v_az.get()}\n')
                f.write(f'RX Config: {rx_cfg_text}\n\n')

                f.write('-- General DRM Data --\n')
                f.write(f'Bitrate at start: {log.bitrate}\n')
                f.write(f'Mode / Bandwidth: {log.mode} / {log.bandwidth}\n')
                f.write(f'Main Service Channel: {self.v_msc.get()}\n')
                f.write(f'Protection Level: {self.v_pl.get()}\n')
                f.write(f'Audio Codec: {self.v_audio_codec.get()}\n')
                f.write(f'Prot. / Audio: {self.v_audio_mode.get()}\n')
                f.write(f'Decoded Audio: {self.v_audio_pct.get()}\n')
                f.write(f'FAC CRC: {self.v_fac.get()}\n\n')

                f.write('-- Software Radio --\n')
                f.write('DRM Software: Dream\n')
                f.write(f'S/W Version: {log.sw_version}\n')
        tk.Button(br,text='Save',command=save_txt,width=8).pack(side=tk.LEFT,padx=5)
        tk.Button(br,text='Close',command=dlg.destroy,width=8).pack(side=tk.LEFT,padx=5)

    # ─────────────────────────────────────────────────
    # SETUP
    # ─────────────────────────────────────────────────
    def _open_setup(self):
        dlg=tk.Toplevel(self.root); dlg.title('Basic Setup Parameters')
        dlg.configure(bg=GUI_BG)
        # Taller + resizable (July 2026): confirmed by testing that the
        # bottom-most buttons could end up hidden/clipped below the
        # window edge at the old fixed 680px height, depending on how
        # much content the OS/font combination needed. The dialog is
        # already scrollable (see below), but making it taller by
        # default — and resizable, for anyone who still needs more —
        # avoids requiring the user to scroll just to find the buttons.
        dlg.resizable(True, True)
        _saved_setup_geom = self.cfg.get('setup_geometry', '')
        if _saved_setup_geom:
            try:
                dlg.geometry(_saved_setup_geom)
            except Exception:
                center_dialog(dlg, self.root, 780, 760)
        else:
            center_dialog(dlg, self.root, 780, 760)
        dlg.minsize(650, 500)
        dlg.grab_set()

        def _save_setup_geometry(event=None):
            if event is not None and event.widget is not dlg:
                return
            try:
                self.cfg.set('setup_geometry', dlg.geometry())
            except Exception:
                pass
        dlg.bind('<Configure>', _save_setup_geometry, add='+')
        dlg.transient(self.root)   # v_rig_test_06: keep dialog above its parent
        dlg.lift()
        dlg.focus_force()

        # ── Scrollable container ──────────────────────────────────────────
        outer = tk.Frame(dlg, bg=GUI_BG)
        outer.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(outer, bg=GUI_BG, highlightthickness=0)
        vsb    = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Inner frame — all widgets go here
        inner = tk.Frame(canvas, bg=GUI_BG)
        inner_id = canvas.create_window((0, 0), window=inner, anchor='nw')

        def _on_inner_configure(event):
            canvas.configure(scrollregion=canvas.bbox('all'))
        def _on_canvas_configure(event):
            canvas.itemconfig(inner_id, width=event.width)
        inner.bind('<Configure>', _on_inner_configure)
        canvas.bind('<Configure>', _on_canvas_configure)

        # Mouse wheel scrolling — Windows + Linux
        def _on_mousewheel(event):
            if event.num == 4:
                canvas.yview_scroll(-1, 'units')
            elif event.num == 5:
                canvas.yview_scroll(1, 'units')
            else:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        canvas.bind_all('<MouseWheel>', _on_mousewheel)
        canvas.bind_all('<Button-4>',   _on_mousewheel)
        canvas.bind_all('<Button-5>',   _on_mousewheel)
        # Unbind mouse wheel when dialog closes
        def _on_close():
            canvas.unbind_all('<MouseWheel>')
            canvas.unbind_all('<Button-4>')
            canvas.unbind_all('<Button-5>')
            dlg.destroy()
        dlg.protocol('WM_DELETE_WINDOW', _on_close)

        # ── All content packed into 'inner' ───────────────────────────────
        P = inner   # shorthand — use P instead of dlg for all .pack() calls

        fd=tk.LabelFrame(P,text='Select Distance',bg=GUI_BG,font=('Arial',8,'bold'))
        fd.pack(fill=tk.X,padx=8,pady=3)
        uv=tk.StringVar(value=self.cfg.get('unit','kilometer'))
        tk.Radiobutton(fd,text='Kilometer',variable=uv,value='kilometer',bg=GUI_BG).pack(side=tk.LEFT)
        tk.Radiobutton(fd,text='Miles',    variable=uv,value='miles',    bg=GUI_BG).pack(side=tk.LEFT)
        # Plot Field Background
        fbg=tk.LabelFrame(P,text='Plot Field Background',bg=GUI_BG,font=('Arial',8,'bold'))
        fbg.pack(fill=tk.X,padx=8,pady=3)
        bgv=tk.StringVar(value=self.cfg.get('plot_bg','darkblue'))
        tk.Radiobutton(fbg,text='Dark Blue',   variable=bgv,value='darkblue',bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        tk.Radiobutton(fbg,text='Darkblue 2',  variable=bgv,value='navy2',   bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        tk.Radiobutton(fbg,text='Dark Purple', variable=bgv,value='dpurple', bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        tk.Radiobutton(fbg,text='Dark Teal',   variable=bgv,value='dteal',   bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        tk.Radiobutton(fbg,text='White',       variable=bgv,value='white',   bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        # Plot Frame Color
        ffr=tk.LabelFrame(P,text='Plot Frame Color',bg=GUI_BG,font=('Arial',8,'bold'))
        ffr.pack(fill=tk.X,padx=8,pady=3)
        frv=tk.StringVar(value=self.cfg.get('frame_bg','darkblue'))
        tk.Radiobutton(ffr,text='Dark Blue',   variable=frv,value='darkblue',bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        tk.Radiobutton(ffr,text='Darkblue 2',  variable=frv,value='navy2',   bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        tk.Radiobutton(ffr,text='Dark Purple', variable=frv,value='dpurple', bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        tk.Radiobutton(ffr,text='Dark Teal',   variable=frv,value='dteal',   bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        tk.Radiobutton(ffr,text='Gray',        variable=frv,value='gray',    bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        tk.Radiobutton(ffr,text='White',       variable=frv,value='white',   bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        # Screenshot Alerts
        fsa=tk.LabelFrame(P,text='Screenshot Alerts',bg=GUI_BG,font=('Arial',8,'bold'))
        fsa.pack(fill=tk.X,padx=8,pady=3)
        sav=tk.BooleanVar(value=self.cfg.get('screenshot_alerts',True))
        tk.Radiobutton(fsa,text='Yes',variable=sav,value=True, bg=GUI_BG).pack(side=tk.LEFT)
        tk.Radiobutton(fsa,text='No', variable=sav,value=False,bg=GUI_BG).pack(side=tk.LEFT)
        # Multiple Sites Alert
        fms=tk.LabelFrame(P,text='Multiple Sites Alert',bg=GUI_BG,font=('Arial',8,'bold'))
        fms.pack(fill=tk.X,padx=8,pady=3)
        msv=tk.BooleanVar(value=self.cfg.get('multiple_sites_alert',True))
        tk.Radiobutton(fms,text='Yes',variable=msv,value=True, bg=GUI_BG).pack(side=tk.LEFT)
        tk.Radiobutton(fms,text='No', variable=msv,value=False,bg=GUI_BG).pack(side=tk.LEFT)
        # Autoplot 5 Sec. Alert
        fap=tk.LabelFrame(P,text='Autoplot 5 Sec. Alert',bg=GUI_BG,font=('Arial',8,'bold'))
        fap.pack(fill=tk.X,padx=8,pady=3)
        ap5v=tk.BooleanVar(value=self.cfg.get('ap_5s_alert',True))
        tk.Radiobutton(fap,text='Yes',variable=ap5v,value=True, bg=GUI_BG).pack(side=tk.LEFT)
        tk.Radiobutton(fap,text='No', variable=ap5v,value=False,bg=GUI_BG).pack(side=tk.LEFT)
        # Set Event Info
        fsei=tk.LabelFrame(P,text='Dream-Information in Set-Event Dialog',bg=GUI_BG,font=('Arial',8,'bold'))
        fsei.pack(fill=tk.X,padx=8,pady=3)
        seiv=tk.BooleanVar(value=self.cfg.get('set_event_info_shown',True))
        tk.Radiobutton(fsei,text='Show',variable=seiv,value=True, bg=GUI_BG).pack(side=tk.LEFT)
        tk.Radiobutton(fsei,text='Hide',variable=seiv,value=False,bg=GUI_BG).pack(side=tk.LEFT)

        # ── Start DReaM in Linux: X11 / xWayland / Wayland ─────────────────
        # Always visible, on every OS — deliberately NOT hidden on Windows
        # (per user decision 2026-07): on Windows/macOS/Linux-X11 this
        # setting simply has no effect, but showing it consistently avoids
        # the user having to guess why a setting might be missing.
        # Only actually applied at Dream start when running on Linux —
        # see _set_event() below.
        fxw = tk.LabelFrame(P, text='Start DReaM in Linux: X11 - xWayland - Wayland',
                             bg=GUI_BG, font=('Arial', 8, 'bold'))
        fxw.pack(fill=tk.X, padx=8, pady=3)
        dwv_initial = self.cfg.get('dream_display_mode', 'xwayland')
        if dwv_initial not in ('wayland',):
            dwv_initial = 'xwayland'   # legacy 'x11' values also map here
        dwv = tk.StringVar(value=dwv_initial)
        tk.Radiobutton(fxw, text='X11/xWayland', variable=dwv, value='xwayland',
                       bg=GUI_BG).pack(side=tk.LEFT, padx=6)
        tk.Radiobutton(fxw, text='Wayland', variable=dwv, value='wayland',
                       bg=GUI_BG).pack(side=tk.LEFT, padx=6)
        # Receiver Coordinates
        frc=tk.LabelFrame(P,text='Receiver Coordinates',bg=GUI_BG,font=('Arial',8,'bold'))
        frc.pack(fill=tk.X,padx=8,pady=3)
        lat_dv=tk.IntVar(value=self.cfg.get('rx_lat_deg',46))
        lat_mv=tk.StringVar(value=f"{self.cfg.get('rx_lat_min',57):02d}")
        lat_ns=tk.StringVar(value=self.cfg.get('rx_lat_ns','N'))
        lon_dv=tk.IntVar(value=self.cfg.get('rx_lon_deg',7))
        lon_mv=tk.StringVar(value=f"{self.cfg.get('rx_lon_min',26):02d}")
        lon_ew=tk.StringVar(value=self.cfg.get('rx_lon_ew','E'))
        # ── Validate: max 2 digits — Latitude degrees (max 90) and both
        # Minutes fields (max 59) all fit in 2 digits, same pattern
        # already used for the Timer-Events time fields elsewhere. ─────
        def _val_2dig_coord(val):
            return len(val) <= 2 and (val == '' or val.isdigit())
        vcmd_coord = (frc.register(_val_2dig_coord), '%P')

        # Aug 2026, user bug report: a Longitude DEGREE can be up to
        # 180 (e.g. New Zealand ≈ 174°E) — the 2-digit cap above was
        # silently truncating/rejecting the 3rd digit for any receiver
        # located roughly east of 99°E or west of 99°W, corrupting the
        # stored RX position (and every distance/azimuth calculated
        # from it) without any error message. Longitude degrees only —
        # Latitude degrees and both Minutes fields are intentionally
        # left at the 2-digit validator above, since 90/59 never need a
        # 3rd digit and a tighter limit there still helps prevent typos.
        def _val_3dig_lon_coord(val):
            return len(val) <= 3 and (val == '' or val.isdigit())
        vcmd_coord_lon = (frc.register(_val_3dig_lon_coord), '%P')

        def _select_all_on_focus(event):
            # Fires both on a manual click into the field AND when the
            # auto-tab logic below calls .focus_set() on it — either way,
            # the pre-filled old value (e.g. the original example
            # coordinates) is selected, so the very next keystroke
            # replaces it outright instead of being appended to it.
            event.widget.select_range(0, tk.END)
            event.widget.icursor(tk.END)

        for row,(lbl,dv,mv,hv,opts) in enumerate([('Latitude:', lat_dv,lat_mv,lat_ns,['N','S']),
                                                   ('Longitude:',lon_dv,lon_mv,lon_ew,['E','W'])]):
            tk.Label(frc,text=lbl,bg=GUI_BG,font=('Arial',8)).grid(row=row,column=0,sticky='w',padx=3)
            # Longitude degrees get the 3-digit validator (up to 180);
            # Latitude degrees keep the original 2-digit one (max 90).
            _is_lon_row = (lbl == 'Longitude:')
            e_deg = tk.Entry(frc,textvariable=dv,width=4,
                              validate='key',
                              validatecommand=(vcmd_coord_lon if _is_lon_row else vcmd_coord))
            e_deg.grid(row=row,column=1)
            e_deg.bind('<FocusIn>', _select_all_on_focus)
            tk.Label(frc,text='Deg.',bg=GUI_BG,font=('Arial',8)).grid(row=row,column=2)
            e_min = tk.Entry(frc,textvariable=mv,width=4,
                              validate='key', validatecommand=vcmd_coord)
            e_min.grid(row=row,column=3)
            e_min.bind('<FocusIn>', _select_all_on_focus)
            tk.Label(frc,text='Min.',bg=GUI_BG,font=('Arial',8)).grid(row=row,column=4)
            om = tk.OptionMenu(frc,hv,*opts)
            om.grid(row=row,column=5)
            def _make_autotab(src, dst, maxlen=2):
                def _check(event, s=src, d=dst, m=maxlen):
                    if len(s.get()) >= m:
                        d.focus_set()
                src.bind('<KeyRelease>', _check)
            # Aug 2026, user feedback round 2: Auto-tab REMOVED
            # specifically from the Longitude-degree field — waiting for
            # a 3rd digit before jumping felt awkward for the (common)
            # 2-digit case. User now Tabs/clicks to the Minutes field
            # manually for Longitude; Latitude degrees and both Minutes
            # fields keep their normal 2-digit auto-tab.
            if not _is_lon_row:
                _make_autotab(e_deg, e_min)
            _make_autotab(e_min, om)

        # ── Shared confirmation label — reused by all three 'Set' buttons
        # below, so the user always sees the same kind of feedback,
        # regardless of which field they just saved.
        setup_status_lbl = tk.Label(P, text='', bg=GUI_BG,
                                     font=('Arial',8,'italic'), fg='#007700')

        def set_coords():
            # Same fields/logic as the main 'OK' button already saves for
            # coordinates — extracted here so a user can confirm a save
            # immediately, without needing to understand that 'OK' also
            # saves everything and closes the whole dialog. Both paths
            # remain fully independent and safe to use in any order.
            try:
                lat_min_int = int(lat_mv.get() or 0)
                lon_min_int = int(lon_mv.get() or 0)
            except ValueError:
                setup_status_lbl.config(
                    text='Invalid minutes value — please enter numbers only.',
                    fg='#cc0000')
                return
            self.cfg.set('rx_lat_deg', lat_dv.get())
            self.cfg.set('rx_lat_min', lat_min_int)
            self.cfg.set('rx_lat_ns',  lat_ns.get())
            self.cfg.set('rx_lon_deg', lon_dv.get())
            self.cfg.set('rx_lon_min', lon_min_int)
            self.cfg.set('rx_lon_ew',  lon_ew.get())
            self.v_lat_disp.set(f"{lat_dv.get()}°{lat_min_int:02d}'{lat_ns.get()}")
            self.v_lon_disp.set(f"{lon_dv.get()}°{lon_min_int:02d}'{lon_ew.get()}")
            if self.sel_tx:
                self._apply_tx_site()
            self._replot()
            setup_status_lbl.config(text='Receiver coordinates saved.', fg='#007700')

        tk.Button(frc,text='Set',font=('Arial',9),width=5,bg='#aaddaa',
                  command=set_coords).grid(row=0,column=6,rowspan=2,padx=(8,3))

        fln=tk.LabelFrame(P,text='Location Name',bg=GUI_BG,font=('Arial',8,'bold'))
        fln.pack(fill=tk.X,padx=8,pady=3)
        loc_nv=tk.StringVar(value=self.cfg.get('location_name',''))

        def _limit_loc_name(*_):
            v = loc_nv.get()
            if len(v) > 16:
                loc_nv.set(v[:16])

        loc_nv.trace_add('write', _limit_loc_name)
        tk.Entry(fln,textvariable=loc_nv,width=18).pack(side=tk.LEFT,padx=5,pady=2)

        def set_location_name():
            name = loc_nv.get().strip()
            self.cfg.set('location_name', name)
            self.v_location.set(name if name else 'RX Location')
            setup_status_lbl.config(text='Location name saved.', fg='#007700')

        tk.Button(fln,text='Set',font=('Arial',9),width=5,bg='#aaddaa',
                  command=set_location_name).pack(side=tk.LEFT,padx=5)

        # Nickname
        fn=tk.LabelFrame(P,text='Nickname',bg=GUI_BG,font=('Arial',8,'bold'))
        fn.pack(fill=tk.X,padx=8,pady=3)
        nv=tk.StringVar(value=self.cfg.get('nickname','Nickname'))
        tk.Entry(fn,textvariable=nv,width=12).pack(side=tk.LEFT,padx=5)

        def set_nickname():
            # Verified: 'nickname' is only ever read fresh from cfg where
            # needed (screenshot filename generation) — no separate cached
            # display variable exists that would additionally need updating
            # here, unlike coordinates/location name above.
            self.cfg.set('nickname', nv.get())
            setup_status_lbl.config(text='Nickname saved.', fg='#007700')

        tk.Button(fn,text='Set',font=('Arial',9),width=5,bg='#aaddaa',
                  command=set_nickname).pack(side=tk.LEFT)

        setup_status_lbl.pack(fill=tk.X,padx=10,pady=(0,2))

        # Dream and Receiver-Configuration
        frxc=tk.LabelFrame(P,text='Dream and Receiver-Configuration',bg=GUI_BG,font=('Arial',8,'bold'))
        frxc.pack(fill=tk.X,padx=8,pady=3)
        tk.Button(frxc,text='DReaM Info',font=('Arial',9),bg='#dddddd',width=10,
                  command=self._show_dream_info_window).pack(side=tk.RIGHT,padx=5,pady=3)
        tk.Button(frxc,text='Setup',font=('Arial',9),bg='#dddddd',width=10,
                  command=self._open_rx_config).pack(side=tk.LEFT,padx=5,pady=3)
        tk.Label(frxc,text='Set Dream path and Transceiver settings',
                 bg=GUI_BG,font=('Arial',8),fg='#555555').pack(side=tk.LEFT,padx=5)
        # VERSION + OK/Cancel — always visible at bottom of dialog (outside scroll)
        tk.Label(dlg,text=VERSION,bg=GUI_BG,
                 font=('Arial',7,'italic'),fg='#555').pack(pady=2)

        def ok():
            self.cfg.set('unit',uv.get()); self.cfg.set('plot_bg',bgv.get()); self.cfg.set('frame_bg',frv.get())
            self.cfg.set('screenshot_alerts',sav.get()); self.cfg.set('multiple_sites_alert',msv.get())
            self.cfg.set('ap_5s_alert', ap5v.get())
            self.cfg.set('set_event_info_shown', seiv.get())
            if dwv is not None:
                self.cfg.set('dream_display_mode', dwv.get())
            lat_min_int = int(lat_mv.get() or 0)
            lon_min_int = int(lon_mv.get() or 0)
            self.cfg.set('rx_lat_deg', lat_dv.get())
            self.cfg.set('rx_lat_min', lat_min_int)
            self.cfg.set('rx_lat_ns',  lat_ns.get())
            self.cfg.set('rx_lon_deg', lon_dv.get())
            self.cfg.set('rx_lon_min', lon_min_int)
            self.cfg.set('rx_lon_ew',  lon_ew.get())
            self.cfg.set('location_name', loc_nv.get())
            self.v_lat_disp.set(f"{lat_dv.get()}°{lat_min_int:02d}'{lat_ns.get()}")
            self.v_lon_disp.set(f"{lon_dv.get()}°{lon_min_int:02d}'{lon_ew.get()}")
            loc_name = loc_nv.get().strip()
            if loc_name:
                self.v_location.set(loc_name)
            if self.sel_tx:
                self._apply_tx_site()
            self._replot()
            canvas.unbind_all('<MouseWheel>')
            canvas.unbind_all('<Button-4>')
            canvas.unbind_all('<Button-5>')
            dlg.destroy()

        br=tk.Frame(dlg,bg=GUI_BG); br.pack(pady=6)
        tk.Button(br,text='OK',    command=ok,          width=8).pack(side=tk.LEFT,padx=5)
        tk.Button(br,text='Cancel',command=_on_close,   width=8).pack(side=tk.LEFT,padx=5)

    # ─────────────────────────────────────────────────
    # STUB ACTIONS
    # ─────────────────────────────────────────────────
    def _publish(self):
        """
        Publish / Web Links dialog.
        Shows up to 5 configurable web links.
        First link is always the DRM Forum (default, can be changed).
        One click opens the link in the default browser.
        Links are saved in drmplotter_cfg.json.
        """
        import webbrowser

        # Load saved links (default: DRM Forum as first entry)
        links = self.cfg.get('web_links',
                    ['https://www.drmrx.org/forum/', '', '', '', ''])
        # Ensure always 5 slots
        while len(links) < 5:
            links.append('')

        dlg = tk.Toplevel(self.root)
        dlg.title('Publish — Web Links')
        dlg.configure(bg=GUI_BG)
        dlg.resizable(False, False)
        center_dialog(dlg, self.root, 490, 330)
        dlg.grab_set()
        dlg.transient(self.root)   # v_rig_test_06: keep dialog above its parent
        dlg.lift()
        dlg.focus_force()

        tk.Label(dlg, text='Web Links — click to open in browser',
                 bg=GUI_BG, font=('Arial', 11, 'bold')).pack(pady=(10, 4))
        tk.Label(dlg, text='Link 1 is the default (DRM Forum). You can change any link.',
                 bg=GUI_BG, font=('Arial', 9), fg='#555555').pack(pady=(0, 6))

        # Entry fields for each link
        entries = []
        form = tk.Frame(dlg, bg=GUI_BG)
        form.pack(fill=tk.X, padx=12)

        for i in range(5):
            row = tk.Frame(form, bg=GUI_BG)
            row.pack(fill=tk.X, pady=3)
            lbl_text = f'Link {i+1}{"  (default)" if i==0 else ""}:'
            tk.Label(row, text=lbl_text, bg=GUI_BG,
                     font=('Arial', 10), width=16, anchor='w').pack(side=tk.LEFT)
            e = tk.Entry(row, font=('Arial', 10), width=30)
            e.insert(0, links[i])
            e.pack(side=tk.LEFT, padx=(0, 4))
            # Open button
            def make_open(idx):
                def open_link():
                    url = entries[idx].get().strip()
                    if url:
                        try:
                            webbrowser.open(url)
                        except Exception as ex:
                            messagebox.showerror('Error', str(ex))
                    else:
                        messagebox.showwarning('No Link',
                            f'Link {idx+1} is empty.')
                return open_link
            tk.Button(row, text='Open', font=('Arial', 10), width=6,
                      bg='#aaddff', command=make_open(i)).pack(side=tk.LEFT)
            entries.append(e)

        # Bottom buttons
        sep = ttk.Separator(dlg, orient='horizontal')
        sep.pack(fill=tk.X, padx=12, pady=8)
        btn_row = tk.Frame(dlg, bg=GUI_BG)
        btn_row.pack(pady=(0, 10))

        def save_links():
            new_links = [e.get().strip() for e in entries]
            self.cfg.set('web_links', new_links)
            messagebox.showinfo('Saved', 'Links saved.')

        tk.Button(btn_row, text='Save Links', font=('Arial', 9),
                  bg='#aaddaa', width=10,
                  command=save_links).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_row, text='Close',      font=('Arial', 9),
                  width=8,
                  command=dlg.destroy).pack(side=tk.LEFT, padx=5)

    def _add_text(self):
        if not self.plot_rows:
            messagebox.showwarning('Add Text', 'Load a log first.')
            return

        t0_raw = self.plot_rows[0].get('TIME', '?')
        t1_raw = self.plot_rows[-1].get('TIME', '?')
        t0_hm  = t0_raw[:5] if len(t0_raw) >= 5 else t0_raw
        t1_hm  = t1_raw[:5] if len(t1_raw) >= 5 else t1_raw

        dlg = tk.Toplevel(self.root)
        dlg.title('Add Comments')
        dlg.configure(bg=GUI_BG)
        dlg.resizable(False, False)
        _saved_ac_geom = self.cfg.get('add_comments_geometry', '')
        if _saved_ac_geom:
            try:
                dlg.geometry(_saved_ac_geom)
            except Exception:
                center_dialog(dlg, self.root, 680, 400)
        else:
            center_dialog(dlg, self.root, 680, 400)

        def _save_ac_geometry(event=None):
            # Live while dragging, same as the DRM-Radio-List and Help
            # windows — the dialog's size never actually changes (fixed,
            # not resizable), but the drag POSITION does, and that's what
            # this persists. Only reacts to events on dlg itself, not on
            # any child widget bubbling one up.
            if event is not None and event.widget is not dlg:
                return
            try:
                self.cfg.set('add_comments_geometry', dlg.geometry())
            except Exception:
                pass
        dlg.bind('<Configure>', _save_ac_geometry, add='+')

        # ── Buttons FIRST at BOTTOM ───────────────────────────────────
        br = tk.Frame(dlg, bg=GUI_BG)
        br.pack(side=tk.BOTTOM, pady=8)
        take_btn    = tk.Button(br, text='Take Text', font=('Arial',9,'bold'),
                                bg='#aaddaa', width=11)
        clear_btn   = tk.Button(br, text='Clear All', font=('Arial',9), width=8)
        close_btn   = tk.Button(br, text='Close',     font=('Arial',9), width=8,
                                command=dlg.destroy)
        for b in [take_btn, clear_btn, close_btn]:
            b.pack(side=tk.LEFT, padx=5)

        # ── Header ───────────────────────────────────────────────────
        tk.Label(dlg,
                 text=f'Time span:  {t0_hm}  until  {t1_hm}        Comment (Max. 40 Characters)',
                 bg=GUI_BG, font=('Arial', 9)).pack(padx=8, pady=(8,2))

        # ── Column headers ────────────────────────────────────────────
        hdr = tk.Frame(dlg, bg=GUI_BG)
        hdr.pack(fill=tk.X, padx=10)
        tk.Label(hdr, text='#',            bg=GUI_BG, font=('Arial',9,'bold'), width=2 ).pack(side=tk.LEFT)
        tk.Label(hdr, text='Time (HHMM)',  bg=GUI_BG, font=('Arial',9,'bold'), width=10).pack(side=tk.LEFT)
        tk.Label(hdr, text='Comment text', bg=GUI_BG, font=('Arial',9,'bold'), width=30).pack(side=tk.LEFT)
        tk.Label(hdr, text='Pos %',        bg=GUI_BG, font=('Arial',9,'bold'), width=6 ).pack(side=tk.LEFT)
        tk.Label(hdr, text='Clear',        bg=GUI_BG, font=('Arial',9,'bold'), width=5 ).pack(side=tk.LEFT)

        # ── 6 comment rows ────────────────────────────────────────────
        time_entries = []
        text_entries = []
        pos_vars     = []

        # Validate: max 4 digits only (HHMM format)
        def _val_4dig(val):
            return len(val) <= 4 and (val == '' or val.isdigit())
        vcmd4 = (dlg.register(_val_4dig), '%P')

        # Auto-tab: jump from time entry to comment entry after 4 digits
        def make_autotab(time_var, text_e):
            def _cb(*_):
                if len(time_var.get()) == 4:
                    text_e.focus_set()
                    text_e.icursor(tk.END)
            return _cb

        for i in range(6):
            row = tk.Frame(dlg, bg=GUI_BG)
            row.pack(fill=tk.X, padx=10, pady=1)
            tk.Label(row, text=str(i+1), bg=GUI_BG, width=2, font=('Arial',9)).pack(side=tk.LEFT)
            te_var = tk.StringVar()
            te = tk.Entry(row, textvariable=te_var, width=5,
                          font=('Arial',9), validate='key',
                          validatecommand=vcmd4)
            te.pack(side=tk.LEFT, padx=2)
            ce = tk.Entry(row, width=30, font=('Arial',9)); ce.pack(side=tk.LEFT, padx=2)
            # Auto-tab: after 4 digits jump to comment field
            te_var.trace_add('write', make_autotab(te_var, ce))
            # Spinbox: 10..90 in steps of 5, default 50 = middle
            pv = tk.StringVar(value='50')
            sb = tk.Spinbox(row, from_=10, to=90, increment=5,
                            textvariable=pv, width=4,
                            font=('Arial',9), justify='center',
                            command=lambda: transfer_to_plot())
            sb.pack(side=tk.LEFT, padx=2)
            def make_clear(t, c, p):
                def do(): t.delete(0,tk.END); c.delete(0,tk.END); p.set('50')
                return do
            tk.Button(row, text='X', width=3, font=('Arial',8),
                      command=make_clear(te, ce, pv)).pack(side=tk.LEFT, padx=2)
            time_entries.append(te)
            text_entries.append(ce)
            pos_vars.append(pv)

        # ── Pre-fill entries from saved annotations ────────────────────
        for i, ann in enumerate(self._annotations[:6]):
            time_entries[i].insert(0, ann.get('time', ''))
            text_entries[i].insert(0, ann.get('text', ''))
            pos_vars[i].set(str(ann.get('pos', 50)))

        # ── Row 7: free comment + position navigator ──────────────────
        fr7 = tk.Frame(dlg, bg=GUI_BG)
        fr7.pack(fill=tk.X, padx=10, pady=(4,0))
        tk.Label(fr7, text='7  Free comment (no time):',
                 bg=GUI_BG, font=('Arial',9)).pack(side=tk.LEFT)
        free_entry = tk.Entry(fr7, width=32, font=('Arial',9))
        free_entry.pack(side=tk.LEFT, padx=4)
        # Pre-fill free comment
        if self._annotation_free:
            free_entry.insert(0, self._annotation_free)

        # Position navigator — arrows shift free comment x/y by 0.05
        if not hasattr(self, '_free_x'): self._free_x = 0.50
        if not hasattr(self, '_free_y'): self._free_y = 0.50
        free_x_var = tk.DoubleVar(value=self._free_x)
        free_y_var = tk.DoubleVar(value=self._free_y)

        nav = tk.Frame(fr7, bg=GUI_BG)
        nav.pack(side=tk.LEFT, padx=(4,0))

        pos_lbl_var = tk.StringVar(
            value=f'x:{self._free_x:.2f} y:{self._free_y:.2f}')

        def move(dx, dy):
            self._free_x = round(max(0.0, min(1.0, self._free_x + dx)), 2)
            self._free_y = round(max(0.0, min(1.0, self._free_y + dy)), 2)
            free_x_var.set(self._free_x)
            free_y_var.set(self._free_y)
            pos_lbl_var.set(f'x:{self._free_x:.2f} y:{self._free_y:.2f}')
            transfer_to_plot()

        STEP = 0.05
        # Top row: ▲
        nav_top = tk.Frame(nav, bg=GUI_BG)
        nav_top.pack()
        tk.Button(nav_top, text='▲', width=2, font=('Arial',8),
                  command=lambda: move(0, +STEP)).pack()
        # Middle row: ◄  pos_label  ►
        nav_mid = tk.Frame(nav, bg=GUI_BG)
        nav_mid.pack()
        tk.Button(nav_mid, text='◄', width=2, font=('Arial',8),
                  command=lambda: move(-STEP, 0)).pack(side=tk.LEFT)
        tk.Label(nav_mid, textvariable=pos_lbl_var, bg=GUI_BG,
                 font=('Arial',7), width=12).pack(side=tk.LEFT)
        tk.Button(nav_mid, text='►', width=2, font=('Arial',8),
                  command=lambda: move(+STEP, 0)).pack(side=tk.LEFT)
        # Bottom row: ▼
        nav_bot = tk.Frame(nav, bg=GUI_BG)
        nav_bot.pack()
        tk.Button(nav_bot, text='▼', width=2, font=('Arial',8),
                  command=lambda: move(0, -STEP)).pack()
        # Reset button
        tk.Button(nav, text='⌂', width=2, font=('Arial',8),
                  command=lambda: (move(0.50-self._free_x,
                                        0.50-self._free_y))).pack(pady=(1,0))

        # ── Show Vertical Lines checkbox ──────────────────────────────
        show_vlines_var = tk.IntVar(value=1)
        ck_row = tk.Frame(dlg, bg=GUI_BG)
        ck_row.pack(fill=tk.X, padx=12, pady=(4,0))
        tk.Checkbutton(ck_row, text='Show Vertical Lines',
                       variable=show_vlines_var, bg=GUI_BG,
                       font=('Arial',9)).pack(side=tk.LEFT)

        # ── Functions ─────────────────────────────────────────────────
        def transfer_to_plot():
            """Transfer current dialog content to plot — dialog stays open."""
            annotations = []
            for i in range(6):
                t_str = time_entries[i].get().strip().replace(':','')
                c_str = text_entries[i].get().strip()
                try:
                    pos = max(10, min(90, int(pos_vars[i].get())))
                except ValueError:
                    pos = 50
                if c_str:
                    annotations.append({'time':t_str,'text':c_str[:40],'pos':pos})
            self._annotations     = annotations
            self._annotation_free = free_entry.get().strip()
            self._show_vlines     = bool(show_vlines_var.get())
            self._replot()
            # Dialog stays open — text remains for further editing

        def clear_all():
            """Clear all entries and remove annotations from plot."""
            for te, ce, pv in zip(time_entries, text_entries, pos_vars):
                te.delete(0, tk.END); ce.delete(0, tk.END); pv.set('50')
            free_entry.delete(0, tk.END)
            self._annotations     = []
            self._annotation_free = ''
            self._replot()

        # Take Text = transfer without closing
        # Refresh   = same as Take Text (re-transfer after editing)
        take_btn.config(command=transfer_to_plot)
        clear_btn.config(command=clear_all)

    def _about(self):
        """About window — shows program info, text and PNG images."""
        win = tk.Toplevel(self.root)
        win.title('About  DRM-Log Plotter rebuild')
        win.configure(bg=GUI_BG)
        win.resizable(True, True)
        center_dialog(win, self.root, 560, 680)

        # Scrollable content area
        frame = tk.Frame(win, bg=GUI_BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        canvas = tk.Canvas(frame, bg=GUI_BG, highlightthickness=0)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg=GUI_BG)
        canvas_window = canvas.create_window((0, 0), window=inner, anchor='nw')

        def _on_resize(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind('<Configure>', _on_resize)

        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox('all'))
        inner.bind('<Configure>', _on_frame_configure)

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), 'units')
        canvas.bind_all('<MouseWheel>', _on_mousewheel)

        # ── Helper to add text ────────────────────────────────────────
        self._about_images = []   # keep refs so images are not garbage collected

        def add_text(text, font=('Arial', 10), fg='#000000', pady=4):
            tk.Label(inner, text=text, bg=GUI_BG, font=font,
                     fg=fg, justify=tk.LEFT, wraplength=520,
                     anchor='w').pack(fill=tk.X, padx=10, pady=pady)

        def add_image(path):  # pylint: disable=unused-variable
            """Add a PNG image to the About window."""
            try:
                from PIL import Image, ImageTk
                img = Image.open(path)
                # Scale down if wider than 520px
                max_w = 520
                if img.width > max_w:
                    ratio = max_w / img.width
                    img = img.resize((max_w, int(img.height * ratio)),
                                     Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self._about_images.append(photo)
                tk.Label(inner, image=photo, bg=GUI_BG).pack(pady=6)
            except Exception as e:
                tk.Label(inner, text=f'[Image: {path} — {e}]',
                         bg=GUI_BG, fg='#888888',
                         font=('Arial', 8)).pack(pady=2)

        # ── Content — text will be added here ────────────────────────
        add_text('DRM-Log Plotter rebuild',
                 font=('Arial', 14, 'bold'), fg='#000080')
        add_text('Code Base: 100% rebuild by CLAUDE.AI',
                 font=('Arial', 9, 'italic'), fg='#555555')
        add_text('Original concept from Terje Isberg',
                 font=('Arial', 9, 'italic'), fg='#555555', pady=1)

        ttk.Separator(inner, orient='horizontal').pack(
            fill=tk.X, padx=10, pady=8)

        add_text('Original Project from 2007 to 2022',
                 font=('Arial', 10, 'bold'), fg='#000080')
        add_text('This rebuild is intended as a tribute to Terje Isberg.',
                 font=('Arial', 10), fg='#333333', pady=2)

        ttk.Separator(inner, orient='horizontal').pack(
            fill=tk.X, padx=10, pady=6)

        add_text('Original thanks to:',
                 font=('Arial', 10, 'bold'), fg='#000080')
        add_text(
            'Andreas, Brendan, Christopher, Friedrich, Heinrich, Ludo, John M., '
            'Neil, Pete, Simone, Sixten, Stephan, Zyg who either found bugs or '
            'provided many new ideas.  Special thanks to Andreas, who helped a lot '
            'with the final layout, to Norbert, who kindly provided his code for '
            'the Azimuth calculation and to H.C. Liu who came up with the Twitter '
            'option idea.',
            font=('Arial', 10), fg='#333333', pady=2)

        add_text('— Terje Isberg',
                 font=('Arial', 10, 'italic'), fg='#555555', pady=4)

        ttk.Separator(inner, orient='horizontal').pack(
            fill=tk.X, padx=10, pady=8)

        add_text('The new project was initiated by Andy, DL9MDV.',
                 font=('Arial', 10), fg='#333333', pady=2)
        add_text('Thanks to:',
                 font=('Arial', 10, 'bold'), fg='#000080')
        add_text('DRM-RX-Forum Member Per for the DRM-Radio-List idea, '
                 'good tips,\nand help with the tests.',
                 font=('Arial', 10), fg='#333333', pady=2)
        add_text('This project also demonstrates the incredible possibilities of CLAUDE.ai.',
                 font=('Arial', 10), fg='#333333', pady=2)

        ttk.Separator(inner, orient='horizontal').pack(
            fill=tk.X, padx=10, pady=8)

        add_text('Mistakes can happen.',
                 font=('Arial', 10, 'italic'), fg='#555555', pady=1)
        add_text('You use this code at your own risk.',
                 font=('Arial', 10, 'italic'), fg='#555555', pady=1)

        # ── Legal Notice reset ───────────────────────────────────────
        ttk.Separator(inner, orient='horizontal').pack(
            fill=tk.X, padx=10, pady=8)

        def reset_legal():
            self.cfg.set('skip_legal', False)
            messagebox.showinfo('Legal Notice',
                'The Legal Notice will be shown again at the next program start.')

        tk.Button(inner, text='Show Legal Notice again at next start',
                  font=('Arial', 9), fg='#000080',
                  command=reset_legal).pack(pady=(2, 6))

        def reset_welcome():
            self.cfg.set('skip_welcome', False)
            messagebox.showinfo('Welcome Window',
                'The Welcome window will be shown again at the next program start.')

        tk.Button(inner, text='Show Welcome Window again at next start',
                  font=('Arial', 9), fg='#000080',
                  command=reset_welcome).pack(pady=(2, 6))

        # ── Close button ─────────────────────────────────────────────
        tk.Button(win, text='Close', font=('Arial', 10),
                  width=10, command=win.destroy).pack(pady=8)

    def _show_help(self):
        """
        Show help text.
        Loads drmlogplotter_help.txt — searches the AppImage's own folder
        first when running as an AppImage (BASE_DIR points to the writable
        ~/.local/share/drm_log_plotter/ data folder in that case, NOT the
        folder the .AppImage file itself sits in — same class of issue
        already fixed once for the Audio helper lookup), then falls back
        to BASE_DIR (correct as-is for .py, .exe, and plain .bin).
        Shows a clear "place file here" hint, with the correct folder,
        when the file is not found anywhere.
        """
        _appimage_path = os.environ.get('APPIMAGE', '').strip()
        if _appimage_path:
            search_dir = os.path.dirname(os.path.abspath(_appimage_path))
        else:
            search_dir = BASE_DIR

        help_file   = os.path.join(search_dir, 'drmlogplotter_help.txt')
        help_source = ''

        if os.path.exists(help_file):
            try:
                content = _read_file_robust(help_file)
                help_source = '  [loaded from: drmlogplotter_help.txt]'
            except Exception:
                content = (
                    "Could not read drmlogplotter_help.txt.\n"
                    "Please check the file and try again."
                )
                help_source = '  [error reading help file]'
        else:
            content = (
                "Help file not found.\n\n"
                "Please place  drmlogplotter_help.txt  in the same folder "
                "as this program's executable file:\n\n"
                f"  {search_dir}"
            )
            help_source = '  [help file not found]'

        # Centre on main window
        w, h = 660, 540

        dlg = tk.Toplevel(self.root)
        dlg.title('DRM-Log Plotter – Help')
        dlg.configure(bg=GUI_BG)
        _saved_help_geom = self.cfg.get('help_window_geometry', '')
        if _saved_help_geom:
            try:
                dlg.geometry(_saved_help_geom)
            except Exception:
                center_dialog(dlg, self.root, w, h)
        else:
            center_dialog(dlg, self.root, w, h)

        def _save_help_geometry(event=None):
            # Live while dragging/resizing, same as the DRM-Radio-List
            # window — only reacts to events on dlg itself, not on any
            # child widget bubbling one up.
            if event is not None and event.widget is not dlg:
                return
            try:
                self.cfg.set('help_window_geometry', dlg.geometry())
            except Exception:
                pass
        dlg.bind('<Configure>', _save_help_geometry, add='+')
        # v_rig_test_08: Help stays visible while the user configures other
        # dialogs (e.g. Setup) at the same time — intentionally NOT modal
        # (no grab_set(), other windows stay fully clickable/usable), but
        # kept always-on-top so it never gets buried behind the main
        # window when the user clicks something else. Purely visual —
        # doesn't affect focus or functionality of any other window.
        dlg.attributes('-topmost', True)
        dlg.lift()
        dlg.focus_force()

        # Source info label
        tk.Label(dlg, text=help_source, bg=GUI_BG,
                 font=('Arial', 8, 'italic'), fg='#666666').pack(anchor='w', padx=6)

        # Text area with scrollbar
        frame = tk.Frame(dlg, bg=GUI_BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(2,5))
        txt = tk.Text(frame, font=('Courier', 11), wrap=tk.WORD,
                      bg='white', bd=0, relief=tk.FLAT)
        sb  = ttk.Scrollbar(frame, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(fill=tk.BOTH, expand=True)
        txt.insert('1.0', content)
        txt.configure(state=tk.DISABLED)

        # Mouse wheel
        txt.bind('<MouseWheel>', lambda e: txt.yview_scroll(int(-1*(e.delta/120)), 'units'))

        tk.Button(dlg, text='Close', font=('Arial',9), width=10,
                  command=dlg.destroy).pack(pady=6)

    def _resolve_dream_ini_path(self):
        """
        Resolve the actual Dream.ini file to read/write — single source of
        truth used by every part of the code that touches Dream.ini
        (start-up enablelog/delay write, LED-4 log status check, and the
        enablelog/delay reset on Stop Dream).

        Different Dream builds keep Dream.ini in different places:
          - Windows and some Linux builds: same folder as the executable.
          - Many Linux/Qt-based builds (confirmed by testing): the user's
            home directory, independent of where the binary itself lives.

        Priority:
          1. Explicit override in 'dream_ini_path' (set via "Set" or
             "Save & Close" in RX Config → Dream.ini location) — used
             as-is if the file still exists.
          2. Same folder as the Dream executable ('dream_path').
          3. The user's home directory.

        Returns the full file path if found, otherwise None.
        """
        configured = self.cfg.get('dream_ini_path', '').strip()
        if configured and os.path.isfile(configured):
            return configured

        dream_path = self.cfg.get('dream_path', '').strip()
        if dream_path:
            candidate = os.path.join(
                os.path.dirname(os.path.abspath(dream_path)), 'Dream.ini')
            if os.path.isfile(candidate):
                return candidate

        home_candidate = os.path.join(os.path.expanduser('~'), 'Dream.ini')
        if os.path.isfile(home_candidate):
            return home_candidate

        return None

    def _open_rx_config(self):
        """
        RX Config dialog — stores Dream path + Transceiver settings
        persistently in config. Opened via [RX Config] button in Set Event.
        """
        import subprocess, platform

        rx_dlg = tk.Toplevel(self.root)
        rx_dlg.title('Dream and Receiver Configuration')
        rx_dlg.configure(bg=GUI_BG)
        # Resizable now (V02) — the dialog also scrolls (see below), so it
        # stays fully usable even on smaller screens / smaller Thonny windows.
        rx_dlg.resizable(True, True)
        _saved_rxcfg_geom = self.cfg.get('rx_config_geometry', '')
        if _saved_rxcfg_geom:
            try:
                rx_dlg.geometry(_saved_rxcfg_geom)
            except Exception:
                center_dialog(rx_dlg, self.root, 760, 830)
        else:
            center_dialog(rx_dlg, self.root, 760, 830)
        rx_dlg.minsize(600, 450)
        rx_dlg.grab_set()
        rx_dlg.transient(self.root)   # v_rig_test_06: keep dialog above its parent
        rx_dlg.lift()
        rx_dlg.focus_force()

        def _save_rxcfg_geometry(event=None):
            if event is not None and event.widget is not rx_dlg:
                return
            try:
                self.cfg.set('rx_config_geometry', rx_dlg.geometry())
            except Exception:
                pass
        rx_dlg.bind('<Configure>', _save_rxcfg_geometry, add='+')

        # ── Scrollable content area ─────────────────────────────────────
        # V02 fix: the dialog grew taller with the new Serial Port
        # Parameters block and no longer reliably fits every screen /
        # window size. All content frames (fl, fr, ft, fn, rx_status)
        # now live inside 'rx_scroll_frame', which sits in a Canvas with
        # a vertical Scrollbar. Save & Close / Cancel stay pinned to the
        # bottom of the dialog, outside the scroll area, always visible.
        rx_canvas = tk.Canvas(rx_dlg, bg=GUI_BG, highlightthickness=0)
        rx_scrollbar = tk.Scrollbar(rx_dlg, orient='vertical',
                                    command=rx_canvas.yview)
        rx_canvas.configure(yscrollcommand=rx_scrollbar.set)

        rx_scroll_frame = tk.Frame(rx_canvas, bg=GUI_BG)
        rx_canvas_window = rx_canvas.create_window(
            (0, 0), window=rx_scroll_frame, anchor='nw')

        def _rx_on_frame_configure(event=None):
            rx_canvas.configure(scrollregion=rx_canvas.bbox('all'))
        rx_scroll_frame.bind('<Configure>', _rx_on_frame_configure)

        def _rx_on_canvas_configure(event):
            # Keep the inner frame exactly as wide as the canvas —
            # avoids an unwanted horizontal scrollbar.
            rx_canvas.itemconfig(rx_canvas_window, width=event.width)
        rx_canvas.bind('<Configure>', _rx_on_canvas_configure)

        def _rx_on_mousewheel(event):
            if platform.system() == 'Linux':
                delta = -1 if event.num == 4 else 1
            else:
                delta = -1 if event.delta > 0 else 1
            rx_canvas.yview_scroll(delta, 'units')
        # Bind wheel scrolling only while the pointer is over the dialog —
        # avoids hijacking scroll events elsewhere in the app.
        def _rx_bind_wheel(_e=None):
            rx_canvas.bind_all('<MouseWheel>', _rx_on_mousewheel)   # Windows/macOS
            rx_canvas.bind_all('<Button-4>', _rx_on_mousewheel)     # Linux up
            rx_canvas.bind_all('<Button-5>', _rx_on_mousewheel)     # Linux down
        def _rx_unbind_wheel(_e=None):
            rx_canvas.unbind_all('<MouseWheel>')
            rx_canvas.unbind_all('<Button-4>')
            rx_canvas.unbind_all('<Button-5>')
        rx_canvas.bind('<Enter>', _rx_bind_wheel)
        rx_canvas.bind('<Leave>', _rx_unbind_wheel)

        # ── Dream Location ────────────────────────────────────────────
        fl = tk.LabelFrame(rx_scroll_frame, text='Dream Location', bg=GUI_BG,
                           font=('Arial',9,'bold'), padx=6, pady=4)
        # fl packed at end in correct order

        if platform.system() == 'Windows':
            default_dream = self.cfg.get('dream_path', r'C:\Dream\Dream.exe')
        else:
            default_dream = self.cfg.get('dream_path', '/usr/local/bin/dream')

        path_var = tk.StringVar(value=default_dream)
        path_row = tk.Frame(fl, bg=GUI_BG)
        path_row.pack(fill=tk.X)
        tk.Label(path_row, text='Dream path:', bg=GUI_BG,
                 font=('Arial',11), width=16, anchor='w').pack(side=tk.LEFT)
        tk.Entry(path_row, textvariable=path_var,
                 font=('Arial',11), width=30).pack(side=tk.LEFT, padx=(2,4))

        # ── Dream Log File Path ───────────────────────────────────────
        # Folder where Dream writes DreamLog.txt and DreamLogLong.csv.
        # Windows: same folder as Dream.exe (leave blank = auto-derive).
        # Linux:   may differ from the Dream binary folder (e.g. ~/.dream or ~/)
        logpath_row = tk.Frame(fl, bg=GUI_BG)
        logpath_row.pack(fill=tk.X, pady=(4,0))
        tk.Label(logpath_row, text='Log file path:', bg=GUI_BG,
                 font=('Arial',11), width=16, anchor='w').pack(side=tk.LEFT)
        logpath_var = tk.StringVar(value=self.cfg.get('dream_log_path', ''))
        tk.Entry(logpath_row, textvariable=logpath_var,
                 font=('Arial',11), width=30).pack(side=tk.LEFT, padx=(2,4))

        def browse_logpath():
            folder = filedialog.askdirectory(
                parent=rx_dlg,
                title='Select folder where Dream writes DreamLog.txt',
                initialdir=logpath_var.get() or os.path.expanduser('~'))
            if folder:
                logpath_var.set(os.path.normpath(folder))

        def take_logpath():
            p = logpath_var.get().strip()
            if p and not os.path.isdir(p):
                status_lbl.config(text=f'Folder not found: {p}', fg='#cc0000')
                return
            self.cfg.set('dream_log_path', os.path.normpath(p) if p else '')
            status_lbl.config(
                text=f'Log file path saved: {p}' if p else
                     'Log file path cleared — will auto-derive.',
                fg='#007700')

        tk.Button(logpath_row, text='Browse', font=('Arial',10),
                  command=browse_logpath).pack(side=tk.LEFT, padx=(0,4))
        tk.Button(logpath_row, text='Set', font=('Arial',9), width=5,
                  bg='#aaddaa', command=take_logpath).pack(side=tk.LEFT)

        tk.Label(fl, text='Leave "Log file path" blank to use the same folder as Dream.exe  '
                           '(Windows default).\nOn Linux set this to the folder where '
                           'Dream writes its log files (e.g.  /home/user/dream-logs ).',
                 bg=GUI_BG, font=('Arial',8), fg='#555555',
                 justify=tk.LEFT).pack(anchor='w', padx=2, pady=(2,2))

        status_lbl = tk.Label(rx_scroll_frame, text='', bg=GUI_BG,
                              font=('Arial',9,'italic'), fg='#007700')
        status_lbl.pack(pady=(2,0))

        # ── Browse — manual Dream.exe lookup (Variante B: Browse + Set) ──
        # "Set" saves the path to config immediately (same two-step
        # pattern as the "Hamlib / rigctl path" Browse+Set further below),
        # so the user does not have to close the whole RX Config dialog
        # via "Save & Close" first before the new Dream path becomes active.
        _dream_browse_result = [None]

        def browse_dream():
            if platform.system() == 'Windows':
                ftypes = [('Dream executable', 'Dream.exe'),
                          ('Executable', '*.exe'), ('All files', '*.*')]
            else:
                ftypes = [('All files', '*')]
            p = filedialog.askopenfilename(
                parent=rx_dlg,
                title='Select Dream executable',
                initialdir=os.path.dirname(path_var.get().strip())
                           if path_var.get().strip() else os.path.expanduser('~'),
                filetypes=ftypes)
            if p:
                p = os.path.normpath(p)
                path_var.set(p)
                _dream_browse_result[0] = p
                status_lbl.config(
                    text=f'Selected: {p}  —  click "Set" to save.',
                    fg='#0000aa')

        def take_dream():
            p = path_var.get().strip()
            if not p:
                status_lbl.config(text='No path selected — please use "Browse" first.',
                                  fg='#cc6600')
                return
            if not os.path.isfile(p):
                status_lbl.config(text=f'File not found: {p}', fg='#cc0000')
                return
            self.cfg.set('dream_path', os.path.normpath(p))
            _dream_browse_result[0] = None
            status_lbl.config(text=f'Dream path saved: {p}', fg='#007700')

        tk.Button(path_row, text='Browse', font=('Arial',10),
                  command=browse_dream).pack(side=tk.LEFT, padx=(0,4))
        tk.Button(path_row, text='Set', font=('Arial',9), width=5,
                  bg='#aaddaa', command=take_dream).pack(side=tk.LEFT)

        # ── Dream.ini location ──────────────────────────────────────────
        # Some Dream builds keep Dream.ini next to the executable (Windows
        # default, some Linux builds). Others — confirmed on Linux — write
        # it to the user's home directory instead, independent of where
        # the binary lives. This field lets the user override the location
        # explicitly when auto-detection (program folder → home directory)
        # picks the wrong one, e.g. a leftover/stray Dream.ini from an
        # earlier experiment sitting in the program folder.
        ini_row = tk.Frame(fl, bg=GUI_BG)
        ini_row.pack(fill=tk.X, pady=(4,0))
        tk.Label(ini_row, text='Dream.ini location:', bg=GUI_BG,
                 font=('Arial',11), width=16, anchor='w').pack(side=tk.LEFT)
        ini_path_var = tk.StringVar(value=self.cfg.get('dream_ini_path', ''))
        tk.Entry(ini_row, textvariable=ini_path_var,
                 font=('Arial',11), width=30).pack(side=tk.LEFT, padx=(2,4))

        def browse_ini():
            p = filedialog.askopenfilename(
                parent=rx_dlg,
                title='Select Dream.ini',
                initialdir=os.path.dirname(ini_path_var.get().strip())
                           if ini_path_var.get().strip() else os.path.expanduser('~'),
                filetypes=[('Dream.ini', 'Dream.ini'), ('All files', '*.*')])
            if p:
                p = os.path.normpath(p)
                ini_path_var.set(p)
                status_lbl.config(
                    text=f'Selected: {p}  —  click "Set" to save.',
                    fg='#0000aa')

        def take_ini():
            p = ini_path_var.get().strip()
            if not p:
                status_lbl.config(text='No path selected — please use "Browse" first.',
                                  fg='#cc6600')
                return
            if not os.path.isfile(p):
                status_lbl.config(text=f'File not found: {p}', fg='#cc0000')
                return
            self.cfg.set('dream_ini_path', os.path.normpath(p))
            status_lbl.config(text=f'Dream.ini location saved: {p}', fg='#007700')

        tk.Button(ini_row, text='Browse', font=('Arial',10),
                  command=browse_ini).pack(side=tk.LEFT, padx=(0,4))
        tk.Button(ini_row, text='Set', font=('Arial',9), width=5,
                  bg='#aaddaa', command=take_ini).pack(side=tk.LEFT)

        tk.Label(fl, text='Leave blank to auto-detect (program folder, then '
                           'home directory) each time. Set explicitly only '
                           'if auto-detection picks the wrong Dream.ini.',
                 bg=GUI_BG, font=('Arial',8), fg='#555555',
                 justify=tk.LEFT).pack(anchor='w', padx=2, pady=(2,2))

        # ── Transceiver Control ───────────────────────────────────────
        # TRX_LIST starts minimal — filled from Hamlib (rigctl -l) on dialog open.
        # Only '— none —' as placeholder until Hamlib loads.
        # The saved device name and model_id are always restored from cfg.json.
        TRX_LIST = [
            ('— none —', None),
        ]

        def parse_rigctl_list(output):
            """Parse rigctl -l output — robust for Windows and Linux.

            rigctl -l columns (space-separated, variable widths):
              <model_id>  <Manufacturer>  <Model...words>  <Version>  <Status>

            Windows Hamlib variations handled:
              - Version may be '(none)' or missing entirely
              - Status may be absent
              - exit code may be non-zero even with valid output
              - Output may come from stdout OR stderr (combined before parsing)

            Strategy:
              1. First word → model_id (integer) — skip non-numeric lines
              2. Second word → manufacturer
              3. Walk backwards: skip known Status words, find Version pattern
              4. Everything between mfr and version → full model name
              5. If version not found → take parts[2..] minus last known-status word
            """
            import re as _re
            # Version: YYYYMMDD.N  or  X.Y  or  X.Y.Z  or  (none)
            _ver_pat = _re.compile(
                r'^\d{6,8}\.\d+$'      # 20201203.0
                r'|^\d+\.\d+\.\d+$'    # 1.2.3
                r'|^\d+\.\d+$'         # 0.5
                r'|^\(none\)$'         # (none)
            )
            _status = {'stable', 'beta', 'untested', 'alpha', 'new',
                       'unknown', 'experimental'}

            entries = []
            for line in output.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                parts = stripped.split()
                # Need at least: model_id  mfr  model
                if len(parts) < 3:
                    continue
                # First part must be the numeric model id
                try:
                    model_id = int(parts[0])
                except ValueError:
                    continue   # header or non-data line — skip
                mfr = parts[1]

                # Walk backwards from end to find version boundary.
                # Skip trailing Status words, then look for Version pattern.
                ver_idx  = None
                tail_idx = len(parts) - 1   # start from last word

                # Skip trailing status word(s) if present
                while tail_idx > 2 and parts[tail_idx].lower() in _status:
                    tail_idx -= 1

                # Check if this word is a version number
                if tail_idx > 2 and _ver_pat.match(parts[tail_idx]):
                    ver_idx = tail_idx

                if ver_idx is not None and ver_idx > 2:
                    # Full model name = everything between mfr and version
                    model = ' '.join(parts[2:ver_idx])
                elif ver_idx is None and tail_idx > 2:
                    # No version found — take everything up to tail_idx+1
                    model = ' '.join(parts[2:tail_idx + 1])
                else:
                    # Fallback: single word model name
                    model = parts[2]

                # Skip empty model names
                if not model.strip():
                    continue

                display = f'{mfr} {model}'
                entries.append((display, model_id))

            # Sort alphabetically; '— none —' prepended after sort
            entries.sort(key=lambda x: x[0].lower())
            return [('— none —', None)] + entries
        def detect_ports():
            found = []
            if platform.system() == 'Windows':
                try:
                    import serial.tools.list_ports
                    found = [p.device for p in
                             serial.tools.list_ports.comports()]
                except ImportError:
                    pass
                if not found:
                    try:
                        import winreg
                        key = winreg.OpenKey(
                            winreg.HKEY_LOCAL_MACHINE,
                            r'HARDWARE\DEVICEMAP\SERIALCOMM')
                        i = 0
                        while True:
                            try:
                                found.append(winreg.EnumValue(key, i)[1])
                                i += 1
                            except OSError:
                                break
                        winreg.CloseKey(key)
                    except Exception:
                        pass
                if not found:
                    found = [f'COM{n}' for n in range(1, 9)]
            else:
                import glob
                for pat in ['/dev/ttyUSB*', '/dev/ttyACM*',
                            '/dev/ttyS*', '/dev/cu.*']:
                    found += sorted(glob.glob(pat))
                if not found:
                    found = ['/dev/ttyUSB0', '/dev/ttyACM0']
            return found

        def find_rigctl():
            import shutil
            # Try with and without .exe extension
            for name in ('rigctl', 'rigctl.exe'):
                found = shutil.which(name)
                if found: return os.path.normpath(found)
            if platform.system() == 'Windows':
                candidates = [
                    r'C:\Program Files\hamlib-w64\bin\rigctl.exe',
                    r'C:\Program Files (x86)\hamlib\bin\rigctl.exe',
                    r'C:\hamlib\bin\rigctl.exe',
                    r'C:\hamlib-w64\bin\rigctl.exe',
                ]
                for c in candidates:
                    if os.path.isfile(c): return os.path.normpath(c)
            return None

        def rigctl_not_found_msg():
            if platform.system() == 'Windows':
                return ('rigctl.exe not found.\n'
                        'Download Hamlib from https://hamlib.sourceforge.io')
            return 'rigctl not found. Install: sudo apt install libhamlib-utils'

        ft = tk.LabelFrame(rx_scroll_frame,
                           text='RX-Control',
                           bg=GUI_BG, font=('Arial',9,'bold'), padx=6, pady=4)
        # ft packed at end in correct order

        trx_enable_var = tk.IntVar(value=self.cfg.get('trx_enable', 1))
        tk.Checkbutton(ft, text='Enable RX Control',
                       variable=trx_enable_var, bg=GUI_BG,
                       font=('Arial',9)).pack(anchor='w')

        # Transceiver selection
        tr1 = tk.Frame(ft, bg=GUI_BG)
        tr1.pack(fill=tk.X, pady=(4,2))
        tk.Label(tr1, text='Transceiver:', bg=GUI_BG,
                 font=('Arial',10), width=14, anchor='w').pack(side=tk.LEFT)

        saved_trx = self.cfg.get('trx_name', '— none —')
        trx_var   = tk.StringVar(value=saved_trx)
        # Start with saved name visible even before Hamlib loads.
        # If saved_trx is not in TRX_LIST yet, add it temporarily so the
        # Combobox shows it — it will be replaced by the full list shortly.
        _initial_values = [t[0] for t in TRX_LIST]
        if saved_trx and saved_trx not in _initial_values:
            _initial_values = [saved_trx] + _initial_values
        trx_cb = ttk.Combobox(ft, textvariable=trx_var,
                              values=_initial_values,
                              state='readonly', width=44)
        trx_cb.pack(fill=tk.X, padx=4, pady=(2,4))

        # ── Auto-load full Hamlib list on dialog open ─────────────────
        # Runs in a background thread — never blocks the dialog UI.
        # dlg_alive guards against _apply() firing on a destroyed dialog
        # (e.g. when the user closes and re-opens RX Config quickly).
        _hamlib_dlg_alive = [True]

        def _on_rx_dlg_close():
            _hamlib_dlg_alive[0] = False
            rx_dlg.destroy()
        rx_dlg.protocol('WM_DELETE_WINDOW', _on_rx_dlg_close)

        def _auto_load_hamlib(status_widget):
            # Priority: 1) saved rigctl path from cfg.json (user already selected it)
            #           2) system PATH / known install locations
            _cfg_rc = self.cfg.get('trx_rigctl', '').strip()
            if _cfg_rc and os.path.isfile(_cfg_rc):
                rc = _cfg_rc
            else:
                rc = find_rigctl()
            if not rc:
                try:
                    status_widget.config(
                        text='rigctl not found — use Browse to select rigctl / rigctl.exe',
                        fg='#cc6600')
                except Exception: pass
                return

            # Show loading indicator
            try:
                status_widget.config(
                    text='Loading Hamlib model list — please wait...',
                    fg='#0000aa')
            except Exception: pass

            def _load_thread():
                try:
                    r = _subprocess_run([rc, '-l'], capture_output=True,
                                        timeout=60, stdin=_subprocess.DEVNULL)
                    # Combine stdout + stderr — some Windows Hamlib builds
                    # write the model list to stderr instead of stdout.
                    stdout_txt = r.stdout.decode('utf-8', errors='replace')
                    stderr_txt = r.stderr.decode('utf-8', errors='replace')
                    output = stdout_txt if len(stdout_txt) >= len(stderr_txt) \
                             else stderr_txt
                    if output.strip():
                        full  = parse_rigctl_list(output)
                        names = [t[0] for t in full]
                        def _apply():
                            # Guard: dialog may have been closed while thread ran
                            if not _hamlib_dlg_alive[0]:
                                return
                            TRX_LIST.clear(); TRX_LIST.extend(full)
                            trx_cb['values'] = names
                            if saved_trx in names:
                                trx_var.set(saved_trx)
                            try:
                                status_widget.config(
                                    text=f'Hamlib: {len(full)-1} models loaded.',
                                    fg='#007700')
                            except Exception: pass
                        try:
                            if _hamlib_dlg_alive[0]:
                                rx_dlg.after(0, _apply)
                        except Exception: pass
                    else:
                        def _err():
                            if not _hamlib_dlg_alive[0]: return
                            try:
                                status_widget.config(
                                    text='Hamlib returned no data — using built-in list.',
                                    fg='#cc6600')
                            except Exception: pass
                        try:
                            if _hamlib_dlg_alive[0]:
                                rx_dlg.after(0, _err)
                        except Exception: pass
                except subprocess.TimeoutExpired:
                    def _timeout():
                        if not _hamlib_dlg_alive[0]: return
                        try:
                            status_widget.config(
                                text='Hamlib load timed out — using built-in list.',
                                fg='#cc0000')
                        except Exception: pass
                    try:
                        if _hamlib_dlg_alive[0]:
                            rx_dlg.after(0, _timeout)
                    except Exception: pass
                except Exception as ex:
                    def _exc(e=ex):
                        if not _hamlib_dlg_alive[0]: return
                        try:
                            status_widget.config(
                                text=f'Hamlib load error: {e} — using built-in list.',
                                fg='#cc6600')
                        except Exception: pass
                    try:
                        if _hamlib_dlg_alive[0]:
                            rx_dlg.after(0, _exc)
                    except Exception: pass

            import threading as _thr
            _thr.Thread(target=_load_thread, daemon=True).start()

        # ══════════════════════════════════════════════════════════════
        # FRAME: RigCTL — path to rigctl executable (all platforms)
        # ══════════════════════════════════════════════════════════════
        fr = tk.LabelFrame(rx_scroll_frame, text='Hamlib / RigCTL', bg=GUI_BG,
                           font=('Arial',9,'bold'), padx=6, pady=6)
        # fr packed at end in correct order

        rigctl_cmd = find_rigctl()
        trx_rigctl_var = tk.StringVar(
            value=self.cfg.get('trx_rigctl', rigctl_cmd or ''))

        fr1 = tk.Frame(fr, bg=GUI_BG)
        fr1.pack(fill=tk.X, pady=2)
        tk.Label(fr1, text='Hamlib / rigctl path:', bg=GUI_BG,
                 font=('Arial',10), width=20, anchor='w').pack(side=tk.LEFT)
        tk.Entry(fr1, textvariable=trx_rigctl_var,
                 font=('Arial',9), width=30).pack(side=tk.LEFT, padx=4)

        # _browse_result holds the path selected by Browse — before Take is clicked
        _browse_result = [None]

        def browse_rigctl():
            """Open file dialog — user selects rigctl executable."""
            if platform.system() == 'Windows':
                ftypes = [('Executable', 'rigctl.exe'), ('All', '*.*')]
            else:
                ftypes = [('All files', '*')]
            p = filedialog.askopenfilename(
                title='Select rigctl executable', filetypes=ftypes)
            if p:
                p = os.path.normpath(p)
                trx_rigctl_var.set(p)
                _browse_result[0] = p
                if os.path.isfile(p):
                    rx_status.config(
                        text=f'rigctl selected: {p}  —  click "Set" to save.',
                        fg='#0000aa')
                else:
                    rx_status.config(
                        text='File not found — please select a valid rigctl executable.',
                        fg='#cc0000')
                    _browse_result[0] = None

        def take_rigctl():
            """Save the browsed rigctl path immediately into config,
            then reload the Hamlib model list automatically so the
            Transceiver dropdown is populated without closing the dialog."""
            p = trx_rigctl_var.get().strip()
            if not p:
                rx_status.config(
                    text='No path selected — please use Browse first.',
                    fg='#cc6600')
                return
            if not os.path.isfile(p):
                rx_status.config(
                    text=f'File not found: {p}',
                    fg='#cc0000')
                return
            self.cfg.set('trx_rigctl', p)
            rx_status.config(
                text=f'rigctl path saved: {p}  —  loading Hamlib model list...',
                fg='#007700')
            _browse_result[0] = None   # reset after successful save
            # Immediately reload Hamlib list with the new rigctl path —
            # no need to close and reopen the dialog.
            _auto_load_hamlib(rx_status)

        fr2 = tk.Frame(fr, bg=GUI_BG)
        fr2.pack(anchor='w', pady=(4,2))
        tk.Button(fr2, text='Browse...', font=('Arial',10),
                  width=10, command=browse_rigctl).pack(side=tk.LEFT, padx=(0,6))
        tk.Button(fr2, text='Set', font=('Arial',9),
                  width=5, bg='#aaddaa',
                  command=take_rigctl).pack(side=tk.LEFT)

        # ══════════════════════════════════════════════════════════════
        # FRAME: Connection Mode — USB/Serial or Network
        # ══════════════════════════════════════════════════════════════
        fn = tk.LabelFrame(rx_scroll_frame, text='Connection Mode', bg=GUI_BG,
                           font=('Arial',9,'bold'), padx=6, pady=6)
        # fn packed at end in correct order

        conn_mode_var = tk.StringVar(
            value=self.cfg.get('trx_conn_mode', 'usb'))

        # Radio buttons
        rb_row = tk.Frame(fn, bg=GUI_BG)
        rb_row.pack(fill=tk.X, pady=(0,6))
        tk.Radiobutton(rb_row, text='USB / Serial', variable=conn_mode_var,
                       value='usb', bg=GUI_BG,
                       font=('Arial',10)).pack(side=tk.LEFT, padx=(0,20))
        tk.Radiobutton(rb_row, text='Network', variable=conn_mode_var,
                       value='network', bg=GUI_BG,
                       font=('Arial',10)).pack(side=tk.LEFT)

        # USB section
        fusb = tk.Frame(fn, bg=GUI_BG)
        fusb.pack(fill=tk.X, pady=2)

        # ── Row: Port / Baud ─────────────────────────────────────────
        fusb_row1 = tk.Frame(fusb, bg=GUI_BG)
        fusb_row1.pack(fill=tk.X)
        tk.Label(fusb_row1, text='Port:', bg=GUI_BG,
                 font=('Arial',10), width=14, anchor='w').pack(side=tk.LEFT)
        trx_port_var = tk.StringVar(value=self.cfg.get('trx_port',
            'COM3' if platform.system()=='Windows' else '/dev/ttyUSB0'))
        port_cb = ttk.Combobox(fusb_row1, textvariable=trx_port_var,
                               font=('Arial',10), width=12)
        port_cb.pack(side=tk.LEFT, padx=4)

        def refresh_usb_ports():
            ports = detect_ports()
            port_cb['values'] = ports
            cur = trx_port_var.get()
            if cur not in ports and ports:
                trx_port_var.set(ports[0])
        refresh_usb_ports()
        tk.Button(fusb_row1, text='↺', font=('Arial',10), width=2,
                  command=refresh_usb_ports).pack(side=tk.LEFT, padx=(0,6))
        tk.Label(fusb_row1, text='Baud:', bg=GUI_BG,
                 font=('Arial',10)).pack(side=tk.LEFT, padx=(4,2))
        trx_baud_var = tk.StringVar(value=self.cfg.get('trx_baud','9600'))
        ttk.Combobox(fusb_row1, textvariable=trx_baud_var,
                     values=['1200','4800','9600','19200',
                             '38400','57600','115200'],
                     state='readonly', width=8).pack(side=tk.LEFT)

        # ── Serial Port Parameters (WSJT-X style) ───────────────────────
        # Left on 'Default' for every field, these are never sent to
        # rigctl at all (see _rigctl_setconf_args) — so existing, already
        # working profiles (e.g. ICOM CI-V) are unaffected by this block
        # unless the user explicitly changes a value.
        fsp = tk.LabelFrame(fusb, text='Serial Port Parameters', bg=GUI_BG,
                            font=('Arial',9,'bold'), padx=6, pady=4)
        fsp.pack(fill=tk.X, pady=(6,0))

        # Data Bits
        db_row = tk.Frame(fsp, bg=GUI_BG)
        db_row.pack(fill=tk.X, pady=1)
        tk.Label(db_row, text='Data Bits:', bg=GUI_BG,
                 font=('Arial',10), width=14, anchor='w').pack(side=tk.LEFT)
        trx_databits_var = tk.StringVar(
            value=self.cfg.get('trx_databits', 'Default'))
        for val in ('Default', 'Seven', 'Eight'):
            tk.Radiobutton(db_row, text=val, variable=trx_databits_var,
                           value=val, bg=GUI_BG,
                           font=('Arial',9)).pack(side=tk.LEFT, padx=(0,10))

        # Stop Bits
        sb_row = tk.Frame(fsp, bg=GUI_BG)
        sb_row.pack(fill=tk.X, pady=1)
        tk.Label(sb_row, text='Stop Bits:', bg=GUI_BG,
                 font=('Arial',10), width=14, anchor='w').pack(side=tk.LEFT)
        trx_stopbits_var = tk.StringVar(
            value=self.cfg.get('trx_stopbits', 'Default'))
        for val in ('Default', 'One', 'Two'):
            tk.Radiobutton(sb_row, text=val, variable=trx_stopbits_var,
                           value=val, bg=GUI_BG,
                           font=('Arial',9)).pack(side=tk.LEFT, padx=(0,10))

        # Handshake
        hs_row = tk.Frame(fsp, bg=GUI_BG)
        hs_row.pack(fill=tk.X, pady=1)
        tk.Label(hs_row, text='Handshake:', bg=GUI_BG,
                 font=('Arial',10), width=14, anchor='w').pack(side=tk.LEFT)
        trx_handshake_var = tk.StringVar(
            value=self.cfg.get('trx_handshake', 'Default'))
        for val in ('Default', 'None', 'XON/XOFF', 'Hardware'):
            tk.Radiobutton(hs_row, text=val, variable=trx_handshake_var,
                           value=val, bg=GUI_BG,
                           font=('Arial',9)).pack(side=tk.LEFT, padx=(0,10))

        # Force Control Lines: DTR / RTS
        # Values map directly to Hamlib's own --set-conf tokens
        # (dtr_state=ON/OFF, rts_state=ON/OFF) — 'Default' sends nothing,
        # leaving the Hamlib backend's own default untouched.
        fc_row = tk.Frame(fsp, bg=GUI_BG)
        fc_row.pack(fill=tk.X, pady=(3,1))
        tk.Label(fc_row, text='Force Control Lines:', bg=GUI_BG,
                 font=('Arial',10), width=18, anchor='w').pack(side=tk.LEFT)
        tk.Label(fc_row, text='DTR:', bg=GUI_BG,
                 font=('Arial',10)).pack(side=tk.LEFT, padx=(0,2))
        trx_dtr_var = tk.StringVar(value=self.cfg.get('trx_dtr', 'Default'))
        ttk.Combobox(fc_row, textvariable=trx_dtr_var,
                     values=['Default', 'On', 'Off'],
                     state='readonly', width=8).pack(side=tk.LEFT, padx=(0,12))
        tk.Label(fc_row, text='RTS:', bg=GUI_BG,
                 font=('Arial',10)).pack(side=tk.LEFT, padx=(0,2))
        trx_rts_var = tk.StringVar(value=self.cfg.get('trx_rts', 'Default'))
        ttk.Combobox(fc_row, textvariable=trx_rts_var,
                     values=['Default', 'On', 'Off'],
                     state='readonly', width=8).pack(side=tk.LEFT)

        # Network section
        fnet = tk.Frame(fn, bg=GUI_BG)
        fnet.pack(fill=tk.X, pady=2)
        tk.Label(fnet, text='Host:', bg=GUI_BG,
                 font=('Arial',10), width=14, anchor='w').pack(side=tk.LEFT)
        trx_net_host_var = tk.StringVar(
            value=self.cfg.get('trx_net_host', '127.0.0.1'))
        tk.Entry(fnet, textvariable=trx_net_host_var,
                 font=('Arial',10), width=16).pack(side=tk.LEFT, padx=4)
        tk.Label(fnet, text='Port:', bg=GUI_BG,
                 font=('Arial',10)).pack(side=tk.LEFT, padx=(8,2))
        trx_net_port_var = tk.StringVar(
            value=self.cfg.get('trx_net_port', '4532'))
        tk.Entry(fnet, textvariable=trx_net_port_var,
                 font=('Arial',10), width=6).pack(side=tk.LEFT)

        # Grey out inactive section based on mode (recursive — reaches
        # widgets nested inside sub-frames, e.g. Serial Port Parameters)
        def _set_state_recursive(widget, state):
            try: widget.config(state=state)
            except Exception: pass
            for child in widget.winfo_children():
                _set_state_recursive(child, state)

        def _update_conn_mode(*_):
            usb_state = 'normal' if conn_mode_var.get()=='usb' else 'disabled'
            net_state = 'normal' if conn_mode_var.get()=='network' else 'disabled'
            for w in fusb.winfo_children():
                _set_state_recursive(w, usb_state)
            for w in fnet.winfo_children():
                _set_state_recursive(w, net_state)
        conn_mode_var.trace_add('write', _update_conn_mode)
        _update_conn_mode()   # apply on open

        # ── Test Connection (now uses connection mode) ─────────────────
        def get_rigctl_cmd():
            v = os.path.normpath(trx_rigctl_var.get().strip())
            if v and os.path.isfile(v): return v
            return find_rigctl()

        def _build_rigctl_args(model_id, command):
            """Build rigctl command list for USB or Network mode.
            -l (no-vfo): suppresses VFO init sequence — prevents IC-7300
            bandpass relay switching on CAT connection open."""
            rc = get_rigctl_cmd()
            if not rc: return None, 'rigctl not found'
            cmd = [rc, '-m', str(model_id)]
            if conn_mode_var.get() == 'network':
                host = trx_net_host_var.get().strip()
                nport = trx_net_port_var.get().strip()
                cmd += ['-r', f'{host}:{nport}']
            else:
                cmd += ['-r', trx_port_var.get().strip(),
                        '-s', trx_baud_var.get().strip()]
                cmd += self._rigctl_setconf_args()
            cmd.append(command)
            return cmd, None

        def test_trx():
            trx_name = trx_var.get()
            model_id = next((t[1] for t in TRX_LIST
                             if t[0] == trx_name), None)
            if not model_id:
                status_lbl.config(
                    text='No Hamlib model for this transceiver.',
                    fg='#cc6600')
                return
            cmd, err = _build_rigctl_args(model_id, 'f')
            if not cmd:
                status_lbl.config(text=err, fg='#cc0000')
                return
            try:
                result = _subprocess_run(
                    cmd, capture_output=True, text=True, timeout=5,
                    encoding='utf-8', errors='replace',
                    stdin=subprocess.DEVNULL)
                if result.returncode == 0:
                    mode_txt = ('Network' if conn_mode_var.get()=='network'
                                else 'USB')
                    status_lbl.config(
                        text=f'TRX connected [{mode_txt}] — '
                             f'freq: {result.stdout.strip()} Hz',
                        fg='#007700')
                else:
                    status_lbl.config(
                        text=f'TRX error: {result.stderr.strip()[:60]}',
                        fg='#cc0000')
            except subprocess.TimeoutExpired:
                status_lbl.config(
                    text='Timeout — check connection settings', fg='#cc0000')
            except Exception as ex:
                status_lbl.config(text=f'TRX error: {ex}', fg='#cc0000')

        tr3 = tk.Frame(ft, bg=GUI_BG)
        tr3.pack(anchor='w', pady=(4,2))

        # ── LED indicator ─────────────────────────────────────────────
        trx_led_c = tk.Canvas(tr3, width=16, height=16, bg=GUI_BG,
                              highlightthickness=0)
        trx_led_c.pack(side=tk.LEFT, padx=(0, 4))
        trx_led_o = trx_led_c.create_oval(2, 2, 14, 14,
                                           fill='#888888', outline='#555555')

        def _set_trx_led(color):
            """color: 'green', 'red', 'grey'"""
            fill, outline = {
                'green': ('#00cc00', '#008800'),
                'red':   ('#cc0000', '#880000'),
                'grey':  ('#888888', '#555555'),
            }.get(color, ('#888888', '#555555'))
            trx_led_c.itemconfig(trx_led_o, fill=fill, outline=outline)

        # ── Test Connection button ────────────────────────────────────
        tk.Button(tr3, text='Test Connection', font=('Arial', 10),
                  width=16, command=test_trx).pack(side=tk.LEFT, padx=(0, 16))

        # ── Frequency test field + Set Freq button ────────────────────
        tk.Label(tr3, text='Test Freq:', bg=GUI_BG,
                 font=('Arial', 10)).pack(side=tk.LEFT, padx=(0, 3))

        # Validate: digits only, max 6 characters (up to 999999 kHz)
        def _val_freq_rx(val):
            return len(val) <= 6 and (val == '' or val.isdigit())
        vcmd_freq_rx = (tr3.register(_val_freq_rx), '%P')

        test_freq_var = tk.StringVar()
        tk.Entry(tr3, textvariable=test_freq_var, width=7,
                 font=('Arial', 10), validate='key',
                 validatecommand=vcmd_freq_rx).pack(side=tk.LEFT, padx=(0, 2))
        tk.Label(tr3, text='kHz', bg=GUI_BG,
                 font=('Arial', 10)).pack(side=tk.LEFT, padx=(0, 8))

        def set_freq_trx():
            """Send 'F <hz>' command to TRX — via raw socket (netrig) or rigctl."""
            freq_str = test_freq_var.get().strip()
            if not freq_str:
                status_lbl.config(text='Enter a frequency first (kHz).',
                                  fg='#cc6600')
                return
            trx_name = trx_var.get()
            model_id = next((t[1] for t in TRX_LIST
                             if t[0] == trx_name), None)
            if not model_id:
                status_lbl.config(text='No Hamlib model for this transceiver.',
                                  fg='#cc6600')
                return
            try:
                freq_hz = int(freq_str) * 1000
            except ValueError:
                status_lbl.config(text='Invalid frequency value.', fg='#cc0000')
                return
            is_netrig = self._is_netrigctl_mode(conn_mode_var.get(), model_id)

            # ── v_rig_test_05: raw-socket path for Network + Hamlib NET rigctl ──
            if is_netrig:
                host = trx_net_host_var.get().strip()
                port = trx_net_port_var.get().strip()
                ok, info = self._netrigctl_socket_set_freq(host, port, freq_hz)
                self._netrigctl_led_state = 'green' if ok else 'red'
                if ok:
                    _set_trx_led('green')
                    status_lbl.config(
                        text=f'TRX set to {freq_str} kHz — {info}', fg='#007700')
                else:
                    _set_trx_led('red')
                    status_lbl.config(
                        text=f'Set Freq error [{host}:{port}]: {info}',
                        fg='#cc0000')
                return

            # ── Original rigctl path — USB, or Network with a real rig ──
            cmd, err = _build_rigctl_args(model_id, 'F')
            if not cmd:
                status_lbl.config(text=err, fg='#cc0000')
                return
            cmd.append(str(freq_hz))   # rigctl F <hz>
            # DIAGNOSTIC (v_rig_test_01): see comment in test_trx_with_led above.
            cmd_str = ' '.join(cmd)
            try:
                result = _subprocess_run(
                    cmd, capture_output=True, text=True, timeout=5,
                    encoding='utf-8', errors='replace',
                    stdin=subprocess.DEVNULL)
                ok = (result.returncode == 0)
                if ok:
                    _set_trx_led('green')
                    status_lbl.config(
                        text=f'TRX set to {freq_str} kHz — OK',
                        fg='#007700')
                else:
                    _set_trx_led('red')
                    status_lbl.config(
                        text=f'Set Freq error (code {result.returncode}): '
                             f'{result.stderr.strip()[:80]}  |  cmd: {cmd_str}',
                        fg='#cc0000')
            except subprocess.TimeoutExpired:
                _set_trx_led('red')
                status_lbl.config(
                    text=f'Timeout — check connection settings  |  cmd: {cmd_str}',
                    fg='#cc0000')
            except Exception as ex:
                _set_trx_led('red')
                status_lbl.config(text=f'Set Freq error: {ex}  |  cmd: {cmd_str}',
                                  fg='#cc0000')

        tk.Button(tr3, text='Set Freq', font=('Arial', 10),
                  width=9, command=set_freq_trx).pack(side=tk.LEFT)

        # ── Wire LED into test_trx so it also updates the LED ─────────
        # Redefine test_trx to include LED feedback
        # (original test_trx is already defined above and bound to button —
        #  we patch it here by replacing with a wrapper)
        _orig_test_trx = test_trx

        def test_trx_with_led():
            trx_name = trx_var.get()
            model_id = next((t[1] for t in TRX_LIST
                             if t[0] == trx_name), None)
            if not model_id:
                _set_trx_led('grey')
                status_lbl.config(
                    text='No Hamlib model for this transceiver.',
                    fg='#cc6600')
                return
            is_netrig = self._is_netrigctl_mode(conn_mode_var.get(), model_id)

            # ── v_rig_test_05: raw-socket path for Network + Hamlib NET
            # rigctl — bypasses 'rigctl' entirely, confirmed reliable by
            # an isolated test (5/5 rounds, sub-millisecond replies). ──
            if is_netrig:
                freq_str = test_freq_var.get().strip()
                if not freq_str:
                    _set_trx_led('grey')
                    status_lbl.config(
                        text='Enter a Test Freq value first (kHz).',
                        fg='#cc6600')
                    return
                try:
                    freq_hz = int(freq_str) * 1000
                except ValueError:
                    _set_trx_led('grey')
                    status_lbl.config(text='Invalid Test Freq value.',
                                      fg='#cc6600')
                    return
                host = trx_net_host_var.get().strip()
                port = trx_net_port_var.get().strip()
                ok, info = self._netrigctl_socket_set_freq(host, port, freq_hz)
                self._netrigctl_led_state = 'green' if ok else 'red'
                if ok:
                    _set_trx_led('green')
                    status_lbl.config(
                        text=f'TRX connected [Network] — set to {freq_str} '
                             f'kHz — {info}', fg='#007700')
                else:
                    _set_trx_led('red')
                    status_lbl.config(
                        text=f'TRX error [{host}:{port}]: {info}',
                        fg='#cc0000')
                return

            # ── Original rigctl path — USB, or Network with a real rig ──
            cmd, err = _build_rigctl_args(model_id, 'f')
            if not cmd:
                _set_trx_led('red')
                status_lbl.config(text=err, fg='#cc0000')
                return
            # DIAGNOSTIC (v_rig_test_01): show the exact command that was
            # attempted whenever the test fails — lets us compare it 1:1
            # against a manual terminal test to spot any hidden difference
            # (wrong model ID, wrong host/port string, stray characters).
            cmd_str = ' '.join(cmd)
            try:
                result = _subprocess_run(
                    cmd, capture_output=True, text=True, timeout=5,
                    encoding='utf-8', errors='replace',
                    stdin=subprocess.DEVNULL)
                ok = (result.returncode == 0)
                if ok:
                    _set_trx_led('green')
                    status_lbl.config(
                        text=f'TRX connected [USB] — '
                             f'freq: {result.stdout.strip()} Hz',
                        fg='#007700')
                else:
                    _set_trx_led('red')
                    status_lbl.config(
                        text=f'TRX error (code {result.returncode}): '
                             f'{result.stderr.strip()[:80]}  |  cmd: {cmd_str}',
                        fg='#cc0000')
            except subprocess.TimeoutExpired:
                _set_trx_led('red')
                status_lbl.config(
                    text=f'Timeout — check connection settings  |  cmd: {cmd_str}',
                    fg='#cc0000')
            except Exception as ex:
                _set_trx_led('red')
                status_lbl.config(text=f'TRX error: {ex}  |  cmd: {cmd_str}', fg='#cc0000')

        # Rebind the Test Connection button to the LED-aware version
        for widget in tr3.winfo_children():
            if isinstance(widget, tk.Button) and widget.cget('text') == 'Test Connection':
                widget.config(command=test_trx_with_led)
                break

        # ── Pack frames in correct visual order ──────────────────────────
        fl.pack(fill=tk.X, padx=10, pady=(10,4))  # Dream Location
        fr.pack(fill=tk.X, padx=10, pady=(0,4))   # RigCTL
        ft.pack(fill=tk.X, padx=10, pady=(0,4))   # RX-Control (Rig selection first, WSJT-X style)
        fn.pack(fill=tk.X, padx=10, pady=(0,4))   # Connection Mode (Serial/Network parameters)

        # Status label for Hamlib load result
        rx_status = tk.Label(rx_scroll_frame, text='Loading Hamlib list...',
                             bg=GUI_BG, font=('Arial',8,'italic'),
                             fg='#555555')
        rx_status.pack(pady=(0,2))

        # Now call auto-load — delayed 200ms so dialog is fully
        # rendered and visible before the background thread starts.
        rx_dlg.after(200, lambda: _auto_load_hamlib(rx_status))

        # ── Save & Close ──────────────────────────────────────────────
        def save_and_close():
            self.cfg.set('dream_path',
                os.path.normpath(path_var.get().strip()) if path_var.get().strip() else '')
            self.cfg.set('dream_ini_path',
                os.path.normpath(ini_path_var.get().strip()) if ini_path_var.get().strip() else '')
            self.cfg.set('dream_log_path',
                os.path.normpath(logpath_var.get().strip()) if logpath_var.get().strip() else '')
            self.cfg.set('trx_enable',    trx_enable_var.get())
            self.cfg.set('trx_name',      trx_var.get())
            self.cfg.set('trx_rigctl',    trx_rigctl_var.get().strip())
            self.cfg.set('trx_conn_mode', conn_mode_var.get())
            self.cfg.set('trx_port',      trx_port_var.get().strip())
            self.cfg.set('trx_baud',      trx_baud_var.get().strip())
            self.cfg.set('trx_net_host',  trx_net_host_var.get().strip())
            self.cfg.set('trx_net_port',  trx_net_port_var.get().strip())
            self.cfg.set('trx_databits',  trx_databits_var.get())
            self.cfg.set('trx_stopbits',  trx_stopbits_var.get())
            self.cfg.set('trx_handshake', trx_handshake_var.get())
            self.cfg.set('trx_dtr',       trx_dtr_var.get())
            self.cfg.set('trx_rts',       trx_rts_var.get())
            model_id = next((t[1] for t in TRX_LIST
                             if t[0] == trx_var.get()), None)
            if model_id:
                self.cfg.set('trx_model_id', model_id)
            status_lbl.config(text='Settings saved.', fg='#007700')
            _hamlib_dlg_alive[0] = False   # prevent stale thread from firing
            rx_dlg.after(600, rx_dlg.destroy)

        btn_row = tk.Frame(rx_dlg, bg=GUI_BG)
        btn_row.pack(side=tk.BOTTOM, pady=(8,10))
        tk.Button(btn_row, text='Save & Close',
                  font=('Arial',10,'bold'), bg='#aaddaa', width=14,
                  command=save_and_close).pack(side=tk.LEFT, padx=8)
        tk.Button(btn_row, text='Cancel',
                  font=('Arial',10), width=10,
                  command=rx_dlg.destroy).pack(side=tk.LEFT, padx=8)

        # ── Pack the scrollable area last — fills all remaining space
        # above the fixed Save & Close / Cancel button row ─────────────
        rx_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        rx_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _show_dream_info_window(self):
        """
        Shows the 'Important Information' window about Dream start modes.
        Callable both automatically (from _set_event, on first use) and
        manually (from the 'DReaM Info' button in Basic Setup).
        Checkbox logic: checked = show again at next Set-Event start.
        """
        info_dlg = tk.Toplevel(self.root)
        info_dlg.title('DReaM use with DRMLogPlotter-rebuild')
        info_dlg.configure(bg='#d4d0c8')
        info_dlg.resizable(True, True)
        center_dialog(info_dlg, self.root, 600, 760)
        info_dlg.minsize(500, 300)
        info_dlg.grab_set()
        info_dlg.transient(self.root)   # v_rig_test_06: keep dialog above its parent
        info_dlg.lift()
        info_dlg.focus_force()

        # ── Scrollable container ──────────────────────────────────────────
        # Added because a fixed, non-scrolling window (the previous
        # behaviour) silently clips any content taller than the window —
        # confirmed as the cause of the new X11/Wayland hint not being
        # visible after it was added (2026-07). Same pattern as the
        # scrollable 'Basic Setup Parameters' dialog (_open_setup()).
        info_outer = tk.Frame(info_dlg, bg='#d4d0c8')
        info_outer.pack(fill=tk.BOTH, expand=True)
        info_canvas = tk.Canvas(info_outer, bg='#d4d0c8', highlightthickness=0)
        info_vsb = ttk.Scrollbar(info_outer, orient='vertical',
                                  command=info_canvas.yview)
        info_canvas.configure(yscrollcommand=info_vsb.set)
        info_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        info_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        I = tk.Frame(info_canvas, bg='#d4d0c8')   # shorthand, all widgets go here
        info_inner_id = info_canvas.create_window((0, 0), window=I, anchor='nw')

        def _info_on_inner_configure(event):
            info_canvas.configure(scrollregion=info_canvas.bbox('all'))
        def _info_on_canvas_configure(event):
            info_canvas.itemconfig(info_inner_id, width=event.width)
        I.bind('<Configure>', _info_on_inner_configure)
        info_canvas.bind('<Configure>', _info_on_canvas_configure)

        def _info_on_mousewheel(event):
            if event.num == 4:
                info_canvas.yview_scroll(-1, 'units')
            elif event.num == 5:
                info_canvas.yview_scroll(1, 'units')
            else:
                info_canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        info_canvas.bind_all('<MouseWheel>', _info_on_mousewheel)
        info_canvas.bind_all('<Button-4>',   _info_on_mousewheel)
        info_canvas.bind_all('<Button-5>',   _info_on_mousewheel)

        def _info_on_close():
            info_canvas.unbind_all('<MouseWheel>')
            info_canvas.unbind_all('<Button-4>')
            info_canvas.unbind_all('<Button-5>')
            info_dlg.destroy()
        info_dlg.protocol('WM_DELETE_WINDOW', _info_on_close)

        # ── Linux/Raspberry Pi note — always first, own separator ─────────
        # Shown for every Linux user (not only when Wayland is detected —
        # this is a general disclaimer about the experimental screen-layer
        # setting itself, distinct from the more specific Wayland/Audio-
        # Codec hint further below). Never shown on Windows/macOS.
        if _platform.system() == 'Linux':
            tk.Label(I,
                     text='Note for Linux / Raspberry Pi users:',
                     bg='#d4d0c8', font=('Arial', 9, 'bold'),
                     justify=tk.LEFT, anchor='w').pack(
                         padx=20, pady=(14, 0), fill=tk.X)
            tk.Label(I,
                     text=(
                         "Please note that under 'Basic Setup Parameters' "
                         "you have the option\n"
                         "to select the screen layer for Linux. This is "
                         "experimental \u2014\n"
                         "no guarantee of function."
                     ),
                     bg='#d4d0c8', font=('Arial', 9), justify=tk.LEFT,
                     anchor='w').pack(padx=20, pady=(2, 4), fill=tk.X)
            ttk.Separator(I, orient='horizontal').pack(
                fill=tk.X, padx=16, pady=(4, 4))

        tk.Label(I,
                 text='Important Information',
                 bg='#d4d0c8', font=('Arial', 11, 'bold'),
                 fg='#000080').pack(pady=(14, 4))

        ttk.Separator(I, orient='horizontal').pack(
            fill=tk.X, padx=16, pady=4)

        _wayland_hint = ""
        if _is_linux_wayland_session():
            _wayland_hint = (
                "  \u26a0  This is the Linux version, running on a Wayland "
                "desktop session.\n"
                "     Should Audio Codec detection not work correctly, "
                "please check the\n"
                "     'Start DReaM in Linux: X11 - xWayland - Wayland' "
                "setting under\n"
                "     Basic Setup Parameters.\n\n"
            )

        info_text = (
            _wayland_hint +
            "When Dream is started via the DRM-Log Plotter rebuild,\n"
            "the following actions are performed automatically:\n\n"
            "  \u2022  The dream.ini is adjusted for the duration of the log\n"
            "     and reset to normal after Dream stops.\n\n"
            "  \u2022  A DreamAudio.json is created in the Dream directory\n"
            "     containing Audio Codec information for each log.\n\n"
            "  \u2022  When archiving logs, also save the DreamAudio.json\n"
            "     from the Dream directory to keep Audio Codec info."
        )
        tk.Label(I, text=info_text, bg='#d4d0c8',
                 font=('Arial', 9), justify=tk.LEFT,
                 anchor='w').pack(padx=20, pady=4, fill=tk.X)

        ttk.Separator(I, orient='horizontal').pack(
            fill=tk.X, padx=16, pady=6)

        # ── "Dream start modes — overview" — slightly bold heading ───────
        tk.Label(I, text='Dream start modes \u2014 overview:',
                 bg='#d4d0c8', font=('Arial', 9, 'bold'),
                 justify=tk.LEFT, anchor='w').pack(
                     padx=20, pady=(2, 2), fill=tk.X)

        modes_text = (
            "\n"
            "  Manual start\n"
            "  \u2192 Listen only. No log, no DreamAudio.json.\n\n"
            "  Manual start + Log\n"
            "  \u2192 15 sec. log delay. DreamAudio.json created in /dream.\n\n"
            "  Timer-Event + Log\n"
            "  \u2192 15 sec. log delay. DreamAudio.json created in /dream.\n\n"
            "  Timer-Event + Log + AutoPlot\n"
            "  \u2192 15 sec. log delay, AutoPlot starts after 20 sec.\n"
            "     DreamAudio.json created in /dream.\n\n"
        )
        tk.Label(I, text=modes_text, bg='#d4d0c8',
                 font=('Arial', 9), justify=tk.LEFT,
                 anchor='w').pack(padx=20, pady=0, fill=tk.X)

        # ── "Stop Dream Button:" ──────────────────────────────────────────
        stop_text = (
            "  Stop Dream Button:\n"
            "  \u2192 Stops all processes correctly. dream.ini reset to normal."
        )
        tk.Label(I, text=stop_text, bg='#d4d0c8',
                 font=('Arial', 9), justify=tk.LEFT,
                 anchor='w').pack(padx=20, pady=(0, 2), fill=tk.X)

        warn_text = (
            "\n  \u26a0  Stop Dream externally\n"
            "  \u2192 Processes NOT stopped correctly! dream.ini NOT reset!"
        )
        tk.Label(I, text=warn_text, bg='#d4d0c8',
                 font=('Arial', 9), justify=tk.LEFT,
                 anchor='w').pack(padx=20, pady=0, fill=tk.X)

        ttk.Separator(I, orient='horizontal').pack(
            fill=tk.X, padx=16, pady=6)

        # ── Checkbox — direct logic: checked = show again at Set-Event ───
        show_again = tk.BooleanVar(
            value=self.cfg.get('set_event_info_shown', True))
        tk.Checkbutton(I,
                       text="Show this information again - please note Basic Setup Parameters",
                       variable=show_again,
                       bg='#d4d0c8',
                       font=('Arial', 9)).pack(anchor='w', padx=20)

        def _info_ok():
            self.cfg.set('set_event_info_shown', show_again.get())
            _info_on_close()

        tk.Button(I, text='OK',
                  font=('Arial', 10), width=8,
                  command=_info_ok).pack(pady=(6, 14))

        info_dlg.wait_window()

    def _rigctl_freq_for_station(self, station_khz_str):
        """
        Every frequency the user enters anywhere in the programme (the
        'Log-Frequency' field, a Timer-Event slot, a DRM-Radio-List click,
        a preset) is always the TRUE station/broadcast frequency — that is
        what Dream itself receives, unchanged. This method computes the
        one place that's different: what actually goes to rigctl. If the
        SDR USB/LSB correction is enabled, the signed offset (positive for
        USB, negative for LSB — see the sideband radio buttons in
        'Correction of Dream-Log-Frequency...') is subtracted, so the
        receiver's widened filter sits centred on the true signal. No-op
        (returns the value unchanged) when the correction is off.

        A proper class method (not nested inside _set_event()) so it can
        be shared by every rigctl call site in the programme, including
        the standalone 'Radio List' button in the Main-GUI.
        """
        if not station_khz_str or not self.cfg.get('sdr_usb_lsb_enabled', False):
            return station_khz_str
        try:
            offset = int(self.cfg.get('sdr_usb_lsb_offset', 0))
            v = float(station_khz_str) - offset
            return str(int(v)) if v == int(v) else str(v)
        except ValueError:
            return station_khz_str   # not a plain number — leave untouched

    def _send_freq_to_rigctl(self, freq):
        """
        Core rigctl-send logic — the ONE place in the programme that
        actually talks to rigctl/netrigctl to change the receiver
        frequency. Shared by every caller: the 'Set' button in 'Dream
        Manual Start / Stop', 'Correction of Dream-Log-Frequency...'s own
        'Set' button, and the DRM-Radio-List window (whether opened from
        inside 'Dream — Start & Schedule' or standalone from the
        Main-GUI's 'Transmitter Site' frame).

        Deliberately UI-free: no widget is touched here, only the TRX
        config is read and rigctl/netrigctl actually called. Callers show
        the result however fits their own window (status label text, LED
        indicators, etc.) — this keeps a single, exactly-once-maintained
        implementation of the actual protocol logic, while every calling
        window/dialog stays independent and doesn't need to know about
        any other window's widgets.

        freq: the TRUE station frequency (string, kHz) — the SDR USB/LSB
        offset correction is applied internally via
        self._rigctl_freq_for_station(), exactly as everywhere else.

        Returns (ok, message, fg_color, led_state):
            ok         — bool, whether the frequency was actually sent.
            message    — human-readable status text.
            fg_color   — '#007700' success / '#cc6600' warning (not
                         configured) / '#cc0000' error — matches the
                         colours already used throughout the programme.
            led_state  — None (don't touch any LED), 'green' (successful
                         send) or 'red' (a real send attempt failed) —
                         callers that have LED indicators (like the
                         Status frame in 'Dream — Start & Schedule') can
                         act on this; callers without LEDs simply ignore it.
        """
        import subprocess, shutil
        freq = str(freq).strip()
        if not freq:
            return False, 'Please enter a Log Frequency first!', '#cc0000', None

        # 'freq' is always the TRUE station frequency (Dream-Log
        # convention). rigctl_freq is what actually goes to the receiver —
        # corrected for the SDR USB/LSB offset if that correction is
        # enabled; a no-op otherwise.
        rigctl_freq = self._rigctl_freq_for_station(freq)

        if not self.cfg.get('trx_enable', 0):
            return False, 'Transceiver Control not enabled in RX Config.', '#cc6600', None

        trx_name = self.cfg.get('trx_name', '')
        port     = self.cfg.get('trx_port', '')
        baud     = self.cfg.get('trx_baud', '9600')
        model_id = self.cfg.get('trx_model_id', None)
        conn_mode_chk = self.cfg.get('trx_conn_mode', 'usb')
        net_host_chk  = self.cfg.get('trx_net_host', '')
        net_port_chk  = self.cfg.get('trx_net_port', '')
        # DIAGNOSTIC (v_rig_test_01) + FIX (v_rig_test_03): in Network
        # mode, 'trx_port' is legitimately empty (Host/Port is used
        # instead) — check trx_net_host/trx_net_port there instead, so
        # Network-mode setups are no longer blocked before ever
        # attempting the actual rigctl call.
        if conn_mode_chk == 'network':
            missing_fields = (not trx_name or not net_host_chk
                               or not net_port_chk or not model_id)
        else:
            missing_fields = (not trx_name or not port or not model_id)
        if missing_fields:
            missing = []
            if not trx_name: missing.append('trx_name')
            if conn_mode_chk == 'network':
                if not net_host_chk: missing.append('trx_net_host')
                if not net_port_chk: missing.append('trx_net_port')
            else:
                if not port: missing.append('trx_port')
            if not model_id: missing.append('trx_model_id')
            return False, (f'Please configure Receiver Settings in RX Config '
                            f'first! (missing: {", ".join(missing)}, '
                            f'conn_mode={conn_mode_chk})'), '#cc0000', None

        # ── v_rig_test_05: raw-socket path for Network + Hamlib NET
        # rigctl — completely bypasses rigctl, so it doesn't need
        # rigctl_path/port/baud at all for this one specific mode. ──
        if self._is_netrigctl_mode(conn_mode_chk, model_id):
            if not net_host_chk or not net_port_chk:
                return False, 'Please configure Host/Port in RX Config first!', '#cc0000', None
            try:
                freq_hz = int(float(rigctl_freq) * 1000)
            except ValueError:
                return False, 'Invalid Log Frequency value.', '#cc0000', None
            ok, info = self._netrigctl_socket_set_freq(
                net_host_chk, net_port_chk, freq_hz)
            self._netrigctl_led_state = 'green' if ok else 'red'
            if ok:
                if rigctl_freq != freq:
                    msg = (f'TRX set to {rigctl_freq} kHz (SDR offset '
                           f'applied for station {freq} kHz) — {info}')
                else:
                    msg = f'TRX set to {freq} kHz — {info}'
                return True, msg, '#007700', 'green'
            else:
                return False, f'TRX error [{net_host_chk}:{net_port_chk}]: {info}', '#cc0000', 'red'

        # ── Original rigctl path — USB, or Network with a real rig ──
        rigctl_path = self.cfg.get('trx_rigctl', '')
        rigctl = (rigctl_path if rigctl_path and os.path.isfile(rigctl_path)
                  else shutil.which('rigctl'))
        if not rigctl:
            return False, 'rigctl not found — check RX Config settings.', '#cc0000', None
        try:
            freq_hz = int(float(rigctl_freq) * 1000)
            cmd_args = [rigctl, '-m', str(model_id),
                        '-r', port, '-s', baud]
            cmd_args += self._rigctl_setconf_args()
            cmd_args += ['F', str(freq_hz)]
            result = _subprocess_run(
                cmd_args, capture_output=True, text=True, timeout=5,
                encoding='utf-8', errors='replace',
                stdin=subprocess.DEVNULL)
            cmd_str = ' '.join(cmd_args)   # DIAGNOSTIC (v_rig_test_01)
            ok = (result.returncode == 0)
            if ok:
                if rigctl_freq != freq:
                    msg = (f'TRX set to {rigctl_freq} kHz (SDR offset '
                           f'applied for station {freq} kHz) — OK')
                else:
                    msg = f'TRX set to {freq} kHz — OK'
                return True, msg, '#007700', 'green'
            else:
                msg = (f'TRX error (code {result.returncode}): '
                       f'{result.stderr.strip()[:80]}  |  cmd: {cmd_str}')
                return False, msg, '#cc0000', 'red'
        except subprocess.TimeoutExpired:
            cmd_str = ' '.join(cmd_args)   # DIAGNOSTIC (v_rig_test_01)
            return False, (f'TRX timeout — check port and baud rate  |  '
                            f'cmd: {cmd_str}'), '#cc0000', 'red'
        except Exception as ex:
            return False, f'TRX error: {ex}', '#cc0000', None

    def _toggle_drm_radio_list_window(self):
        """Toggle wrapper (Aug 2026, user request) for the standalone
        Main-GUI 'Radio List' button only — a 2nd click while the
        window is already open closes it instead of opening a further
        copy. Deliberately does not touch the embedded/parametrised
        call path (freq_var/parent/on_freq_sent) used elsewhere."""
        win = getattr(self, '_drm_radio_list_win', None)
        if win is not None and win.winfo_exists():
            win.destroy()
            return
        self._open_drm_radio_list_window()

    def _open_drm_radio_list_window(self, freq_var=None, parent=None, on_freq_sent=None):
        """
        Opens the DRM-Radio-List browser window. Called both from the
        embedded 'DRM-Radio-List' button inside 'Dream — Start & Schedule'
        (passing that dialog's own freq_var + itself as parent, plus
        on_freq_sent so this window's rigctl sends also update THAT
        dialog's Status-frame LEDs/status label, exactly as before) and
        from the standalone 'Radio List' button in the Main-GUI's
        'Transmitter Site' frame (no freq_var/parent given — fully
        self-sufficient). Either way, the actual rigctl-sending logic
        lives in exactly one place: self._send_freq_to_rigctl().

        freq_var: StringVar to read/write the current Log-Frequency. If
        None, a fresh one is created, initialised from the same
        persisted value ('last_event_freq') that 'Dream Manual Start /
        Stop' uses — so whichever entry point opens first, the user
        sees the same starting frequency.
        parent: window this Toplevel is created under. Defaults to
        self.root. MUST be the actual enclosing dialog when opened from
        within a modal dialog chain — see _manage_drm_schedule()'s
        docstring for why (Tk's local grab_set() restricts events to
        the grabbing widget and its descendants only).
        on_freq_sent: optional callback(ok, msg, fg, led_state), called
        after every attempted rigctl send from this window — used by the
        embedded call site to also update its own status label and LED
        indicators. Left None by the standalone entry point, which
        relies purely on this window's own status line.
        """
        if freq_var is None:
            freq_var = tk.StringVar(value=self.cfg.get('last_event_freq', ''))
        if parent is None:
            parent = self.root

        def set_to_log_freq():
            """Thin per-window wrapper around the shared rigctl-send core —
            keeps on_row_select()/preset_click() below unchanged from the
            embedded version, while giving this window its own feedback
            (list_status) and optionally notifying an embedding dialog."""
            ok, msg, fg, led = self._send_freq_to_rigctl(freq_var.get())
            if on_freq_sent:
                try:
                    on_freq_sent(ok, msg, fg, led)
                except Exception:
                    pass
            if not ok:
                list_status.config(text=msg, fg=fg)
            return ok

        rl = tk.Toplevel(parent)
        rl.title('DRM-Radio-List')
        rl.configure(bg=GUI_BG)
        # Declared early (Aug 2026) so the new 7-segment clock (built
        # further below) can reuse this SAME alive-flag as its own
        # stop condition — the rest of its auto-refresh machinery
        # (_rl_after_id, _auto_refresh, _on_rl_close) is still defined
        # later, unchanged, where it always was.
        _rl_alive = [True]
        # Toggle behaviour (Aug 2026, user request) — only tracked for the
        # standalone Main-GUI entry point (parent was None going in, i.e.
        # this call came from _toggle_drm_radio_list_window()), so the
        # embedded/parametrised call path is left untouched. Cleared on
        # <Destroy> so it works no matter how the window actually closes.
        if parent is self.root:
            self._drm_radio_list_win = rl
            def _clear_drm_radio_list_ref(event=None):
                if event is not None and event.widget is not rl:
                    return
                self._drm_radio_list_win = None
            rl.bind('<Destroy>', _clear_drm_radio_list_ref, add='+')
        # Deliberately NOT transient(parent) (Aug 2026, reverted per user
        # request): marking a Toplevel as transient-for another window
        # makes Windows treat it as a "dialog" and drop the minimize
        # button from its title bar — purely a window-manager side
        # effect, not something needed here. The actual fix that matters
        # (this window staying usable/receiving events even when opened
        # from inside a modal dialog that holds a Tk grab) comes entirely
        # from 'tk.Toplevel(parent)' above establishing the correct
        # widget-hierarchy descendant relationship — removing transient()
        # does not touch that at all.
        # Also deliberately NO grab_set(): this window stays non-modal so
        # the user can keep watching the main window (SNR plot) while
        # it's open.
        _saved_geom = self.cfg.get('drm_radio_list_geometry', '')
        if _saved_geom:
            try:
                rl.geometry(_saved_geom)
            except Exception:
                center_dialog(rl, self.root, 1180, 700)
        else:
            center_dialog(rl, self.root, 1180, 700)

        def _save_geometry(event=None):
            # Fires on every move/resize (live while dragging, per user
            # request) — cheap enough to just save on every event rather
            # than debouncing. Only reacts to events on rl itself, not on
            # any child widget bubbling one up.
            if event is not None and event.widget is not rl:
                return
            try:
                self.cfg.set('drm_radio_list_geometry', rl.geometry())
            except Exception:
                pass
        rl.bind('<Configure>', _save_geometry, add='+')

        list_status = tk.Label(rl, text='No DRMSchedule.ini loaded yet.',
                                bg=GUI_BG, font=('Arial',8,'italic'),
                                fg='#555555', anchor='w')

        # Aug 2026, user request (security): the full path shown on a
        # successful load must NOT stay on screen indefinitely — it can
        # reveal the OS username / folder structure. The entry COUNT is
        # still a useful, harmless confirmation of the list's size, so
        # that part stays visible permanently; only the path portion is
        # auto-stripped after a few seconds. The `full_msg` guard makes
        # sure this only fires if nothing else (a preset click, an
        # error, "Stop Dream sent.", etc.) has since overwritten
        # list_status with an unrelated message in the meantime.
        def _show_loaded_status(n, path):
            full_msg = f'{n} entries loaded from: {path}'
            list_status.config(text=full_msg, fg='#007700')
            def _strip_path():
                if list_status.cget('text') == full_msg:
                    list_status.config(text=f'{n} entries loaded.',
                                       fg='#007700')
            rl.after(6000, _strip_path)

        # ── Top row: Load DRMSchedule / Edit DRM-Schedule ───────
        top = tk.Frame(rl, bg=GUI_BG)
        top.pack(fill=tk.X, padx=8, pady=(8,4))
        path_var = tk.StringVar(value=self.cfg.get('drmschedule_path',''))

        def load_schedule():
            start_dir = (os.path.dirname(path_var.get())
                         if path_var.get() and os.path.isfile(path_var.get())
                         else os.path.expanduser('~'))
            p = filedialog.askopenfilename(
                parent=rl, title='Load DRM Schedule (.ini)',
                initialdir=start_dir if os.path.isdir(start_dir) else os.path.expanduser('~'),
                filetypes=[('DRM Schedule', '*.ini'), ('All files', '*.*')])
            if not p:
                return
            entries = parse_drm_schedule(p)
            if not entries:
                list_status.config(
                    text=f'No valid entries found in: {p}', fg='#cc0000')
                return
            path_var.set(p)
            self.cfg.set('drmschedule_path', p)
            self.drm_schedule = entries
            path_label.pack_forget()
            _show_loaded_status(len(entries), p)
            refresh_view()

        tk.Button(top, text='Load DRMSchedule', font=('Arial',9),
                  bg='#aaddff', command=load_schedule).pack(side=tk.LEFT)
        tk.Button(top, text='Edit DRM-Schedule', font=('Arial',9),
                  bg='#ffddaa',
                  command=lambda: self._manage_drm_schedule(
                      on_change=refresh_view, parent=rl)).pack(side=tk.LEFT, padx=(6,0))

        # ── Top-right: 'Last choice' read-out — purely informational,
        # no function behind it. Shows whatever frequency was last
        # picked in this window (list click or preset), and persists
        # across sessions so the user immediately sees "that was my
        # last pick" when reopening this window. The actual rigctl
        # switch-over (on_row_select() / preset_click() below) is
        # completely untouched — this just piggybacks on those two
        # existing, already-working click handlers.
        #
        # IMPORTANT: packed BEFORE the (potentially long) path label
        # below, not after. Tk's packer hands out cavity space in the
        # ORDER widgets are packed, regardless of side — a long loaded
        # file path packed first would claim all the room and squeeze
        # this side=RIGHT frame down to zero width (invisible), which
        # is exactly what happened before this fix.
        last_choice_frame = tk.Frame(top, bg=GUI_BG, relief=tk.GROOVE, bd=2)
        last_choice_frame.pack(side=tk.RIGHT, padx=(8,20))
        tk.Label(last_choice_frame, text='Last choice was:', bg=GUI_BG,
                 font=('Arial',10), fg='black').pack(side=tk.LEFT, padx=4, pady=2)
        last_choice_var = tk.StringVar(
            value=(self.cfg.get('drm_radio_list_last_choice', '') or '\u2014'))
        tk.Label(last_choice_frame, textvariable=last_choice_var, bg=GUI_BG,
                 font=('Arial',12,'bold'), fg='#33aaff').pack(
                 side=tk.LEFT, padx=(4,2), pady=2)
        tk.Label(last_choice_frame, text='kHz', bg=GUI_BG,
                 font=('Arial',10), fg='black').pack(side=tk.LEFT, padx=(0,4), pady=2)

        # ── UTC clock (Aug 2026, user request) — same bordered look as
        # 'Last choice was', placed directly to its LEFT in the same
        # top row (packed side=RIGHT AFTER last_choice_frame, so it
        # lands immediately to its left).
        _rl_clock_frame = tk.Frame(top, bg=GUI_BG, relief=tk.GROOVE, bd=2)
        _rl_clock_frame.pack(side=tk.RIGHT, padx=(8,0))
        tk.Label(_rl_clock_frame, text='UTC:', bg=GUI_BG,
                 font=('Arial',10), fg='black').pack(side=tk.LEFT, padx=4, pady=2)
        self._build_text_clock(_rl_clock_frame, _rl_alive).pack(
            side=tk.LEFT, padx=(0,4), pady=2)

        def _record_last_choice(khz_str):
            last_choice_var.set(khz_str or '\u2014')
            self.cfg.set('drm_radio_list_last_choice', khz_str)

        # Path label packed LAST — it now simply gets whatever space
        # remains after the buttons and the reserved right-hand
        # display, instead of being able to squeeze the latter out.
        # Aug 2026, user request: this label is only meant to be
        # visible transiently (while no schedule is loaded, or if a
        # load just failed) — once a schedule has been successfully
        # loaded, it's redundant with the 'Loaded N entries from: ...'
        # status message and just clutters the window, so it's hidden
        # afterward (see load_schedule() below, and immediately here
        # too if a previously-successful path is already persisted).
        path_label = tk.Label(top, textvariable=path_var, bg=GUI_BG,
                              font=('Arial',8), fg='#555555')
        path_label.pack(side=tk.LEFT, padx=(8,0))
        if path_var.get():
            path_label.pack_forget()

        # ── Sort-by row (radio buttons, per column) ─────────────
        sort_row = tk.Frame(rl, bg=GUI_BG)
        sort_row.pack(fill=tk.X, padx=8, pady=(2,2))
        tk.Label(sort_row, text='Sort by:', bg=GUI_BG,
                 font=('Arial',8,'bold')).pack(side=tk.LEFT, padx=(0,6))
        SORT_OPTIONS = [
            ('active',    'Active'),
            ('programme', 'Programme'),
            ('time',      'Time'),
            ('khz',       'kHz'),
            ('target',    'Target'),
            ('site',      'Site'),
            ('country',   'Country'),
            ('language',  'Language'),
        ]
        # Default 'active' only matters for a brand-new install / first
        # ever start — from then on, the user's last choice (e.g. 'kHz')
        # is remembered and used again the next time this window opens,
        # instead of silently jumping back to 'Active' every time.
        sort_var = tk.StringVar(value=self.cfg.get('drm_radio_list_sort', 'active'))
        def _on_sort_change():
            self.cfg.set('drm_radio_list_sort', sort_var.get())
            refresh_view()
        for key, label in SORT_OPTIONS:
            tk.Radiobutton(sort_row, text=label, variable=sort_var, value=key,
                           bg=GUI_BG, font=('Arial',8),
                           command=_on_sort_change).pack(side=tk.LEFT, padx=3)

        # ── Treeview (the actual list) ──────────────────────────
        cols = ('programme','time','khz','kw','target','site','country','language')
        headers = {'programme':'Programme','time':'Time (UTC)','khz':'kHz',
                   'kw':'kW','target':'Target','site':'Site',
                   'country':'Country','language':'Language'}
        widths  = {'programme':170,'time':90,'khz':60,'kw':45,
                   'target':150,'site':110,'country':90,'language':90}

        tv_frame = tk.Frame(rl, bg=GUI_BG)
        tv_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(2,4))
        tv_scroll = tk.Scrollbar(tv_frame, orient='vertical')
        tv = ttk.Treeview(tv_frame, columns=cols, show='headings',
                           yscrollcommand=tv_scroll.set, selectmode='browse')
        tv_scroll.config(command=tv.yview)
        tv_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        tv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Column widths: user's last drag-resized widths, if any (per
        # column, falling back to the hardcoded default for any column
        # not yet saved) — same "remember the user's last choice"
        # principle as the persisted Sort-by setting from yesterday.
        #
        # A fixed window width can never reliably guarantee the last
        # column stays visible — the user can (and, confirmed by
        # testing, does) drag column borders wider than any reasonable
        # default window size. The horizontal scrollbar above is the
        # actual, permanent fix: if the columns' total width exceeds the
        # visible table area, the user simply scrolls right instead of
        # the last column ever being invisibly clipped.
        _saved_widths = self.cfg.get('drm_radio_list_col_widths', {}) or {}
        for c in cols:
            tv.heading(c, text=headers[c])
            tv.column(c, width=_saved_widths.get(c, widths[c]), anchor='w')

        def _save_col_widths(event=None):
            try:
                self.cfg.set('drm_radio_list_col_widths',
                              {c: tv.column(c, 'width') for c in cols})
            except Exception:
                pass
        # Fires on every mouse-button release inside the table, including
        # ordinary row clicks — harmless (just re-saves the current,
        # unchanged widths then), and simplest reliable way to catch a
        # column-border drag, since ttk.Treeview has no dedicated
        # "column resized" event of its own.
        tv.bind('<ButtonRelease-1>', _save_col_widths, add='+')
        tv.tag_configure('active',   background='#b6f2b6')  # green = on air now
        tv.tag_configure('soon',     background='#ff9999')  # red = starts within 15 min (Aug 2026)
        tv.tag_configure('lastfreq', background='#aee0ff')  # light blue = matches last-chosen frequency (Aug 2026)
        tv.tag_configure('inactive', background='#fff6b0')  # yellow = not now

        def _fmt_time(e):
            return f"{e['start_h']:02d}{e['start_m']:02d}-{e['stop_h']:02d}{e['stop_m']:02d}"

        def _row_sort_key(key, e, active_now):
            if key == 'active':    return (0 if active_now else 1, e['freq_khz'])
            if key == 'programme': return e['programme'].lower()
            if key == 'time':      return e['start_h']*60 + e['start_m']
            if key == 'khz':       return e['freq_khz']
            if key == 'target':    return e['target'].lower()
            if key == 'site':      return e['site'].lower()
            if key == 'country':   return e['country'].lower()
            if key == 'language':  return e['language'].lower()
            return 0

        def refresh_view():
            tv.delete(*tv.get_children())
            entries = self.drm_schedule
            if not entries:
                return
            now_utc = datetime.now(timezone.utc)
            rows = [(e, drm_entry_is_active(e, now_utc)) for e in entries]
            key = sort_var.get()
            rows.sort(key=lambda r: _row_sort_key(key, r[0], r[1]))
            # Last-chosen frequency (Aug 2026, user request) — read once
            # per refresh; compared as strings since e['freq_khz'] and
            # the persisted last-choice value aren't guaranteed to be
            # the exact same type.
            _last_khz_str = str(self.cfg.get(
                'drm_radio_list_last_choice', '') or '').strip()
            for e, active_now in rows:
                # Priority (Aug 2026, user request, "Vorschlag 1"):
                # on-air (green) and starts-soon (red) reflect actual
                # broadcast timing and always win. The last-chosen-
                # frequency highlight (light blue) only shows on rows
                # that would otherwise be plain "inactive" (yellow) —
                # it never covers up the more time-critical colours.
                if active_now:
                    tag = 'active'
                elif drm_entry_starts_soon(e, now_utc):
                    tag = 'soon'
                elif _last_khz_str and str(e['freq_khz']) == _last_khz_str:
                    tag = 'lastfreq'
                else:
                    tag = 'inactive'
                tv.insert('', 'end', values=(
                    e['programme'], _fmt_time(e), e['freq_khz'], e['power'],
                    e['target'], e['site'], e['country'], e['language']),
                    tags=(tag,))

        # ── Row click: hand frequency over to the EXISTING Set logic ──
        def on_row_select(event=None):
            sel = tv.selection()
            if not sel:
                return
            vals = tv.item(sel[0], 'values')
            if not vals:
                return
            # Collision guard (user requirement, Aug 2026): a running
            # Dream session (whether started manually via 'Dream —
            # Start & Schedule', a Schedule&Event, or the 'Dream Log'
            # button here) is an active process that must never be
            # altered from outside — retuning the receiver underneath
            # it would silently change what is currently being logged.
            # Mirrors exactly the same block/message already used by
            # the 'Dream Log' button (_dream_log_click) further below,
            # so the behaviour is consistent across every entry point
            # in this window. Clearing the selection avoids the row
            # staying visually 'selected' for a station that was never
            # actually tuned to.
            if self._is_dream_running():
                tv.selection_remove(sel)
                try:
                    rl.lift()
                    rl.focus_force()
                except Exception:
                    pass
                messagebox.showinfo(
                    'Dream Log', 'Stop Dream first.', parent=rl)
                list_status.config(text='Stop Dream first.', fg='#cc0000')
                return
            station_khz = str(vals[2])   # true broadcast frequency, as listed
            # freq_var always holds the TRUE station frequency — the
            # SDR USB/LSB correction (if enabled) is applied uniformly
            # inside set_to_log_freq() itself, exactly once, the same
            # way for every entry path (this list, manual typing,
            # Timer-Events, presets). Nothing to compute here anymore.
            freq_var.set(station_khz)
            set_to_log_freq()
            _record_last_choice(station_khz)
            # Aug 2026: refresh immediately so the new last-chosen-
            # frequency highlight (light blue) shows up right away,
            # instead of waiting for the next periodic auto-refresh.
            refresh_view()
            # Persist as 'last_event_freq' NOW (not only when Dream is
            # actually started) — so 'Dream — Start & Schedule', if opened
            # afterward, shows this frequency in 'Log-Frequency'
            # immediately, instead of whatever was last used for an
            # actual Dream start (which could be an old, unrelated value).
            self.cfg.set('last_event_freq', station_khz)
            list_status.config(
                text=f'Station {station_khz} kHz sent to RX '
                     f'(SDR offset, if enabled, applied automatically). '
                     f'Start Dream manually if you want to log this.',
                fg='#007700')

        tv.bind('<<TreeviewSelect>>', on_row_select)
        list_status.pack(fill=tk.X, padx=10, pady=(0,4))

        # ── Presets row (5 buttons, empty by default) ───────────
        preset_row = tk.LabelFrame(rl, text='Presets', bg=GUI_BG,
                                    font=('Arial',8,'bold'))
        preset_row.pack(side=tk.LEFT, padx=8, pady=(0,4))

        # Explanatory text now lives INSIDE the Presets frame, above the
        # button row — and Close (below) is the only OTHER side=LEFT
        # sibling at the 'rl' level, so there is no longer a mix of
        # side=LEFT and side=TOP widgets sharing the same row. That mix
        # was the actual cause of the hint text being squeezed off to
        # the right in the previous version — nothing to do with the
        # Close button's position itself.
        tk.Label(preset_row, text='Left-click a preset: switch to it.   '
                                  'Right-click a preset: save the '
                                  'current Log-Frequency into it.',
                 bg=GUI_BG, font=('Arial',8), fg='#555555',
                 justify=tk.LEFT).pack(anchor='w', padx=4, pady=(2,4))

        preset_btn_row = tk.Frame(preset_row, bg=GUI_BG)
        preset_btn_row.pack(fill=tk.X)

        presets = list(self.cfg.get('drm_radio_presets', ['','','','','']))
        while len(presets) < 4:
            presets.append('')
        preset_btns = []

        def _preset_label(i):
            return f'{presets[i]} kHz' if presets[i] else f'Preset {i+1} (empty)'

        def preset_click(i):
            if not presets[i]:
                list_status.config(
                    text=f'Preset {i+1} is empty — right-click it to '
                         f'save the current Log-Frequency there.',
                    fg='#cc6600')
                return
            # Same collision guard as on_row_select() above — a preset
            # click must not retune the receiver while a Dream session
            # (started from anywhere: manual, Schedule&Event, or the
            # 'Dream Log' button here) is already active.
            if self._is_dream_running():
                try:
                    rl.lift()
                    rl.focus_force()
                except Exception:
                    pass
                messagebox.showinfo(
                    'Dream Log', 'Stop Dream first.', parent=rl)
                list_status.config(text='Stop Dream first.', fg='#cc0000')
                return
            freq_var.set(presets[i])
            ok = set_to_log_freq()
            _record_last_choice(presets[i])
            # Aug 2026: same immediate refresh as the row-click path.
            refresh_view()
            self.cfg.set('last_event_freq', presets[i])
            if ok:
                list_status.config(
                    text=f'Preset {i+1}: frequency {presets[i]} kHz sent to RX.',
                    fg='#007700')
            # else: set_to_log_freq() already put the real error/status
            # message into list_status — nothing more to do here.

        def preset_save(i):
            freq = freq_var.get().strip()
            if not freq:
                list_status.config(
                    text='Enter/select a frequency first (Log-Frequency '
                         'field), then right-click a preset to save it.',
                    fg='#cc6600')
                return
            presets[i] = freq
            self.cfg.set('drm_radio_presets', presets)
            preset_btns[i].config(text=_preset_label(i))
            list_status.config(text=f'Preset {i+1} saved: {freq} kHz.',
                               fg='#007700')

        for i in range(4):
            b = tk.Button(preset_btn_row, text=_preset_label(i), font=('Arial',9),
                          width=15, bg='#dde8ff',
                          command=lambda i=i: preset_click(i))
            b.pack(side=tk.LEFT, padx=4, pady=4)
            b.bind('<Button-3>', lambda ev, i=i: preset_save(i))
            preset_btns.append(b)

        # ── Start Dream / Stop Dream — stacked, same size as Close ──────
        # Deliberately reuse the exact same shared logic as everywhere
        # else in the programme:
        #   - Stop Dream  -> self._stop_dream_from_main() (already
        #     existed, built exactly for "callable without the Schedule
        #     dialog open").
        #   - Start Dream -> self._start_dream_now_from_main() — NEVER
        #     starts a log.
        #   - Dream Log   -> self._start_dream_with_log_from_main() — the
        #     'Dream — Start & Schedule' button of the same name is now
        #     removed entirely (Aug 2026); this is the only place left
        #     to start a logged Dream session, using whichever frequency
        #     is currently in freq_var (station click, preset, or —
        #     unlikely here but harmless — left over from a previous
        #     manual entry).
        start_stop_col = tk.Frame(rl, bg=GUI_BG)
        start_stop_col.pack(side=tk.LEFT, padx=(100,4), pady=(0,4))

        def _start_dream_click():
            # Stage 2 (Aug 2026, user request): same warning the
            # 'Dream — Start & Schedule' dialog's own Start Dream
            # buttons already show — a Timer-Event start imminent
            # within 60s. Previously missing here even though the
            # underlying collision-avoidance itself (pre-stop at T-60s,
            # and the final safety net inside the Timer-Event start
            # itself) already worked correctly regardless of which
            # window the manual start came from.
            _slot_no = self._imminent_timer_event_slot()
            if _slot_no is not None:
                try:
                    rl.lift()
                    rl.focus_force()
                except Exception:
                    pass
                if not messagebox.askyesno(
                        'Timer-Event',
                        f'Timer-Event slot {_slot_no} starts within the '
                        f'next 60 seconds.\n\n'
                        f'Start Dream manually anyway?',
                        parent=rl):
                    return
            ok, msg = self._start_dream_now_from_main(freq_var.get().strip())
            list_status.config(text=msg, fg='#007700' if ok else '#cc0000')

        def _stop_dream_click():
            self._stop_dream_from_main()
            list_status.config(text='Stop Dream sent.', fg='#007700')

        def _dream_log_click():
            # Stage 2 (Aug 2026, user request) — same warning as
            # _start_dream_click() above.
            _slot_no = self._imminent_timer_event_slot()
            if _slot_no is not None:
                try:
                    rl.lift()
                    rl.focus_force()
                except Exception:
                    pass
                if not messagebox.askyesno(
                        'Timer-Event',
                        f'Timer-Event slot {_slot_no} starts within the '
                        f'next 60 seconds.\n\n'
                        f'Start Dream manually anyway?',
                        parent=rl):
                    return
            ok, msg = self._start_dream_with_log_from_main(freq_var.get().strip())
            if ok and ap_flag_var.get():
                # 'Start with AutoPlot (10s)' checkbox — reuse the same
                # log-directory resolution _start_dream_with_log_from_main()
                # itself uses internally, so the just-started log is found
                # reliably regardless of Dream's install location.
                _log_dir = self.cfg.get('dream_log_path', '').strip()
                if not (_log_dir and os.path.isdir(_log_dir)):
                    _dream_path = self.cfg.get('dream_path', '').strip()
                    _log_dir = (os.path.dirname(os.path.abspath(_dream_path))
                                if _dream_path else '')
                if _log_dir:
                    self._radio_list_start_autoplot_after_log(_log_dir)
            if not ok and msg == 'Stop Dream first.':
                # This one specific message is easy to miss as a small
                # status-label line (user feedback, Aug 2026) — shown as
                # a proper popup instead. parent=rl ties it to the
                # DRM-Radio-List window, guaranteeing it stays on top and
                # visible. Deliberately messagebox.showinfo (black text,
                # single 'OK' button, no red) rather than showwarning/
                # showerror — this is a plain heads-up, not an error.
                # Every other outcome of this button keeps using
                # list_status as before — only this one message gets the
                # popup treatment, by explicit request.
                # Aug 2026: lift/focus_force ensures this collision
                # warning rises above every other already-open
                # DRMLogPlotter window, not just its immediate parent.
                try:
                    rl.lift()
                    rl.focus_force()
                except Exception:
                    pass
                messagebox.showinfo('Dream Log', msg, parent=rl)
            list_status.config(text=msg, fg='#007700' if ok else '#cc0000')

        # Layout (user-approved, Aug 2026) — ALL FOUR buttons share one
        # single grid now, rather than Close being a separately packed
        # sibling with hand-tuned padx/pady/anchor. An explicit shared
        # grid ("unsichtbares Raster", per user suggestion) makes exact
        # row alignment a given, not something to eyeball via padding:
        #   [ Start Dream ]   [ Dream Log ]
        #   [ Stop Dream  ]   [   Close   ]
        # Close sits in the SAME grid column as 'Start Dream with Log'
        # (column=1) and the SAME grid row as 'Stop Dream' (row=1) — by
        # construction (not by a hand-tuned padx offset any more, per
        # user request Aug 2026), it is now exactly centred directly
        # below 'Start Dream with Log', regardless of button/font sizing
        # on any platform.
        tk.Button(start_stop_col, text='Start Dream', font=('Arial',9),
                  width=10, bg='#aaddaa',
                  command=_start_dream_click).grid(row=0, column=0, padx=(0,4), pady=(0,2))
        tk.Button(start_stop_col, text='Start Dream with Log', font=('Arial',9),
                  bg='#aaddaa',
                  command=_dream_log_click).grid(row=0, column=1, pady=(0,2))
        # 'Start with AutoPlot (10s)' checkbox (Aug 2026) — sits directly
        # beside 'Start Dream with Log', per user request. Remembered
        # across sessions (persisted in cfg), also per explicit user
        # request: a quick DX-check of one station after another should
        # keep showing the plot without having to re-tick this every
        # time. Interval is deliberately fixed at 10s, not offered as a
        # choice — see _radio_list_start_autoplot_after_log() /
        # _start_autoplot_silent() for the actual (unchanged, reused)
        # AutoPlot-start logic this only triggers.
        ap_flag_var = tk.BooleanVar(
            value=bool(self.cfg.get('radio_list_autoplot_flag', False)))
        def _on_ap_flag_change():
            self.cfg.set('radio_list_autoplot_flag', bool(ap_flag_var.get()))
        tk.Checkbutton(start_stop_col, text='Start with AutoPlot (10s)',
                       variable=ap_flag_var, bg=GUI_BG, font=('Arial',8),
                       command=_on_ap_flag_change).grid(
                       row=0, column=2, padx=(10,0), sticky='w')
        tk.Button(start_stop_col, text='Stop Dream', font=('Arial',9),
                  width=10, bg='#ffccaa',
                  command=_stop_dream_click).grid(row=1, column=0, padx=(0,4))
        # Forward-referencing _on_rl_close() via a lambda is required
        # here since it is only DEFINED further below in this same
        # function, but only ever CALLED later on click, by which
        # point it already exists.
        tk.Button(start_stop_col, text='Close', font=('Arial',9), width=10,
                  bg='#dddddd',
                  command=lambda: _on_rl_close()).grid(
                  row=1, column=1)

        # ── Auto-refresh once a minute: re-colour + re-apply 'Active'
        # sort. Purely cosmetic within this window — no effect on
        # Dream, rigctl, or anything else in DRMLogPlotter.
        # Interval shortened 60s -> 5s (Aug 2026, user request): with
        # the 60s interval, the red ('starts soon') -> green ('on air')
        # colour switch could lag up to a full minute behind the
        # station's actual start time. 5s keeps the list lightweight to
        # redraw (typically well under a few hundred rows) while making
        # that colour change appear within a few seconds of the real
        # start. ──
        _rl_after_id = [None]

        def _auto_refresh():
            if not _rl_alive[0]:
                return
            refresh_view()
            _rl_after_id[0] = rl.after(5000, _auto_refresh)

        def _on_rl_close():
            _rl_alive[0] = False
            if _rl_after_id[0]:
                try: rl.after_cancel(_rl_after_id[0])
                except Exception: pass
            rl.destroy()
        rl.protocol('WM_DELETE_WINDOW', _on_rl_close)

        # self.drm_schedule is already loaded at programme start (if a
        # path was saved before) or via the Load/Edit buttons above —
        # just reflect its current state here.
        if self.drm_schedule:
            _show_loaded_status(len(self.drm_schedule), path_var.get())
        elif path_var.get() and os.path.isfile(path_var.get()):
            entries = parse_drm_schedule(path_var.get())
            if entries:
                self.drm_schedule = entries
                _show_loaded_status(len(entries), path_var.get())

        refresh_view()
        _rl_after_id[0] = rl.after(5000, _auto_refresh)


    # ── Dream.ini helper — sets [Logfile] enablelog + delay ──────────
    def _write_dream_ini(self, enable_log):
        """
        Write enablelog and delay into Dream.ini before starting Dream.

        Dream.ini location is resolved via self._resolve_dream_ini_path()
        — NOT assumed to always sit next to the Dream executable, since
        some Dream builds (confirmed on Linux) keep it in the user's
        home directory instead. See _resolve_dream_ini_path() for the
        full priority order and "Dream.ini location" in RX Config for
        the manual override.

        Dream.ini uses a non-standard format with duplicate keys:
            enablelog=0
            enablelog = 0
        Both variants must be updated. We read line-by-line and write
        back unchanged — no configparser, no format destruction.

        enable_log=True  → enablelog=1, delay=15  (both variants)
        enable_log=False → enablelog=0             (both variants)
                           delay is NOT changed on disable
        Returns (ok, error_message) — error_message is '' on success.
        """
        path = self.cfg.get('dream_path', '').strip()
        if not path:
            return False, 'Please set Dream path in RX Config first!'
        ini_path = self._resolve_dream_ini_path()
        if not ini_path:
            return False, ('Dream.ini not found — checked program folder '
                           'and home directory. Set it manually via '
                           '"Dream.ini location" in RX Config.')
        try:
            # Read raw lines — preserve encoding and line endings exactly
            with open(ini_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            in_logfile = False   # True while inside [Logfile] section
            new_lines  = []
            enablelog_val = '1' if enable_log else '0'

            for line in lines:
                stripped = line.strip()

                # Detect section headers
                if stripped.startswith('['):
                    in_logfile = (stripped.lower() == '[logfile]')
                    new_lines.append(line)
                    continue

                if in_logfile:
                    # Match both variants:
                    #   "enablelog=0"   and   "enablelog = 0"
                    #   "delay=0"       and   "delay = 0"
                    key_raw = stripped.split('=')[0].strip().lower() if '=' in stripped else ''

                    if key_raw == 'enablelog':
                        # Preserve original spacing around '='
                        if ' = ' in line:
                            new_lines.append('enablelog = ' + enablelog_val + '\n')
                        else:
                            new_lines.append('enablelog=' + enablelog_val + '\n')
                        continue

                    if key_raw == 'delay':
                        # Enable  → delay=15  (Dream waits for label to appear)
                        # Disable → delay=0   (restore clean state for manual use)
                        delay_val = '15' if enable_log else '0'
                        if ' = ' in line:
                            new_lines.append(f'delay = {delay_val}\n')
                        else:
                            new_lines.append(f'delay={delay_val}\n')
                        continue

                new_lines.append(line)

            # Write back — same encoding, original line endings preserved
            with open(ini_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)

            return True, ''

        except Exception as ex:
            return False, f'Dream.ini write error: {ex}'

    # ── Helper: check if Dream is already running ─────────────────────
    def _is_dream_running(self):
        """
        Check whether a Dream process is already running on this computer.

        Uses OS-level process inspection — detects Dream regardless of
        how it was started (manually by the user, or via drmlogplotter).

        Windows : 'tasklist' — searches for Dream.exe (case-insensitive)
        Linux   : 'pgrep'   — searches for dream or dream.bin or Dream.bin

        Returns True  = Dream IS running  → block the start
        Returns False = Dream is NOT running → allow the start
        """
        import subprocess
        import platform
        try:
            if platform.system() == 'Windows':
                result = _subprocess_run(
                    ['tasklist', '/FI', 'IMAGENAME eq Dream.exe',
                     '/NH', '/FO', 'CSV'],
                    capture_output=True, text=True, timeout=5,
                    encoding='utf-8', errors='replace')
                return 'dream.exe' in result.stdout.lower()
            else:
                # pgrep -i performs a case-insensitive name search.
                # Returns exit-code 0 when at least one match is found.
                result = subprocess.run(
                    ['pgrep', '-i', '-x', 'dream'],
                    capture_output=True, timeout=5)
                if result.returncode == 0:
                    return True
                # Also check dream.bin / Dream.bin explicitly
                result2 = subprocess.run(
                    ['pgrep', '-i', '-f', 'dream.bin'],
                    capture_output=True, timeout=5)
                return result2.returncode == 0
        except Exception:
            # If the OS call fails for any reason, allow the start
            # (fail-open: better than blocking a valid start attempt).
            return False

    def _build_text_clock(self, parent, alive_flag, font=('Arial', 14, 'bold'),
                           tight=False):
        """
        Simple UTC clock, HH:MM:SS — plain text Label, same font style as
        the 'Last choice was' display right next to it (Aug 2026, user
        request: the earlier 7-segment Canvas version 'funktioniert
        leider nicht', replaced with this instead). Background matches
        the surrounding dialog (GUI_BG) rather than a boxed-in black
        Canvas — 'transparent wie bei Last choice'. Same bright-blue
        text colour as before.

        Shared between the Main-GUI's DRM-Radio-List, the
        'Radio-List for Timer-Event' window, and (Aug 2026, user
        request) the small clock in the Main-GUI's 'TX Sites and UTC'
        frame.

        alive_flag is the SAME [True]/[False] list each window already
        uses for its own 60s auto-refresh loop (_rl_alive / _rl2_alive)
        — reused here so the clock's own 1-second tick loop stops
        itself automatically when that window closes.

        font: overridable so the tight Main-GUI frame can use a smaller
        size than the roomier Radio-List dialogs while keeping the same
        family/weight/colour (default stays ('Arial',14,'bold') so the
        two existing call sites are completely unaffected).

        tight: Aug 2026, user feedback round 3 — when True, zeroes the
        Label's own default border/highlight-thickness/pady. Tk reserves
        a small amount of this by default on every Label (even one that
        never gets keyboard focus), which was enough extra height in
        the space-starved Main-GUI 'TX Sites and UTC' frame to push the
        TX Sites / Radio List buttons a couple of pixels below their
        neighbours. Default False — the two existing Radio-List dialogs
        (plenty of room, never reported as an issue) keep Tk's normal
        defaults exactly as before.

        Returns the Label widget (caller places/packs it).
        """
        clock_var = tk.StringVar()
        if tight:
            lbl = tk.Label(parent, textvariable=clock_var, bg=GUI_BG,
                           font=font, fg='#008800',
                           bd=0, highlightthickness=0, pady=0)
        else:
            lbl = tk.Label(parent, textvariable=clock_var, bg=GUI_BG,
                           font=font, fg='#008800')

        def _tick():
            if not alive_flag[0]:
                return   # window closed — let this loop end itself
            clock_var.set(datetime.now(timezone.utc).strftime('%H:%M:%S'))
            try:
                lbl.after(1000, _tick)
            except Exception:
                pass

        _tick()
        return lbl

    def _imminent_timer_event_slot(self, window_secs=60):
        """Returns the 1-based slot number if any Timer-Event's own
        start is still pending (start-timer alive) AND due within
        window_secs seconds — else None.

        Aug 2026, user request: Stage 2 of the two-stage collision
        protection — warns the user BEFORE they manually start Dream
        into an imminent Timer-Event, mirroring the same 60s window the
        pre-stop timer (_make_slot_prestop_check, in _set_event())
        already uses.

        Promoted from a local helper inside _set_event() to a proper
        shared method (Aug 2026) so both manual-start entry points can
        use it: the 'Dream — Start & Schedule' dialog's own Start Dream
        buttons, AND the separate 'Radio List' window's Start Dream /
        Start Dream with Log buttons — previously only the former had
        this warning. Reads only self._sched_timers / self._sched_state,
        so it works identically regardless of which window calls it, or
        whether the Schedule dialog itself is even open."""
        now = datetime.now()
        for i in range(len(self._sched_state)):
            pair = self._sched_timers[i]
            t_s = pair[0]
            if t_s is None or not t_s.is_alive():
                continue   # not waiting to start — irrelevant
            start_dt = self._sched_state[i].get('start_dt')
            if not start_dt:
                continue
            remaining = (start_dt - now).total_seconds()
            if 0 <= remaining <= window_secs:
                return i + 1
        return None

    def _start_dream_with_log_from_main(self, freq_khz):
        """
        Starts Dream WITH logging — shared by the standalone 'Dream Log'
        button in the DRM-Radio-List window (whether opened from the
        Main-GUI's 'Transmitter Site' frame or, in principle, from
        anywhere else) and mirrors exactly what 'Start Dream with Log' in
        'Dream — Start & Schedule' does for a manual start there (that
        button always disables AutoPlot for manual starts — so this
        method deliberately never touches AutoPlot either; nothing lost).

        freq_khz is required (matches 'Start Dream with Log' in the
        dialog, which also refuses to start without one) — a frequency
        is meaningless to log without.

        Returns (ok: bool, message: str).
        """
        import subprocess
        if self._is_dream_running():
            return False, 'Stop Dream first.'
        if not freq_khz:
            return False, 'Please select a station/frequency first!'
        path = self.cfg.get('dream_path', '').strip()
        if not path or not os.path.exists(path):
            return False, 'Please set Dream path in RX Config first!'
        ok, err = self._write_dream_ini(True)
        if not ok:
            return False, err
        try:
            cmd = [path, '-r', str(freq_khz)]
            self.cfg.set('last_event_freq', str(freq_khz))
            _dream_dir = os.path.dirname(os.path.abspath(path))
            # Same X11/xWayland/Wayland handling as the dialog's own
            # _do_start() — see there for the full rationale. Only
            # affects Linux; no-op on Windows/macOS.
            dream_env = os.environ.copy()
            if _platform.system() == 'Linux':
                _display_mode = self.cfg.get('dream_display_mode', 'xwayland')
                if _display_mode != 'wayland':
                    if _is_linux_wayland_session() and not _xwayland_available():
                        return False, ('XWayland not found — install with: '
                                       'sudo apt install xwayland')
                    dream_env['QT_QPA_PLATFORM'] = 'xcb'
            proc = subprocess.Popen(cmd, cwd=_dream_dir, env=dream_env)
            self._dream_proc[0] = proc
            try:
                self._stop_dream_btn.configure(state=tk.NORMAL)
            except Exception:
                pass
            self._dream_start_time = datetime.now()
            self._dream_log_flag   = True

            # ── Schedule audio info read 30s after Dream start — same as
            # the dialog's own _do_start() does for enable_log=True. ────
            _configured_log_path = self.cfg.get('dream_log_path', '').strip()
            if _configured_log_path and os.path.isdir(_configured_log_path):
                _log_dir_audio = _configured_log_path
            else:
                _log_dir_audio = os.path.dirname(os.path.abspath(path))
            _st_str = self._dream_start_time.strftime('%Y-%m-%d %H:%M:%S')
            self._schedule_dream_audio_read(
                _log_dir_audio, _st_str, str(freq_khz), delay_ms=30000)

            return True, f'Dream Log started at {freq_khz} kHz.'
        except Exception as ex:
            return False, f'Could not start Dream: {ex}'

    def _start_dream_now_from_main(self, freq_khz):
        """
        Starts Dream WITHOUT logging — "just to listen". Shared by the
        'Start Dream Now' button in 'Dream Manual Start / Stop' and the
        standalone 'Start Dream' button in the DRM-Radio-List window,
        whether that window was opened from inside 'Dream — Start &
        Schedule' or directly, standalone, from the Main-GUI's
        'Transmitter Site' frame.

        Logging must always go through 'Dream — Start & Schedule' — this
        method never enables it, by explicit design (user requirement,
        Aug 2026): "Start Dream" outside that dialog is for listening
        only, never for producing a log file.

        Mirrors the existing self._stop_dream_from_main() in spirit —
        callable with or without 'Dream — Start & Schedule' open.

        Returns (ok: bool, message: str).
        """
        import subprocess
        if self._is_dream_running():
            return False, ('Dream is already running.\n\n'
                            'Only one instance of Dream can be active at a '
                            'time. Please stop the running Dream first.')
        path = self.cfg.get('dream_path', '').strip()
        if not path or not os.path.exists(path):
            return False, 'Please set Dream path in RX Config first!'
        ok, err = self._write_dream_ini(False)
        if not ok:
            return False, err
        try:
            cmd = [path]
            if freq_khz:
                cmd += ['-r', str(freq_khz)]
                self.cfg.set('last_event_freq', str(freq_khz))
            _dream_dir = os.path.dirname(os.path.abspath(path))
            # Same X11/xWayland/Wayland handling as the dialog's own
            # _do_start() — see there for the full rationale. Only
            # affects Linux; no-op on Windows/macOS.
            dream_env = os.environ.copy()
            if _platform.system() == 'Linux':
                _display_mode = self.cfg.get('dream_display_mode', 'xwayland')
                if _display_mode != 'wayland':
                    if _is_linux_wayland_session() and not _xwayland_available():
                        return False, ('XWayland not found — install with: '
                                       'sudo apt install xwayland')
                    dream_env['QT_QPA_PLATFORM'] = 'xcb'
            proc = subprocess.Popen(cmd, cwd=_dream_dir, env=dream_env)
            self._dream_proc[0] = proc
            try:
                self._stop_dream_btn.configure(state=tk.NORMAL)
            except Exception:
                pass
            self._dream_start_time = datetime.now()
            self._dream_log_flag   = False
            if freq_khz:
                return True, f'Dream started at {freq_khz} kHz (no log).'
            return True, 'Dream started (no log).'
        except Exception as ex:
            return False, f'Could not start Dream: {ex}'

    def _set_event(self):
        """
        Dream Simple Scheduled Event.
        Starts and stops Dream.exe at a pre-set local time with a given frequency.
        Uses subprocess to launch Dream with the -r <freq> parameter.
        """
        import threading
        import platform

        # ── Show info window on first use (unless disabled by user) ──────────
        if self.cfg.get('set_event_info_shown', True):
            self._show_dream_info_window()

        # Default Dream path based on OS
        dlg = tk.Toplevel(self.root)
        dlg.title('Dream — Start & Schedule')
        dlg.configure(bg=GUI_BG)
        # Resizable by mouse-drag (Aug 2026, user request) — was
        # previously locked to a fixed size (resizable(False, False)),
        # which also silently prevented the user from dragging it larger
        # themselves if e.g. the Close button was still cut off for them.
        # minsize prevents shrinking back below the safe height fixed
        # earlier — Windows keeps its extra safety margin as a hard
        # floor, not just a one-time default.
        dlg.resizable(True, True)
        # Windows-only extra height (Aug 2026, user request): a user
        # reported the Close button cut off at the bottom on their
        # Windows 11 PC — not reproducible on the developer's own W11
        # machines, most likely due to a difference in Windows display
        # scaling (100%/125%/150%...) rather than the Windows version
        # itself. One extra button-height (~60px) of safety margin,
        # added only on Windows — Linux/macOS keep the exact original
        # 720px height, unchanged.
        _target_h = 780 if _platform.system() == 'Windows' else 720
        # Minsize lowered (Aug 2026, user request) — was locked to
        # (780, _target_h), i.e. effectively the same as the default
        # size, so the window could only be dragged LARGER, never
        # smaller. Same freedom as 'Basic Setup Parameters' (minsize
        # 650x500): the user decides how much of the dialog they want
        # visible — e.g. shrinking it down to only show the Timer-Event
        # rows. _target_h (the Windows Close-button safety margin) still
        # sets the DEFAULT/initial height on first open; it just no
        # longer forces a floor the user can never shrink below.
        dlg.minsize(600, 300)
        # Aug 2026: the "ignore saved geometry if smaller than
        # _target_h" migration guard from the Windows-height fix has
        # been REMOVED here — it was only ever meant to repair a
        # too-small size saved by an old, pre-fix version. Now that the
        # user can deliberately resize this dialog much smaller on
        # purpose (minsize just above), that same guard was wrongly
        # treating every intentionally-shrunk size as "old and broken"
        # and silently reverting it back to the default size on every
        # open. The saved geometry is now always trusted; dlg.minsize()
        # above already guarantees it can never be smaller than usable.
        _saved_se_geom = self.cfg.get('set_event_geometry', '')
        if _saved_se_geom:
            try:
                dlg.geometry(_saved_se_geom)
            except Exception:
                center_dialog(dlg, self.root, 780, _target_h)
        else:
            center_dialog(dlg, self.root, 780, _target_h)

        def _save_se_geometry(event=None):
            if event is not None and event.widget is not dlg:
                return
            try:
                self.cfg.set('set_event_geometry', dlg.geometry())
            except Exception:
                pass
        dlg.bind('<Configure>', _save_se_geometry, add='+')

        dlg.grab_set()
        dlg.transient(self.root)   # v_rig_test_06: keep dialog above its parent
        dlg.lift()
        dlg.focus_force()

        # ══════════════════════════════════════════════════════════════════
        # STATUS FRAME — top of dialog, shows all 4 LEDs + status text
        # ══════════════════════════════════════════════════════════════════
        # LED helper
        LED_COLORS = {
            'grey'  : ('#888888', '#555555'),
            'green' : ('#22cc22', '#116611'),
            'yellow': ('#ffee00', '#ccaa00'),
            'red'   : ('#cc2222', '#881111'),
            'blue'  : ('#2277ff', '#0044bb'),   # done — event completed
            'orange': ('#ff8800', '#cc5500'),   # manually stopped — early end
        }
        def make_led(parent):
            c = tk.Canvas(parent, width=16, height=16, bg=GUI_BG,
                          highlightthickness=0)
            o = c.create_oval(2, 2, 14, 14, fill='#888888', outline='#555555')
            return c, o
        def set_led(canvas, oval, color):
            fill, outline = LED_COLORS.get(color, LED_COLORS['grey'])
            canvas.itemconfig(oval, fill=fill, outline=outline)

        fst = tk.LabelFrame(dlg, text='Status', bg=GUI_BG,
                            font=('Arial',9,'bold'), padx=8, pady=6)
        fst.pack(fill=tk.X, padx=10, pady=(10,4))

        # Row 1 — four LEDs
        led_row = tk.Frame(fst, bg=GUI_BG)
        led_row.pack(fill=tk.X, pady=(2,6))

        def _make_led_item(parent, label):
            c, o = make_led(parent)
            c.pack(side=tk.LEFT, padx=(10,2))
            tk.Label(parent, text=label, bg=GUI_BG,
                     font=('Arial',9)).pack(side=tk.LEFT, padx=(0,10))
            return c, o

        led1_c, led1_o = _make_led_item(led_row, 'RX Connected')
        led2_c, led2_o = _make_led_item(led_row, 'Frequency Set')
        led3_c, led3_o = _make_led_item(led_row, 'Dream')
        led4_c, led4_o = _make_led_item(led_row, 'Dream Log')
        led5_c, led5_o = _make_led_item(led_row, 'Timer')
        led6_c, led6_o = _make_led_item(led_row, 'AutoPlot')

        # Row 2 — status text (replaces bottom status_lbl)
        status_lbl = tk.Label(fst, text='Ready.', bg=GUI_BG,
                              font=('Arial',9,'italic'), fg='#555555',
                              anchor='w')
        status_lbl.pack(fill=tk.X, padx=10, pady=(0,4))

        # Holds the timestamp until which the periodic 'Ready.' reset in
        # _refresh_status() below must NOT overwrite status_lbl — used by
        # important validation warnings (e.g. accept_schedule()'s gap
        # check) so they stay visible for a fixed duration instead of
        # being wiped out by the very next 2-second refresh tick.
        _status_hold_until = [None]
        def _show_status_warning(text, hold_secs=10, fg='#cc0000'):
            status_lbl.config(text=text, fg=fg)
            _status_hold_until[0] = datetime.now() + timedelta(seconds=hold_secs)

        # ══════════════════════════════════════════════════════════════════
        # HELPER: find Dream.ini next to Dream.exe or in known locations
        # ══════════════════════════════════════════════════════════════════
        # ══ # ══════════════════════════════════════════════════════════════════
        # ══════════════════════════════════════════════════════════════════
        # ── Dream process reference — point to self for dialog survival ──
        dream_proc   = self._dream_proc    # survives dialog close
        monitor_stop = self._monitor_stop  # survives dialog close

        def _safe_led(key, canvas, oval, color):
            """Set a Status-frame LED — saves state and guards widget call."""
            self._sched_led_status[key] = color
            try:
                set_led(canvas, oval, color)
            except Exception:
                pass   # dialog closed — state saved, widget gone

        # Aug 2026, user request: RED on 'Frequency Set' is meant only as
        # a brief, non-alarming nudge ('Hamlib found nothing to switch'),
        # not a permanent warning — auto-reverts to grey after 9s unless
        # overwritten sooner by a fresh result. Single in-flight timer
        # (list, not plain var, so the closure below can rebind it) —
        # a new failure cancels and restarts the countdown rather than
        # stacking timers.
        _led2_red_timeout_id = [None]
        def _flash_led2_red(delay_ms=9000):
            if _led2_red_timeout_id[0] is not None:
                try:
                    dlg.after_cancel(_led2_red_timeout_id[0])
                except Exception:
                    pass
            def _revert():
                _led2_red_timeout_id[0] = None
                # Only revert if still red — a newer green/red result in
                # the meantime must not be undone by this stale timer.
                if self._sched_led_status.get('led2') == 'red':
                    _safe_led('led2', led2_c, led2_o, 'grey')
            try:
                _led2_red_timeout_id[0] = dlg.after(delay_ms, _revert)
            except Exception:
                pass   # dialog already closed

        def _report_rigctl_result(ok, msg, fg, led, status_widget=None):
            """Central place (Aug 2026, user request) for turning a
            self._send_freq_to_rigctl() result into led1/led2 state +
            status text for THIS dialog's Status frame. Used by both the
            manual 'Set' button and the Timer-Event firing logic below,
            so the two are guaranteed to always behave identically —
            exactly one place to maintain instead of two independent
            copies of the same decision.

            led=='green': a real rigctl send succeeded — led1+led2 solid
              green, no timeout, full message shown.
            led=='red': a real rigctl attempt was made and genuinely
              failed (TRX IS configured, but e.g. wrong COM port/device
              not responding) — led1 also goes red (kept for 'RX
              Connected' consistency), led2 flashes red for 9s then
              auto-greys, and the DETAILED technical message from
              _send_freq_to_rigctl is shown, since a genuinely
              configured device is worth troubleshooting properly.
            led is None: nothing was even attempted. Two different
            reasons, deliberately handled differently (Aug 2026, user
            logic: 'no function enabled -> no query at all'):
              - 'Enable RX Control' is explicitly OFF in RX Config: the
                user has consciously said they have no remote-
                controllable RX at all — led2 is left completely
                untouched (stays grey, no flash, no timer). Only the
                status text (if any) shows the factual 'not enabled'
                message, so a click still gets *some* visible
                confirmation, just not an LED that implies a failed
                attempt at something that was never asked for.
              - 'Enable RX Control' is ON (the default) but nothing else
                is configured yet — Hamlib genuinely 'found nothing to
                switch'. This IS still worth a brief visual nudge (the
                user may be expecting remote control and not realise
                it's unconfigured) — led2 flashes red for 9s then
                auto-greys, with the short, non-technical hint instead
                of the detailed configuration message.
            """
            if led == 'green':
                _safe_led('led1', led1_c, led1_o, 'green')
                _safe_led('led2', led2_c, led2_o, 'green')
                if status_widget is not None:
                    # Aug 2026 bugfix: a plain status_widget.config() here
                    # was overwritten almost instantly by the dialog's own
                    # periodic 2s 'Ready.' refresh — _show_status_warning()
                    # holds it visible for a fixed duration instead.
                    _show_status_warning(msg, hold_secs=5, fg=fg)
                return
            if led == 'red':
                _safe_led('led1', led1_c, led1_o, 'red')
                _safe_led('led2', led2_c, led2_o, 'red')
                _flash_led2_red()
                if status_widget is not None:
                    _show_status_warning(msg, hold_secs=5, fg=fg)
                return
            # led is None — RX Control off entirely -> leave led2 alone.
            if not self.cfg.get('trx_enable', 0):
                if status_widget is not None:
                    _show_status_warning(msg, hold_secs=5, fg=fg)
                return
            # RX Control on, but nothing else configured -> the existing
            # brief red nudge + short hint.
            _safe_led('led2', led2_c, led2_o, 'red')
            _flash_led2_red()
            if status_widget is not None:
                _show_status_warning(
                    'No Hamlib/rigctl possible - Please check Basic Setup',
                    hold_secs=5, fg='#cc6600')


        def _start_monitor():
            import threading, time
            def _monitor():
                while not monitor_stop[0]:
                    time.sleep(3)
                    if monitor_stop[0]: break
                    proc = dream_proc[0]
                    if proc is not None and proc.poll() is not None:
                        dream_proc[0] = None
                        def _mon_ui_ext():
                            _safe_led('led3', led3_c, led3_o, 'red')
                            _safe_led('led4', led4_c, led4_o, 'grey')
                            try:
                                status_lbl.config(
                                    text='Dream was closed externally.',
                                    fg='#cc6600')
                            except Exception: pass
                        def _mon_ui_reset():
                            if dream_proc[0] is None:
                                _safe_led('led3', led3_c, led3_o, 'grey')
                                try:
                                    status_lbl.config(text='', fg='#555555')
                                except Exception: pass
                        self.root.after(0,    _mon_ui_ext)
                        self.root.after(5000, _mon_ui_reset)
                        break
            t = threading.Thread(target=_monitor, daemon=True)
            t.start()

        def _on_dlg_close():
            _dlg_alive[0] = False   # stop _refresh_loop
            # Cancel any pending after() call — prevents
            # 'invalid command name' error on Windows
            if _refresh_after_id[0]:
                try:
                    dlg.after_cancel(_refresh_after_id[0])
                except Exception:
                    pass
                _refresh_after_id[0] = None
            # Save field values to persistent state (same as Close button)
            for i in range(NUM_SLOTS):
                sv = slot_vars[i]
                current_led = self._sched_state[i]['led']
                self._sched_state[i].update({
                    'sh'      : sv['sh'].get(),
                    'sm'      : sv['sm'].get(),
                    'eh'      : sv['eh'].get(),
                    'em'      : sv['em'].get(),
                    'freq'    : sv['freq'].get(),
                    'log'     : sv['log'].get(),
                    'autoplot': sv['autoplot'].get(),
                    'led'     : current_led,
                })
            monitor_stop[0] = True
            dlg.destroy()
        dlg.protocol('WM_DELETE_WINDOW', _on_dlg_close)

        # ── Core: start Dream — reads config for path and TRX ─────────────
        def _do_start(freq_khz, enable_log):
            """Start Dream using config values for path."""
            import subprocess

            # ── Guard: block a second Dream instance ──────────────────────
            if self._is_dream_running():
                # Aug 2026, user request: ALL collision-warning popups must
                # rise to the very top of this app's own window stack, not
                # stay buried behind other already-open DRMLogPlotter
                # windows. lift()+focus_force() on the parent, right before
                # showing the (now explicitly parented) messagebox.
                try:
                    dlg.lift()
                    dlg.focus_force()
                except Exception:
                    pass
                messagebox.showinfo(
                    'Dream is active',
                    'Dream is already running.\n\n'
                    'Only one instance of Dream can be active at a time.\n'
                    'Please stop the running Dream first.',
                    parent=dlg)
                return
            # ── /Guard ────────────────────────────────────────────────────

            path = self.cfg.get('dream_path', '').strip()
            if not path or not os.path.exists(path):
                try:
                    status_lbl.config(
                        text='Please set Dream path in RX Config first!',
                        fg='#cc0000')
                except Exception: pass
                return
            try:
                # Write Dream.ini before starting — sets enablelog + delay
                _ini_ok, _ini_err = self._write_dream_ini(enable_log)
                if not _ini_ok:
                    try:
                        status_lbl.config(text=_ini_err, fg='#cc0000')
                    except Exception: pass
                    return
                cmd = [path]
                if freq_khz:
                    cmd += ['-r', str(freq_khz)]
                    self.cfg.set('last_event_freq', str(freq_khz))
                _dream_dir = os.path.dirname(os.path.abspath(path))
                # ── Working directory for the Dream process ────────────────
                # Always the Dream program folder (Version 37 behaviour).
                # Confirmed via testing (Linux, 2026-07): Dream.ini and the
                # resulting log files are NOT written relative to cwd — Dream
                # resolves them itself (program folder or home directory, see
                # _resolve_dream_ini_path()). Changing cwd to 'dream_log_path'
                # (tried in v38) had no effect on where Dream actually writes
                # and broke Dream.ini discovery on Linux — reverted.
                #
                # ── Linux only: apply the X11/xWayland/Wayland setting ─────
                # The Basic Setup Parameters radio buttons are visible on
                # every OS (2026-07 decision — avoids user confusion about
                # a 'missing' setting), but only have an actual effect on
                # Linux. On Windows/macOS this block is skipped entirely —
                # forcing QT_QPA_PLATFORM=xcb there would be meaningless at
                # best (no 'xcb' Qt plugin on Windows) and could prevent
                # Dream from starting at worst, so the OS guard below is
                # deliberate and must stay in place regardless of what the
                # user selected in Basic Setup Parameters.
                #
                # 'X11' and 'xWayland' both force the xcb Qt platform plugin
                # — technically the same action. Under a genuine X11 session
                # this is simply the native default (harmless); under a
                # Wayland session it routes Dream through the XWayland
                # compatibility layer, which AT-SPI-based Audio Codec
                # detection (DRMLogPlotter_Audio.py) needs to see Dream's
                # widget tree. Only 'Wayland' leaves dream_env untouched,
                # letting Qt pick its native-Wayland QPA plugin as before.
                dream_env = os.environ.copy()
                if _platform.system() == 'Linux':
                    _display_mode = self.cfg.get('dream_display_mode', 'xwayland')
                    if _display_mode != 'wayland':
                        # The 'Xwayland' binary itself is only required when
                        # actually running under a Wayland session — under
                        # a real X11 session, xcb is already native and no
                        # such check is needed.
                        if _is_linux_wayland_session() and not _xwayland_available():
                            status_lbl.config(
                                text='XWayland not found — install with: '
                                     'sudo apt install xwayland',
                                fg='#cc0000')
                            return
                        dream_env['QT_QPA_PLATFORM'] = 'xcb'
                    # 'wayland' mode: leave dream_env untouched — Qt picks
                    # its own native-Wayland QPA plugin as before.
                dream_proc[0] = subprocess.Popen(
                    cmd, cwd=_dream_dir, env=dream_env)
                self._dream_proc[0] = dream_proc[0]   # share with Main-GUI
                # Enable Stop Dream button in Main-GUI
                try:
                    self._stop_dream_btn.configure(state=tk.NORMAL)
                except Exception:
                    pass
                _safe_led('led3', led3_c, led3_o, 'green')
                _safe_led('led4', led4_c, led4_o, 'green' if enable_log else 'grey')
                self._dream_start_time = datetime.now()
                self._dream_log_flag   = enable_log
                # ── Schedule audio info read 30s after Dream start ────────
                if enable_log:
                    # Priority 1: user-configured dream_log_path in RX Config
                    # Priority 2: same folder as Dream.exe (Windows default)
                    # Priority 3: same folder as already-loaded DreamLog.txt
                    _configured_log_path = self.cfg.get(
                        'dream_log_path', '').strip()
                    if _configured_log_path and os.path.isdir(
                            _configured_log_path):
                        _log_dir_audio = _configured_log_path
                    else:
                        _log_dir_audio = os.path.dirname(os.path.abspath(path))
                    # Frequency — from the value Dream was actually
                    # started with (freq_khz, correct for BOTH manual and
                    # Timer-Event starts — previously this re-read the
                    # manual dialog's own field directly, which could be
                    # stale/unrelated to the actual frequency during a
                    # Timer-Event start), then config, then ''.
                    _fq_raw = str(freq_khz) if freq_khz else ''
                    if not _fq_raw:
                        _fq_raw = str(self.cfg.get('last_event_freq', ''))
                    _fq_str = _fq_raw.strip()
                    _st_str = self._dream_start_time.strftime(
                        '%Y-%m-%d %H:%M:%S')
                    self._schedule_dream_audio_read(
                        _log_dir_audio, _st_str, _fq_str, delay_ms=30000)
                # Use self._autoplot_enabled[0] — set per slot in accept_schedule()
                # or explicitly set to False for manual start.
                _ap_active = self._autoplot_enabled[0]
                if _ap_active:
                    # Determine the folder where Dream writes its log files.
                    # Priority: 1) user-configured dream_log_path in RX Config
                    #           2) same folder as Dream.exe  (Windows default)
                    _configured_log_path = self.cfg.get('dream_log_path', '').strip()
                    if _configured_log_path and os.path.isdir(_configured_log_path):
                        _log_dir = _configured_log_path
                    else:
                        _log_dir = os.path.dirname(os.path.abspath(path))
                    derived_txt = os.path.join(_log_dir, 'DreamLog.txt')
                    derived_csv = os.path.join(_log_dir, 'DreamLogLong.csv')
                    LOG_DELAY = 15    # seconds Dream delays before logging
                    AP_DELAY  =  5    # 5s buffer after log start → total 20s
                    countdown_active = [True]   # set False by stop-timer to cancel
                    self._ap_countdown_active = countdown_active
                    def _ap_countdown():
                        if not countdown_active[0]:
                            return   # stop-timer cancelled
                        # Trigger the actual AutoPlot load.
                        if True:
                            # ── Set paths (always use derived paths here) ──
                            self.txt_path = derived_txt
                            self.csv_path = derived_csv
                            # ── Check files exist ──────────────────────────
                            if not os.path.exists(derived_txt):
                                countdown_active[0] = False
                                _safe_led('led6', led6_c, led6_o, 'red')
                                try:
                                    status_lbl.config(
                                        text=f'AutoPlot: DreamLog.txt not found in:\n'
                                             f'{_log_dir}',
                                        fg='#cc0000')
                                except Exception: pass
                                return
                            try:
                                status_lbl.config(
                                    text='AutoPlot starting...', fg='#007700')
                            except Exception: pass
                            try:
                                # Load both files
                                self.all_logs = parse_dreamlog_txt(derived_txt)
                                self.all_csv  = (load_csv_rows(derived_csv)
                                                 if os.path.exists(derived_csv)
                                                 else [])
                                # Fixed July 2026: this AutoPlot/Timer-Event
                                # auto-load path populates all_logs/sel_log
                                # just like the manual "Update" button does,
                                # but previously forgot to also (re-)enable
                                # the Screenshot button — confirmed as the
                                # cause of it staying greyed out after a
                                # Timer-Event log + AutoPlot finished, on
                                # every OS (not Pi-specific).
                                self.ss_btn.configure(
                                    state=tk.NORMAL if self.all_logs else tk.DISABLED)
                                if self.all_logs:
                                    # Populate the log listbox
                                    self.log_lb.delete(0, tk.END)
                                    for log in self.all_logs:
                                        self.log_lb.insert(tk.END, log.display_name())
                                    self.log_lb.select_set(0)
                                    # Always select the newest log (last entry) —
                                    # Dream appends new logs chronologically at the end.
                                    # Older logs from previous days sit before it.
                                    idx = len(self.all_logs) - 1
                                    self.sel_log = self.all_logs[idx]
                                    self.zoom_active = False
                                    self.zoom_t0 = self.zoom_t1 = None
                                    self._annotations     = []
                                    self._annotation_free = ''
                                    self._show_vlines     = True
                                    self._free_x          = 0.50
                                    self._free_y          = 0.50
                                    next_start = (
                                        self.all_logs[idx + 1].start_time
                                        if idx + 1 < len(self.all_logs)
                                        else self.sel_log.start_time + timedelta(hours=6))
                                    self.plot_rows = filter_csv_for_log(
                                        self.all_csv,
                                        self.sel_log.start_time,
                                        next_start)
                                    self._update_meta()
                                    self._update_tx_site(silent=True)
                                    self._update_stats()
                                    self._replot()
                                    # Update LED indicators
                                    self._set_led(self.led_h, self._led_h, True)
                                    self._set_led(self.led_l, self._led_l,
                                                  bool(self.all_csv))
                                    self.v_logs_count.set(str(len(self.all_logs)))
                                    # Timer-started AutoPlot: 10s interval, no dialog
                                    self._start_autoplot_silent(10)
                                    # Mark countdown as finished so the
                                    # "AutoPlot starts in X sec." text in
                                    # _refresh_loop is not redrawn on its
                                    # next 2s tick (ap_waiting becomes False).
                                    countdown_active[0] = False
                                    try:
                                        status_lbl.config(
                                            text='',
                                            fg='#555555')
                                    except Exception: pass
                                else:
                                    countdown_active[0] = False
                                    _safe_led('led6', led6_c, led6_o, 'red')
                                    try:
                                        status_lbl.config(
                                            text='AutoPlot: no logs found in DreamLog.txt yet.',
                                            fg='#cc6600')
                                    except Exception: pass
                            except Exception as ex:
                                countdown_active[0] = False
                                _safe_led('led6', led6_c, led6_o, 'red')
                                try:
                                    status_lbl.config(
                                        text=f'AutoPlot load error: {ex}',
                                        fg='#cc0000')
                                except Exception: pass
                    # Schedule _ap_countdown: AutoPlot always requires Log,
                    #   so enable_log is always True here.
                    #   Log + AutoPlot → 15s log delay + 5s buffer = 20s total
                    ap_after_ms = (LOG_DELAY + AP_DELAY) * 1000
                    # Save start time and total for countdown display in _refresh_loop
                    self._ap_countdown_start = datetime.now()
                    self._ap_countdown_total = ap_after_ms / 1000
                    self.root.after(ap_after_ms, _ap_countdown)
                monitor_stop[0] = False
                _start_monitor()
            except Exception as ex:
                try:
                    status_lbl.config(
                        text=f'Error starting Dream: {ex}',
                        fg='#cc0000')
                except Exception: pass

        def start_dream():
            freq = freq_var.get().strip()
            # Manual start: AutoPlot is NOT started automatically.
            # The user can start it manually via the Auto Plot button in the main window.
            self._autoplot_enabled[0] = False
            # Stage 2 (Aug 2026, user request): warn — don't block — if a
            # Timer-Event start is imminent. The user is actively at the
            # PC right now (unlike an unattended Timer-Event start), so a
            # confirmation popup is appropriate here. Stage 3 (inside the
            # Timer-Event start itself) is the real safety net regardless
            # of what the user answers here.
            _slot_no = self._imminent_timer_event_slot()
            if _slot_no is not None:
                try:
                    dlg.lift()
                    dlg.focus_force()
                except Exception:
                    pass
                if not messagebox.askyesno(
                        'Timer-Event',
                        f'Timer-Event slot {_slot_no} starts within the '
                        f'next 60 seconds.\n\n'
                        f'Start Dream manually anyway?',
                        parent=dlg):
                    return
            if not freq:
                try:
                    dlg.lift()
                    dlg.focus_force()
                except Exception:
                    pass
                ans = messagebox.askyesno(
                    'Start Dream',
                    'No frequency entered.\n\n'
                    'Start Dream without setting a Log-Frequency?\n\n'
                    '(The last frequency in Dream.ini will remain.)',
                    parent=dlg)
                if not ans: return
                _do_start(freq_khz=None, enable_log=False)
            else:
                _do_start(freq_khz=freq, enable_log=False)

        def start_dream_with_log():
            freq = freq_var.get().strip()
            # Manual start: AutoPlot is NOT started automatically.
            # The user can start it manually via the Auto Plot button in the main window.
            self._autoplot_enabled[0] = False
            # Stage 2 — same warning as start_dream() above.
            _slot_no = self._imminent_timer_event_slot()
            if _slot_no is not None:
                try:
                    dlg.lift()
                    dlg.focus_force()
                except Exception:
                    pass
                if not messagebox.askyesno(
                        'Timer-Event',
                        f'Timer-Event slot {_slot_no} starts within the '
                        f'next 60 seconds.\n\n'
                        f'Start Dream manually anyway?',
                        parent=dlg):
                    return
            if not freq:
                try:
                    dlg.lift()
                    dlg.focus_force()
                except Exception:
                    pass
                messagebox.showwarning(
                    'Start Dream with Log',
                    'Please enter a frequency first!\n\n'
                    'A frequency is required to start Dream with logging.',
                    parent=dlg)
                return
            _do_start(freq_khz=freq, enable_log=True)

        def stop_dream(cancel_other_slots=True):
            """Terminate Dream, show orange LED briefly.

            cancel_other_slots=True (default): original manual-stop
            behaviour, used by the "Stop Dream" button — the user is
            intentionally aborting everything, including any other still-
            pending scheduled Timer-Events.

            cancel_other_slots=False: used by the automatic, timer-driven
            stop path (_make_slot_stop) — that slot's OWN stop-timer has
            already fired naturally to get here, so this must NOT reach
            into and cancel any OTHER slot's still-pending stop-timer.
            (Bug fix, Aug 2026: previously this loop ran unconditionally
            regardless of caller, so the very first Timer-Event to end
            naturally silently cancelled every LATER event's stop-timer
            too — those events would then start correctly at their
            scheduled time but never auto-stop, running until the user
            intervened manually.)
            """
            import subprocess

            # ── Step 1: Cancel OTHER slots' stop-timers and set Orange ────
            # Only for the manual-stop case — see docstring above.
            any_cancelled = False
            if cancel_other_slots:
                for i, pair in enumerate(self._sched_timers):
                    t_e = pair[1]   # stop-timer thread
                    if t_e is not None and t_e.is_alive():
                        t_e.cancel()
                        self._sched_timers[i][1] = None
                        self._sched_state[i]['led'] = 'orange'
                        any_cancelled = True
                        # Slot LED → orange immediately
                        try:
                            set_led(slot_leds[i][0], slot_leds[i][1], 'orange')
                        except Exception:
                            pass

            # ── Cancel AutoPlot countdown if still waiting (65s delay) ───
            # Without this, _ap_countdown fires after the delay and starts
            # AutoPlot even though Dream has already been terminated.
            if hasattr(self, '_ap_countdown_active') and self._ap_countdown_active[0]:
                self._ap_countdown_active[0] = False
                # Signal to _refresh_loop that AutoPlot countdown was cancelled
                # so LED6 and the AutoPlot slot-LED can show orange briefly.
                self._ap_countdown_cancelled = True
                # Clear countdown start so text disappears immediately
                self._ap_countdown_start = None
                # Mark the slot that had AutoPlot=1 as orange
                # Bugfix (Aug 2026): was hardcoded range(3), excluding
                # slot 4 (added later). NUM_SLOTS (defined further below
                # in this same _set_event() call, already resolved by
                # the time this closure actually runs) always reflects
                # the real row count.
                for i in range(NUM_SLOTS):
                    if self._sched_state[i].get('autoplot', 0):
                        self._sched_state[i]['led'] = 'orange'
                # Clear countdown text immediately
                try:
                    status_lbl.config(text='Ready.', fg='#555555')
                except Exception:
                    pass

            if any_cancelled:
                # LED5 in Schedule dialog → orange immediately
                _safe_led('led5', led5_c, led5_o, 'orange')
                self._sched_led_status['led5'] = 'orange'

                # After 10 seconds → blue (done — event was handled, just early)
                def _orange_to_blue():
                    # Bugfix (Aug 2026): same range(3) -> NUM_SLOTS fix.
                    for i in range(NUM_SLOTS):
                        if self._sched_state[i].get('led') == 'orange':
                            self._sched_state[i]['led'] = 'blue'
                            try:
                                set_led(slot_leds[i][0],
                                        slot_leds[i][1], 'blue')
                            except Exception:
                                pass
                    _safe_led('led5', led5_c, led5_o, 'grey')
                    self._sched_led_status['led5'] = 'grey'
                    # Clear AutoPlot cancelled flag → LED6 → grey
                    self._ap_countdown_cancelled = False
                try:
                    self.root.after(10000, _orange_to_blue)
                except Exception:
                    pass

            # ── Step 2: Terminate Dream after short delay ─────────────────
            def _do_stop():
                if dream_proc[0]:
                    try:
                        _stop_dream_process(dream_proc[0])
                        dream_proc[0] = None
                    except Exception as ex:
                        # Bugfix (Aug 2026): this branch used to 'return'
                        # here, silently skipping everything below —
                        # including greying out the Main-GUI 'Stop Dream'
                        # button. That made the button stay red/enabled
                        # after a Timer-Event's natural end whenever
                        # terminating Dream raised (e.g. Dream already
                        # exiting on its own right at the scheduled stop
                        # time). Now mirrors the manual-stop path
                        # (_stop_dream_from_main._do_stop): the error is
                        # only shown, never allowed to abort the cleanup
                        # that follows.
                        try:
                            status_lbl.config(
                                text=f'Error stopping Dream: {ex}',
                                fg='#cc0000')
                        except Exception: pass
                else:
                    if platform.system() == 'Windows':
                        _subprocess_call(
                            ['taskkill', '/IM', 'Dream.exe'],
                            stdout=_subprocess.DEVNULL,
                            stderr=_subprocess.DEVNULL)
                    else:
                        _subprocess_call(
                            ['pkill', '-TERM', 'dream'],
                            stdout=_subprocess.DEVNULL,
                            stderr=_subprocess.DEVNULL)
                _safe_led('led3', led3_c, led3_o, 'grey')
                _safe_led('led4', led4_c, led4_o, 'grey')
                # Reset log flag so Log-LED in Main-GUI turns grey
                self._dream_log_flag  = False
                self._dream_start_time = None
                if not any_cancelled:
                    _safe_led('led5', led5_c, led5_o, 'grey')
                # Reset Dream.ini: enablelog=0, delay=0 — clean state for next start
                # Bugfix (Aug 2026): was called as a bare name here,
                # missing the 'self.' object reference. _write_dream_ini
                # only exists as a method of this class — the bare call
                # raised an unguarded NameError every single time this
                # automatic (Timer-Event) stop path ran, aborting the
                # rest of _do_stop() right here and never reaching the
                # 'Stop Dream' button greying-out three lines below.
                # That was the actual, exact cause of the button staying
                # red after a Timer-Event's natural end — not the
                # earlier exception-handling issue already fixed above.
                self._write_dream_ini(False)
                # Grey out the Stop Dream button in Main-GUI — keeps it
                # in sync regardless of which Stop path was used.
                try:
                    self._stop_dream_btn.configure(state=tk.DISABLED)
                except Exception:
                    pass
                try:
                    status_lbl.config(text='Ready.', fg='#555555')
                except Exception: pass
            self.root.after(500, _do_stop)

        def set_to_log_freq():
            """Set TRX to Log Frequency — thin wrapper around the shared
            self._send_freq_to_rigctl() core, adding this dialog's own
            Status-frame LED indicators on top of the shared status text.
            LED/status handling itself now lives in the single shared
            _report_rigctl_result() helper (Aug 2026, user request) —
            identical behaviour to the Timer-Event firing path below."""
            ok, msg, fg, led = self._send_freq_to_rigctl(freq_var.get())
            _report_rigctl_result(ok, msg, fg, led, status_lbl)

        # ══════════════════════════════════════════════════════════════════
        # COMBINED FRAME: Log Frequency and Manual Start
        # ══════════════════════════════════════════════════════════════════
        ff = tk.LabelFrame(dlg, text='Dream Manual Start / Stop',
                           bg=GUI_BG, font=('Arial',9,'bold'), padx=6, pady=6)
        ff.pack(fill=tk.X, padx=10, pady=(0,4))

        # ── Frequency entry row ───────────────────────────────────────
        fq_row = tk.Frame(ff, bg=GUI_BG)
        fq_row.pack(fill=tk.X)
        tk.Label(fq_row, text='Log-Frequency (kHz):', bg=GUI_BG,
                 font=('Arial',11), width=20, anchor='w').pack(side=tk.LEFT)
        freq_var = tk.StringVar(value=self.cfg.get('last_event_freq',''))
        # Max 5 digits (kHz values never exceed 5 digits) + select-all on
        # focus, same fix already applied to RX Coordinates and Zoom —
        # without this, a new value was simply appended to the old one
        # instead of replacing it.
        def _val_freq_5dig(val):
            return len(val) <= 5 and (val == '' or val.isdigit())
        vcmd_freq5 = (fq_row.register(_val_freq_5dig), '%P')
        def _freq_select_all_on_focus(event):
            event.widget.select_range(0, tk.END)
            event.widget.icursor(tk.END)
        freq_entry = tk.Entry(fq_row, textvariable=freq_var, font=('Arial',11),
                              width=8, validate='key', validatecommand=vcmd_freq5)
        freq_entry.pack(side=tk.LEFT)
        freq_entry.bind('<FocusIn>', _freq_select_all_on_focus)
        tk.Button(fq_row, text='Set', font=('Arial',10), width=4,
                  bg='#aaddff',
                  command=set_to_log_freq).pack(side=tk.LEFT, padx=(6,0))

        # Own row, full width, with a line break after the dash — keeps
        # this readable regardless of dialog width, instead of being cut
        # off at the end of a single crowded button row.
        freq_hint_row = tk.Frame(ff, bg=GUI_BG)
        freq_hint_row.pack(fill=tk.X)
        tk.Label(freq_hint_row,
                 text='  Changes RX frequency —\n  if remote control is configured',
                 bg=GUI_BG, font=('Arial',8), fg='#555555',
                 justify=tk.LEFT, anchor='w').pack(side=tk.LEFT)

        # SDR USB/LSB offset settings (checkbox, magnitude, USB/LSB
        # sideband) are read from self.cfg directly in
        # self._rigctl_freq_for_station() (a shared class method now,
        # used by every rigctl call site in the programme) — the actual
        # controls for them live in their own separate frame further down
        # (under 'Timer-Events'), not here. Kept decoupled deliberately:
        # moving that frame around does not require touching anything here.

        # ── Manual Start / Stop buttons ───────────────────────────────
        def open_dream_folder():
            # Determine best initial directory — priority order:
            # 1) dream_log_path from config (set in RX Config / Basic Setup)
            # 2) directory of already-loaded txt_path
            # 3) home directory as fallback
            import platform as _plat, subprocess as _sp
            start_dir = self.cfg.get('dream_log_path', '').strip()
            if not start_dir and self.txt_path:
                start_dir = os.path.dirname(self.txt_path)
            if not start_dir:
                start_dir = os.path.expanduser('~')
            # Open native file manager — platform specific
            try:
                _sys = _plat.system()
                if _sys == 'Windows':
                    os.startfile(start_dir)
                elif _sys == 'Darwin':   # macOS
                    _sp.Popen(['open', start_dir])
                else:                    # Linux
                    _sp.Popen(['xdg-open', start_dir])
            except Exception as ex:
                messagebox.showerror(
                    'Manage Dream Files',
                    f'Could not open folder:\n{start_dir}\n\n{ex}',
                    parent=dlg)

        bm = tk.Frame(ff, bg=GUI_BG)
        bm.pack(pady=(6,2))
        tk.Button(bm, text='Start Dream Now', font=('Arial',10),
                  bg='#aaddaa', width=16,
                  command=start_dream).pack(side=tk.LEFT, padx=6)
        tk.Button(bm, text='Start Dream with Log', font=('Arial',10),
                  bg='#aaffaa', width=16,
                  command=start_dream_with_log).pack(side=tk.LEFT, padx=6)
        tk.Button(bm, text='Stop Dream', font=('Arial',10),
                  bg='#ffccaa', width=16,
                  command=stop_dream).pack(side=tk.LEFT, padx=6)
        tk.Button(bm, text='Manage Dream Files', font=('Arial',10),
                  bg='#aaccff', width=16,
                  command=open_dream_folder).pack(side=tk.LEFT, padx=6)

        # ══════════════════════════════════════════════════════════════════
        # SECTION 3 — Scheduled Start  (Modus B) — 3 sequential slots
        # ══════════════════════════════════════════════════════════════════
        fs = tk.LabelFrame(dlg,
                           text='Timer-Events — Dream automatic Start  ( with RX remote: use VFO A )',
                           bg=GUI_BG, font=('Arial',9,'bold'), padx=6, pady=4)
        fs.pack(fill=tk.X, padx=10, pady=4)

        # ── Validate: max 2 digits only ──────────────────────────────
        def _val_2dig(val):
            return len(val) <= 2 and (val == '' or val.isdigit())
        vcmd2 = (fs.register(_val_2dig), '%P')

        # ── Validate: max 5 digits for frequency ─────────────────────
        def _val_freq(val):
            return len(val) <= 5 and (val == '' or val.isdigit())
        vcmd_freq = (fs.register(_val_freq), '%P')

        # ── Grid-based layout with vertical separator between Start and Stop ──
        # Column map:
        #  0=#  1=Start-HH  2=:  3=Start-MM  4=SEP  5=Stop-HH  6=:  7=Stop-MM
        #  8=Freq  9=Log  10=Status
        NUM_SLOTS = 4
        slot_vars = []
        slot_leds = []
        SEP_COL = 4   # vertical separator column index

        # Shared grid frame — header + data rows all in one frame
        grid_frame = tk.Frame(fs, bg=GUI_BG)
        grid_frame.pack(fill=tk.X, pady=(2,4))

        # Column minsizes — separator column (4) is narrow
        # Col: 0=#  1=Start-HH  2=:  3=Start-MM  4=SEP  5=Stop-HH  6=:  7=Stop-MM
        #      8=Freq  9=Log  10=AutoPlot  11=Status-LED  12=Set  13=Clear  14=(Radio-List button, row 1 only)
        _col_minsizes = [30, 40, 14, 40,  18,  40, 14, 40, 70, 40, 60, 40, 44, 54, 20]
        for col, ms in enumerate(_col_minsizes):
            grid_frame.columnconfigure(col, weight=0, minsize=ms)

        # ── Header row (row 0) ───────────────────────────────────────
        tk.Label(grid_frame, text='#', bg=GUI_BG,
                 font=('Arial',9,'bold')).grid(
            row=0, column=0, padx=(8,4), pady=(2,4), sticky='w')

        tk.Label(grid_frame, text='Start  (HH : MM)', bg=GUI_BG,
                 font=('Arial',9,'bold')).grid(
            row=0, column=1, columnspan=3, pady=(2,4), sticky='w')

        # Separator header — empty label, same column as separator
        tk.Label(grid_frame, text='', bg=GUI_BG).grid(
            row=0, column=SEP_COL)

        tk.Label(grid_frame, text='Stop  (HH : MM)', bg=GUI_BG,
                 font=('Arial',9,'bold')).grid(
            row=0, column=5, columnspan=3, pady=(2,4), sticky='w')

        for col, txt in [(8,'Freq kHz'), (9,'Log'), (10,'AutoPlot'), (11,'Status'),
                          (12,''), (13,'')]:
            tk.Label(grid_frame, text=txt, bg=GUI_BG,
                     font=('Arial',9,'bold')).grid(
                row=0, column=col, padx=6, pady=(2,4), sticky='w')

        def make_mini_led(parent):
            c = tk.Canvas(parent, width=14, height=14, bg=GUI_BG,
                          highlightthickness=0)
            o = c.create_oval(2,2,12,12, fill='#888888', outline='#555555')
            return c, o

        def make_vsep(parent, row):
            """Draw a 2px vertical separator line in the separator column."""
            c = tk.Canvas(parent, width=8, height=28, bg=GUI_BG,
                          highlightthickness=0)
            c.create_line(4, 2, 4, 26, fill='#888888', width=2)
            c.grid(row=row, column=SEP_COL, padx=0, pady=0)

        def _auto_tab2(var, nxt):
            def _cb(*_):
                if len(var.get()) == 2:
                    nxt.focus_set(); nxt.select_range(0, tk.END)
            return _cb

        for idx in range(NUM_SLOTS):
            r = idx + 1   # grid row (0 = header)

            # Col 0: slot number
            tk.Label(grid_frame, text=str(idx+1), bg=GUI_BG,
                     font=('Arial',9,'bold')).grid(
                row=r, column=0, padx=(8,4), sticky='w')

            # Col 1-3: Start HH : MM
            sh_v = tk.StringVar(); sm_v = tk.StringVar()
            e_sh = tk.Entry(grid_frame, textvariable=sh_v, width=3,
                            font=('Arial',10), validate='key',
                            validatecommand=vcmd2)
            e_sh.grid(row=r, column=1, padx=6, pady=3)
            tk.Label(grid_frame, text=':', bg=GUI_BG,
                     font=('Arial',10,'bold')).grid(row=r, column=2, padx=2)
            e_sm = tk.Entry(grid_frame, textvariable=sm_v, width=3,
                            font=('Arial',10), validate='key',
                            validatecommand=vcmd2)
            e_sm.grid(row=r, column=3, padx=6, pady=3)

            # Col 4: vertical separator
            make_vsep(grid_frame, r)

            # Col 5-7: Stop HH : MM
            eh_v = tk.StringVar(); em_v = tk.StringVar()
            e_eh = tk.Entry(grid_frame, textvariable=eh_v, width=3,
                            font=('Arial',10), validate='key',
                            validatecommand=vcmd2)
            e_eh.grid(row=r, column=5, padx=6, pady=3)
            tk.Label(grid_frame, text=':', bg=GUI_BG,
                     font=('Arial',10,'bold')).grid(row=r, column=6, padx=2)
            e_em = tk.Entry(grid_frame, textvariable=em_v, width=3,
                            font=('Arial',10), validate='key',
                            validatecommand=vcmd2)
            e_em.grid(row=r, column=7, padx=6, pady=3)

            # Col 8: Frequency — stored in e_fq for auto-tab target
            fq_v = tk.StringVar()
            e_fq = tk.Entry(grid_frame, textvariable=fq_v, width=6,
                            font=('Arial',10), validate='key',
                            validatecommand=vcmd_freq)
            e_fq.grid(row=r, column=8, padx=10, pady=3)

            # Auto-tab chain: Start-HH → Start-MM → Stop-HH → Stop-MM → Freq
            sh_v.trace_add('write', _auto_tab2(sh_v, e_sm))
            sm_v.trace_add('write', _auto_tab2(sm_v, e_eh))
            eh_v.trace_add('write', _auto_tab2(eh_v, e_em))
            em_v.trace_add('write', _auto_tab2(em_v, e_fq))

            # Col 9: Log checkbox
            log_v = tk.IntVar(value=0)
            ap_v  = tk.IntVar(value=0)   # defined here so log_cb can reference it

            def _on_log_toggle(lv=log_v, av=ap_v):
                if not lv.get():
                    av.set(0)   # AutoPlot off when Log is off

            log_cb = tk.Checkbutton(grid_frame, variable=log_v,
                                    bg=GUI_BG, command=_on_log_toggle)
            log_cb.grid(row=r, column=9, padx=8)

            # Col 10: AutoPlot checkbox — only meaningful when Log is enabled
            def _on_ap_toggle(lv=log_v, av=ap_v):
                if av.get() and not lv.get():
                    av.set(0)   # guard: cannot enable AP without Log

            tk.Checkbutton(grid_frame, variable=ap_v,
                           bg=GUI_BG, command=_on_ap_toggle).grid(
                           row=r, column=10, padx=8)

            # Col 11: Mini status LED
            led_c, led_o = make_mini_led(grid_frame)
            led_c.grid(row=r, column=11, padx=8)

            # Col 12-13: per-row Set / Clear buttons (Aug 2026) — replace
            # the old single 'Accept Schedule' button, which processed
            # all three rows together and could end up interfering with
            # an already-running event elsewhere in the list. Each button
            # here only ever touches its OWN row (idx), never any other
            # — forward-referencing _slot_set()/_slot_clear() via lambda
            # since they're only DEFINED further below in this same
            # function, but only ever CALLED later on click, by which
            # point they already exist.
            tk.Button(grid_frame, text='Set', font=('Arial',10), width=4,
                      bg='#aaddff',
                      command=lambda i=idx: _slot_set(i)).grid(
                      row=r, column=12, padx=4)
            tk.Button(grid_frame, text='Clear', font=('Arial',10), width=6,
                      bg='#ffdddd',
                      command=lambda i=idx: _slot_clear(i)).grid(
                      row=r, column=13, padx=4)

            # New standalone 'Radio-List' button (Aug 2026) — placed once,
            # at the height of the FIRST row's Clear button, one column
            # further right. Deliberately unrelated to the Main-GUI's own
            # 'Radio List' button — opens a separate, reduced window
            # ('Radio-List for Timer-Event') that only ever COPIES a
            # station's time/frequency as plain text into the next free
            # Timer-Event row; it never touches rigctl or Dream at all.
            if idx == 0:
                tk.Button(grid_frame, text='Radio-List', font=('Arial',9),
                          bg='#ffe0aa',
                          command=lambda: _open_radio_list_for_timer()).grid(
                          row=r, column=14, padx=(16,0), sticky='w')

            slot_vars.append({
                'sh': sh_v, 'sm': sm_v,
                'eh': eh_v, 'em': em_v,
                'freq': fq_v, 'log': log_v, 'autoplot': ap_v,
            })
            slot_leds.append((led_c, led_o))

        # ── Timer storage — restore from persistent state ────────────
        sched_timers = self._sched_timers   # reference, not copy!

        # ── Restore slot fields and LEDs from saved state ─────────────
        # Bugfix (Aug 2026): was hardcoded range(3) — this is the exact
        # cause of slot 4's event appearing 'deleted' after closing and
        # reopening this dialog. The underlying saved data in
        # self._sched_state[3] / self._sched_timers[3] was never touched
        # by this bug and stayed intact; it just was never copied back
        # into slot 4's visible input fields on dialog-open. Now uses
        # NUM_SLOTS, matching the row-building loop above.
        any_timer_active = False
        for i in range(NUM_SLOTS):
            ss  = self._sched_state[i]
            sv  = slot_vars[i]
            sv['sh'].set(ss['sh'])
            sv['sm'].set(ss['sm'])
            sv['eh'].set(ss['eh'])
            sv['em'].set(ss['em'])
            sv['freq'].set(ss['freq'])
            sv['log'].set(ss['log'])
            sv['autoplot'].set(ss.get('autoplot', 0))
            set_led(slot_leds[i][0], slot_leds[i][1], ss['led'])
            if ss['led'] in ('yellow', 'green'):
                any_timer_active = True
        # ── _refresh_status: live current state when dialog opens ───────────
        def _refresh_status():
            """
            Called once when the dialog opens (and can be called any time).
            Determines the real current state from live sources:
              LED 1/2 (TRX) : last known state from _sched_led_status
              LED 3 (Dream) : live process check (dream.exe / dream.bin)
              LED 4 (Log)   : Dream running + enablelog=1 in Dream.ini
              LED 5 (Timer) : any timer thread still alive
              Slot LEDs     : derived from timer thread state
            """
            import platform

            # ── LED 1/2: TRX — use last known state (no timeout risk) ──
            set_led(led1_c, led1_o,
                    self._sched_led_status.get('led1', 'grey'))
            set_led(led2_c, led2_o,
                    self._sched_led_status.get('led2', 'grey'))

            # ── LED 3: Dream — live process check ─────────────────────
            dream_running = self._is_dream_running()
            led3_col = 'green' if dream_running else 'grey'
            set_led(led3_c, led3_o, led3_col)
            self._sched_led_status['led3'] = led3_col

            # ── LED 4: Dream Log — Dream running + enablelog=1 ────────
            led4_col = 'grey'
            if dream_running:
                try:
                    _ini = self._resolve_dream_ini_path()
                    if _ini:
                        with open(_ini, 'r',
                                  encoding='utf-8',
                                  errors='replace') as _f:
                            for _line in _f:
                                _k = _line.strip().split('=')[0]\
                                    .strip().lower()
                                _v = _line.strip().split('=')[-1]\
                                    .strip() if '=' in _line else ''
                                if _k == 'enablelog' and _v == '1':
                                    led4_col = 'green'
                                    break
                except Exception:
                    pass
            set_led(led4_c, led4_o, led4_col)
            self._sched_led_status['led4'] = led4_col

            # ── LED 5 + Slot LEDs: derive from timer thread state ─────
            # FIX (Aug 2026): 'any_active' used to be set True for BOTH
            # "start-timer counting down" (waiting) AND "stop-timer
            # counting down" (actually running) — so this Status-frame
            # LED jumped straight to green right after Accept Schedule,
            # even though the correct per-slot LED right next to it
            # already showed yellow/Waiting correctly. Now split into two
            # separate flags, same as the Main-GUI's own independent
            # Timer LED (_timer_led_tick) already did correctly.
            any_waiting = False
            any_active  = False
            # Bugfix (Aug 2026): was hardcoded range(3) — slot 4 (added
            # later) was never evaluated here, so its live LED colour
            # was never (re-)derived by this status refresh, and it
            # never contributed to any_waiting/any_active below.
            for i in range(NUM_SLOTS):
                pair   = self._sched_timers[i]
                t_s    = pair[0]   # start timer
                t_e    = pair[1]   # stop  timer
                ss     = self._sched_state[i]
                fields_filled = any([
                    ss['sh'], ss['sm'], ss['eh'], ss['em']])

                if t_s is not None and t_s.is_alive():
                    # Start timer still counting down
                    slot_col = 'yellow'
                    any_waiting = True
                elif t_e is not None and t_e.is_alive():
                    # Stop timer counting — event is running
                    slot_col = 'green'
                    any_active = True
                elif ss.get('led') == 'orange':
                    # Manually stopped before scheduled end — keep orange
                    # Do NOT overwrite with blue even if t_s/t_e are None
                    slot_col = 'orange'
                elif (t_s is not None or t_e is not None) and fields_filled:
                    # Both timers finished naturally — event completed
                    slot_col = 'blue'
                elif ss.get('led') == 'blue':
                    # Persist blue after _orange_to_blue() fired
                    slot_col = 'blue'
                elif fields_filled:
                    # Fields filled but never accepted / already cleared
                    slot_col = ss.get('led', 'grey')
                else:
                    slot_col = 'grey'

                self._sched_state[i]['led'] = slot_col
                set_led(slot_leds[i][0], slot_leds[i][1], slot_col)

            # LED5: green (active) > yellow (waiting) > orange > blue/grey
            # Bugfix (Aug 2026): same range(3) -> NUM_SLOTS fix for both
            # any_orange and any_blue below.
            any_orange = any(
                self._sched_state[i].get('led') == 'orange'
                for i in range(NUM_SLOTS))
            any_blue = any(
                self._sched_state[i].get('led') == 'blue'
                for i in range(NUM_SLOTS))
            if any_active:
                led5_col = 'green'
            elif any_waiting:
                led5_col = 'yellow'
            elif any_orange:
                led5_col = 'orange'
            elif any_blue:
                led5_col = '#2277ff'
            else:
                led5_col = 'grey'
            set_led(led5_c, led5_o, led5_col)
            self._sched_led_status['led5'] = led5_col

            # ── Status text ───────────────────────────────────────────
            # Error messages are shown directly in status_lbl.
            # LEDs show all operational status.

            # ── LED 6: AutoPlot ───────────────────────────────────────
            # orange = countdown cancelled (manually stopped)
            # yellow = _ap_countdown running  (waiting for DreamLog.txt)
            # green  = AutoPlot active        (self.ap_active == True)
            # grey   = AutoPlot off
            ap_cancelled = getattr(self, '_ap_countdown_cancelled', False)
            ap_waiting = (hasattr(self, '_ap_countdown_active') and
                          bool(self._ap_countdown_active[0]) and
                          not self.ap_active)
            ap_running = self.ap_active

            if ap_running:
                led6_col = 'green'
            elif ap_cancelled:
                led6_col = 'orange'
            elif ap_waiting:
                led6_col = 'yellow'
            else:
                led6_col = 'grey'
            _safe_led('led6', led6_c, led6_o, led6_col)
            self._sched_led_status['led6'] = led6_col

            # ── Countdown text under AutoPlot LED ─────────────────────
            # Derived entirely from existing _ap_countdown_start/_total.
            # No new process or thread needed — just math in this 2s tick.
            if ap_waiting and hasattr(self, '_ap_countdown_start') \
                          and hasattr(self, '_ap_countdown_total'):
                elapsed   = (datetime.now() -
                             self._ap_countdown_start).total_seconds()
                remaining = max(0, int(self._ap_countdown_total - elapsed))
                try:
                    status_lbl.config(
                        text=f'AutoPlot starts in {remaining} sec.',
                        fg='#007700')
                except Exception:
                    pass
            else:
                # Not waiting — clear countdown text immediately, unless
                # an important warning is still within its hold period.
                try:
                    hold = _status_hold_until[0]
                    if not ap_running and (hold is None or datetime.now() >= hold):
                        status_lbl.config(text='Ready.', fg='#555555')
                except Exception:
                    pass

        # ── Call _refresh_status on open and every 2s while dialog open ─
        _dlg_alive       = [True]   # set False when dialog closes — stops loop
        _refresh_after_id = [None]  # holds pending after() ID for cancellation

        def _refresh_loop():
            """Periodic refresh — updates all LEDs every 2 seconds.
            Stops automatically when dialog is closed."""
            if not _dlg_alive[0]:
                return   # dialog gone — stop looping
            try:
                _refresh_status()
            except Exception:
                pass   # safety net — never let loop die silently
            try:
                _refresh_after_id[0] = dlg.after(2000, _refresh_loop)
            except Exception:
                pass   # dialog destroyed between check and after()

        _refresh_loop()   # first call immediately on open, then every 2s

        # ── Text countdown removed — LEDs show all status information ──────

        def _make_slot_start(slot_idx, freq, use_log, use_ap):
            """Returns the function that fires when slot_idx timer starts."""
            def _fn():
                def _ui():
                    # ── Stage 3 (Aug 2026, user request): final safety
                    # net, right at the moment this slot's own start
                    # actually fires — regardless of what happened in
                    # between (pre-stop at T-60s, or the user manually
                    # confirming a restart anyway via the Stage-2
                    # warning). If Dream is still/again running at this
                    # exact instant, stop it now and proceed with this
                    # slot's own scheduled start — "the Timer takes over
                    # airspace" — instead of silently doing nothing while
                    # the slot's LED still turned green as if it had
                    # started (the original bug this whole mechanism was
                    # built to close).
                    if self._is_dream_running():
                        try:
                            status_lbl.config(
                                text=f'Timer-Event: stopping still-running '
                                     f'Dream to start slot {slot_idx+1}.',
                                fg='#cc6600')
                        except Exception:
                            pass
                        if self._dream_proc[0] is not None:
                            _stop_dream_process(self._dream_proc[0])
                            self._dream_proc[0] = None
                        else:
                            # No tracked process handle (e.g. Dream was
                            # started completely outside this programme)
                            # — fall back to killing by name, same
                            # fallback the manual Stop-Dream path uses.
                            try:
                                if _platform.system() == 'Windows':
                                    _subprocess_call(
                                        ['taskkill', '/IM', 'Dream.exe'],
                                        stdout=_subprocess.DEVNULL,
                                        stderr=_subprocess.DEVNULL)
                                else:
                                    _subprocess_call(
                                        ['pkill', '-TERM', 'dream'],
                                        stdout=_subprocess.DEVNULL,
                                        stderr=_subprocess.DEVNULL)
                            except Exception:
                                pass
                        # Brief, bounded wait for it to actually exit
                        # before starting the new session — same short
                        # blocking-wait style already used by
                        # _stop_dream_process() itself (up to ~1s there).
                        import time as _time
                        for _ in range(30):   # up to ~3s
                            if not self._is_dream_running():
                                break
                            _time.sleep(0.1)
                    # ── AutoPlot flag: set BEFORE _do_start is called ─────────
                    self._autoplot_enabled[0] = use_ap
                    # ── State first — always ──────────────────────────
                    self._sched_state[slot_idx]['led'] = 'green'
                    # ── Widget update — dialog may be closed ──────────
                    try:
                        set_led(slot_leds[slot_idx][0],
                                slot_leds[slot_idx][1], 'green')
                    except Exception:
                        pass   # widget gone — state saved above
                    _safe_led('led5', led5_c, led5_o, 'green')
                    # Set frequency via TRX if configured
                    #
                    # Aug 2026, user request: this used to be its own,
                    # separate copy of the rigctl-calling logic — now it
                    # goes through the exact same shared
                    # self._send_freq_to_rigctl() + _report_rigctl_result()
                    # path the manual 'Set' button uses, so both always
                    # behave identically (one place to maintain, not two).
                    #
                    # Also: the Log-Frequency textbox now shows the
                    # firing Timer-Event's frequency — visual confirmation
                    # of which single frequency is currently active (the
                    # programme only ever works with one at a time), and
                    # the field users relying on Dream-only (no remote RX)
                    # still need for a clean manual start/log afterwards.
                    if freq:
                        freq_var.set(freq)
                        self.cfg.set('last_event_freq', freq)
                        ok, msg, fg, led = self._send_freq_to_rigctl(freq)
                        _report_rigctl_result(ok, msg, fg, led)

                    if use_log:
                        # 'freq' is always the TRUE station frequency —
                        # this is exactly what Dream itself should receive
                        # for its own log (unchanged). The SDR USB/LSB
                        # offset only ever applies to the rigctl call
                        # above, which already used the corrected value
                        # via _rigctl_freq_for_station().
                        _do_start(freq_khz=freq if freq else None,
                                  enable_log=True)
                    else:
                        _do_start(freq_khz=freq if freq else None,
                                  enable_log=False)
                self.root.after(0, _ui)
            return _fn

        def _make_slot_stop(slot_idx):
            """Returns the function that fires when slot_idx timer stops."""
            def _fn():
                def _ui():
                    # ── Cancel any running AutoPlot countdown ─────────────
                    if hasattr(self, '_ap_countdown_active'):
                        self._ap_countdown_active[0] = False
                    # ── Always update persistent state first ──────────────
                    # Do NOT overwrite 'orange' (manually stopped) with 'blue'.
                    # orange is set by stop_dream() and must survive until
                    # _reset_orange() clears it after 5 seconds.
                    if self._sched_state[slot_idx].get('led') != 'orange':
                        self._sched_state[slot_idx]['led'] = 'blue'
                        # ── Try to update slot LED widget — may be destroyed ──
                        # Dialog could have been closed; widget may not exist.
                        # MUST NOT block stop_dream() — so wrap in try/except.
                        try:
                            set_led(slot_leds[slot_idx][0],
                                    slot_leds[slot_idx][1], 'blue')
                        except Exception:
                            pass   # widget gone — state already saved above
                    # ── Stop AutoPlot and Dream — always execute ───────────
                    try:
                        self._stop_autoplot_silent()
                    except Exception:
                        pass
                    try:
                        stop_dream(cancel_other_slots=False)
                    except Exception:
                        pass
                    # ── Update Timer LED if dialog is still open ───────────
                    # Check only start-timers — stop-timer is firing right
                    # now so is_alive() would wrongly return True.
                    all_done = all(
                        pair[0] is None or not pair[0].is_alive()
                        for pair in sched_timers
                    )
                    if all_done:
                        _safe_led('led5', led5_c, led5_o, 'grey')
                        try:
                            status_lbl.config(
                                text='Ready.', fg='#555555')
                        except Exception:
                            pass   # dialog closed — no widget to update
                self.root.after(0, _ui)
            return _fn

        def _is_slot_active(idx):
            """True if slot idx's event is genuinely running right now —
            its start-timer has already fired, its stop-timer hasn't."""
            t_s, t_e = sched_timers[idx]
            started = (t_s is None) or (not t_s.is_alive())
            running = (t_e is not None) and t_e.is_alive()
            return started and running

        def _compute_start_stop(sh, sm, eh, em, now):
            """Same date logic used throughout: today's start/stop,
            pushed a day forward if the event spans midnight, then
            (repeatedly, for the once-daily-jump case) pushed a further
            day forward if still more than 5 minutes in the past, then
            finally clamped to 'now + 1s' if still not in the future."""
            start_dt = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
            stop_dt  = now.replace(hour=eh, minute=em, second=0, microsecond=0)
            if stop_dt <= start_dt:
                stop_dt += timedelta(days=1)
            START_PAST_TOLERANCE_MIN = 5
            while start_dt < now - timedelta(minutes=START_PAST_TOLERANCE_MIN):
                start_dt += timedelta(days=1)
                stop_dt  += timedelta(days=1)
            if start_dt <= now:
                start_dt = now + timedelta(seconds=1)
            return start_dt, stop_dt

        def _hhmm_to_minutes(h, m):
            return h * 60 + m

        def _time_in_window_inclusive(t, start, stop):
            """True if wall-clock minute t (0-1439) falls within
            [start, stop], BOTH ends inclusive (so an exact touch counts
            as 'inside' too — deliberately, per user request: two events
            that exactly border each other, end == start, are a
            collision, not a valid schedule). Handles midnight
            wraparound automatically: if stop < start, the window is
            understood to run past midnight into the next day."""
            if start <= stop:
                return start <= t <= stop
            else:
                return t >= start or t <= stop

        def _slots_collide(a_start, a_stop, b_start, b_stop):
            """True if event A (a_start..a_stop) and event B
            (b_start..b_stop) — all in minutes-since-midnight, 0-1439 —
            overlap OR merely touch (share their boundary). Deliberately
            pure wall-clock comparison, NO date involved at all (per
            explicit user request, Aug 2026): every Timer-Event is
            simply understood to happen 'tonight' on the local PC clock;
            an event that runs past midnight is handled automatically by
            _time_in_window_inclusive()'s wraparound logic above, not by
            any separate day/date bookkeeping."""
            return (_time_in_window_inclusive(a_start, b_start, b_stop) or
                    _time_in_window_inclusive(b_start, a_start, a_stop))

        def _neighbor_minutes(n_idx):
            """(start_min, stop_min) for neighbor n_idx's OWN entered
            fields, purely as clock minutes — or None if that neighbor
            has no usable time fields at all (empty/never touched)."""
            if n_idx < 0 or n_idx >= NUM_SLOTS:
                return None
            ss = self._sched_state[n_idx]
            try:
                n_sh = int(ss.get('sh','')); n_sm = int(ss.get('sm',''))
                n_eh = int(ss.get('eh','')); n_em = int(ss.get('em',''))
            except (ValueError, TypeError):
                return None
            return _hhmm_to_minutes(n_sh, n_sm), _hhmm_to_minutes(n_eh, n_em)

        def _make_slot_prestop_check(idx):
            """Returns the function that fires ~60s before slot idx's own
            start time (Aug 2026, user request).

            Auto-stops Dream IF it is currently running AND that running
            session does not belong to any OTHER currently-active
            Timer-Event slot — i.e. it must be a manually-started Dream
            (via 'Start Dream'/'Start Dream with Log' or the
            Radio-List), left running by the user. This prevents a
            silent collision: _do_start()'s own 'Dream is already
            running' guard would otherwise quietly refuse this slot's
            scheduled start with no visible effect — the slot's LED
            still turned green as if it had started, even though
            nothing had actually happened and the old Dream just kept
            running unchanged.

            Deliberately does NOT touch a Dream session that legitimately
            belongs to another still-active Timer-Event slot —
            collision-free scheduling (_slots_collide(), checked at Set
            time) already guarantees that other slot will have finished
            on its own well before this one starts, so nothing needs to
            be force-stopped in that case.

            The Sammel-LEDs (Main-GUI + this dialog's own Status LED)
            already show the user, well ahead of time, that a
            Timer-Event is armed and waiting — so an automatic stop here
            is simply the logical consequence of the user's own earlier
            scheduling, not a surprise.
            """
            def _fn():
                def _ui():
                    if not self._is_dream_running():
                        return   # nothing running — nothing to do
                    # Is this running Dream legitimately owned by another,
                    # still-active Timer-Event slot? Same "start-timer
                    # dead, stop-timer alive" test used everywhere else
                    # in this file to mean "genuinely active right now"
                    # (not merely waiting).
                    for j in range(NUM_SLOTS):
                        if j == idx:
                            continue
                        pair = self._sched_timers[j]
                        t_s_j, t_e_j = pair[0], pair[1]
                        if (t_s_j is None or not t_s_j.is_alive()) and \
                           (t_e_j is not None and t_e_j.is_alive()):
                            return   # owned by another active event — leave it
                    # Otherwise: a manually-started Dream is blocking this
                    # slot's own scheduled start — stop it now, about a
                    # minute ahead of time, so the actual start-timer
                    # below finds a clean, idle Dream instead of
                    # silently failing its own 'already running' guard.
                    try:
                        status_lbl.config(
                            text=f'Timer-Event: stopping manually-running '
                                 f'Dream before slot {idx+1} starts.',
                            fg='#cc6600')
                    except Exception:
                        pass
                    stop_dream(cancel_other_slots=False)
                self.root.after(0, _ui)
            return _fn

        def _slot_set(idx):
            """Validate and (re)arm ONLY this one row's own timer — never
            touches any other row. (Redesign, Aug 2026, replacing the old
            single 'Accept Schedule' button: that button processed all
            three rows together every time it was clicked, including
            already-running ones, which caused a false Dream-collision
            popup and could even orphan a genuinely running event — see
            the extensive analysis earlier in this file's history.)"""
            if _is_slot_active(idx):
                try:
                    dlg.lift()
                    dlg.focus_force()
                except Exception:
                    pass
                messagebox.showinfo('Timer-Event', 'First stop Dream.', parent=dlg)
                return

            sv = slot_vars[idx]
            sh_s = sv['sh'].get().strip()
            sm_s = sv['sm'].get().strip()
            eh_s = sv['eh'].get().strip()
            em_s = sv['em'].get().strip()

            if not (sh_s and sm_s and eh_s and em_s):
                _show_status_warning(
                    f'Slot {idx+1}: all four time fields are required.')
                return

            try:
                sh = int(sh_s); sm = int(sm_s)
                eh = int(eh_s); em = int(em_s)
            except ValueError:
                _show_status_warning(f'Slot {idx+1}: invalid time format')
                return

            freq    = sv['freq'].get().strip()
            use_log = bool(sv['log'].get())
            use_ap  = bool(sv['autoplot'].get())

            if use_log and not freq:
                _show_status_warning(
                    f'Slot {idx+1}: frequency required for Log start!')
                return

            now = datetime.now()
            start_dt, stop_dt = _compute_start_stop(sh, sm, eh, em, now)

            # ── Collision check against every OTHER slot ────────────────
            # (Aug 2026, simplified per user request): pure wall-clock
            # comparison, no date involved at all — see _slots_collide()
            # above for the exact rule (overlap OR exact touch counts as
            # a collision; midnight wraparound handled automatically).
            # Checks every other slot, not just the immediate neighbor —
            # a genuine collision doesn't care about row position.
            a_start_min = _hhmm_to_minutes(sh, sm)
            a_stop_min  = _hhmm_to_minutes(eh, em)
            for n_idx in range(NUM_SLOTS):
                if n_idx == idx:
                    continue
                nbr = _neighbor_minutes(n_idx)
                if nbr is None:
                    continue   # neighbor empty/unset — nothing to check
                n_start_min, n_stop_min = nbr
                if _slots_collide(a_start_min, a_stop_min, n_start_min, n_stop_min):
                    _show_status_warning(
                        f'Slot {idx+1}: time collides with slot {n_idx+1}!')
                    return

            # ── Cancel this row's own previous timer (if any) — safe,
            # already confirmed above this row is NOT currently active.
            for t in sched_timers[idx]:
                if t: t.cancel()
            # Aug 2026: also cancel this row's own previous pre-stop
            # timer (see _make_slot_prestop_check()) — same "row not
            # currently active" safety already confirmed above.
            if self._sched_prestop_timers[idx]:
                self._sched_prestop_timers[idx].cancel()

            self._autoplot_enabled[0] = False   # reset; set again at fire time
            start_secs = (start_dt - now).total_seconds()
            stop_secs  = (stop_dt  - now).total_seconds()

            t_start = threading.Timer(
                start_secs, _make_slot_start(idx, freq, use_log, use_ap))
            t_stop  = threading.Timer(
                stop_secs,  _make_slot_stop(idx))
            t_start.daemon = True
            t_stop.daemon  = True
            t_start.start()
            t_stop.start()
            sched_timers[idx]       = [t_start, t_stop]
            self._sched_timers[idx] = [t_start, t_stop]
            # Pre-stop timer (Aug 2026, user request) — fires ~60s before
            # this slot's own start, auto-stopping a manually-running
            # Dream so it doesn't collide with the scheduled start below.
            # If the start is itself less than 60s away, fires almost
            # immediately (max(0, ...)) rather than not at all.
            prestop_secs = max(0.0, start_secs - 60.0)
            t_prestop = threading.Timer(
                prestop_secs, _make_slot_prestop_check(idx))
            t_prestop.daemon = True
            t_prestop.start()
            self._sched_prestop_timers[idx] = t_prestop
            self._sched_state[idx] = {
                'sh': sh_s, 'sm': sm_s,
                'eh': eh_s, 'em': em_s,
                'freq': freq, 'log': int(use_log),
                'autoplot': int(use_ap), 'led': 'yellow',
                # Real, fully-dated start/stop — used only to actually
                # arm the background timers below (a computer needs a
                # concrete date to know exactly when to fire). The
                # collision check above is now a separate, pure
                # wall-clock (date-free) comparison — see
                # _slots_collide() earlier in this function.
                'start_dt': start_dt, 'stop_dt': stop_dt}

            set_led(slot_leds[idx][0], slot_leds[idx][1], 'yellow')
            _safe_led('led5', led5_c, led5_o, 'yellow')
            status_lbl.config(text=f'Slot {idx+1} set.', fg='#007700')

        def _slot_clear(idx):
            """Clear ONLY this one row — never touches any other row.
            Blocked with 'First stop Dream' if this row is currently
            active, exactly like _slot_set()."""
            if _is_slot_active(idx):
                try:
                    dlg.lift()
                    dlg.focus_force()
                except Exception:
                    pass
                messagebox.showinfo('Timer-Event', 'First stop Dream.', parent=dlg)
                return
            for t in sched_timers[idx]:
                if t: t.cancel()
            if self._sched_prestop_timers[idx]:
                self._sched_prestop_timers[idx].cancel()
                self._sched_prestop_timers[idx] = None
            sched_timers[idx]       = [None, None]
            self._sched_timers[idx] = [None, None]
            self._sched_state[idx]  = {
                'sh':'','sm':'','eh':'','em':'',
                'freq':'','log':0,'autoplot':0,'led':'grey'}
            sv = slot_vars[idx]
            for v in [sv['sh'], sv['sm'], sv['eh'], sv['em'], sv['freq']]:
                v.set('')
            sv['log'].set(0)
            sv['autoplot'].set(0)
            set_led(slot_leds[idx][0], slot_leds[idx][1], 'grey')
            status_lbl.config(text=f'Slot {idx+1} cleared.', fg='#555555')

        def _find_free_timer_slot():
            """Index of the first slot with all four time fields empty —
            deliberately independent of which row a later-starting event
            might sit in; only 'is it empty' matters, never row order.

            FIX (Aug 2026): reads the LIVE, visible field values
            (slot_vars) directly, not self._sched_state — that only gets
            updated once the user actually clicks a row's own "Set"
            button. Checking it here meant a row merely FILLED by
            'Radio-List for Timer-Event' (but not yet confirmed with
            Set) still counted as "free", so a second click overwrote
            the same row instead of moving on to the next one. Reading
            the visible fields directly fixes that AND gives exactly the
            requested behaviour: clicking the Radio-List repeatedly
            fills row 1, then row 2, then row 3 — purely a data copy,
            never triggering Set/activation on its own."""
            for i in range(NUM_SLOTS):
                sv = slot_vars[i]
                if not (sv['sh'].get().strip() or sv['sm'].get().strip() or
                        sv['eh'].get().strip() or sv['em'].get().strip()):
                    return i
            return None

        def _utc_hhmm_to_local(hh, mm):
            """Converts a UTC hour/minute (today's date, purely as an
            anchor — only the resulting local hour/minute is used) to the
            PC's own local time, via Python's built-in timezone-aware
            datetime conversion. Reads whatever timezone the operating
            system itself is set to — correct for any user worldwide,
            including DST, with nothing hardcoded."""
            utc_dt = datetime.now(timezone.utc).replace(
                hour=hh, minute=mm, second=0, microsecond=0)
            local_dt = utc_dt.astimezone()
            return local_dt.hour, local_dt.minute

        def _copy_confirm_dialog(parent, text):
            """Small custom Yes/No confirmation — NOT a native
            messagebox, specifically so its position can be remembered
            (native dialogs don't support that). Explicit Arial font
            throughout (Linux would otherwise substitute a different
            default font here). A proper descendant of 'parent' (via
            Toplevel(parent) + its own grab_set()), so it works correctly
            even while 'Dream — Start & Schedule' holds its own grab —
            same pattern already proven for every other nested dialog in
            this programme."""
            result = {'ok': False}
            cd = tk.Toplevel(parent)
            cd.title('Copy to Timer-Event-List?')
            cd.configure(bg=GUI_BG)
            # Bugfix (Aug 2026): this dialog was missing transient()/
            # lift()/focus_force() — every other dialog in this
            # programme sets these. grab_set() alone only restricts
            # INPUT to this window; it does nothing for its stacking
            # position. Without transient(), the window manager doesn't
            # know this popup belongs to 'parent' and can fail to keep
            # it on top — most visible after a rapid double-click, where
            # OS-level anti-focus-stealing protection is far more likely
            # to kick in than after a single, slower click.
            cd.transient(parent)
            _saved_geom3 = self.cfg.get('radio_list_timer_confirm_geometry', '')
            if _saved_geom3:
                try:
                    cd.geometry(_saved_geom3)
                except Exception:
                    center_dialog(cd, parent, 380, 190)
            else:
                center_dialog(cd, parent, 380, 190)

            def _save_geometry3(event=None):
                if event is not None and event.widget is not cd:
                    return
                try:
                    self.cfg.set('radio_list_timer_confirm_geometry', cd.geometry())
                except Exception:
                    pass
            cd.bind('<Configure>', _save_geometry3, add='+')

            tk.Label(cd, text=text, font=('Arial', 10), bg=GUI_BG,
                     fg='black', justify=tk.LEFT).pack(padx=16, pady=(18,12))

            btn_row3 = tk.Frame(cd, bg=GUI_BG)
            btn_row3.pack(pady=(0,14))

            def _yes():
                result['ok'] = True
                cd.destroy()
            def _no():
                result['ok'] = False
                cd.destroy()

            tk.Button(btn_row3, text='OK', font=('Arial',10), width=8,
                      bg='#aaddaa', command=_yes).pack(side=tk.LEFT, padx=6)
            tk.Button(btn_row3, text='Cancel', font=('Arial',10), width=8,
                      command=_no).pack(side=tk.LEFT, padx=6)

            cd.protocol('WM_DELETE_WINDOW', _no)

            # FIX (Aug 2026): grab_set() was previously called right after
            # creating 'cd', before any widgets existed — a well-known
            # Tkinter render-order pitfall where the window appears but
            # its content never gets painted until the user manually
            # interacts with it (drag/resize). Packing everything FIRST,
            # then forcing a redraw with update_idletasks(), and only
            # THEN grabbing input, guarantees the text and buttons are
            # actually visible the moment this window appears.
            cd.update_idletasks()
            # Bugfix (Aug 2026): explicit lift()/focus_force(), same as
            # every other dialog — don't just rely on the OS's default
            # 'new window gets focus' behaviour, which is exactly what
            # a rapid double-click can suppress.
            cd.lift()
            cd.focus_force()
            cd.grab_set()
            cd.wait_window()
            return result['ok']

        # Toggle behaviour (Aug 2026, user request) — tracks the
        # currently-open 'Radio-List for Timer-Event' window for this
        # one open instance of 'Dream — Start & Schedule'. A local
        # mutable container (not self.), since _open_radio_list_for_timer()
        # is itself a fresh nested closure created every time this outer
        # dialog opens — matches its own lifetime correctly.
        _rl2_window_ref = [None]

        def _open_radio_list_for_timer():
            """
            'Radio-List for Timer-Event' — a separate, reduced copy of
            the Main-GUI's DRM-Radio-List window (Aug 2026). Deliberately
            unrelated to that window's own button/logic: no rigctl, no
            Dream control, no Presets — clicking a row here only ever
            COPIES that station's start/stop time (converted from UTC to
            the PC's local time) and frequency, as plain text, into the
            next free Timer-Event row. Uses the SAME shared schedule data
            (self.drm_schedule, same file path) as the Main-GUI's window,
            so Load/Edit here stay in sync with it.

            Toggle behaviour (Aug 2026, user request): a 2nd click on the
            'Radio-List' button while this window is already open closes
            it instead of opening a further copy.
            """
            if _rl2_window_ref[0] is not None and _rl2_window_ref[0].winfo_exists():
                _rl2_window_ref[0].destroy()
                return
            rl2 = tk.Toplevel(dlg)
            rl2.title('Radio-List for Timer-Event')
            rl2.configure(bg=GUI_BG)
            # Declared early (Aug 2026) so the new 7-segment clock (built
            # further below) can reuse this SAME alive-flag as its own
            # stop condition — the rest of the auto-refresh machinery is
            # still defined later, unchanged, where it always was.
            _rl2_alive = [True]
            _rl2_window_ref[0] = rl2
            def _clear_rl2_ref(event=None):
                if event is not None and event.widget is not rl2:
                    return
                _rl2_window_ref[0] = None
            rl2.bind('<Destroy>', _clear_rl2_ref, add='+')
            # transient(dlg) — fixes this window sinking behind the
            # Main-GUI whenever the user clicks back into 'Dream — Start
            # & Schedule' (e.g. a row's own 'Set' button). Without this,
            # the window manager doesn't know the two belong together and
            # can restack them incorrectly. Trade-off (Aug 2026, accepted
            # for this window specifically): transient windows lose their
            # taskbar minimize button on Windows — unlike the standalone
            # DRM-Radio-List window (where that was fixed the other way),
            # this one is only ever opened as a helper FROM WITHIN this
            # dialog, so staying reliably on top matters more here.
            rl2.transient(dlg)
            _saved_geom2 = self.cfg.get('radio_list_timer_geometry', '')
            if _saved_geom2:
                try:
                    rl2.geometry(_saved_geom2)
                except Exception:
                    center_dialog(rl2, self.root, 1180, 790)
            else:
                center_dialog(rl2, self.root, 1180, 790)

            def _save_geometry2(event=None):
                if event is not None and event.widget is not rl2:
                    return
                try:
                    self.cfg.set('radio_list_timer_geometry', rl2.geometry())
                except Exception:
                    pass
            rl2.bind('<Configure>', _save_geometry2, add='+')

            list_status2 = tk.Label(rl2, text='No DRMSchedule.ini loaded yet.',
                                    bg=GUI_BG, font=('Arial',10,'italic'),
                                    fg='#555555', anchor='w')

            top2 = tk.Frame(rl2, bg=GUI_BG)
            top2.pack(fill=tk.X, padx=8, pady=(8,4))
            path_var2 = tk.StringVar(value=self.cfg.get('drmschedule_path',''))

            def load_schedule2():
                start_dir = (os.path.dirname(path_var2.get())
                             if path_var2.get() and os.path.isfile(path_var2.get())
                             else os.path.expanduser('~'))
                p = filedialog.askopenfilename(
                    parent=rl2, title='Load DRM Schedule (.ini)',
                    initialdir=start_dir if os.path.isdir(start_dir) else os.path.expanduser('~'),
                    filetypes=[('DRM Schedule', '*.ini'), ('All files', '*.*')])
                if not p:
                    return
                entries = parse_drm_schedule(p)
                if not entries:
                    list_status2.config(
                        text=f'No valid entries found in: {p}', fg='#cc0000')
                    return
                path_var2.set(p)
                self.cfg.set('drmschedule_path', p)
                self.drm_schedule = entries
                path_label2.pack_forget()
                list_status2.config(
                    text=f'Loaded {len(entries)} entries from: {p}',
                    fg='#007700')
                refresh_view2()

            tk.Button(top2, text='Load DRMSchedule', font=('Arial',9),
                      bg='#aaddff', command=load_schedule2).pack(side=tk.LEFT)
            tk.Button(top2, text='Edit DRM-Schedule', font=('Arial',9),
                      bg='#ffddaa',
                      command=lambda: self._manage_drm_schedule(
                          on_change=lambda: refresh_view2(), parent=rl2)
                      ).pack(side=tk.LEFT, padx=(6,0))
            # Aug 2026, user request: same hide-after-successful-load
            # behaviour as the Main-GUI's DRM-Radio-List — see comment
            # there for the full explanation.
            path_label2 = tk.Label(top2, textvariable=path_var2, bg=GUI_BG,
                                   font=('Arial',8), fg='#555555')
            path_label2.pack(side=tk.LEFT, padx=(8,0))
            if path_var2.get():
                path_label2.pack_forget()

            # ── UTC clock (Aug 2026, user request) — same bordered look
            # as the Main-GUI's DRM-Radio-List clock. 'Last choice was'
            # was tried here too but removed again per user follow-up:
            # this window only ever copies stations into Timer-Event
            # slots, it never actually 'tunes' anything, so a Last-choice
            # read-out didn't make sense here after all.
            _rl2_clock_frame = tk.Frame(top2, bg=GUI_BG, relief=tk.GROOVE, bd=2)
            _rl2_clock_frame.pack(side=tk.RIGHT, padx=(8,20))
            tk.Label(_rl2_clock_frame, text='UTC:', bg=GUI_BG,
                     font=('Arial',10), fg='black').pack(side=tk.LEFT, padx=4, pady=2)
            self._build_text_clock(_rl2_clock_frame, _rl2_alive).pack(
                side=tk.LEFT, padx=(0,4), pady=2)

            sort_row2 = tk.Frame(rl2, bg=GUI_BG)
            sort_row2.pack(fill=tk.X, padx=8, pady=(2,2))
            tk.Label(sort_row2, text='Sort by:', bg=GUI_BG,
                     font=('Arial',8,'bold')).pack(side=tk.LEFT, padx=(0,6))
            SORT_OPTIONS2 = [
                ('active',    'Active'),
                ('programme', 'Programme'),
                ('time',      'Time'),
                ('khz',       'kHz'),
                ('target',    'Target'),
                ('site',      'Site'),
                ('country',   'Country'),
                ('language',  'Language'),
            ]
            sort_var2 = tk.StringVar(value=self.cfg.get('radio_list_timer_sort', 'active'))
            def _on_sort_change2():
                self.cfg.set('radio_list_timer_sort', sort_var2.get())
                refresh_view2()
            for key, label in SORT_OPTIONS2:
                tk.Radiobutton(sort_row2, text=label, variable=sort_var2, value=key,
                               bg=GUI_BG, font=('Arial',8),
                               command=_on_sort_change2).pack(side=tk.LEFT, padx=3)

            cols2 = ('programme','time','khz','kw','target','site','country','language')
            headers2 = {'programme':'Programme','time':'Time (UTC)','khz':'kHz',
                       'kw':'kW','target':'Target','site':'Site',
                       'country':'Country','language':'Language'}
            widths2  = {'programme':170,'time':90,'khz':60,'kw':45,
                       'target':150,'site':110,'country':90,'language':90}

            tv_frame2 = tk.Frame(rl2, bg=GUI_BG)
            tv_frame2.pack(fill=tk.BOTH, expand=True, padx=8, pady=(2,4))
            tv_scroll2 = tk.Scrollbar(tv_frame2, orient='vertical')
            tv2 = ttk.Treeview(tv_frame2, columns=cols2, show='headings',
                               yscrollcommand=tv_scroll2.set, selectmode='browse')
            tv_scroll2.config(command=tv2.yview)
            tv_scroll2.pack(side=tk.RIGHT, fill=tk.Y)
            tv2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            _saved_widths2 = self.cfg.get('radio_list_timer_col_widths', {}) or {}
            for c in cols2:
                tv2.heading(c, text=headers2[c])
                tv2.column(c, width=_saved_widths2.get(c, widths2[c]), anchor='w')

            def _save_col_widths2(event=None):
                try:
                    self.cfg.set('radio_list_timer_col_widths',
                                  {c: tv2.column(c, 'width') for c in cols2})
                except Exception:
                    pass
            tv2.bind('<ButtonRelease-1>', _save_col_widths2, add='+')
            tv2.tag_configure('active',   background='#b6f2b6')
            tv2.tag_configure('soon',     background='#ff9999')  # red = starts within 15 min (Aug 2026)
            tv2.tag_configure('lastfreq', background='#aee0ff')  # light blue = matches last-chosen frequency in the Main-GUI Radio List (Aug 2026)
            tv2.tag_configure('inactive', background='#fff6b0')

            def _fmt_time2(e):
                return f"{e['start_h']:02d}{e['start_m']:02d}-{e['stop_h']:02d}{e['stop_m']:02d}"

            def _row_sort_key2(key, e, active_now):
                if key == 'active':    return (0 if active_now else 1, e['freq_khz'])
                if key == 'programme': return e['programme'].lower()
                if key == 'time':      return e['start_h']*60 + e['start_m']
                if key == 'khz':       return e['freq_khz']
                if key == 'target':    return e['target'].lower()
                if key == 'site':      return e['site'].lower()
                if key == 'country':   return e['country'].lower()
                if key == 'language':  return e['language'].lower()
                return 0

            # Maps each Treeview row id to its source entry dict, so a
            # click can look up exact start_h/start_m/stop_h/stop_m/
            # freq_khz directly — no re-parsing of displayed text needed.
            _entry_by_iid = {}

            def refresh_view2():
                tv2.delete(*tv2.get_children())
                _entry_by_iid.clear()
                entries = self.drm_schedule
                if not entries:
                    return
                now_utc = datetime.now(timezone.utc)
                rows = [(e, drm_entry_is_active(e, now_utc)) for e in entries]
                key = sort_var2.get()
                rows.sort(key=lambda r: _row_sort_key2(key, r[0], r[1]))
                # Aug 2026, user request: same red/blue row colouring as
                # the Main-GUI's DRM-Radio-List. This window has no
                # 'Last choice' display of its own (it copies stations
                # into Timer-Event slots rather than tuning a receiver),
                # so it reuses the SAME persisted last-chosen-frequency
                # value as that other window — showing here, too, which
                # rows match whatever frequency is currently tuned.
                _last_khz_str = str(self.cfg.get(
                    'drm_radio_list_last_choice', '') or '').strip()
                for e, active_now in rows:
                    if active_now:
                        tag = 'active'
                    elif drm_entry_starts_soon(e, now_utc):
                        tag = 'soon'
                    elif _last_khz_str and str(e['freq_khz']) == _last_khz_str:
                        tag = 'lastfreq'
                    else:
                        tag = 'inactive'
                    iid = tv2.insert('', 'end', values=(
                        e['programme'], _fmt_time2(e), e['freq_khz'], e['power'],
                        e['target'], e['site'], e['country'], e['language']),
                        tags=(tag,))
                    _entry_by_iid[iid] = e

            def _get_slot_minutes(i):
                """(start_min, stop_min) for slot i's CURRENT visible
                fields, or None if not fully filled — same 'trust the
                visible fields, not self._sched_state' principle as
                _find_free_timer_slot()."""
                sv = slot_vars[i]
                try:
                    o_sh = int(sv['sh'].get().strip())
                    o_sm = int(sv['sm'].get().strip())
                    o_eh = int(sv['eh'].get().strip())
                    o_em = int(sv['em'].get().strip())
                except (ValueError, TypeError):
                    return None
                return _hhmm_to_minutes(o_sh, o_sm), _hhmm_to_minutes(o_eh, o_em)

            def _compute_copy_target(e):
                """
                Shared by both the single-click (with confirmation) and
                double-click (direct, no confirmation) paths — Aug 2026.
                Finds the next free Timer-Event slot, applies the 24-hour
                station guard and the automatic +-1 minute adjustment,
                exactly as before. Returns None if the copy cannot
                proceed (a popup was already shown explaining why), or
                (free_idx, sh_l, sm_l, eh_l, em_l, adj_note) on success.
                Deliberately does NOT touch slot_vars or show the
                confirmation text itself — callers decide what to do
                with the result.
                """
                free_idx = _find_free_timer_slot()
                if free_idx is None:
                    try:
                        rl2.lift()
                        rl2.focus_force()
                    except Exception:
                        pass
                    messagebox.showinfo('Timer-Event',
                                        'First clear one Timer-Event.',
                                        parent=rl2)
                    return None

                # ── 24-hour ('round the clock') station guard (Aug 2026) ──
                # A station logged as 0000-2400 UTC stores its stop hour
                # as literally 24 — Python's datetime cannot represent
                # that (hour must be 0-23), so converting it to local
                # time would crash. Deliberately NOT auto-correcting this
                # to 00:00/next-day (user's explicit decision, Aug 2026):
                # that would reintroduce date/rollover bookkeeping into
                # the Timer-Event collision logic, which was just made
                # deliberately date-free. A clear popup asking for manual
                # entry is the safer choice.
                if e['stop_h'] >= 24:
                    messagebox.showinfo(
                        'Timer-Event',
                        'This station broadcasts 24 hours\n'
                        '(00:00\u201324:00 UTC).\n\n'
                        'Please manually enter this Timer-Event\n'
                        'with an end time of 23:59.',
                        parent=rl2)
                    return None

                sh_l, sm_l = _utc_hhmm_to_local(e['start_h'], e['start_m'])
                eh_l, em_l = _utc_hhmm_to_local(e['stop_h'],  e['stop_m'])

                # ── Automatic +-1 minute adjustment (Aug 2026) ──────────
                # International schedules very often place consecutive
                # transmissions exactly back-to-back on the hour (e.g.
                # 21:00-22:00 then 22:00-23:00) — which the deliberate
                # "touching = collision" rule (see _slots_collide()) would
                # otherwise correctly flag as a collision the moment the
                # user later clicks that row's own "Set" button. Checking
                # for this now, at copy time, and nudging by one minute
                # avoids that surprise later — checked in BOTH directions:
                # the new start touching an existing row's end (push
                # start +1 min), and the new end touching an existing
                # row's start (pull end -1 min). Compared against every
                # OTHER already-filled row's CURRENT visible fields —
                # same "filled counts, Set not required" principle as
                # the free-slot search above.
                new_start_min = _hhmm_to_minutes(sh_l, sm_l)
                new_stop_min  = _hhmm_to_minutes(eh_l, em_l)
                adj_start = False
                adj_end   = False
                for i in range(NUM_SLOTS):
                    if i == free_idx:
                        continue
                    other = _get_slot_minutes(i)
                    if other is None:
                        continue
                    o_start_min, o_stop_min = other
                    if new_start_min == o_stop_min:
                        new_start_min = (new_start_min + 1) % 1440
                        adj_start = True
                    if new_stop_min == o_start_min:
                        new_stop_min = (new_stop_min - 1) % 1440
                        adj_end = True
                sh_l, sm_l = divmod(new_start_min, 60)
                eh_l, em_l = divmod(new_stop_min, 60)

                adj_note = ''
                if adj_start and adj_end:
                    adj_note = '  (start +1 min, end -1 min — avoids touching a neighbor)'
                elif adj_start:
                    adj_note = '  (start +1 min — avoids touching a neighbor)'
                elif adj_end:
                    adj_note = '  (end -1 min — avoids touching a neighbor)'

                return free_idx, sh_l, sm_l, eh_l, em_l, adj_note

            def _apply_copy_target(free_idx, e, sh_l, sm_l, eh_l, em_l):
                """Writes the computed local start/stop + frequency into
                the given Timer-Event slot's visible fields. Shared by
                both single- and double-click paths (Aug 2026)."""
                slot_vars[free_idx]['sh'].set(f'{sh_l:02d}')
                slot_vars[free_idx]['sm'].set(f'{sm_l:02d}')
                slot_vars[free_idx]['eh'].set(f'{eh_l:02d}')
                slot_vars[free_idx]['em'].set(f'{em_l:02d}')
                slot_vars[free_idx]['freq'].set(str(e['freq_khz']))
                list_status2.config(
                    text=f'Copied to Timer-Event slot {free_idx+1}. '
                         f'Click that row\'s own "Set" button to arm it.',
                    fg='#007700')

            # Pending single-click action, so a genuine double-click can
            # cancel it before the confirmation popup ever appears — see
            # on_row_select2()/on_row_dblclick2() below for why this is
            # needed.
            _pending_click_after_id = [None]

            def on_row_select2(event=None):
                """
                Single click (via <<TreeviewSelect>>).

                IMPORTANT (Aug 2026): this virtual event also fires on
                the FIRST press of a double-click — Tk has no way to
                know in advance that a second click is coming. Opening
                the confirmation popup immediately here would therefore
                also open it (and, worse, steal the second click) on
                every double-click too, defeating the whole point of
                the no-confirmation double-click path below. So the
                actual confirmation is scheduled after a short delay
                (standard double-click threshold) instead of running
                immediately; on_row_dblclick2() cancels this pending
                action the moment a real double-click is detected, so
                the popup never gets a chance to appear in that case.
                A plain single click still shows the popup exactly as
                before, just ~250ms later — not perceptible in normal use.
                """
                sel = tv2.selection()
                if not sel:
                    return
                e = _entry_by_iid.get(sel[0])
                if not e:
                    return

                if _pending_click_after_id[0] is not None:
                    try:
                        rl2.after_cancel(_pending_click_after_id[0])
                    except Exception:
                        pass
                    _pending_click_after_id[0] = None

                def _do_single_click_confirm():
                    _pending_click_after_id[0] = None
                    result = _compute_copy_target(e)
                    if result is None:
                        return
                    free_idx, sh_l, sm_l, eh_l, em_l, adj_note = result
                    confirm_text = (
                        f"{e['freq_khz']} kHz\n"
                        f"{e['start_h']:02d}:{e['start_m']:02d}\u2013"
                        f"{e['stop_h']:02d}:{e['stop_m']:02d} UTC "
                        f"\u2192 {sh_l:02d}:{sm_l:02d}\u2013{eh_l:02d}:{em_l:02d} local"
                        f"{adj_note}\n"
                        f"Copy to Timer-Event-List?"
                    )
                    if _copy_confirm_dialog(rl2, confirm_text):
                        _apply_copy_target(free_idx, e, sh_l, sm_l, eh_l, em_l)

                _pending_click_after_id[0] = rl2.after(
                    250, _do_single_click_confirm)

            def on_row_dblclick2(event=None):
                """Double click (Aug 2026, user request) — copies
                straight to the next free Timer-Event slot, NO
                confirmation popup. International double-click
                convention: single click = review/confirm, double click
                = immediate action. The 'First clear one Timer-Event.'
                and 24-hour-station guards still apply — those are safety
                checks, not the confirmation step being skipped here.
                First cancels the single-click confirmation scheduled by
                on_row_select2()'s first half of this same double-click,
                so that popup never appears at all."""
                if _pending_click_after_id[0] is not None:
                    try:
                        rl2.after_cancel(_pending_click_after_id[0])
                    except Exception:
                        pass
                    _pending_click_after_id[0] = None
                sel = tv2.selection()
                if not sel:
                    return
                e = _entry_by_iid.get(sel[0])
                if not e:
                    return
                result = _compute_copy_target(e)
                if result is None:
                    return
                free_idx, sh_l, sm_l, eh_l, em_l, adj_note = result
                _apply_copy_target(free_idx, e, sh_l, sm_l, eh_l, em_l)

            tv2.bind('<<TreeviewSelect>>', on_row_select2)
            # Double-click (Aug 2026, user request) — direct copy, no
            # confirmation popup. Bound separately from the single-click
            # selection event above; both paths share the same
            # underlying logic via _compute_copy_target()/_apply_copy_target().
            tv2.bind('<Double-Button-1>', on_row_dblclick2)

            def _on_rl2_close():
                _rl2_alive[0] = False
                if _rl2_after_id[0]:
                    try: rl2.after_cancel(_rl2_after_id[0])
                    except Exception: pass
                # Aug 2026: also cancel any still-pending single-click
                # confirmation (see on_row_select2()) so it can't fire
                # after this window is already gone.
                if _pending_click_after_id[0] is not None:
                    try: rl2.after_cancel(_pending_click_after_id[0])
                    except Exception: pass
                rl2.destroy()

            bottom_row2 = tk.Frame(rl2, bg=GUI_BG)
            bottom_row2.pack(fill=tk.X, padx=10, pady=(6,4))

            # Hint text — packed RIGHT first so it reliably claims the
            # far-right edge. list_status2 (packed LEFT, expanding) then
            # takes whatever space remains on the left.
            tk.Label(bottom_row2, text='Click in the list to select a Timer-Event',
                     bg=GUI_BG, font=('Arial',13), fg='#555555').pack(
                     side=tk.RIGHT, padx=(8,0))
            list_status2.pack(in_=bottom_row2, side=tk.LEFT, fill=tk.X, expand=True)

            # Close — its own row, packed with no side so it centers
            # horizontally in the window by default (pack's default
            # anchor is 'center'), instead of sharing the row above.
            close_row2 = tk.Frame(rl2, bg=GUI_BG)
            close_row2.pack(fill=tk.X, padx=10, pady=(4,14))
            tk.Button(close_row2, text='Close', font=('Arial',9), width=10,
                      bg='#dddddd',
                      command=lambda: _on_rl2_close()).pack()

            _rl2_after_id = [None]
            # Interval shortened 60s -> 5s (Aug 2026, user request) —
            # same reasoning as the Main-GUI's DRM-Radio-List above.
            def _auto_refresh2():
                if not _rl2_alive[0]:
                    return
                refresh_view2()
                _rl2_after_id[0] = rl2.after(5000, _auto_refresh2)
            rl2.protocol('WM_DELETE_WINDOW', _on_rl2_close)

            if self.drm_schedule:
                list_status2.config(
                    text=f'{len(self.drm_schedule)} entries loaded from: {path_var2.get()}',
                    fg='#007700')
            refresh_view2()
            _rl2_after_id[0] = rl2.after(5000, _auto_refresh2)

        def clear_event():
            # ── Cancel all pending timers ──────────────────────────
            for pair in sched_timers:
                for t in pair:
                    if t: t.cancel()
            for i in range(NUM_SLOTS):
                sched_timers[i]       = [None, None]
                self._sched_timers[i] = [None, None]
                self._sched_state[i]  = {
                    'sh':'','sm':'','eh':'','em':'',
                    'freq':'','log':0,'autoplot':0,'led':'grey'}
                sv = slot_vars[i]
                for v in [sv['sh'], sv['sm'], sv['eh'], sv['em'], sv['freq']]:
                    v.set('')
                sv['log'].set(0)
                sv['autoplot'].set(0)
                set_led(*slot_leds[i], 'grey')
            # ── Stop Dream if running ──────────────────────────────
            # Cancel any AutoPlot countdown first
            if hasattr(self, '_ap_countdown_active'):
                self._ap_countdown_active[0] = False
            self._dream_start_time = None   # reset dream start time
            self._stop_autoplot_silent()
            stop_dream()
            # ── Reset all LEDs ─────────────────────────────────────
            _safe_led('led1', led1_c, led1_o, 'grey')
            _safe_led('led2', led2_c, led2_o, 'grey')
            _safe_led('led3', led3_c, led3_o, 'grey')
            _safe_led('led4', led4_c, led4_o, 'grey')
            _safe_led('led5', led5_c, led5_o, 'grey')
            _safe_led('led6', led6_c, led6_o, 'grey')
            try:
                status_lbl.config(
                    text='All schedules cleared — Dream stopped.',
                    fg='#555555')
            except Exception: pass

        bs = tk.Frame(fs, bg=GUI_BG)
        bs.pack(pady=(6,2))
        tk.Button(bs, text='Clear All', font=('Arial',10), width=10,
                  command=clear_event).pack(side=tk.LEFT, padx=4)

        # ══════════════════════════════════════════════════════════════════
        # SEPARATE FRAME: SDR-RX USB/LSB rigctl-Frequency correction
        # ══════════════════════════════════════════════════════════════════
        # For SDR receivers with no native DRM mode: the user tunes in USB
        # or LSB with a widened filter (~10 kHz) and offsets the RX
        # frequency by a few kHz so the filter sits centred on the DRM
        # signal (e.g. 5870 kHz in USB instead of the true 5875 kHz for
        # BBC). Everywhere the user enters a frequency — the 'Log-Frequency'
        # field in 'Dream Manual Start / Stop' above, each Timer-Event's own
        # frequency field, a DRM-Radio-List click, a preset — it is always
        # the TRUE station/broadcast frequency; that is exactly what Dream
        # itself receives, unchanged. Only rigctl needs the offset-corrected
        # value, computed on the fly by _rigctl_freq_for_station() at the
        # one moment it actually matters (the rigctl call itself), never
        # stored anywhere else. Persistent (not per-session): a user's SDR
        # setup is normally static, and this applies automatically to
        # manual start, Timer-Events, and the DRM-Radio-List alike.
        # Deliberately a standalone frame (July 2026, moved out of 'Dream
        # Manual Start / Stop' per user request) — this is an independent
        # option, not tied to manual start specifically.
        usb_frame = tk.LabelFrame(
            dlg, text='Correction of DReam-Log-Frequency if SDR-RX in USB-LSB Mode used',
            bg=GUI_BG, font=('Arial',9,'bold'), relief=tk.GROOVE, bd=2,
            padx=8, pady=6)
        usb_frame.pack(fill=tk.X, padx=10, pady=(8,4))

        tk.Label(usb_frame,
                 text='Always input the real STATION/BROADCAST Frequency, '
                      'for both manual and Timer-Event use —\n'
                      'the RX/rigctl frequency for SDR-RX in USB/LSB Mode '
                      'is corrected automatically in the background.',
                 bg=GUI_BG, font=('Arial',9), justify=tk.LEFT,
                 anchor='w').pack(fill=tk.X, pady=(0,8))

        usb_row = tk.Frame(usb_frame, bg=GUI_BG)
        usb_row.pack(fill=tk.X)
        usb_lsb_var = tk.BooleanVar(value=self.cfg.get('sdr_usb_lsb_enabled', False))
        tk.Checkbutton(usb_row, text='SDR-RX - USB/LSB use', variable=usb_lsb_var,
                       bg=GUI_BG, font=('Arial',11),
                       command=lambda: self.cfg.set('sdr_usb_lsb_enabled',
                                                    usb_lsb_var.get())
                       ).pack(side=tk.LEFT)

        # ── USB / LSB sideband selector ─────────────────────────────────
        # Determines the SIGN of the offset that is actually stored in
        # 'sdr_usb_lsb_offset' — USB = positive, LSB = negative. Nothing
        # downstream needs to change for this: _rigctl_freq_for_station()
        # (in 'Dream Manual Start / Stop' above) already just reads the
        # signed value from config, exactly as before. The 'Offset (kHz)'
        # field below is now a plain, unsigned magnitude (0..10) — the
        # sideband choice is what decides the sign, so there is no longer
        # a way for the user to enter a value that contradicts the
        # selected sideband.
        sideband_var = tk.StringVar(
            value=self.cfg.get('sdr_usb_lsb_sideband', 'USB'))

        def _signed_offset(magnitude):
            return magnitude if sideband_var.get() == 'USB' else -magnitude

        def _save_current_offset():
            """Recompute the signed offset from magnitude + sideband and
            store it — shared by the magnitude auto-save trace below AND
            by the sideband radio buttons themselves (switching USB<->LSB
            must immediately re-sign whatever magnitude is already
            entered, without requiring the user to retype it)."""
            try:
                mag = int(float(usb_offset_var.get().strip() or 0))
            except ValueError:
                return
            mag = max(0, min(10, mag))   # clamp to 0..10 (magnitude only)
            self.cfg.set('sdr_usb_lsb_offset', _signed_offset(mag))

        sideband_frame = tk.Frame(usb_row, bg=GUI_BG)
        sideband_frame.pack(side=tk.LEFT, padx=(10,10))

        def _on_sideband_change():
            self.cfg.set('sdr_usb_lsb_sideband', sideband_var.get())
            _save_current_offset()

        tk.Radiobutton(sideband_frame, text='USB', variable=sideband_var,
                       value='USB', bg=GUI_BG, font=('Arial',11),
                       command=_on_sideband_change).pack(side=tk.LEFT)
        tk.Radiobutton(sideband_frame, text='LSB', variable=sideband_var,
                       value='LSB', bg=GUI_BG, font=('Arial',11),
                       command=_on_sideband_change).pack(side=tk.LEFT)

        # Own row below — the checkbox/sideband row above was getting
        # cramped with everything squeezed onto one line. Offset entry,
        # hint text and Set button now have their own line underneath.
        offset_row = tk.Frame(usb_frame, bg=GUI_BG)
        offset_row.pack(fill=tk.X, pady=(6,0))

        tk.Label(offset_row, text='  Offset (kHz):', bg=GUI_BG,
                 font=('Arial',11)).pack(side=tk.LEFT)
        usb_offset_var = tk.StringVar(
            value=str(abs(int(self.cfg.get('sdr_usb_lsb_offset', 0)))))
        def _on_offset_change(*_a):
            try:
                mag = int(float(usb_offset_var.get().strip() or 0))
            except ValueError:
                return   # leave stored value untouched while typing
            _save_current_offset()
        usb_offset_var.trace_add('write', _on_offset_change)
        tk.Entry(offset_row, textvariable=usb_offset_var, font=('Arial',11),
                 width=5).pack(side=tk.LEFT)
        tk.Label(offset_row, text='  e.g. 5, range 0..10 (sign set by USB/LSB above)',
                 bg=GUI_BG, font=('Arial',8), fg='#555555').pack(side=tk.LEFT)

        offset_status_lbl = tk.Label(usb_frame, text='', bg=GUI_BG,
                                      font=('Arial',9,'italic'), fg='#007700')

        def set_offset_confirm():
            """
            Takes over the ENTIRE current state of this frame — checkbox,
            sideband, and offset magnitude — whether the correction is
            currently on or off. There is no error/warning case anymore:
            from the user's point of view, 'Set' means 'apply whatever
            this frame currently shows', not 'only if the checkbox
            happens to be ticked'.

            Also explicitly refreshes the live rigctl-Frequency display
            (not relying solely on the background traces) and immediately
            sends the result to rigctl via the same set_to_log_freq() used
            by the 'Set' button in 'Dream Manual Start / Stop' above — so
            the receiver actually switches at the same moment the display
            updates, instead of the offset only being stored for later.
            """
            if usb_lsb_var.get():
                try:
                    mag = int(float(usb_offset_var.get().strip() or 0))
                    mag = max(0, min(10, mag))   # clamp to 0..10 (magnitude only)
                except ValueError:
                    offset_status_lbl.config(text='Invalid offset value.',
                                              fg='#cc0000')
                    return
                usb_offset_var.set(str(mag))
                self.cfg.set('sdr_usb_lsb_offset', _signed_offset(mag))
                band = sideband_var.get()
                sign = '+' if band == 'USB' else '-'
                offset_status_lbl.config(text=f'Offset ok {sign}{mag} kHz ({band})',
                                          fg='#007700')
            else:
                offset_status_lbl.config(
                    text='Offset-Function OFF — Log-Frequency is sent unchanged.',
                    fg='#007700')
            rigctl_disp_var.set(_compute_live_rigctl_freq())
            set_to_log_freq()   # actually switch the receiver, same call as above

        tk.Button(offset_row, text='Set', font=('Arial',10), width=4,
                  bg='#aaddff', command=set_offset_confirm).pack(
                  side=tk.LEFT, padx=(6,0))

        # ── Live rigctl-Frequency read-out, right in this same frame ────
        # Shows what would actually be sent to rigctl right now, given the
        # current Log-Frequency plus whatever is set here (checkbox,
        # USB/LSB, offset magnitude). freq_var itself always holds the
        # TRUE station frequency — this is purely a read-out; nothing
        # here is ever written back into freq_var.
        #
        # IMPORTANT: this reads the three controls' live Tk variables
        # directly (usb_lsb_var / sideband_var / usb_offset_var), NOT
        # self.cfg via _rigctl_freq_for_station() — Tkinter fires a
        # variable's trace BEFORE running the widget's own command=
        # callback, so at the moment this trace runs, self.cfg would
        # still hold the OLD checkbox/sideband value (one step stale;
        # e.g. unticking the checkbox wouldn't visibly change anything
        # here). The controls themselves are always current at trace
        # time, so reading them directly avoids that gap entirely. The
        # actual rigctl-sending code (set_to_log_freq(), Timer-Events)
        # is unaffected — it only ever reads self.cfg much later at
        # send-time, by which point it is already correctly saved.
        rigctl_disp_frame = tk.Frame(offset_row, bg=GUI_BG)
        rigctl_disp_frame.pack(side=tk.LEFT, padx=(14,0))
        tk.Label(rigctl_disp_frame, text='rigctl-Frequency:', bg=GUI_BG,
                 font=('Arial',10), fg='black').pack(side=tk.LEFT)

        def _compute_live_rigctl_freq():
            station = freq_var.get().strip()
            if not station or not usb_lsb_var.get():
                return station or '\u2014'
            try:
                mag = int(float(usb_offset_var.get().strip() or 0))
                mag = max(0, min(10, mag))   # clamp to 0..10, same as elsewhere
                offset = mag if sideband_var.get() == 'USB' else -mag
                v = float(station) - offset
                return str(int(v)) if v == int(v) else str(v)
            except ValueError:
                return station   # not a plain number — show as-is

        rigctl_disp_var = tk.StringVar(value=_compute_live_rigctl_freq())
        tk.Label(rigctl_disp_frame, textvariable=rigctl_disp_var, bg=GUI_BG,
                 font=('Arial',11,'bold'), fg='#008800').pack(
                 side=tk.LEFT, padx=(4,2))
        tk.Label(rigctl_disp_frame, text='kHz', bg=GUI_BG,
                 font=('Arial',10), fg='black').pack(side=tk.LEFT)

        def _sync_rigctl_display(*_a):
            rigctl_disp_var.set(_compute_live_rigctl_freq())

        freq_var.trace_add('write', _sync_rigctl_display)
        usb_offset_var.trace_add('write', _sync_rigctl_display)
        usb_lsb_var.trace_add('write', _sync_rigctl_display)
        sideband_var.trace_add('write', _sync_rigctl_display)

        offset_status_lbl.pack(anchor='w', pady=(2,0))

        # ── AutoPlot info note — replaces removed global checkbox ───────────
        # ── Close ─────────────────────────────────────────────────────────
        def _close_dlg():
            _dlg_alive[0] = False   # stop _refresh_loop
            # Cancel any pending after() call — prevents
            # 'invalid command name' error on Windows
            if _refresh_after_id[0]:
                try:
                    dlg.after_cancel(_refresh_after_id[0])
                except Exception:
                    pass
                _refresh_after_id[0] = None
            # Save current field values to persistent state before closing
            for i in range(NUM_SLOTS):
                sv = slot_vars[i]
                # Only overwrite led state if not already yellow/green/blue
                # (i.e. don't overwrite a running/done timer's LED)
                current_led = self._sched_state[i]['led']
                self._sched_state[i].update({
                    'sh'      : sv['sh'].get(),
                    'sm'      : sv['sm'].get(),
                    'eh'      : sv['eh'].get(),
                    'em'      : sv['em'].get(),
                    'freq'    : sv['freq'].get(),
                    'log'     : sv['log'].get(),
                    'autoplot': sv['autoplot'].get(),
                    'led'     : current_led,   # preserve timer LED colour
                })
            # Show info if active timers are still running
            any_active = any(
                (pair[0] is not None and pair[0].is_alive()) or
                (pair[1] is not None and pair[1].is_alive())
                for pair in sched_timers)
            if any_active:
                status_lbl.config(
                    text='Dialog closed — scheduled timers still active.',
                    fg='#000080')
                dlg.after(1500, dlg.destroy)
            else:
                dlg.destroy()
        tk.Button(dlg, text='Close', font=('Arial',10), width=10,
                  command=_close_dlg).pack(pady=(20,8))
    def _print_plot(self):
        """
        Print the plot area to the system printer.

        Workflow:
          1. Check a log is loaded
          2. Step 1 dialog  — inform user, ask to continue
          3. Switch background to white + replot (visible to user)
          4. Save temp PNG
          5. Step 2 dialog  — printer selection (platform specific)
          6. Send to printer
          7. Restore original background
          8. Cleanup temp file after spool delay
        """
        import tempfile, time, threading, sys, subprocess

        # ── Guard: need a loaded log ──────────────────────────────────
        if not self.plot_rows:
            messagebox.showwarning('Print Plot',
                'No log is loaded.\nPlease load and plot a log first.')
            return

        original_bg = self.cfg.get('plot_bg', 'black')

        # ══ STEP 1 DIALOG — inform + confirm ═════════════════════════
        step1 = tk.Toplevel(self.root)
        step1.title('Print Plot  —  Step 1 of 2')
        step1.configure(bg=GUI_BG)
        step1.resizable(False, False)
        center_dialog(step1, self.root, 380, 170)
        step1.grab_set()
        step1.transient(self.root)   # v_rig_test_06: keep dialog above its parent
        step1.lift()
        step1.focus_force()

        tk.Label(step1,
                 text='Print Plot',
                 bg=GUI_BG, font=('Arial', 11, 'bold')).pack(pady=(14, 4))
        tk.Label(step1,
                 text='The plot background will be temporarily\n'
                      'switched to white for printing.\n'
                      'Please wait while the plot is prepared.',
                 bg=GUI_BG, font=('Arial', 9), justify='center').pack(padx=16)

        confirmed = [False]
        def do_continue():
            confirmed[0] = True
            step1.destroy()
        def do_cancel():
            step1.destroy()

        br1 = tk.Frame(step1, bg=GUI_BG)
        br1.pack(pady=(10, 12))
        tk.Button(br1, text='Continue', font=('Arial', 10, 'bold'),
                  bg='#aaddaa', width=10,
                  command=do_continue).pack(side=tk.LEFT, padx=8)
        tk.Button(br1, text='Cancel', font=('Arial', 10),
                  width=8, command=do_cancel).pack(side=tk.LEFT, padx=8)

        step1.wait_window()
        if not confirmed[0]:
            return

        # ══ Switch to white background — visible to user ══════════════
        self.cfg.set('plot_bg', 'white')
        self._replot()
        self.root.update_idletasks()
        self.root.update()

        # ══ Save temp PNG ═════════════════════════════════════════════
        try:
            tmp = tempfile.NamedTemporaryFile(
                suffix='.png', prefix='drmplot_print_', delete=False)
            tmp_path = tmp.name
            tmp.close()
            self.fig.savefig(tmp_path, dpi=150,
                             bbox_inches='tight',
                             facecolor='white', edgecolor='none')
        except Exception as e:
            messagebox.showerror('Print Plot',
                f'Could not create print file:\n{e}')
            self.cfg.set('plot_bg', original_bg)
            self._replot()
            return

        # ══ STEP 2 DIALOG — printer selection ════════════════════════
        step2 = tk.Toplevel(self.root)
        step2.title('Print Plot  —  Step 2 of 2')
        step2.configure(bg=GUI_BG)
        step2.resizable(False, False)
        center_dialog(step2, self.root, 400, 200)
        step2.grab_set()
        step2.transient(self.root)   # v_rig_test_06: keep dialog above its parent
        step2.lift()
        step2.focus_force()

        tk.Label(step2,
                 text='Ready to Print',
                 bg=GUI_BG, font=('Arial', 11, 'bold')).pack(pady=(14, 4))

        if sys.platform.startswith('win'):
            # Windows: native dialog handles printer selection
            tk.Label(step2,
                     text='Click "Print" to open the\n'
                          'Windows printer selection dialog.',
                     bg=GUI_BG, font=('Arial', 9),
                     justify='center').pack(padx=16, pady=4)
            printer_var = None
        else:
            # Linux / macOS: show default printer, allow override
            try:
                default_printer = subprocess.check_output(
                    ['lpstat', '-d'],
                    stderr=subprocess.DEVNULL).decode().strip()
                default_printer = default_printer.replace(
                    'system default destination:', '').strip()
            except Exception:
                default_printer = ''

            tk.Label(step2,
                     text='Printer name (leave blank for default printer):',
                     bg=GUI_BG, font=('Arial', 9)).pack(padx=16, pady=(4, 2))
            printer_var = tk.StringVar(value=default_printer)
            tk.Entry(step2, textvariable=printer_var,
                     font=('Arial', 10), width=28).pack(padx=16)

        print_ok = [False]
        def do_print():
            print_ok[0] = True
            step2.destroy()
        def do_cancel2():
            step2.destroy()

        br2 = tk.Frame(step2, bg=GUI_BG)
        br2.pack(pady=(10, 12))
        tk.Button(br2, text='Print', font=('Arial', 10, 'bold'),
                  bg='#aaddaa', width=10,
                  command=do_print).pack(side=tk.LEFT, padx=8)
        tk.Button(br2, text='Cancel', font=('Arial', 10),
                  width=8, command=do_cancel2).pack(side=tk.LEFT, padx=8)

        step2.wait_window()

        # ══ Restore background regardless of user choice ══════════════
        self.cfg.set('plot_bg', original_bg)
        self._replot()

        if not print_ok[0]:
            try: os.remove(tmp_path)
            except Exception: pass
            return

        # ══ Send to printer ═══════════════════════════════════════════
        try:
            if sys.platform.startswith('win'):
                if platform.system() == 'Windows':
                    os.startfile(tmp_path, 'print')
                else:
                    import subprocess as _sp
                    _sp.call(['lp', tmp_path])
                msg = 'The plot has been sent to the Windows print dialog.'
            elif sys.platform == 'darwin':
                subprocess.Popen(['lpr', tmp_path])
                msg = 'The plot has been sent to the default printer.'
            else:
                pname = printer_var.get().strip() if printer_var else ''
                if pname:
                    subprocess.Popen(['lp', '-d', pname, tmp_path])
                    msg = f'The plot has been sent to printer: {pname}'
                else:
                    subprocess.Popen(['lp', tmp_path])
                    msg = 'The plot has been sent to the default printer.'

            messagebox.showinfo('Print Plot — Done', msg)

        except Exception as e:
            messagebox.showerror('Print Plot', f'Could not print:\n{e}')

        # ══ Cleanup temp file after spool delay ═══════════════════════
        def _cleanup():
            time.sleep(15)
            try: os.remove(tmp_path)
            except Exception: pass

        threading.Thread(target=_cleanup, daemon=True).start()

# ══════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════
def show_welcome(root, cfg):
    """
    Welcome / disclaimer window shown on first start.
    Has a 'Don't show again' checkbox — stored in config.
    Returns True  = user clicked Start (continue)
    Returns False = user clicked Close Program (exit)
    """
    # Skip if user previously chose "Don't show again"
    if cfg.get('skip_welcome', False):
        return True

    result = [False]   # mutable container for return value

    dlg = tk.Toplevel(root)
    dlg.title('Welcome — DRM-Log Plotter rebuild')
    dlg.configure(bg='#d4d0c8')
    dlg.resizable(False, False)
    dlg.withdraw()                          # hide before drawing
    # Centre on screen (main window is still hidden at this point)
    w, h = 520, 420
    sw = dlg.winfo_screenwidth()
    sh = dlg.winfo_screenheight()
    dlg.geometry(f'{w}x{h}+{(sw-w)//2}+{(sh-h)//2}')
    dlg.deiconify()                         # show, already positioned

    # Prevent closing via X button (force choice)
    dlg.grab_set()
    # v_rig_test_07: transient(root) removed here — root is still
    # withdraw()'n at this point (Welcome/Legal Notice show before the
    # main window appears), and some Linux/X11 window managers hang
    # silently (no error) when a dialog is made transient for a
    # withdrawn parent. lift()/focus_force() alone are sufficient here.
    dlg.lift()
    dlg.focus_force()
    dlg.protocol('WM_DELETE_WINDOW', lambda: None)

    # Title
    tk.Label(dlg, text='DRM-Log Plotter rebuild',
             bg='#d4d0c8', font=('Arial', 14, 'bold'),
             fg='#000080').pack(pady=(18, 4))

    ttk.Separator(dlg, orient='horizontal').pack(fill=tk.X, padx=20, pady=6)

    # Welcome text
    text = (
        "Welcome to DRM-Log Plotter rebuild!\n\n"
        "This program helps you analyze log files created by\n"
        "the DReaM DRM software decoder.\n\n"
        "Use this program at your own risk.\n"
        "If you are unsure about its purpose, please close it.\n\n"
        "This program is released under the\n"
        "GNU General Public License v3 (GPL-3.0)\n"
        "\u2014 Free and Open Source Software."
    )
    tk.Label(dlg, text=text, bg='#d4d0c8',
             font=('Arial', 10), justify=tk.CENTER,
             fg='#222222').pack(pady=(4, 10))

    ttk.Separator(dlg, orient='horizontal').pack(fill=tk.X, padx=20, pady=6)

    # Icon attribution
    tk.Label(dlg,
             text='The Program Icon is kindly provided free of charge by\n'
                  'https://www.flaticon.com',
             bg='#d4d0c8', font=('Arial', 10), justify=tk.CENTER,
             fg='#555555').pack(pady=(2, 6))

    ttk.Separator(dlg, orient='horizontal').pack(fill=tk.X, padx=20, pady=6)
    skip_var = tk.IntVar(value=0)
    tk.Checkbutton(dlg, text="Don't show this window at start again",
                   variable=skip_var, bg='#d4d0c8',
                   font=('Arial', 9)).pack(pady=(2, 8))

    # Buttons
    btn_row = tk.Frame(dlg, bg='#d4d0c8')
    btn_row.pack(pady=(0, 24))

    def do_close():
        root.destroy()

    def do_start():
        if skip_var.get():
            cfg.set('skip_welcome', True)
        result[0] = True
        dlg.destroy()

    tk.Button(btn_row, text='Close Program',
              font=('Arial', 10), width=14,
              bg='#ffaaaa', command=do_close).pack(side=tk.LEFT, padx=12)
    tk.Button(btn_row, text='Start Program',
              font=('Arial', 10, 'bold'), width=14,
              bg='#aaddaa', command=do_start).pack(side=tk.LEFT, padx=12)

    dlg.wait_window()
    return result[0]


LEGAL_TEXT = """COPYRIGHT & LICENSE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Copyright © 2026  Andreas (Andy) Schmid [Author]
All rights reserved by the author.

This software was developed with the assistance of Claude.ai
(Anthropic, PBC). The copyright and all rights to this software
belong to the author. Anthropic claims no ownership of the
generated code under its current Terms of Service.

This program is free software: you can redistribute it and/or
modify it under the terms of the GNU General Public License as
published by the Free Software Foundation, either version 3 of
the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU General Public License for more details:
https://www.gnu.org/licenses/gpl-3.0.html


THIRD-PARTY LIBRARIES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This software makes use of the following open-source libraries:

  • Python Standard Library  — PSF License (compatible with GPL)
    (tkinter, configparser, os, threading, datetime, pathlib …)
  • Matplotlib                — BSD License (compatible with GPL)
  • Pillow (PIL)              — HPND License (compatible with GPL)

All third-party libraries are used unmodified and retain their
respective licenses and copyrights.


DATA PRIVACY  (DSGVO / GDPR)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This software runs entirely on your local computer.

  • No personal data is collected, transmitted, or shared with
    any server, cloud service, or third party.
  • No internet connection is required or established by this
    software during normal operation.
  • The optional nickname you may enter is stored locally in the
    configuration file (drmplotter_cfg.json) on your computer
    only. The nickname is never transmitted automatically by this
    software. It appears solely in the filename of screenshots
    generated by the user, and is only shared externally if the
    user manually distributes those screenshot files.
  • Log files analysed by this software remain on your local
    computer and are not accessed by the author or any third party.

This software is therefore exempt from mandatory GDPR/DSGVO
registration requirements under Art. 2 GDPR (personal/household
activity exemption) when used privately.


DISCLAIMER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This software is provided "as is", without warranty of any kind,
express or implied. The author shall not be liable for any claim,
damage, or other liability arising from the use of this software.

Use of this software is entirely at your own risk.

By clicking "I Accept" you confirm that you have read and
understood this legal notice, and that you agree to use this
software under the terms of the GNU GPL v3.0.
Acceptance is stored locally and will not be shown again if you
check "Don't show this notice again".
"""


def show_legal_notice(root, cfg):
    """
    Legal notice window shown after the Welcome screen.
    Has a scrollable text area with the full legal notice.
    User must click 'I Accept' to continue or 'Decline' to exit.
    A 'Don\'t show again' checkbox suppresses future display.
    Returns True  = accepted
    Returns False = declined (exit)
    """
    if cfg.get('skip_legal', False):
        return True

    result = [False]

    dlg = tk.Toplevel(root)
    dlg.title('Legal Notice — DRM-Log Plotter rebuild')
    dlg.configure(bg='#d4d0c8')
    dlg.resizable(False, False)
    dlg.withdraw()
    w, h = 700, 620
    sw = dlg.winfo_screenwidth()
    sh = dlg.winfo_screenheight()
    dlg.geometry(f'{w}x{h}+{(sw-w)//2}+{(sh-h)//2}')
    dlg.deiconify()
    dlg.grab_set()
    # v_rig_test_07: transient(root) removed here — root is still
    # withdraw()'n at this point (Welcome/Legal Notice show before the
    # main window appears), and some Linux/X11 window managers hang
    # silently (no error) when a dialog is made transient for a
    # withdrawn parent. lift()/focus_force() alone are sufficient here.
    dlg.lift()
    dlg.focus_force()
    dlg.protocol('WM_DELETE_WINDOW', lambda: None)

    # Title bar
    tk.Label(dlg, text='Legal Notice',
             bg='#d4d0c8', font=('Arial', 13, 'bold'),
             fg='#000080').pack(pady=(14, 2))
    tk.Label(dlg, text='Please read carefully before using this software.',
             bg='#d4d0c8', font=('Arial', 9, 'italic'),
             fg='#555555').pack(pady=(0, 6))

    ttk.Separator(dlg, orient='horizontal').pack(fill=tk.X, padx=16, pady=4)

    # Scrollable text area
    frame = tk.Frame(dlg, bg='#d4d0c8')
    frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=4)

    txt = tk.Text(frame, font=('Courier', 10), wrap=tk.WORD,
                  bg='#f8f8f0', fg='#111111', bd=1, relief=tk.SUNKEN,
                  state=tk.NORMAL, cursor='arrow')
    sb  = ttk.Scrollbar(frame, command=txt.yview)
    txt.configure(yscrollcommand=sb.set)
    sb.pack(side=tk.RIGHT, fill=tk.Y)
    txt.pack(fill=tk.BOTH, expand=True)
    txt.insert('1.0', LEGAL_TEXT)
    txt.configure(state=tk.DISABLED)
    txt.bind('<MouseWheel>',
             lambda e: txt.yview_scroll(int(-1*(e.delta/120)), 'units'))

    ttk.Separator(dlg, orient='horizontal').pack(fill=tk.X, padx=16, pady=6)

    # "Don't show again" checkbox
    skip_var = tk.IntVar(value=0)
    tk.Checkbutton(dlg, text="Don't show this notice again",
                   variable=skip_var, bg='#d4d0c8',
                   font=('Arial', 9)).pack(pady=(0, 6))

    # Buttons
    btn_row = tk.Frame(dlg, bg='#d4d0c8')
    btn_row.pack(pady=(0, 14))

    def do_decline():
        root.destroy()

    def do_accept():
        if skip_var.get():
            cfg.set('skip_legal', True)
        result[0] = True
        dlg.destroy()

    tk.Button(btn_row, text='Decline',
              font=('Arial', 10), width=12,
              bg='#ffaaaa', command=do_decline).pack(side=tk.LEFT, padx=14)
    tk.Button(btn_row, text='I Accept',
              font=('Arial', 10, 'bold'), width=14,
              bg='#aaddaa', command=do_accept).pack(side=tk.LEFT, padx=14)

    dlg.wait_window()
    return result[0]


def _ensure_uia_typelib():
    """
    Ensure comtypes UIAutomationClient.py is generated on Windows.
    Called once at startup — silently skipped on Linux/macOS.
    This allows PyInstaller to pack the file without requiring Dream to run.
    """
    if _platform.system() != 'Windows':
        return
    try:
        # Try import first — if it works, typelib already exists
        from comtypes.gen import UIAutomationClient  # noqa: F401
    except (ImportError, OSError):
        # Not yet generated — create it now from the Windows DLL
        try:
            import comtypes.client
            comtypes.client.GetModule(
                r'C:\Windows\System32\UIAutomationCore.dll')
        except Exception:
            pass   # silent fail — Audio Codec Detection simply won't work


def main():
    # ── Generate UIA typelib on first run (Windows only) ─────────────────────
    # This ensures comtypes\gen\UIAutomationClient.py exists before PyInstaller
    # tries to pack it. No Dream needed — runs silently at every startup.
    _ensure_uia_typelib()

    root = tk.Tk()
    root.title(APP_TITLE)
    root.minsize(1000, 660)

    # ── Application-wide default font (Aug 2026) ──────────────────────────
    # Tk's native dialogs (messagebox.askyesno/showinfo/showwarning/
    # showerror, and the standard filedialog browsers) render using Tk's
    # built-in NAMED fonts — 'TkDefaultFont' etc. — not whatever font the
    # custom-built dialogs elsewhere in this programme use. That's the
    # "plain/system-looking" text seen in native confirmation/warning
    # popups, visually inconsistent with the Arial styling used
    # everywhere else. Re-pointing these named fonts to Arial here, once,
    # right after the root window is created, changes EVERY native
    # dialog application-wide — including the 50+ existing
    # messagebox.*() call sites throughout the programme, and any future
    # ones — without touching a single one of them individually.
    try:
        import tkinter.font as _tkfont
        for _fname in ('TkDefaultFont', 'TkTextFont', 'TkHeadingFont',
                        'TkCaptionFont', 'TkSmallCaptionFont',
                        'TkIconFont', 'TkMenuFont', 'TkTooltipFont'):
            try:
                _tkfont.nametofont(_fname).configure(family='Arial', size=10)
            except Exception:
                pass   # a given named font may not exist on every platform
    except Exception:
        pass   # never let font styling prevent the programme from starting

    # Hide main window until dialogs are confirmed
    root.withdraw()

    # Load config early so welcome/legal screens can check skip flags
    cfg = Config()

    # 1. Welcome window
    if not show_welcome(root, cfg):
        return   # user clicked Close — exit

    # 2. Legal notice window
    if not show_legal_notice(root, cfg):
        return   # user declined — exit

    # Now show the main window
    root.deiconify()
    root.lift()
    root.focus_force()

    DRMPlotter(root)
    root.mainloop()

if __name__=='__main__':
    main()
