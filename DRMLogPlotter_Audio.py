#!/usr/bin/env python3
"""
DRMLogPlotter_Audio.py
══════════════════════
Standalone helper tool for DRM-Log Plotter rebuild.
Reads the Audio Codec information from Dream's Qt5 window
using Windows UI Automation (UIA) via comtypes.

Called automatically by DRMLogPlotter.exe 30 seconds after Dream starts.
Output: single JSON line to stdout.

Usage:
  DRMLogPlotter_Audio.exe [--debug]

Output examples:
  {"codec": "AAC", "protection": "EEP", "sbr": "Off", "audio_mode": "Mono"}
  {"codec": "xHE-AAC", "protection": "EEP", "sbr": "Off", "audio_mode": "Mono"}
  {"codec": "\u2014", "protection": "\u2014", "sbr": "Off", "audio_mode": "\u2014"}

This tool sets QT_ACCESSIBILITY=1 in its own process environment before
searching for Dream's window — so the main DRMLogPlotter.exe does not
need to start Dream with QT_ACCESSIBILITY and avoids subprocess conflicts.
"""

import sys
import json
import re
import os
import platform
import subprocess

DEBUG = '--debug' in sys.argv
SYSTEM = platform.system()

def dbg(msg):
    if DEBUG:
        print(f'[DBG] {msg}', file=sys.stderr)

FALLBACK = {'codec': '—', 'protection': '—', 'sbr': 'Off', 'audio_mode': '—'}

# ── Set QT_ACCESSIBILITY in our own process ───────────────────────────────────
# This is safe here — we are a separate process from DRMLogPlotter.exe.
os.environ['QT_ACCESSIBILITY'] = '1'

# ── Label classifiers ─────────────────────────────────────────────────────────
def is_bitrate_protection_label(text):
    t = text.upper().strip()
    return 'KBPS' in t and ('EEP' in t or 'UEP' in t)

def is_codec_label(text):
    t = text.upper().strip()
    return bool(re.search(r'\bAAC\b|XHE[\s\-]*AAC|AAC\+', t)) and \
           'KBPS' not in t

def is_mode_label(text):
    t = text.upper().strip()
    return t in ('MONO', 'STEREO') or \
           bool(re.search(r'P[\-\s]*STEREO|PARAMETRIC', t))

def is_sbr_label(text):
    t = text.upper().strip()
    return bool(re.search(r'^/?[\s]*SBR$', t))

def is_dream_window(title):
    t = title.lower()
    return 'dream' in t and 'log plotter' not in t and \
           'diagnose' not in t and 'audio' not in t

# ── Assembler ─────────────────────────────────────────────────────────────────
def assemble_from_labels(label_list):
    protection = '—'; codec = '—'; audio_mode = '—'; sbr = 'Off'
    for text in label_list:
        t = text.strip()
        if not t:
            continue
        if is_bitrate_protection_label(t):
            tu = t.upper()
            protection = 'UEP' if 'UEP' in tu else 'EEP'
            dbg(f'  Protection: "{t}" → {protection}')
        elif is_codec_label(t):
            tu = t.upper()
            if re.search(r'XHE[\s\-]*AAC', tu): codec = 'xHE-AAC'
            elif 'AAC+' in tu:                   codec = 'AAC+'
            elif 'AAC'  in tu:                   codec = 'AAC'
            dbg(f'  Codec: "{t}" → {codec}')
        elif is_mode_label(t):
            tu = t.upper()
            if re.search(r'P[\-\s]*STEREO|PARAMETRIC', tu): audio_mode = 'P-Stereo'
            elif 'STEREO' in tu: audio_mode = 'Stereo'
            elif 'MONO'   in tu: audio_mode = 'Mono'
            dbg(f'  Mode: "{t}" → {audio_mode}')
        elif is_sbr_label(t):
            sbr = 'On'
            dbg(f'  SBR: "{t}" → On')
    # Tab bar fallback
    for text in label_list:
        tu = text.upper()
        if '|' in text and 'AAC' in tu and 'KBPS' in tu:
            if codec == '—':
                if re.search(r'XHE[\s\-]*AAC', tu): codec = 'xHE-AAC'
                elif 'AAC+' in tu: codec = 'AAC+'
                elif 'AAC'  in tu: codec = 'AAC'
            if audio_mode == '—':
                if 'STEREO' in tu: audio_mode = 'Stereo'
                elif 'MONO' in tu:  audio_mode = 'Mono'
            if 'SBR' in tu: sbr = 'On'
    if codec == '—' and protection == '—':
        return None
    return {'codec': codec, 'protection': protection,
            'sbr': sbr, 'audio_mode': audio_mode}

