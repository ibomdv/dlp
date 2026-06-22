#!/usr/bin/env python3
"""
DRM-Log Plotter - Python Rebuild
Code Base is 100% rebuild and created by CLAUDE.AI
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import csv, os, re, json, math
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use('TkAgg')
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np

# ══════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════
APP_TITLE       = "DRM-Log Plotter rebuild  ( v. 0.99 beta experimental )"
VERSION         = "Based on Original DRM-Log Plotter v. 22.1 (Python Rebuild by CLAUDE.AI)"

# ── Absolute base directory — works for both .py script and compiled .exe ──
# sys.frozen is set by PyInstaller/auto-py-to-exe when running as .exe
import sys as _sys
if os.environ.get('APPIMAGE'):
    # Running as AppImage — mount point is read-only.
    # Use ~/.local/share/drm_log_plotter/ for all user data.
    BASE_DIR = os.path.join(os.path.expanduser('~'),
                            '.local', 'share', 'drm_log_plotter')
    os.makedirs(BASE_DIR, exist_ok=True)
elif getattr(_sys, 'frozen', False):
    # Running as compiled .exe or .bin — use directory of the executable.
    BASE_DIR = os.path.dirname(_sys.executable)
else:
    # Running as .py script — use directory of this file.
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE     = os.path.join(BASE_DIR, "drmplotter_cfg.json")
TX_SITES_FILE   = os.path.join(BASE_DIR, "drmtransmittersites.txt")
LOGFILES_DIR    = os.path.join(BASE_DIR, "logfiles")
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "screenshots")

MAX_AUDIO_FRAMES = 1500
SNR_MAX  = 45
DOPPLER_MAX  = 1.0   # 1 Hz maps to 20 dB height on the plot

import subprocess as _subprocess
import platform as _platform

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

COL_AUDIO   = "#2f6fdd"
COL_SNR     = "#ff3333"
COL_DOPPLER = "#007722"
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
        freq   = self.frequency.replace(" kHz","").strip()
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
        center_dialog(self.win, parent, 620, 390)
        self.win.grab_set()
        self.win.focus_set()

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

        # Nickname frame
        fn = tk.LabelFrame(mid, text='Enter your Nickname',
                           bg=bg, font=('Arial',8), padx=4, pady=2)
        fn.pack(side=tk.LEFT, padx=(0,4))
        self.nick_var = tk.StringVar(value=self.cfg.get('nickname',''))
        tk.Entry(fn, textvariable=self.nick_var, width=10,
                 font=('Arial',9), bg='white').pack(side=tk.LEFT, padx=(0,2))
        tk.Button(fn, text='OK', width=3,
                  command=self._save_nick).pack(side=tk.LEFT)

        # Edit a Profile frame
        fe = tk.LabelFrame(mid, text='Edit a Profile',
                           bg=bg, font=('Arial',8), padx=4, pady=2)
        fe.pack(side=tk.LEFT, padx=(0,4))
        tk.Button(fe, text='Save',   width=5,
                  command=self._save_edit  ).pack(side=tk.LEFT, padx=2)
        tk.Button(fe, text='Cancel', width=6,
                  command=self._cancel_edit).pack(side=tk.LEFT, padx=2)

        # Add a New Entry frame
        fa = tk.LabelFrame(mid, text='Add a New Entry',
                           bg=bg, font=('Arial',8), padx=4, pady=2)
        fa.pack(side=tk.LEFT)
        tk.Button(fa, text='Add Profile', width=10,
                  command=self._add_profile).pack(padx=2, pady=1)

        # ── List row ───────────────────────────────────────────────────
        lf = tk.Frame(w, bg=bg)
        lf.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        sb = ttk.Scrollbar(lf)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.lb = tk.Listbox(lf, font=('Arial',9), bg='white',
                             selectbackground='#000080', selectforeground='white',
                             yscrollcommand=sb.set, relief=tk.SUNKEN, bd=1)
        self.lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.lb.yview)
        self.lb.bind('<Double-Button-1>', self._on_dbl_click)

        # ── Bottom button row ──────────────────────────────────────────
        bot = tk.Frame(w, bg=bg)
        bot.pack(fill=tk.X, padx=8, pady=(0,8))
        self.count_var = tk.StringVar()
        tk.Button(bot, text='Delete All', width=9,
                  command=self._delete_all).pack(side=tk.LEFT, padx=(0,3))
        tk.Button(bot, text='Remove',     width=7,
                  command=self._remove    ).pack(side=tk.LEFT, padx=3)
        tk.Button(bot, text='Edit',       width=5,
                  command=self._edit_sel  ).pack(side=tk.LEFT, padx=3)
        tk.Label(bot, textvariable=self.count_var,
                 bg=bg, font=('Arial',8), width=10).pack(side=tk.LEFT, padx=8)
        tk.Button(bot, text='Select',     width=7,
                  command=self._select    ).pack(side=tk.LEFT, padx=3)
        tk.Button(bot, text='Close',      width=7,
                  command=self.win.destroy).pack(side=tk.LEFT, padx=3)

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
        s = self.lb.curselection()
        if s:
            self.header_var.set(self.profiles[s[0]])
            self.cfg.set('header_text', self.profiles[s[0]])
        self.win.destroy()


class DRMPlotter:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.configure(bg=GUI_BG)
        self.root.resizable(True, True)

        self.cfg      = Config()
        # Load TX sites from saved path (if user loaded one before) or default file
        tx_path = self.cfg.get('tx_sites_path', TX_SITES_FILE)
        self.tx_sites = parse_tx_sites(tx_path)
        if not self.tx_sites and tx_path != TX_SITES_FILE:
            # Fallback to default if saved path no longer exists
            self.tx_sites = parse_tx_sites(TX_SITES_FILE)

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
        self.ap_interval  = 30
        self.ap_scroll   = 'Full'
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
        self._sched_timers       = [[None,None],[None,None],[None,None]]
        self._sched_state        = [
            {'sh':'','sm':'','eh':'','em':'','freq':'','log':0,'autoplot':0,'led':'grey'}
            for _ in range(3)]
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

        # Left sub-column: Label / Frequency / TX Location / Date
        lc = tk.Frame(ml, bg=GUI_BG)
        lc.grid(row=0, column=0, sticky='nw')
        self.v_label  = tk.StringVar(value='label')
        self.v_freq   = tk.StringVar(value='freq')
        self.v_txloc  = tk.StringVar(value='site')
        self.v_date   = tk.StringVar(value='date')
        for i,(txt,var) in enumerate([('Label:',self.v_label),('Frequency:',self.v_freq),
                                       ('TX Location:',self.v_txloc),('Date:',self.v_date)]):
            tk.Label(lc,text=txt,bg=GUI_BG,font=('Arial',10),anchor='w',width=11).grid(row=i,column=0,sticky='w',pady=2)
            tk.Label(lc,textvariable=var,bg=GUI_BG,font=('Arial',10,'bold'),
                     fg='#000080',anchor='w',width=16).grid(row=i,column=1,sticky='w',pady=2)

        ttk.Separator(ml,orient='vertical').grid(row=0,column=1,sticky='ns',padx=5)

        # Right sub-column: Mode / Bitrate / MSC / PL
        rc = tk.Frame(ml, bg=GUI_BG)
        rc.grid(row=0, column=2, sticky='nw')
        self.v_mode    = tk.StringVar(value='bw')
        self.v_bitrate = tk.StringVar(value='kbps')
        self.v_msc     = tk.StringVar(value='qam')
        self.v_pl      = tk.StringVar(value='PL')
        for i,(txt,var) in enumerate([('Mode / Bandwidth:',self.v_mode),
                                       ('Bitrate (at log start):',self.v_bitrate),
                                       ('Main Service Channel:',self.v_msc),
                                       ('Protection Level:',self.v_pl)]):
            tk.Label(rc,text=txt,bg=GUI_BG,font=('Arial',10),anchor='w',width=18).grid(row=i,column=0,sticky='w',pady=2)
            tk.Label(rc,textvariable=var,bg=GUI_BG,font=('Arial',10,'bold'),
                     fg='#000080',anchor='w',width=10).grid(row=i,column=1,sticky='w',pady=2)

        # ── 2) Stats block (Mitte) — mit Rahmen, Schrift Arial 8 ──────────
        sf_outer = tk.LabelFrame(parent, text='Data evaluation result', bg=GUI_BG,
                                 font=('Arial',9,'bold'), relief=tk.GROOVE, bd=2, padx=4, pady=2)
        sf_outer.pack(side=tk.LEFT, fill=tk.Y, padx=(6,6))
        sf = sf_outer   # alle Widgets direkt in den Rahmen

        self.v_audio_pct = tk.StringVar(value='audio')
        self.v_fac       = tk.StringVar(value='sfm')
        self.v_audio_max = tk.StringVar(value='---')

        # Row 0: Decoded Audio (blau)  |  spacer  |  FAC CRC (grau)
        tk.Label(sf, text='Decoded Audio:', bg=GUI_BG, font=('Arial',10),
                 fg=COL_AUDIO).grid(row=0, column=0, sticky='w', padx=(4,1))
        tk.Label(sf, textvariable=self.v_audio_pct, bg=GUI_BG, font=('Arial',10,'bold'),
                 fg=COL_AUDIO).grid(row=0, column=1, sticky='w', padx=(1,8))
        tk.Label(sf, text='FAC CRC:', bg=GUI_BG, font=('Arial',10),
                 fg='#000000').grid(row=0, column=3, sticky='w', padx=(4,1))
        tk.Label(sf, textvariable=self.v_fac, bg=GUI_BG, font=('Arial',10,'bold'),
                 fg='#000000').grid(row=0, column=4, sticky='w', padx=(1,8))
        tk.Label(sf, text='Audio Frames max.:', bg=GUI_BG, font=('Arial',10),
                 fg=COL_AUDIO).grid(row=0, column=6, sticky='w', padx=(4,1))
        tk.Label(sf, textvariable=self.v_audio_max, bg=GUI_BG, font=('Arial',10,'bold'),
                 fg=COL_AUDIO).grid(row=0, column=7, sticky='w', padx=(1,4))

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
            ('Doppler', self.v_dop_max, self.v_dop_min, self.v_dop_avg, 'Hz', COL_DOPPLER),
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
                    elif ri == 1:
                        lbl.config(cursor='hand2')
                        lbl.bind('<Button-1>', lambda e: self._toggle_snr_dot('min'))
                    elif ri == 2:
                        lbl.config(cursor='hand2')
                        lbl.bind('<Button-1>', lambda e: self._toggle_snr_dot('avg'))
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

        # ── 3b) Timer / TRX Connect — separate frame, below DRM Modes Used ─
        tf = tk.LabelFrame(right_wrapper, text='', bg=GUI_BG,
                           font=('Arial',8,'bold'), padx=4, pady=4)
        tf.pack(side=tk.TOP, fill=tk.X, pady=(4,0))

        # ── Left half: Timer ──────────────────────────────────────────────
        tf_left = tk.Frame(tf, bg=GUI_BG)
        tf_left.pack(side=tk.LEFT, fill=tk.Y, padx=(0,2))
        # Column title
        tk.Label(tf_left, text='Timer', bg=GUI_BG,
                 font=('Arial',8,'bold')).pack(anchor='w')
        # LED + status text
        tf_left_row = tk.Frame(tf_left, bg=GUI_BG)
        tf_left_row.pack(anchor='w')
        self._timer_led_canvas = tk.Canvas(tf_left_row, width=14, height=14,
                                           bg=GUI_BG, highlightthickness=0)
        self._timer_led_canvas.pack(side=tk.LEFT, padx=(0,3))
        self._timer_led_oval = self._timer_led_canvas.create_oval(
            2, 2, 12, 12, fill='#888888', outline='#555555')
        self._timer_led_var = tk.StringVar(value='Off')
        tk.Label(tf_left_row, textvariable=self._timer_led_var,
                 bg=GUI_BG, font=('Arial',8), width=7,
                 anchor='w').pack(side=tk.LEFT)

        # ── Separator ─────────────────────────────────────────────────────
        tk.Frame(tf, width=1, bg='#888888').pack(
            side=tk.LEFT, fill=tk.Y, padx=(6,4))

        # ── Right half: RX Connect ───────────────────────────────────────
        tf_right = tk.Frame(tf, bg=GUI_BG)
        tf_right.pack(side=tk.LEFT, fill=tk.Y, padx=(2,0))
        # Column title
        tk.Label(tf_right, text='RX Connect', bg=GUI_BG,
                 font=('Arial',8,'bold')).pack(anchor='w')
        # LED + status text
        tf_right_row = tk.Frame(tf_right, bg=GUI_BG)
        tf_right_row.pack(anchor='w')
        self._trx_led_canvas = tk.Canvas(tf_right_row, width=14, height=14,
                                         bg=GUI_BG, highlightthickness=0)
        self._trx_led_canvas.pack(side=tk.LEFT, padx=(0,3))
        self._trx_led_oval = self._trx_led_canvas.create_oval(
            2, 2, 12, 12, fill='#888888', outline='#555555')
        self._trx_led_var = tk.StringVar(value='Off')
        tk.Label(tf_right_row, textvariable=self._trx_led_var,
                 bg=GUI_BG, font=('Arial',8), width=6,
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

        _frame_init = '#0a0a1a' if self.cfg.get('frame_bg','darkblue') in ('darkblue','black') else ('#aaaaaa' if self.cfg.get('frame_bg') == 'gray' else '#ffffff')
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
                      'gray':'#aaaaaa','white':'#ffffff'}
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
        self.v_location = tk.StringVar(value=_loc_name if _loc_name else 'Logging location:')
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
        self.ap_btn = tk.Button(ap_row, text='Auto Plot', font=('Arial',9),
                                command=self._toggle_autoplot)
        self.ap_btn.pack(side=tk.LEFT)

        # 3) Transmitter Site — taller text area, button aligned with Auto Plot button
        fts = tk.LabelFrame(parent, text='Transmitter Site', bg=GUI_BG,
                            font=('Arial',9,'bold'), padx=3, pady=2)
        fts.pack(side=tk.LEFT, padx=2, fill=tk.Y)
        self.v_tx_display = tk.StringVar(value='')
        # Listbox — click to select site directly
        self._tx_hint_lbl = tk.Label(fts, text='', bg=GUI_BG,
                                     font=('Arial',8,'italic'), fg='#cc2200')
        self._tx_hint_lbl.pack()
        tx_lb_frame = tk.Frame(fts, bg='white', relief=tk.SUNKEN, bd=1)
        tx_lb_frame.pack(fill=tk.X, pady=2)
        self.tx_lb = tk.Listbox(tx_lb_frame, font=('Arial',9), height=3,
                                bg='white', fg='#000080',
                                selectbackground='#000080',
                                selectforeground='white',
                                activestyle='none',
                                relief=tk.FLAT, bd=0)
        self.tx_lb.pack(fill=tk.X, padx=2, pady=1)
        self.tx_lb.bind('<<ListboxSelect>>', self._on_tx_lb_select)
        tk.Button(fts, text='TX Sites', font=('Arial',9), width=10,
                  command=self._open_tx_sites).pack(pady=(4,2))

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
                          font=('Arial',9,'bold'),padx=5,pady=3)
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
        tk.Button(fuf,text='Update',font=('Arial',9,'bold'),bg='#aaddaa',
                  command=self._update_files).grid(row=4,column=0,columnspan=2,pady=3,sticky='ew')

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

        if self.cfg.get('unit') == 'miles':
            dist = round(dist * 0.621371, 1)
            unit = 'miles'
        else:
            unit = 'km'

        az_back = int(round((az + 180) % 360))  # back-azimuth, rounded to integer
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
        prev_real = None   # tracks last REAL mode (ignores X0000 glitches)
        for r in rows:
            fmq = r.get('FREQ/MODE/QAM PL:ABH', '').strip()
            parts = fmq.split('/')
            mode_code = parts[1] if len(parts) > 1 else fmq
            # Skip dummy entries: X0000 = no valid signal / TX encoder glitch
            if mode_code.endswith('0000'):
                continue   # do NOT update prev_real — so return to same mode is ignored
            # Only show when the real mode actually changes
            if mode_code != prev_real:
                time_str = r.get('TIME', '?').strip()
                if '.' in time_str:
                    time_str = time_str.split('.')[0]
                time_hhmm = time_str[:5]
                self.modes_text.insert(tk.END, mode_code + ' from ' + time_hhmm + '\n')
                prev_real = mode_code
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
        fg = 'black' if _frame_val in ('white', 'gray') else 'white'
        # Ensure figure background is also updated on every replot
        _frame_map = {'darkblue':'#0a0a1a','black':'#0a0a1a',
                      'navy2':'#0a1628','dpurple':'#160a1e','dteal':'#0a1a1a',
                      'gray':'#aaaaaa','white':'#ffffff'}
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
        times,snr,audio,doppler,delay=[],[],[],[],[]
        for r in rows:
            try:
                dt=parse_dt(r['DATE'], r['TIME'])
                times.append(dt)
                raw_snr = float(r.get('SNR', 0))
                fac_val = int(r.get('FAC', '1')) if r.get('FAC','').strip().isdigit() else 1
                # Only set SNR=0 when FAC=0 AND SNR is genuinely low (real signal loss)
                # A single FAC=0 glitch from the TX encoder must NOT zero the SNR
                # Threshold: if SNR > 5 dB with FAC=0 → TX encoder glitch → keep real SNR
                if fac_val == 0 and raw_snr <= 5.0:
                    snr.append(0.0)   # real signal loss
                else:
                    snr.append(raw_snr)   # valid signal or TX encoder glitch
                ao = float(r.get('AUDIOOK', 0))
                at = float(r.get('AUDIO', 0))
                # ratio 0.0–1.0 regardless of absolute frame counts
                ratio = (ao / at) if at > 0 else 0.0
                ratio = max(0.0, min(1.0, ratio))
                audio.append(ratio)
                doppler.append(float(r.get('DOPPLER', 0)))
                delay.append(float(r.get('DELAY', 0)))
            except: continue
        if not times: self.canvas.draw(); return

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
                ax.plot(xs, ya_smooth, color=COL_AUDIO, linewidth=lw, zorder=5)
            else:
                ax.plot(xs, ya, color=COL_AUDIO, linewidth=lw, zorder=5)

        # SNR (red)
        if self.opt_snr.get() and snr:
            ax.plot(xs,snr,color=COL_SNR,linewidth=1.2,zorder=4)

        # Doppler (green): logarithmic scale
        # Formula: y_dB = 20.959 * log10(Hz) + 20
        # → 1 Hz = 20 dB, 3 Hz = 30 dB, 0.1 Hz ≈ 0 dB
        def _dop_to_db(v):
            if v <= 0: return 0.0
            y = 20.959 * math.log10(max(v, 0.05)) + 20.0
            return max(0.0, min(SNR_MAX, y))
        if self.opt_doppler.get() and doppler:
            yd = [_dop_to_db(v) for v in doppler]
            # Smooth doppler to remove staircase effect — rolling average
            win = min(30, max(5, len(yd)//20))  # window size
            yd_s = []
            for i in range(len(yd)):
                s = max(0, i-win); e = min(len(yd), i+win+1)
                yd_s.append(sum(yd[s:e]) / (e-s))
            ax.plot(xs, yd_s, color=COL_DOPPLER, linewidth=1.4, zorder=3)

        # Delay (ochre): 0-10 ms → 0-10 dB scale
        if self.opt_delay.get() and delay:
            ax.plot(xs,[min(v,10.0) for v in delay],color=COL_DELAY,linewidth=0.8,zorder=3)

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
                    comp_dts_full.append(dt)
                    cs_full.append(float(r.get('SNR', 0)))
                    ao = float(r.get('AUDIOOK', 0))
                    at = float(r.get('AUDIO',   0))
                    ratio = (ao / at) if at > 0 else 0.0
                    ca_full.append(max(0.0, min(1.0, ratio)))
                except:
                    continue

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
                            linewidth=1.2, zorder=4)
                if self.opt_doppler.get() and doppler:
                    yd2 = [_dop_to_db(v) for v in doppler]
                    w2  = min(30, max(5, len(yd2)//20))
                    yd2s = [sum(yd2[max(0,i-w2):min(len(yd2),i+w2+1)]) /
                            (min(len(yd2),i+w2+1)-max(0,i-w2))
                            for i in range(len(yd2))]
                    ax.plot(main_abs, yd2s, color=COL_DOPPLER,
                            linewidth=1.4, zorder=3)
                if self.opt_delay.get() and delay:
                    ax.plot(main_abs, [min(v, 10.0) for v in delay],
                            color=COL_DELAY, linewidth=0.8, zorder=3)
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
                            linewidth=lw2, zorder=5)

                # ── Compare SNR (cyan) — only if data in window ───────────
                if ct_abs:
                    ax.plot(ct_abs, cs, color='#00cccc', linewidth=1.4,
                            linestyle='-', zorder=6)

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
                    ax.plot(ct_abs, yac, color='#ddcc00',
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
                ax.text(0.01, 0.97, info,
                        transform=ax.transAxes, color='#00cccc',
                        fontsize=8, va='top', ha='left',
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
        dop_ticks = [(3.0,'3'), (2.0,'2'), (1.5,'1.5'), (1.0,'1 Hz'),
                     (0.5,'0.5'), (0.4,'0.4'), (0.3,'0.3'),
                     (0.2,'0.2'), (0.15,'0.15'), (0.1,'0.1')]
        for hz, label in dop_ticks:
            y = _dop_y(hz)
            if y < 0 or y > 1.0: continue
            ax.annotate('', xy=(1.0, y), xytext=(1.008, y),
                        xycoords='axes fraction', textcoords='axes fraction',
                        arrowprops=dict(arrowstyle='-', color=COL_DOPPLER,
                                        lw=1.0),
                        annotation_clip=False)
            ax.text(1.012, y, label, transform=ax.transAxes,
                    color=COL_DOPPLER, fontsize=9, va='center', ha='left',
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

        tk.Label(dlg, text='Refresh Rate:', bg=GUI_BG,
                 font=('Arial', 10)).grid(row=0, column=0, padx=15, pady=12, sticky='w')
        rv = tk.StringVar(value='30')
        tk.OptionMenu(dlg, rv, '5', '10', '30', '60', '120', '240').grid(
            row=0, column=1, padx=5)
        tk.Label(dlg, text='seconds', bg=GUI_BG,
                 font=('Arial', 10)).grid(row=0, column=2, padx=5)

        tk.Label(dlg, text='Scroll:', bg=GUI_BG,
                 font=('Arial', 10)).grid(row=1, column=0, padx=15, pady=12, sticky='w')
        sv = tk.StringVar(value='Full')
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
        Used exclusively by the Set Event timer after the 65-second delay.
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
                cmd.append('f')   # query current frequency — lightest command

                # ── Run test ──────────────────────────────────────────
                # creationflags is Windows-only — never pass it on Linux
                if platform.system() == 'Windows':
                    res = subprocess.run(cmd, capture_output=True,
                                         text=True, timeout=5,
                                         encoding='utf-8', errors='replace',
                                         creationflags=0x08000000)
                else:
                    res = subprocess.run(cmd, capture_output=True,
                                         text=True, timeout=5,
                                         encoding='utf-8', errors='replace')
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
    # RIGCTL HEALTH LOOP  (every 30s, independent of all other loops)
    # ─────────────────────────────────────────────────
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
          yellow / 'Waiting' — at least one start-timer is counting down
          green  / 'Active'  — at least one stop-timer is counting down
                               (event is running right now)
          blue   / 'Done'    — all timers finished, at least one slot done
        """
        # ── Derive state from live timer threads ──────────────────────
        any_waiting   = False   # start-timer alive  → yellow
        any_active    = False   # stop-timer  alive  → green
        any_cancelled = False   # manually stopped   → orange
        any_done      = False   # slot led == 'blue'  → blue (after green)

        for i in range(3):
            pair = self._sched_timers[i]
            t_s  = pair[0]   # start-timer thread
            t_e  = pair[1]   # stop-timer  thread

            if t_e is not None and t_e.is_alive():
                any_active = True
            elif t_s is not None and t_s.is_alive():
                any_waiting = True
            elif self._sched_state[i].get('led') == 'orange':
                any_cancelled = True
            elif self._sched_state[i].get('led') == 'blue':
                any_done = True

        # ── Choose colour + text (priority: active > waiting > cancelled > done > off) ──
        if any_active:
            fill, outline, text = '#22cc22', '#116611', 'Active'
        elif any_waiting:
            fill, outline, text = '#ffee00', '#ccaa00', 'Waiting'
        elif any_cancelled:
            fill, outline, text = '#ff8800', '#cc5500', 'Stopped'
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

        # ── Update RX Connect LED ─────────────────────────────────────────
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
    def _open_tx_sites(self): self._manage_tx_sites()

    def _pick_tx_site(self,matches):
        dlg=tk.Toplevel(self.root); dlg.title('Select Transmitter Site'); dlg.configure(bg=GUI_BG)
        center_dialog(dlg, self.root, 420, 200)
        dlg.grab_set()
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
                self.v_dist.set(f'{int(round(dist))} km'); self.v_az.set(f'{int(round(az))} / {int(round((az+180)%360))} deg.')
            dlg.destroy()
        tk.Button(dlg,text='Select',command=sel).pack(pady=5)

    def _manage_tx_sites(self):
        dlg = tk.Toplevel(self.root)
        dlg.title('Manage the Transmitter Sites List')
        dlg.configure(bg=GUI_BG)
        center_dialog(dlg, self.root, 800, 520)

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
        for r, lbl in enumerate(['Service Name','TX Location','Frequency (kHz)']):
            tk.Label(lf, text=lbl, bg=GUI_BG, font=('Arial',10)).grid(row=r, column=0, sticky='w', pady=3)
            e = tk.Entry(lf, width=24, font=('Arial',10))
            e.grid(row=r, column=1, padx=3, pady=3)
            entries[lbl] = e
        tk.Label(lf, text='Lat:', bg=GUI_BG, font=('Arial',10)).grid(row=3, column=0, sticky='w')
        lat_d = tk.Entry(lf, width=5, font=('Arial',10)); lat_d.grid(row=3, column=1, sticky='w')
        lat_m = tk.Entry(lf, width=5, font=('Arial',10)); lat_m.grid(row=3, column=2, sticky='w')
        lat_ns = tk.StringVar(value='N'); tk.OptionMenu(lf, lat_ns, 'N','S').grid(row=3, column=3)
        tk.Label(lf, text='Lon:', bg=GUI_BG, font=('Arial',10)).grid(row=4, column=0, sticky='w')
        lon_d = tk.Entry(lf, width=5, font=('Arial',10)); lon_d.grid(row=4, column=1, sticky='w')
        lon_m = tk.Entry(lf, width=5, font=('Arial',10)); lon_m.grid(row=4, column=2, sticky='w')
        lon_ew = tk.StringVar(value='E'); tk.OptionMenu(lf, lon_ew, 'E','W').grid(row=4, column=3)
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
        tk.Button(btn_f, text='Load from PC (any CSV file)',
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
        label=(self.sel_log.label if self.sel_log else 'log').replace(' ','_')
        p=filedialog.asksaveasfilename(initialdir=LOGFILES_DIR,
            initialfile=f'{label}_{datetime.now().strftime("%Y%m%d_%H%M")}.csv',
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
        # Build filename: Frequency-DDMMYYYY-StartUTC-EndUTC-Nickname.png
        # e.g. 6120-31052026-2000-2030-Andy.png  (original format)
        def safe(s):
            for c in r'\/:*?"<>|': s = s.replace(c, '')
            return s.strip()
        nickname = safe(self.cfg.get('nickname', '').strip())
        if self.sel_log:
            freq  = self.sel_log.frequency.replace(' ','').replace('kHz','')
            if self.sel_log.start_time:
                date_s  = self.sel_log.start_time.strftime('%d%m%Y')
                start_s = self.sel_log.start_time.strftime('%H%M')
            else:
                date_s  = datetime.now().strftime('%d%m%Y')
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
            date_s  = datetime.now().strftime('%d%m%Y')
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
            from PIL import ImageGrab
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
            img = ImageGrab.grab(bbox=(x, y, x + width, y + height))

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
        center_dialog(dlg, self.root, 680, 580)
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
                                    ('Decoded Audio:',self.v_audio_pct.get()),('FAC CRC:',self.v_fac.get())]): ar(fdrm,i,l,v)
        fsw=lf('Software Radio',2,0); ar(fsw,0,'DRM Software:','Dream'); ar(fsw,1,'S/W Version:',log.sw_version)
        br=tk.Frame(dlg,bg=GUI_BG); br.pack(pady=5)
        def save_txt():
            p=filedialog.asksaveasfilename(defaultextension='.txt',filetypes=[('Text','*.txt')])
            if p:
                with open(p,'w',encoding='utf-8') as f:
                    f.write(f'DRM Log Summary\nLabel: {log.label}\nSNR max: {fmt(sn_max)} dB  min: {fmt(sn_min)} dB  avg: {fmt(sn_avg)} dB\n'
                            f'Delay max: {fmt(dl_max)} ms  avg: {fmt(dl_avg)} ms\nDoppler max: {fmt(dp_max)} Hz  avg: {fmt(dp_avg)} Hz\n'
                            f'Audio: {self.v_audio_pct.get()}\n')
        tk.Button(br,text='Save',command=save_txt,width=8).pack(side=tk.LEFT,padx=5)
        tk.Button(br,text='Close',command=dlg.destroy,width=8).pack(side=tk.LEFT,padx=5)

    # ─────────────────────────────────────────────────
    # SETUP
    # ─────────────────────────────────────────────────
    def _open_setup(self):
        dlg=tk.Toplevel(self.root); dlg.title('Basic Setup Parameters')
        dlg.configure(bg=GUI_BG)
        center_dialog(dlg, self.root, 640, 615)
        dlg.grab_set()
        fd=tk.LabelFrame(dlg,text='Select Distance',bg=GUI_BG,font=('Arial',8,'bold'))
        fd.pack(fill=tk.X,padx=8,pady=3)
        uv=tk.StringVar(value=self.cfg.get('unit','kilometer'))
        tk.Radiobutton(fd,text='Kilometer',variable=uv,value='kilometer',bg=GUI_BG).pack(side=tk.LEFT)
        tk.Radiobutton(fd,text='Miles',    variable=uv,value='miles',    bg=GUI_BG).pack(side=tk.LEFT)
        # Plot Field Background — controls ax.set_facecolor (plot area only)
        fbg=tk.LabelFrame(dlg,text='Plot Field Background',bg=GUI_BG,font=('Arial',8,'bold'))
        fbg.pack(fill=tk.X,padx=8,pady=3)
        bgv=tk.StringVar(value=self.cfg.get('plot_bg','darkblue'))
        tk.Radiobutton(fbg,text='Dark Blue',   variable=bgv,value='darkblue',bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        tk.Radiobutton(fbg,text='Darkblue 2',  variable=bgv,value='navy2',   bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        tk.Radiobutton(fbg,text='Dark Purple', variable=bgv,value='dpurple', bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        tk.Radiobutton(fbg,text='Dark Teal',   variable=bgv,value='dteal',   bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        tk.Radiobutton(fbg,text='White',       variable=bgv,value='white',   bg=GUI_BG).pack(side=tk.LEFT,padx=6)

        # Plot Frame Color — controls fig.set_facecolor (scales, time axis, margins)
        ffr=tk.LabelFrame(dlg,text='Plot Frame Color',bg=GUI_BG,font=('Arial',8,'bold'))
        ffr.pack(fill=tk.X,padx=8,pady=3)
        frv=tk.StringVar(value=self.cfg.get('frame_bg','darkblue'))
        tk.Radiobutton(ffr,text='Dark Blue',   variable=frv,value='darkblue',bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        tk.Radiobutton(ffr,text='Darkblue 2',  variable=frv,value='navy2',   bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        tk.Radiobutton(ffr,text='Dark Purple', variable=frv,value='dpurple', bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        tk.Radiobutton(ffr,text='Dark Teal',   variable=frv,value='dteal',   bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        tk.Radiobutton(ffr,text='Gray',        variable=frv,value='gray',    bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        tk.Radiobutton(ffr,text='White',       variable=frv,value='white',   bg=GUI_BG).pack(side=tk.LEFT,padx=6)
        fsa=tk.LabelFrame(dlg,text='Screenshot Alerts',bg=GUI_BG,font=('Arial',8,'bold'))
        fsa.pack(fill=tk.X,padx=8,pady=3)
        sav=tk.BooleanVar(value=self.cfg.get('screenshot_alerts',True))
        tk.Radiobutton(fsa,text='Yes',variable=sav,value=True, bg=GUI_BG).pack(side=tk.LEFT)
        tk.Radiobutton(fsa,text='No', variable=sav,value=False,bg=GUI_BG).pack(side=tk.LEFT)
        fms=tk.LabelFrame(dlg,text='Multiple Sites Alert',bg=GUI_BG,font=('Arial',8,'bold'))
        fms.pack(fill=tk.X,padx=8,pady=3)
        msv=tk.BooleanVar(value=self.cfg.get('multiple_sites_alert',True))
        tk.Radiobutton(fms,text='Yes',variable=msv,value=True, bg=GUI_BG).pack(side=tk.LEFT)
        tk.Radiobutton(fms,text='No', variable=msv,value=False,bg=GUI_BG).pack(side=tk.LEFT)
        fap=tk.LabelFrame(dlg,text='Autoplot 5 Sec. Alert',bg=GUI_BG,font=('Arial',8,'bold'))
        fap.pack(fill=tk.X,padx=8,pady=3)
        ap5v=tk.BooleanVar(value=self.cfg.get('ap_5s_alert',True))
        tk.Radiobutton(fap,text='Yes',variable=ap5v,value=True, bg=GUI_BG).pack(side=tk.LEFT)
        tk.Radiobutton(fap,text='No', variable=ap5v,value=False,bg=GUI_BG).pack(side=tk.LEFT)
        frc=tk.LabelFrame(dlg,text='Receiver Coordinates',bg=GUI_BG,font=('Arial',8,'bold'))
        frc.pack(fill=tk.X,padx=8,pady=3)
        lat_dv=tk.IntVar(value=self.cfg.get('rx_lat_deg',46))
        lat_mv=tk.StringVar(value=f"{self.cfg.get('rx_lat_min',57):02d}")
        lat_ns=tk.StringVar(value=self.cfg.get('rx_lat_ns','N'))
        lon_dv=tk.IntVar(value=self.cfg.get('rx_lon_deg',7))
        lon_mv=tk.StringVar(value=f"{self.cfg.get('rx_lon_min',26):02d}")
        lon_ew=tk.StringVar(value=self.cfg.get('rx_lon_ew','E'))
        for row,(lbl,dv,mv,hv,opts) in enumerate([('Latitude:', lat_dv,lat_mv,lat_ns,['N','S']),
                                                   ('Longitude:',lon_dv,lon_mv,lon_ew,['E','W'])]):
            tk.Label(frc,text=lbl,bg=GUI_BG,font=('Arial',8)).grid(row=row,column=0,sticky='w',padx=3)
            tk.Entry(frc,textvariable=dv,width=4).grid(row=row,column=1)
            tk.Label(frc,text='Deg.',bg=GUI_BG,font=('Arial',8)).grid(row=row,column=2)
            tk.Entry(frc,textvariable=mv,width=4).grid(row=row,column=3)
            tk.Label(frc,text='Min.',bg=GUI_BG,font=('Arial',8)).grid(row=row,column=4)
            tk.OptionMenu(frc,hv,*opts).grid(row=row,column=5)
        fln=tk.LabelFrame(dlg,text='Location Name',bg=GUI_BG,font=('Arial',8,'bold'))
        fln.pack(fill=tk.X,padx=8,pady=3)
        loc_nv=tk.StringVar(value=self.cfg.get('location_name',''))
        tk.Entry(fln,textvariable=loc_nv,width=30).pack(padx=5,pady=2)
        fn=tk.LabelFrame(dlg,text='Nickname',bg=GUI_BG,font=('Arial',8,'bold'))
        fn.pack(fill=tk.X,padx=8,pady=3)
        nv=tk.StringVar(value=self.cfg.get('nickname','Nickname'))
        tk.Entry(fn,textvariable=nv,width=12).pack(side=tk.LEFT,padx=5)
        tk.Button(fn,text='Change',command=lambda:self.cfg.set('nickname',nv.get())).pack(side=tk.LEFT)
        frxc = tk.LabelFrame(dlg, text='Dream and Receiver-Configuration',
                              bg=GUI_BG, font=('Arial',8,'bold'))
        frxc.pack(fill=tk.X, padx=8, pady=3)
        tk.Button(frxc, text='Setup', font=('Arial',9), bg='#dddddd',
                  width=10,
                  command=self._open_rx_config).pack(side=tk.LEFT, padx=5, pady=3)
        tk.Label(frxc, text='Set Dream path and Transceiver settings',
                 bg=GUI_BG, font=('Arial',8),
                 fg='#555555').pack(side=tk.LEFT, padx=5)
        tk.Label(dlg, text=VERSION, bg=GUI_BG,
                 font=('Arial',7,'italic'), fg='#555').pack(pady=2)
        def ok():
            self.cfg.set('unit',uv.get()); self.cfg.set('plot_bg',bgv.get()); self.cfg.set('frame_bg',frv.get())
            self.cfg.set('screenshot_alerts',sav.get()); self.cfg.set('multiple_sites_alert',msv.get())
            self.cfg.set('ap_5s_alert', ap5v.get())
            # Convert minutes from StringVar to int before saving
            lat_min_int = int(lat_mv.get() or 0)
            lon_min_int = int(lon_mv.get() or 0)
            self.cfg.set('rx_lat_deg', lat_dv.get())
            self.cfg.set('rx_lat_min', lat_min_int)
            self.cfg.set('rx_lat_ns',  lat_ns.get())
            self.cfg.set('rx_lon_deg', lon_dv.get())
            self.cfg.set('rx_lon_min', lon_min_int)
            self.cfg.set('rx_lon_ew',  lon_ew.get())
            self.cfg.set('location_name', loc_nv.get())
            # Update display immediately — convert int for :02d format
            self.v_lat_disp.set(f"{lat_dv.get()}°{lat_min_int:02d}'{lat_ns.get()}")
            self.v_lon_disp.set(f"{lon_dv.get()}°{lon_min_int:02d}'{lon_ew.get()}")
            # Update location name in Miscellaneous frame immediately
            loc_name = loc_nv.get().strip()
            if loc_name:
                self.v_location.set(loc_name)
            # Recalculate distance/azimuth with new coordinates
            if self.sel_tx:
                self._apply_tx_site()
            self._replot()
            dlg.destroy()
        br=tk.Frame(dlg,bg=GUI_BG); br.pack(pady=6)
        tk.Button(br,text='OK',    command=ok,          width=8).pack(side=tk.LEFT,padx=5)
        tk.Button(br,text='Cancel',command=dlg.destroy, width=8).pack(side=tk.LEFT,padx=5)

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
        center_dialog(dlg, self.root, 680, 400)

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
        sb = ttk.Scrollbar(frame, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
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

        add_text('Thanks to:',
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

        # ── Close button ─────────────────────────────────────────────
        tk.Button(win, text='Close', font=('Arial', 10),
                  width=10, command=win.destroy).pack(pady=8)

    def _show_help(self):
        """
        Show help text.
        Loads drmlogplotter_help.txt from BASE_DIR — works correctly for
        .py, .exe, .bin and .AppImage (all use BASE_DIR consistently).
        Shows a clear download hint when the file is not found.
        """
        help_file   = os.path.join(BASE_DIR, 'drmlogplotter_help.txt')
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
                "Please download  drmlogplotter_help.txt  from the GitHub repository\n"
                "and place it in the same folder as the drmlogplotter executable:\n\n"
                f"  {BASE_DIR}\n\n"
                "https://github.com/YOUR_USERNAME/drm-log-plotter"
            )
            help_source = '  [help file not found]'

        # Centre on main window
        w, h = 660, 540

        dlg = tk.Toplevel(self.root)
        dlg.title('DRM-Log Plotter – Help')
        dlg.configure(bg=GUI_BG)
        center_dialog(dlg, self.root, w, h)

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

    def _open_rx_config(self):
        """
        RX Config dialog — stores Dream path + Transceiver settings
        persistently in config. Opened via [RX Config] button in Set Event.
        """
        import subprocess, platform

        rx_dlg = tk.Toplevel(self.root)
        rx_dlg.title('RX Config — Receiver Settings')
        rx_dlg.configure(bg=GUI_BG)
        rx_dlg.resizable(False, False)
        center_dialog(rx_dlg, self.root, 640, 640)
        rx_dlg.grab_set()

        # ── Dream Location ────────────────────────────────────────────
        fl = tk.LabelFrame(rx_dlg, text='Dream Location', bg=GUI_BG,
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
                 font=('Arial',11), width=12, anchor='w').pack(side=tk.LEFT)
        tk.Entry(path_row, textvariable=path_var,
                 font=('Arial',11), width=34).pack(side=tk.LEFT, padx=(2,4))

        # ── Dream Log File Path ───────────────────────────────────────
        # Folder where Dream writes DreamLog.txt and DreamLogLong.csv.
        # Windows: same folder as Dream.exe (leave blank = auto-derive).
        # Linux:   may differ from the Dream binary folder (e.g. ~/.dream or ~/)
        logpath_row = tk.Frame(fl, bg=GUI_BG)
        logpath_row.pack(fill=tk.X, pady=(4,0))
        tk.Label(logpath_row, text='Log file path:', bg=GUI_BG,
                 font=('Arial',11), width=12, anchor='w').pack(side=tk.LEFT)
        logpath_var = tk.StringVar(value=self.cfg.get('dream_log_path', ''))
        tk.Entry(logpath_row, textvariable=logpath_var,
                 font=('Arial',11), width=34).pack(side=tk.LEFT, padx=(2,4))

        def browse_logpath():
            folder = filedialog.askdirectory(
                title='Select folder where Dream writes DreamLog.txt',
                initialdir=logpath_var.get() or os.path.expanduser('~'))
            if folder:
                logpath_var.set(folder)

        tk.Button(logpath_row, text='Browse…', font=('Arial',10),
                  command=browse_logpath).pack(side=tk.LEFT)

        tk.Label(fl, text='Leave "Log file path" blank to use the same folder as Dream.exe  '
                           '(Windows default).\nOn Linux set this to the folder where '
                           'Dream writes its log files (e.g.  /home/user/dream-logs ).',
                 bg=GUI_BG, font=('Arial',8), fg='#555555',
                 justify=tk.LEFT).pack(anchor='w', padx=2, pady=(2,2))

        status_lbl = tk.Label(rx_dlg, text='', bg=GUI_BG,
                              font=('Arial',9,'italic'), fg='#007700')
        status_lbl.pack(pady=(2,0))

        def auto_detect():
            candidates = [
                r'C:\Dream\Dream.exe',
                r'C:\Program Files\Dream\Dream.exe',
                '/usr/local/bin/dream',
                '/usr/bin/dream',
            ]
            for p in candidates:
                if os.path.exists(p):
                    path_var.set(p)
                    status_lbl.config(text=f'Found: {p}', fg='#007700')
                    return
            status_lbl.config(text='Dream not found — enter path manually',
                              fg='#cc0000')

        tk.Button(path_row, text='Auto-Detect', font=('Arial',10),
                  command=auto_detect).pack(side=tk.LEFT)

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

        ft = tk.LabelFrame(rx_dlg,
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
                                        timeout=60)
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
        fr = tk.LabelFrame(rx_dlg, text='Hamlib / RigCTL', bg=GUI_BG,
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
                        text=f'rigctl selected: {p}  —  click "Take" to save.',
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
        tk.Button(fr2, text='Take', font=('Arial',10, 'bold'),
                  width=8, bg='#aaddaa',
                  command=take_rigctl).pack(side=tk.LEFT)

        # ══════════════════════════════════════════════════════════════
        # FRAME: Connection Mode — USB/Serial or Network
        # ══════════════════════════════════════════════════════════════
        fn = tk.LabelFrame(rx_dlg, text='Connection Mode', bg=GUI_BG,
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
        tk.Label(fusb, text='Port:', bg=GUI_BG,
                 font=('Arial',10), width=14, anchor='w').pack(side=tk.LEFT)
        trx_port_var = tk.StringVar(value=self.cfg.get('trx_port',
            'COM3' if platform.system()=='Windows' else '/dev/ttyUSB0'))
        port_cb = ttk.Combobox(fusb, textvariable=trx_port_var,
                               font=('Arial',10), width=12)
        port_cb.pack(side=tk.LEFT, padx=4)

        def refresh_usb_ports():
            ports = detect_ports()
            port_cb['values'] = ports
            cur = trx_port_var.get()
            if cur not in ports and ports:
                trx_port_var.set(ports[0])
        refresh_usb_ports()
        tk.Button(fusb, text='↺', font=('Arial',10), width=2,
                  command=refresh_usb_ports).pack(side=tk.LEFT, padx=(0,6))
        tk.Label(fusb, text='Baud:', bg=GUI_BG,
                 font=('Arial',10)).pack(side=tk.LEFT, padx=(4,2))
        trx_baud_var = tk.StringVar(value=self.cfg.get('trx_baud','9600'))
        ttk.Combobox(fusb, textvariable=trx_baud_var,
                     values=['1200','4800','9600','19200',
                             '38400','57600','115200'],
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

        # Grey out inactive section based on mode
        def _update_conn_mode(*_):
            usb_state = 'normal' if conn_mode_var.get()=='usb' else 'disabled'
            net_state = 'normal' if conn_mode_var.get()=='network' else 'disabled'
            for w in fusb.winfo_children():
                try: w.config(state=usb_state)
                except Exception: pass
            for w in fnet.winfo_children():
                try: w.config(state=net_state)
                except Exception: pass
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
                    encoding='utf-8', errors='replace')
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
            """Send 'F <hz>' command to TRX via rigctl."""
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
                freq_hz = str(int(freq_str) * 1000)
            except ValueError:
                status_lbl.config(text='Invalid frequency value.', fg='#cc0000')
                return
            cmd, err = _build_rigctl_args(model_id, 'F')
            if not cmd:
                status_lbl.config(text=err, fg='#cc0000')
                return
            cmd.append(freq_hz)   # rigctl F <hz>
            try:
                result = _subprocess_run(
                    cmd, capture_output=True, text=True, timeout=5,
                    encoding='utf-8', errors='replace')
                if result.returncode == 0:
                    _set_trx_led('green')
                    status_lbl.config(
                        text=f'TRX set to {freq_str} kHz — OK',
                        fg='#007700')
                else:
                    _set_trx_led('red')
                    status_lbl.config(
                        text=f'Set Freq error: {result.stderr.strip()[:60]}',
                        fg='#cc0000')
            except subprocess.TimeoutExpired:
                _set_trx_led('red')
                status_lbl.config(text='Timeout — check connection settings',
                                  fg='#cc0000')
            except Exception as ex:
                _set_trx_led('red')
                status_lbl.config(text=f'Set Freq error: {ex}', fg='#cc0000')

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
            cmd, err = _build_rigctl_args(model_id, 'f')
            if not cmd:
                _set_trx_led('red')
                status_lbl.config(text=err, fg='#cc0000')
                return
            try:
                result = _subprocess_run(
                    cmd, capture_output=True, text=True, timeout=5,
                    encoding='utf-8', errors='replace')
                if result.returncode == 0:
                    _set_trx_led('green')
                    mode_txt = ('Network' if conn_mode_var.get() == 'network'
                                else 'USB')
                    status_lbl.config(
                        text=f'TRX connected [{mode_txt}] — '
                             f'freq: {result.stdout.strip()} Hz',
                        fg='#007700')
                else:
                    _set_trx_led('red')
                    status_lbl.config(
                        text=f'TRX error: {result.stderr.strip()[:60]}',
                        fg='#cc0000')
            except subprocess.TimeoutExpired:
                _set_trx_led('red')
                status_lbl.config(
                    text='Timeout — check connection settings', fg='#cc0000')
            except Exception as ex:
                _set_trx_led('red')
                status_lbl.config(text=f'TRX error: {ex}', fg='#cc0000')

        # Rebind the Test Connection button to the LED-aware version
        for widget in tr3.winfo_children():
            if isinstance(widget, tk.Button) and widget.cget('text') == 'Test Connection':
                widget.config(command=test_trx_with_led)
                break

        # ── Pack frames in correct visual order ──────────────────────────
        fl.pack(fill=tk.X, padx=10, pady=(10,4))  # Dream Location
        fr.pack(fill=tk.X, padx=10, pady=(0,4))   # RigCTL
        fn.pack(fill=tk.X, padx=10, pady=(0,4))   # Connection Mode
        ft.pack(fill=tk.X, padx=10, pady=(0,4))   # Transceiver Control

        # Status label for Hamlib load result
        rx_status = tk.Label(rx_dlg, text='Loading Hamlib list...',
                             bg=GUI_BG, font=('Arial',8,'italic'),
                             fg='#555555')
        rx_status.pack(pady=(0,2))

        # Now call auto-load — delayed 200ms so dialog is fully
        # rendered and visible before the background thread starts.
        rx_dlg.after(200, lambda: _auto_load_hamlib(rx_status))

        # ── Save & Close ──────────────────────────────────────────────
        def save_and_close():
            self.cfg.set('dream_path',     path_var.get().strip())
            self.cfg.set('dream_log_path', logpath_var.get().strip())
            self.cfg.set('trx_enable',    trx_enable_var.get())
            self.cfg.set('trx_name',      trx_var.get())
            self.cfg.set('trx_rigctl',    trx_rigctl_var.get().strip())
            self.cfg.set('trx_conn_mode', conn_mode_var.get())
            self.cfg.set('trx_port',      trx_port_var.get().strip())
            self.cfg.set('trx_baud',      trx_baud_var.get().strip())
            self.cfg.set('trx_net_host',  trx_net_host_var.get().strip())
            self.cfg.set('trx_net_port',  trx_net_port_var.get().strip())
            model_id = next((t[1] for t in TRX_LIST
                             if t[0] == trx_var.get()), None)
            if model_id:
                self.cfg.set('trx_model_id', model_id)
            status_lbl.config(text='Settings saved.', fg='#007700')
            _hamlib_dlg_alive[0] = False   # prevent stale thread from firing
            rx_dlg.after(600, rx_dlg.destroy)

        btn_row = tk.Frame(rx_dlg, bg=GUI_BG)
        btn_row.pack(pady=(8,10))
        tk.Button(btn_row, text='Save & Close',
                  font=('Arial',10,'bold'), bg='#aaddaa', width=14,
                  command=save_and_close).pack(side=tk.LEFT, padx=8)
        tk.Button(btn_row, text='Cancel',
                  font=('Arial',10), width=10,
                  command=rx_dlg.destroy).pack(side=tk.LEFT, padx=8)

    def _set_event(self):
        """
        Dream Simple Scheduled Event.
        Starts and stops Dream.exe at a pre-set local time with a given frequency.
        Uses subprocess to launch Dream with the -r <freq> parameter.
        """
        import threading
        import platform

        # Default Dream path based on OS
        dlg = tk.Toplevel(self.root)
        dlg.title('Dream — Start & Schedule')
        dlg.configure(bg=GUI_BG)
        dlg.resizable(False, False)
        center_dialog(dlg, self.root, 650, 490)
        dlg.grab_set()

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

        # ── Dream.ini helper — sets [Logfile] enablelog + delay ──────────
        def _write_dream_ini(enable_log):
            """
            Write enablelog and delay into Dream.ini before starting Dream.
            Dream.ini is always in the same folder as Dream.exe.

            Dream.ini uses a non-standard format with duplicate keys:
                enablelog=0
                enablelog = 0
            Both variants must be updated. We read line-by-line and write
            back unchanged — no configparser, no format destruction.

            enable_log=True  → enablelog=1, delay=15  (both variants)
            enable_log=False → enablelog=0             (both variants)
                               delay is NOT changed on disable
            Returns True on success, False on error.
            """
            path = self.cfg.get('dream_path', '').strip()
            if not path:
                return False
            dream_dir = os.path.dirname(os.path.abspath(path))
            ini_path  = os.path.join(dream_dir, 'Dream.ini')
            if not os.path.exists(ini_path):
                try:
                    status_lbl.config(
                        text=f'Dream.ini not found in: {dream_dir}',
                        fg='#cc0000')
                except Exception: pass
                return False
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

                return True

            except Exception as ex:
                try:
                    status_lbl.config(
                        text=f'Dream.ini write error: {ex}',
                        fg='#cc0000')
                except Exception: pass
                return False

        # ── Helper: check if Dream is already running ─────────────────────
        def _is_dream_running():
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

        # ── Core: start Dream — reads config for path and TRX ─────────────
        def _do_start(freq_khz, enable_log):
            """Start Dream using config values for path."""
            import subprocess

            # ── Guard: block a second Dream instance ──────────────────────
            if _is_dream_running():
                messagebox.showinfo(
                    'Dream is active',
                    'Dream is already running.\n\n'
                    'Only one instance of Dream can be active at a time.\n'
                    'Please stop the running Dream first.')
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
                if not _write_dream_ini(enable_log):
                    return   # ini write failed — error already shown in status_lbl
                cmd = [path]
                if freq_khz:
                    cmd += ['-r', str(freq_khz)]
                    self.cfg.set('last_event_freq', str(freq_khz))
                _dream_dir = os.path.dirname(os.path.abspath(path))
                dream_proc[0] = subprocess.Popen(cmd, cwd=_dream_dir)
                _safe_led('led3', led3_c, led3_o, 'green')
                _safe_led('led4', led4_c, led4_o, 'green' if enable_log else 'grey')
                self._dream_start_time = datetime.now()
                self._dream_log_flag   = enable_log
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
                    AP_DELAY  = 50    # seconds AutoPlot waits after Dream start
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
                    # Schedule _ap_countdown correctly depending on Log flag:
                    #   Log + AutoPlot → 15s log delay + 65s AP delay = 80s
                    #   AutoPlot only  → 65s AP delay only (no log phase)
                    ap_after_ms = (LOG_DELAY + AP_DELAY) * 1000 if enable_log else AP_DELAY * 1000
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
            if not freq:
                ans = messagebox.askyesno(
                    'Start Dream',
                    'No frequency entered.\n\n'
                    'Start Dream without setting a Log-Frequency?\n\n'
                    '(The last frequency in Dream.ini will remain.)')
                if not ans: return
                _do_start(freq_khz=None, enable_log=False)
            else:
                _do_start(freq_khz=freq, enable_log=False)

        def start_dream_with_log():
            freq = freq_var.get().strip()
            # Manual start: AutoPlot is NOT started automatically.
            # The user can start it manually via the Auto Plot button in the main window.
            self._autoplot_enabled[0] = False
            if not freq:
                messagebox.showwarning(
                    'Start Dream with Log',
                    'Please enter a frequency first!\n\n'
                    'A frequency is required to start Dream with logging.')
                return
            _do_start(freq_khz=freq, enable_log=True)

        def stop_dream():
            """Terminate Dream, cancel any running stop-timers, show orange LED briefly."""
            import subprocess

            # ── Step 1: Cancel stop-timers and set Orange IMMEDIATELY ────
            # This must happen before taskkill so the user sees orange first.
            any_cancelled = False
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
                for i in range(3):
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
                    for i in range(3):
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
                        dream_proc[0].terminate()
                        dream_proc[0] = None
                    except Exception as ex:
                        try:
                            status_lbl.config(
                                text=f'Error stopping Dream: {ex}',
                                fg='#cc0000')
                        except Exception: pass
                        return
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
                if not any_cancelled:
                    _safe_led('led5', led5_c, led5_o, 'grey')
                # Reset Dream.ini: enablelog=0, delay=0 — clean state for next start
                _write_dream_ini(False)
                try:
                    status_lbl.config(text='Ready.', fg='#555555')
                except Exception: pass
            self.root.after(500, _do_stop)

        def set_to_log_freq():
            """Set TRX to Log Frequency — reads TRX settings from config."""
            import subprocess, shutil
            freq = freq_var.get().strip()
            if not freq:
                status_lbl.config(
                    text='Please enter a Log Frequency first!', fg='#cc0000')
                return
            if not self.cfg.get('trx_enable', 0):
                status_lbl.config(
                    text='Transceiver Control not enabled in RX Config.',
                    fg='#cc6600')
                return
            trx_name = self.cfg.get('trx_name', '')
            port     = self.cfg.get('trx_port', '')
            baud     = self.cfg.get('trx_baud', '9600')
            model_id = self.cfg.get('trx_model_id', None)
            if not trx_name or not port or not model_id:
                status_lbl.config(
                    text='Please configure Receiver Settings in RX Config first!',
                    fg='#cc0000')
                return
            rigctl_path = self.cfg.get('trx_rigctl', '')
            rigctl = (rigctl_path if rigctl_path and os.path.isfile(rigctl_path)
                      else shutil.which('rigctl'))
            if not rigctl:
                status_lbl.config(
                    text='rigctl not found — check RX Config settings.',
                    fg='#cc0000')
                return
            try:
                freq_hz = int(float(freq) * 1000)
                # Build command based on connection mode from config
                conn_mode = self.cfg.get('trx_conn_mode', 'usb')
                if conn_mode == 'network':
                    net_host = self.cfg.get('trx_net_host', '127.0.0.1')
                    net_port = self.cfg.get('trx_net_port', '4532')
                    cmd_args = [rigctl, '-m', str(model_id),
                                '-r', f'{net_host}:{net_port}',
                                'F', str(freq_hz)]
                else:
                    cmd_args = [rigctl, '-m', str(model_id),
                                '-r', port, '-s', baud,
                                'F', str(freq_hz)]
                result = _subprocess_run(
                    cmd_args, capture_output=True, text=True, timeout=5,
                    encoding='utf-8', errors='replace')
                if result.returncode == 0:
                    _safe_led('led1', led1_c, led1_o, 'green')
                    _safe_led('led2', led2_c, led2_o, 'green')
                    status_lbl.config(
                        text=f'TRX set to {freq} kHz — OK', fg='#007700')
                else:
                    _safe_led('led1', led1_c, led1_o, 'red')
                    status_lbl.config(
                        text=f'TRX error: {result.stderr.strip()[:60]}',
                        fg='#cc0000')
            except subprocess.TimeoutExpired:
                _safe_led('led1', led1_c, led1_o, 'red')
                status_lbl.config(
                    text='TRX timeout — check port and baud rate',
                    fg='#cc0000')
            except Exception as ex:
                status_lbl.config(text=f'TRX error: {ex}', fg='#cc0000')

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
        tk.Entry(fq_row, textvariable=freq_var, font=('Arial',11),
                 width=8).pack(side=tk.LEFT)
        tk.Button(fq_row, text='Set', font=('Arial',10), width=4,
                  bg='#aaddff',
                  command=set_to_log_freq).pack(side=tk.LEFT, padx=(6,0))
        tk.Label(fq_row,
                 text='  Changes RX frequency — if remote control is configured',
                 bg=GUI_BG, font=('Arial',8), fg='#555555').pack(side=tk.LEFT)

        # ── Manual Start / Stop buttons ───────────────────────────────
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
        NUM_SLOTS = 3
        slot_vars = []
        slot_leds = []
        SEP_COL = 4   # vertical separator column index

        # Shared grid frame — header + data rows all in one frame
        grid_frame = tk.Frame(fs, bg=GUI_BG)
        grid_frame.pack(fill=tk.X, pady=(2,4))

        # Column minsizes — separator column (4) is narrow
        # Col: 0=#  1=Start-HH  2=:  3=Start-MM  4=SEP  5=Stop-HH  6=:  7=Stop-MM
        #      8=Freq  9=Log  10=AutoPlot  11=Status-LED
        _col_minsizes = [30, 40, 14, 40,  18,  40, 14, 40, 70, 40, 60, 40]
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

        for col, txt in [(8,'Freq kHz'), (9,'Log'), (10,'AutoPlot'), (11,'Status')]:
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
            tk.Checkbutton(grid_frame, variable=log_v,
                           bg=GUI_BG).grid(row=r, column=9, padx=8)

            # Col 10: AutoPlot checkbox
            ap_v = tk.IntVar(value=0)
            tk.Checkbutton(grid_frame, variable=ap_v,
                           bg=GUI_BG).grid(row=r, column=10, padx=8)

            # Col 11: Mini status LED
            led_c, led_o = make_mini_led(grid_frame)
            led_c.grid(row=r, column=11, padx=8)

            slot_vars.append({
                'sh': sh_v, 'sm': sm_v,
                'eh': eh_v, 'em': em_v,
                'freq': fq_v, 'log': log_v, 'autoplot': ap_v,
            })
            slot_leds.append((led_c, led_o))

        # ── Timer storage — restore from persistent state ────────────
        sched_timers = self._sched_timers   # reference, not copy!

        # ── Restore slot fields and LEDs from saved state ─────────────
        any_timer_active = False
        for i in range(3):
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
        # ── _refresh_status: live Ist-Zustand beim Öffnen ───────────
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
            dream_running = _is_dream_running()
            led3_col = 'green' if dream_running else 'grey'
            set_led(led3_c, led3_o, led3_col)
            self._sched_led_status['led3'] = led3_col

            # ── LED 4: Dream Log — Dream running + enablelog=1 ────────
            led4_col = 'grey'
            if dream_running:
                try:
                    import os as _os
                    _path = self.cfg.get('dream_path', '').strip()
                    if _path:
                        _ini = _os.path.join(
                            _os.path.dirname(_os.path.abspath(_path)),
                            'Dream.ini')
                        if _os.path.exists(_ini):
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
            any_active = False
            for i in range(3):
                pair   = self._sched_timers[i]
                t_s    = pair[0]   # start timer
                t_e    = pair[1]   # stop  timer
                ss     = self._sched_state[i]
                fields_filled = any([
                    ss['sh'], ss['sm'], ss['eh'], ss['em']])

                if t_s is not None and t_s.is_alive():
                    # Start timer still counting down
                    slot_col = 'yellow'
                    any_active = True
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

            # LED5: green > orange > blue/grey
            any_orange = any(
                self._sched_state[i].get('led') == 'orange'
                for i in range(3))
            any_blue = any(
                self._sched_state[i].get('led') == 'blue'
                for i in range(3))
            if any_active:
                led5_col = 'green'
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
                # Not waiting — clear countdown text immediately
                try:
                    if not ap_running:
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
                    if freq:
                        try:
                            import subprocess, shutil
                            mid  = self.cfg.get('trx_model_id', None)
                            port = self.cfg.get('trx_port', '')
                            baud = self.cfg.get('trx_baud', '9600')
                            rigctl_p = self.cfg.get('trx_rigctl', '')
                            rigctl = (rigctl_p if rigctl_p and
                                      os.path.isfile(rigctl_p)
                                      else shutil.which('rigctl'))
                            conn = self.cfg.get('trx_conn_mode', 'usb')
                            if rigctl and mid and self.cfg.get('trx_enable', 0):
                                fhz = int(float(freq) * 1000)
                                if conn == 'network':
                                    nh = self.cfg.get('trx_net_host','127.0.0.1')
                                    np_ = self.cfg.get('trx_net_port','4532')
                                    cmd_r = [rigctl,'-m',str(mid),
                                             '-r',f'{nh}:{np_}',
                                             'F',str(fhz)]
                                else:
                                    cmd_r = [rigctl,'-m',str(mid),
                                             '-r',port,'-s',baud,
                                             'F',str(fhz)]
                                result = _subprocess_run(cmd_r, timeout=5,
                                                        capture_output=True,
                                                        text=True,
                                                        encoding='utf-8',
                                                        errors='replace')
                                if result.returncode == 0:
                                    _safe_led('led1', led1_c, led1_o, 'green')
                                    _safe_led('led2', led2_c, led2_o, 'green')
                                else:
                                    _safe_led('led1', led1_c, led1_o, 'red')
                                    _safe_led('led2', led2_c, led2_o, 'red')
                        except Exception:
                            _safe_led('led1', led1_c, led1_o, 'red')
                            _safe_led('led2', led2_c, led2_o, 'red')
                    if use_log:
                        # Timer path: use slot frequency directly — independent
                        # of freq_var (manual field) and the RX-switch checkbox.
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
                        stop_dream()
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

        def accept_schedule():
            # Cancel any existing timers first
            for pair in sched_timers:
                for t in pair:
                    if t: t.cancel()
            for i in range(NUM_SLOTS):
                sched_timers[i] = [None, None]

            now = datetime.now()
            accepted   = 0
            prev_stop_dt = None   # stop_dt of the last FUTURE slot accepted

            for idx in range(NUM_SLOTS):
                sv = slot_vars[idx]
                sh_s = sv['sh'].get().strip()
                sm_s = sv['sm'].get().strip()
                eh_s = sv['eh'].get().strip()
                em_s = sv['em'].get().strip()

                # Skip completely empty slots — reset LED to grey
                if not (sh_s and sm_s and eh_s and em_s):
                    set_led(slot_leds[idx][0], slot_leds[idx][1], 'grey')
                    continue

                try:
                    sh = int(sh_s); sm = int(sm_s)
                    eh = int(eh_s); em = int(em_s)
                except ValueError:
                    status_lbl.config(
                        text=f'Slot {idx+1}: invalid time format',
                        fg='#cc0000')
                    return

                freq     = sv['freq'].get().strip()
                use_log  = bool(sv['log'].get())
                use_ap   = bool(sv['autoplot'].get())

                if use_log and not freq:
                    status_lbl.config(
                        text=f'Slot {idx+1}: frequency required for Log start!',
                        fg='#cc0000')
                    return

                # ── Build naive start/stop for today ──────────────────
                start_dt = now.replace(hour=sh, minute=sm,
                                       second=0, microsecond=0)
                stop_dt  = now.replace(hour=eh, minute=em,
                                       second=0, microsecond=0)

                # ── Midnight overflow — stop before start means +1 day ─
                # e.g. Start 23:50 / Stop 00:10 → stop_dt moves to tomorrow
                if stop_dt <= start_dt:
                    stop_dt += timedelta(days=1)

                # ── Detect already-elapsed slots ──────────────────────
                # Must come AFTER midnight correction so that e.g. 00:10
                # tomorrow is never mistaken for 00:10 today (past).
                if stop_dt <= now:
                    set_led(slot_leds[idx][0], slot_leds[idx][1], 'grey')
                    continue

                # ── Push start to future if needed ────────────────────
                # Start may be in the past (e.g. user re-accepts while
                # the slot is already running). Clamp to "now + 1s" so
                # the timer fires almost immediately.
                if start_dt <= now:
                    start_dt = now + timedelta(seconds=1)

                # ── Gap check — only between FUTURE slots ─────────────
                # prev_stop_dt is only set from slots that are actually
                # scheduled (future), never from elapsed ones.
                if prev_stop_dt is not None:
                    gap = (start_dt - prev_stop_dt).total_seconds()
                    if gap < 60:
                        status_lbl.config(
                            text=f'Slot {idx+1}: needs at least 1 min gap '
                                 f'after slot {idx}!',
                            fg='#cc0000')
                        return
                    # ── AutoPlot gap warning ───────────────────────────
                    # If both this slot and the previous slot have AutoPlot
                    # enabled, a gap of exactly 60s may be too tight because
                    # AutoPlot needs a moment to shut down cleanly.
                    # Show a clear warning so the user is informed.
                    prev_ap = bool(self._sched_state[idx-1].get('autoplot', 0)) \
                              if idx > 0 else False
                    if use_ap and prev_ap and gap < 120:
                        if not messagebox.askyesno(
                            'AutoPlot Gap Warning',
                            f'Slot {idx} and Slot {idx+1} both have AutoPlot enabled.\n\n'
                            f'The gap between them is only {int(gap)} seconds.\n\n'
                            f'Recommendation: allow at least 2 minutes between\n'
                            f'AutoPlot-enabled events so AutoPlot can shut down\n'
                            f'cleanly before the next event starts.\n\n'
                            f'Accept the schedule anyway?',
                            icon='warning'
                        ):
                            return

                # ── Schedule the timers ───────────────────────────────
                # Save AutoPlot flag to self — readable after dialog close.
                # For timer-started events the flag is set slot-by-slot
                # inside _make_slot_start, so we only need to initialise here.
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
                # Save slot state for dialog restore
                self._sched_state[idx] = {
                    'sh': sh_s, 'sm': sm_s,
                    'eh': eh_s, 'em': em_s,
                    'freq': freq, 'log': int(use_log),
                    'autoplot': int(use_ap), 'led': 'yellow'}

                set_led(slot_leds[idx][0], slot_leds[idx][1], 'yellow')
                prev_stop_dt = stop_dt
                accepted += 1

            if accepted == 0:
                status_lbl.config(text='No future slots found — nothing scheduled.',
                                  fg='#cc6600')
                _safe_led('led5', led5_c, led5_o, 'grey')
                return

            _safe_led('led5', led5_c, led5_o, 'yellow')
            status_lbl.config(text='', fg='#555555')

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
        tk.Button(bs, text='Accept Schedule', font=('Arial',10),
                  bg='#aaddff', width=16,
                  command=accept_schedule).pack(side=tk.LEFT, padx=8)
        tk.Button(bs, text='Clear All', font=('Arial',10), width=10,
                  command=clear_event).pack(side=tk.LEFT, padx=4)

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
Copyright © 2025  Andreas (Andy) [Author]
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


def main():
    root = tk.Tk()
    root.title(APP_TITLE)
    root.minsize(1000, 660)

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
