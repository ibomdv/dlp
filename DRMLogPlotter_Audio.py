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
    return bool(re.search(r'\bAAC\b|XHE[\s\-]*AAC|AAC\+', t))

def is_mode_label(text):
    t = text.upper().strip()
    if re.search(r'P[\-\s]*STEREO|PARAMETRIC', t):
        return True
    return 'MONO' in t or 'STEREO' in t

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
        # Changed from elif-chain to independent ifs (July 2026): the new
        # screenshot-OCR preprocessing pipeline can return the WHOLE label
        # as one single, space-stripped string ("10.72kbpsEEPxHE-AACMono")
        # instead of Windows/AT-SPI's one-info-per-line style. An elif
        # chain would only ever apply the FIRST matching check per line —
        # confirmed by testing this line matches several checks at once,
        # so all of them need to run independently to fill in every field
        # from a single combined line. Harmless for the one-info-per-line
        # case (only one check is ever true there anyway).
        if is_bitrate_protection_label(t):
            tu = t.upper()
            protection = 'UEP' if 'UEP' in tu else 'EEP'
            dbg(f'  Protection: "{t}" → {protection}')
        if is_codec_label(t):
            tu = t.upper()
            if re.search(r'XHE[\s\-]*AAC', tu): codec = 'xHE-AAC'
            elif 'AAC+' in tu:                   codec = 'AAC+'
            elif 'AAC'  in tu:                   codec = 'AAC'
            dbg(f'  Codec: "{t}" → {codec}')
        if is_mode_label(t):
            tu = t.upper()
            if re.search(r'P[\-\s]*STEREO|PARAMETRIC', tu): audio_mode = 'P-Stereo'
            elif 'STEREO' in tu: audio_mode = 'Stereo'
            elif 'MONO'   in tu: audio_mode = 'Mono'
            dbg(f'  Mode: "{t}" → {audio_mode}')
        if is_sbr_label(t):
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