# ── Windows UIA via comtypes ──────────────────────────────────────────────────
def win_uia_comtypes():
    dbg('Method: UIA comtypes')
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
                if is_dream_window(el.CurrentName or ''):
                    dream_el = el
                    dbg(f'Dream found: "{el.CurrentName}"')
                    break
            except Exception:
                pass
        if not dream_el:
            dbg('Dream window not found via UIA')
            return None
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
        dbg(f'UIA collected {len(labels)} texts')
        return assemble_from_labels(labels)
    except ImportError:
        dbg('comtypes not available')
    except Exception as e:
        dbg(f'UIA error: {e}')
    return None

# ── Windows GetWindowTextW ────────────────────────────────────────────────────
def win_getwindowtext():
    dbg('Method: GetWindowTextW')
    import ctypes, ctypes.wintypes
    user32  = ctypes.windll.user32
    GetText = user32.GetWindowTextW
    GetLen  = user32.GetWindowTextLengthW
    PROC    = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                  ctypes.wintypes.HWND,
                                  ctypes.wintypes.LPARAM)
    def get_text(hwnd):
        n = GetLen(hwnd)
        if n == 0: return ''
        b = ctypes.create_unicode_buffer(n + 1)
        GetText(hwnd, b, n + 1)
        return b.value

    dream_hwnd = [None]
    def _top(hwnd, _):
        if is_dream_window(get_text(hwnd)):
            dream_hwnd[0] = hwnd
            return False
        return True
    user32.EnumWindows(PROC(_top), 0)
    if not dream_hwnd[0]:
        dbg('Dream window not found via EnumWindows')
        return None

    labels = []
    def _child(hwnd, _):
        t = get_text(hwnd)
        if t: labels.append(t)
        return True
    user32.EnumChildWindows(dream_hwnd[0], PROC(_child), 0)
    dbg(f'GetWindowTextW collected {len(labels)} texts')
    return assemble_from_labels(labels)

# ── Linux AT-SPI ──────────────────────────────────────────────────────────────
def linux_atspi():
    dbg('Method: AT-SPI pyatspi')
    try:
        import pyatspi
        desktop = pyatspi.Registry.getDesktop(0)
        for i in range(desktop.childCount):
            app = desktop.getChildAtIndex(i)
            try:
                if 'dream' not in (app.name or '').lower():
                    continue
                if not is_dream_window(app.name or ''):
                    continue
                dbg(f'AT-SPI app: "{app.name}"')
                labels = []
                def _walk(obj):
                    try:
                        name = obj.name or ''
                        if name: labels.append(name)
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
                dbg(f'AT-SPI collected {len(labels)} texts')
                result = assemble_from_labels(labels)
                if result: return result
            except Exception:
                pass
    except ImportError:
        dbg('pyatspi not installed')
    except Exception as e:
        dbg(f'AT-SPI error: {e}')
    return None

def linux_xdotool():
    dbg('Method: xdotool')
    try:
        proc = subprocess.run(['xdotool', 'search', '--name', 'dream'],
                              capture_output=True, text=True, timeout=3)
    except FileNotFoundError:
        dbg('  xdotool command not found — is it installed? '
            '(sudo apt install xdotool)')
        return None
    except Exception as e:
        dbg(f'  xdotool search error: {e}')
        return None

    ids = proc.stdout.strip().splitlines()
    dbg(f'  xdotool search found {len(ids)} window id(s) matching "dream"')
    if not ids:
        dbg('  No window found — is Dream actually running right now?')
        return None

    labels = []
    for wid in ids:
        try:
            name = subprocess.run(['xdotool', 'getwindowname', wid.strip()],
                                  capture_output=True, text=True,
                                  timeout=3).stdout.strip()
        except Exception as e:
            dbg(f'  getwindowname error for {wid}: {e}')
            continue
        dbg(f'  Window {wid}: "{name}"')
        if name and is_dream_window(name):
            labels.append(name)

    dbg(f'  {len(labels)} window title(s) passed is_dream_window() filter')
    if not labels:
        dbg('  No matching Dream window title — xdotool only sees window '
            'TITLES, not the codec/bitrate labels inside the window. '
            'This method is a coarser fallback than AT-SPI/UIA.')
        return None

    result = assemble_from_labels(labels)
    if result:
        return result
    dbg('  Window title(s) found but no codec/protection pattern matched')
    return None

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    result = None
    if SYSTEM == 'Windows':
        result = win_uia_comtypes()
        if not result: result = win_getwindowtext()
    elif SYSTEM == 'Linux':
        result = linux_atspi()
        if not result: result = linux_xdotool()
    else:
        dbg(f'Unsupported platform: {SYSTEM}')

    if result:
        dbg(f'SUCCESS: {result}')
    else:
        result = FALLBACK
        dbg('All methods failed — returning fallback')

    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    main()