def linux_screenshot_ocr():
    """
    Fallback for systems where the AT-SPI/ATK accessibility bridge itself
    fails at runtime (confirmed on Raspberry Pi OS Bookworm, July 2026 —
    'atk_bridge_adaptor_init: runtime check failed', independent of the
    AT-SPI service running or QT_ACCESSIBILITY being set; works fine on
    Linux Mint/Ubuntu, so this method is only ever reached there if AT-SPI
    itself already failed).

    Uses 'grim' — the standard screenshot tool for wlroots-based Wayland
    compositors (including labwc/Raspberry Pi OS) — for a silent, full-
    screen capture via the wlr-screencopy Wayland protocol. Switched from
    three earlier attempts (PIL/gnome-screenshot, scrot, ImageMagick
    'import' — July 2026), which all failed identically because they rely
    on the classic X11 'XGetImage' pixmap-read mechanism. Under a
    compositing Wayland manager like labwc, that mechanism cannot read
    real window/screen content — confirmed by testing: even a direct
    'import -window <ID>' call against a live Dream window failed with no
    further diagnostic detail. 'grim' avoids this entirely by reading the
    compositor's actually-composited output directly, independent of
    whether the underlying app runs via XWayland or natively.

    OCR then runs across the whole screen; assemble_from_labels() already
    filters unrelated text via its codec/protection/mode/SBR regex
    patterns, so extra desktop content elsewhere on screen is ignored.
    """
    dbg('Method: screenshot + OCR (tesseract)')
    import shutil
    if shutil.which('tesseract') is None:
        dbg('  tesseract command not found — is it installed? '
            '(sudo apt install tesseract-ocr)')
        return None
    if shutil.which('grim') is None:
        dbg('  grim command not found — is it installed? '
            '(sudo apt install grim)')
        return None

    # ── Sanity check: only bother if a Dream window actually exists ────────
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
    if not ids:
        dbg('  No window found — is Dream actually running right now?')
        return None

    # ── Bring Dream to the foreground before the screenshot ────────────────
    # grim captures whatever is actually visible on screen — if another
    # window (e.g. a terminal running --debug) currently overlaps Dream's
    # label area, OCR finds nothing there. Confirmed by testing, July
    # 2026: a working run only succeeded because windows happened not to
    # overlap that particular time. Mirrors the same short foreground-
    # raise already used elsewhere in the project ('Dump Dream
    # Configuration' — "the DRM-Plotter will automatically temporarily
    # minimize itself").
    import time
    previous_active = None
    try:
        previous_active = subprocess.run(
            ['xdotool', 'getactivewindow'],
            capture_output=True, text=True, timeout=2).stdout.strip()
    except Exception:
        pass

    for wid in ids:
        wid = wid.strip()
        try:
            subprocess.run(['xdotool', 'windowactivate', '--sync', wid],
                           capture_output=True, text=True, timeout=3)
            subprocess.run(['xdotool', 'windowraise', wid],
                           capture_output=True, text=True, timeout=3)
        except Exception as e:
            dbg(f'  could not raise window {wid}: {e}')
    time.sleep(0.3)   # let the compositor finish rendering after raising

    def _restore_focus():
        if previous_active:
            try:
                subprocess.run(['xdotool', 'windowactivate', previous_active],
                               capture_output=True, text=True, timeout=3)
            except Exception:
                pass

    # ── Silent, full-screen capture via grim (wlr-screencopy) ──────────────
    import tempfile
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
            tmp_path = tf.name
        result = subprocess.run(['grim', tmp_path],
                                capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            dbg(f'  grim failed: {result.stderr.strip()}')
            _restore_focus()
            return None
    except Exception as e:
        dbg(f'  grim error: {e}')
        if tmp_path:
            try: os.remove(tmp_path)
            except OSError: pass
        _restore_focus()
        return None

    _restore_focus()   # Dream's job is done — give focus back right away,
                       # OCR/tesseract can take a moment and shouldn't keep
                       # the user's previous window out of the foreground.

    # ── Sanity check: reject a blank/uniform image ──────────────────────────
    try:
        from PIL import Image
        img = Image.open(tmp_path)
        gray = img.convert('L')
        extrema = gray.getextrema()
    except ImportError:
        dbg('  PIL/Pillow not available')
        try: os.remove(tmp_path)
        except OSError: pass
        return None
    except Exception as e:
        dbg(f'  could not open/inspect screenshot: {e}')
        try: os.remove(tmp_path)
        except OSError: pass
        return None

    if extrema[0] == extrema[1]:
        dbg('  Screenshot is a uniform/blank image — unexpected with grim, '
            'check that grim can access the Wayland compositor '
            '(WAYLAND_DISPLAY / XDG_RUNTIME_DIR set correctly)')
        try: os.remove(tmp_path)
        except OSError: pass
        return None

    # ── Pass 1: coarse OCR with word-level position data (TSV) ─────────────
    # --psm 11 ('sparse text') finds scattered UI text well, but tends to
    # fragment small text (confirmed by testing, July 2026: "aac Mono"
    # split into "a" / "c Mono", with the preceding number "11.64" and
    # trailing "EEP" dropped entirely) — too unreliable to use directly.
    # Used here only to LOCATE roughly where Dream's label sits.
    try:
        pass1 = subprocess.run(
            ['tesseract', tmp_path, 'stdout', '--psm', '11', 'tsv'],
            capture_output=True, text=True, timeout=20)
        tsv_text = pass1.stdout or ''
    except Exception as e:
        dbg(f'  tesseract pass 1 (tsv) error: {e}')
        try: os.remove(tmp_path)
        except OSError: pass
        return None

    import csv, io
    rows = list(csv.DictReader(io.StringIO(tsv_text), delimiter='\t'))

    # Anchor words that reliably survive pass 1 even when the rest of the
    # label gets mangled — used to locate the label's line, not to read
    # the actual values from (that's what pass 2 is for).
    anchor_re = re.compile(r'AAC|XHE|MONO|STEREO|KBPS|SBR|EEP|UEP',
                           re.IGNORECASE)

    anchor_keys = set()
    for row in rows:
        txt = (row.get('text') or '').strip()
        if txt and anchor_re.search(txt):
            anchor_keys.add((row.get('block_num'), row.get('par_num'),
                             row.get('line_num')))

    if not anchor_keys:
        dbg('  Pass 1: no anchor word (AAC/Mono/kbps/EEP/...) found — '
            'giving up on this screenshot')
        # No localized anchor line to trust — do NOT fall back to raw,
        # disconnected screen text here. Confirmed bug (July 2026): this
        # previously picked up unrelated on-screen text (including our
        # own leftover --debug output still visible in a terminal window)
        # and produced a false-positive match. Honest failure is safer.
        try: os.remove(tmp_path)
        except OSError: pass
        return None

    img_w, img_h = gray.size

    def _completeness(entry):
        if not entry:
            return -1
        score = 0
        if entry.get('codec', '—') != '—':      score += 1
        if entry.get('protection', '—') != '—': score += 1
        if entry.get('audio_mode', '—') != '—': score += 1
        if entry.get('sbr') == 'On':             score += 1
        return score

    best_result = None
    best_score  = -1

    # ── Process each anchor line SEPARATELY ─────────────────────────────────
    # Dream can show more than one line that happens to contain a keyword
    # (e.g. its own window-title-bar text "xHE-AAC Mono (10.72 kbps)" —
    # which never includes protection — alongside the actual coloured
    # Audio-Codec label box, which does). Merging every anchor line into
    # ONE crop (previous approach) sometimes joined two unrelated lines
    # into a single, oversized, wrong crop — confirmed by testing, July
    # 2026. Trying each candidate line on its own and keeping the most
    # complete result avoids that.
    for key in anchor_keys:
        lefts, tops, rights, bottoms = [], [], [], []
        for row in rows:
            rkey = (row.get('block_num'), row.get('par_num'), row.get('line_num'))
            if rkey != key:
                continue
            try:
                l, t = int(row['left']), int(row['top'])
                w, h = int(row['width']), int(row['height'])
            except (KeyError, ValueError):
                continue
            lefts.append(l); tops.append(t)
            rights.append(l + w); bottoms.append(t + h)
        if not lefts:
            continue

        avg_h = sum(b - t for t, b in zip(tops, bottoms)) / len(tops)
        # Asymmetric padding: Dream's label format is always
        # "X.XX kbps EEP/UEP  CODEC  MODE" — protection/bitrate sits to
        # the LEFT of the codec/mode words pass 1 typically anchors on,
        # and small decimal numbers are harder for OCR to catch than
        # plain letters. More room on the left compensates for anchor
        # words often being found only on the right half of the line.
        pad_left  = int(avg_h * 14)
        pad_right = int(avg_h * 6)
        pad_y     = int(avg_h * 1.5)
        crop_box = (
            max(0, min(lefts) - pad_left),
            max(0, min(tops) - pad_y),
            min(img_w, max(rights) + pad_right),
            min(img_h, max(bottoms) + pad_y),
        )
        dbg(f'  Pass 1: anchor line {key} found, cropping {crop_box}')

        # ── Pass 2: crop, sharpen, adaptive-threshold, upscale ──────────────
        # Preprocessing pipeline confirmed by hands-on testing (July 2026,
        # test_ocr.py test bench) to make recognition colour-independent —
        # works reliably on Dream's ORIGINAL red label text, not just the
        # turquoise colour originally found to work by accident. Plain
        # grayscale + fixed threshold (previous approach) was not enough;
        # sharpening + ADAPTIVE thresholding (contrast-based, not a fixed
        # brightness cutoff) is what removes the colour dependency.
        try:
            import cv2
            import numpy as np
        except ImportError:
            dbg('  opencv-python-headless not available — skipping this '
                'candidate (install with: pip install opencv-python-headless)')
            continue

        crop = gray.crop(crop_box)
        roi = np.array(crop)   # already single-channel (grayscale) here

        sharpen_kernel = np.array([[0, -1, 0],
                                   [-1,  5, -1],
                                   [0, -1, 0]])
        sharpened = cv2.filter2D(roi, -1, sharpen_kernel)

        thresholded = cv2.adaptiveThreshold(
            sharpened, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            21, 15
        )

        upscaled = cv2.resize(thresholded, None, fx=4, fy=4,
                              interpolation=cv2.INTER_CUBIC)

        crop_path = None
        try:
            import tempfile as _tempfile
            with _tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
                crop_path = tf.name
            cv2.imwrite(crop_path, upscaled)
            tess_config = [
                '--psm', '7',
                '-c', 'tessedit_char_whitelist='
                      'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
                      '-0123456789. ',
            ]
            pass2 = subprocess.run(
                ['tesseract', crop_path, 'stdout'] + tess_config,
                capture_output=True, text=True, timeout=20)
            text2 = pass2.stdout or ''
        except Exception as e:
            dbg(f'  tesseract pass 2 error for {key}: {e}')
            text2 = ''
        finally:
            if crop_path:
                try: os.remove(crop_path)
                except OSError: pass

        labels2 = [line.strip() for line in text2.splitlines() if line.strip()]
        if len(labels2) > 1:
            # Also try the whole recognised text as ONE combined string —
            # protection needs both "kbps" and "EEP"/"UEP" in the SAME
            # string (is_bitrate_protection_label()); if tesseract still
            # splits the line despite --psm 7, this gives that check a
            # chance to match anyway. Codec/mode are unaffected either
            # way since they only need one keyword.
            labels2.append(' '.join(labels2))
        dbg(f'  Pass 2 ({key}): OCR collected {len(labels2)} text line(s)')
        for _i, _line in enumerate(labels2):
            dbg(f'    [{_i}] "{_line}"')

        candidate = assemble_from_labels(labels2)
        score = _completeness(candidate)
        if score > best_score:
            best_result, best_score = candidate, score
        if best_score >= 3:   # codec + protection + mode all found — good enough
            break

    if tmp_path:
        try: os.remove(tmp_path)
        except OSError: pass

    if best_result:
        return best_result

    # Fall back to whatever pass 1 found on the anchor line(s), in case
    # pass 2's tighter crops missed something pass 1 actually got right.
    # Deliberately scoped to anchor_keys only (not the whole screen) and
    # joined per line — avoids the raw-disconnected-word contamination
    # risk fixed above for the "no anchor" case.
    anchor_words = [r.get('text', '').strip() for r in rows
                    if (r.get('block_num'), r.get('par_num'), r.get('line_num'))
                    in anchor_keys and (r.get('text') or '').strip()]
    if not anchor_words:
        return None
    return assemble_from_labels([' '.join(anchor_words)] + anchor_words)

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
        if not result: result = linux_screenshot_ocr()
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
