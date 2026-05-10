"""
DRM Monitor - CSV Plot Tool
Nachbau der Dream-Software GUI mit Matplotlib-Einbettung in Tkinter
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import csv
from datetime import datetime
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np

# ── Farben & Stil ────────────────────────────────────────────────────────────
BG_DARK   = "#1a1a1a"
BG_PANEL  = "#2a2a2a"
BG_FRAME  = "#222222"
FG_WHITE  = "#e0e0e0"
FG_GRAY   = "#888888"
BORDER    = "#444444"
PLOT_BG   = "#000000"

COLOR_SNR     = "#ff3030"    # Rot
COLOR_AUDIO   = "#4080ff"    # Blau
COLOR_DOPPLER = "#30cc30"    # Grün
COLOR_DELAY   = "#cc8830"    # Ocker/Braun

# ── Globale Plot-Daten ───────────────────────────────────────────────────────
x_time    = []
y_snr     = []
y_audiook = []
y_doppler = []
y_delay   = []

# Aktuelle Log-Info (wird beim CSV-Laden gefüllt)
info = {
    "label":      "–",
    "frequency":  "–",
    "tx_loc":     "–",
    "date":       "–",
    "mode_bw":    "–",
    "bitrate":    "–",
    "service_ch": "–",
    "prot_level": "–",
    "drm_modes":  "–",
    "runtime":    "0 h 0 min",
    "snr_max":    "–",
    "snr_min":    "–",
    "snr_avg":    "–",
    "delay_max":  "–",
    "delay_min":  "–",
    "delay_avg":  "–",
    "dop_max":    "–",
    "dop_min":    "–",
    "dop_avg":    "–",
    "decoded_audio": "–",
    "fac_crc":    "–",
    "location":   "–",
    "latitude":   "–",
    "longitude":  "–",
    "distance":   "–",
    "azimuth":    "–",
    "software":   "Dream 2.2.1",
}

# ── Hilfsfunktion ────────────────────────────────────────────────────────────
def safe_strip(v):
    return "" if v is None else str(v).strip()

# ── Textfenster (sekundär) ───────────────────────────────────────────────────
text_window = None
text_widget = None

def show_text_window():
    global text_window, text_widget
    if text_window and tk.Toplevel.winfo_exists(text_window):
        text_window.lift()
        return
    text_window = tk.Toplevel(root)
    text_window.title("Log-Text")
    text_window.geometry("900x500")
    text_window.configure(bg=BG_DARK)
    f = ttk.Frame(text_window)
    f.pack(fill="both", expand=True)
    sb = ttk.Scrollbar(f)
    sb.pack(side="right", fill="y")
    text_widget = tk.Text(f, wrap="word", yscrollcommand=sb.set,
                          bg="#111", fg=FG_WHITE, insertbackground=FG_WHITE,
                          font=("Courier New", 9))
    text_widget.pack(fill="both", expand=True)
    sb.config(command=text_widget.yview)

# ── Info-Labels aktualisieren ────────────────────────────────────────────────
def update_info_labels():
    lbl_label.config(text=info["label"])
    lbl_freq.config(text=info["frequency"])
    lbl_txloc.config(text=info["tx_loc"])
    lbl_date.config(text=info["date"])
    lbl_mode.config(text=info["mode_bw"])
    lbl_bitrate.config(text=info["bitrate"])
    lbl_srvchan.config(text=info["service_ch"])
    lbl_prot.config(text=info["prot_level"])
    lbl_drm.config(text=info["drm_modes"])
    lbl_runtime.config(text=info["runtime"])
    lbl_snr_max.config(text=info["snr_max"])
    lbl_snr_min.config(text=info["snr_min"])
    lbl_snr_avg.config(text=info["snr_avg"])
    lbl_delay_max.config(text=info["delay_max"])
    lbl_delay_min.config(text=info["delay_min"])
    lbl_delay_avg.config(text=info["delay_avg"])
    lbl_dop_max.config(text=info["dop_max"])
    lbl_dop_min.config(text=info["dop_min"])
    lbl_dop_avg.config(text=info["dop_avg"])
    lbl_decoded.config(text=info["decoded_audio"])
    lbl_fac.config(text=info["fac_crc"])
    lbl_misc_loc.config(text=info["location"])
    lbl_misc_lat.config(text=info["latitude"])
    lbl_misc_lon.config(text=info["longitude"])
    lbl_misc_dist.config(text=info["distance"])
    lbl_misc_az.config(text=info["azimuth"])
    lbl_misc_sw.config(text=info["software"])

# ── Plot zeichnen ─────────────────────────────────────────────────────────────
def draw_plot():
    ax_snr.cla()
    ax_frames.cla()
    ax_doppler.cla()

    # Achsen-Grenzen
    ax_snr.set_ylim(0, 45)
    ax_frames.set_ylim(-200, 800)
    ax_doppler.set_ylim(0, 4)

    # Hintergrund
    ax_snr.set_facecolor(PLOT_BG)

    # Gitter: feine Punkte
    ax_snr.grid(True, which="both", linestyle=":", linewidth=0.5,
                color="#333333", alpha=0.8)
    ax_snr.minorticks_on()

    # Y-Achse links: SNR (dB) in Weiß + Delay (ms) in Ocker
    ax_snr.set_ylabel("SNR (dB)", color=FG_WHITE, fontsize=8)
    ax_snr.tick_params(axis="y", colors=FG_WHITE, labelsize=7)
    ax_snr.tick_params(axis="x", colors=FG_WHITE, labelsize=7)
    ax_snr.yaxis.set_major_locator(ticker.MultipleLocator(5))

    # Zweite Y-Achse links: Delay ms (0–10) in Ocker
    ax_delay = ax_snr.twinx()
    ax_delay.set_ylim(0, 45)   # gleiche Pixel-Höhe
    ax_delay.set_yticks([0, 2.22, 4.44, 6.67, 8.89, 11.11])   # 0–10 ms in SNR-Skala
    ax_delay.set_yticklabels(["0", "2", "4", "6", "8", "10"],
                              color=COLOR_DELAY, fontsize=7)
    ax_delay.tick_params(axis="y", colors=COLOR_DELAY, length=0)
    ax_delay.spines["right"].set_visible(False)
    ax_delay.spines["left"].set_position(("outward", 42))
    ax_delay.yaxis.set_label_position("left")
    ax_delay.yaxis.tick_left()
    ax_delay.set_ylabel("ms", color=COLOR_DELAY, fontsize=8)

    # Rechte Achse Frames (Blau) + Doppler Hz (Grün)
    ax_frames.set_ylabel("Frames", color=COLOR_AUDIO, fontsize=8)
    ax_frames.tick_params(axis="y", colors=COLOR_AUDIO, labelsize=7)
    ax_frames.yaxis.set_major_locator(ticker.MultipleLocator(200))
    ax_frames.spines["right"].set_color(COLOR_AUDIO)

    # Doppler-Skala rechts (zweite rechte Achse)
    ax_doppler.set_ylabel("Hz", color=COLOR_DOPPLER, fontsize=8)
    ax_doppler.tick_params(axis="y", colors=COLOR_DOPPLER, labelsize=7)
    ax_doppler.spines["right"].set_position(("outward", 50))
    ax_doppler.spines["right"].set_color(COLOR_DOPPLER)
    ax_doppler.set_yticks([0.1, 0.15, 0.22, 0.30, 0.40, 0.60, 1.0, 1.5, 2.0])
    ax_doppler.set_yticklabels(
        ["0.1","0.15","0.22","0.30","0.40","0.60","1.0","1.5","2.0"],
        color=COLOR_DOPPLER, fontsize=6)

    # Spine-Farben
    for spine in ax_snr.spines.values():
        spine.set_color(BORDER)

    # Gepunktete blaue Linie bei SNR=35
    if x_time:
        ax_snr.axhline(y=35, color=COLOR_AUDIO, linestyle=":",
                       linewidth=1.2, alpha=0.8)

    # Daten plotten (wenn vorhanden)
    if x_time:
        # Senkrechte grüne gestrichelte Linien (Takt: alle ~60s)
        t0 = x_time[0]
        t_end = x_time[-1]
        total_sec = (t_end - t0).total_seconds()
        interval = max(60, int(total_sec / 12))
        t_cur = t0
        while t_cur <= t_end:
            ax_snr.axvline(x=t_cur, color=COLOR_DOPPLER, linestyle="--",
                           linewidth=0.7, alpha=0.6)
            from datetime import timedelta
            t_cur = datetime(t_cur.year, t_cur.month, t_cur.day,
                             t_cur.hour, t_cur.minute, t_cur.second) \
                    if hasattr(t_cur, 'year') else t_cur
            t_cur = t_cur.__class__(
                t_cur.year if hasattr(t_cur,'year') else 1900,
                t_cur.month if hasattr(t_cur,'month') else 1,
                t_cur.day if hasattr(t_cur,'day') else 1,
                t_cur.hour, t_cur.minute, t_cur.second + interval
            ) if False else (t_cur + timedelta(seconds=interval))

        ax_snr.plot(x_time, y_snr,    color=COLOR_SNR,     linewidth=1.2, label="SNR")
        ax_snr.plot(x_time, y_audiook,color=COLOR_AUDIO,   linewidth=1.2, label="Audio")
        ax_frames.plot(x_time, y_audiook, color=COLOR_AUDIO, linewidth=0, alpha=0)  # sync x
        ax_doppler.plot(x_time, y_doppler, color=COLOR_DOPPLER, linewidth=1.0, label="Doppler")
        ax_snr.plot(x_time, [d * 4.5 for d in y_delay],
                   color=COLOR_DELAY, linewidth=1.0, label="Delay")  # skaliert auf SNR-Achse
        ax_delay.plot(x_time, [d * 4.5 for d in y_delay],
                      color=COLOR_DELAY, linewidth=0, alpha=0)

        # X-Achse Zeitformat
        import matplotlib.dates as mdates
        ax_snr.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        fig.autofmt_xdate(rotation=0, ha="center")

    # Titel
    ax_snr.set_title(
        f"RX  –  {info.get('label','–')}",
        color=FG_WHITE, fontsize=9, pad=4
    )

    canvas.draw()

# ── CSV öffnen + plotten ─────────────────────────────────────────────────────
def open_csv_plot():
    global x_time, y_snr, y_audiook, y_doppler, y_delay

    file_path = filedialog.askopenfilename(
        title="DreamLonLog.csv auswählen",
        initialfile="DreamLonLog.csv",
        filetypes=[("CSV Dateien", "*.csv"), ("Alle Dateien", "*.*")]
    )
    if not file_path:
        return

    x_time, y_snr, y_audiook, y_doppler, y_delay = [], [], [], [], []
    freq_mode_info = ""
    date_info = ""

    try:
        raw_text = ""
        with open(file_path, "r", encoding="utf-8") as f:
            raw_text = f.read()

        if text_widget:
            text_widget.delete("1.0", tk.END)
            text_widget.insert(tk.END, raw_text)

        with open(file_path, "r", encoding="utf-8", newline="") as csvfile:
            reader = csv.DictReader(csvfile, delimiter=",", skipinitialspace=True)
            if reader.fieldnames is None:
                messagebox.showerror("Fehler", "Kein Header in der CSV-Datei.")
                return
            actual_fields = [f.strip() for f in reader.fieldnames]

            expected = ["FREQ/MODE/QAM PL:ABH","DATE","TIME","SNR",
                        "AUDIOOK","DOPPLER","DELAY"]
            for ef in expected:
                if ef not in actual_fields:
                    messagebox.showerror("Header-Fehler",
                        f"Spalte nicht gefunden: {ef}\n\nGefunden: {actual_fields}")
                    return

            for row in reader:
                nr = {k.strip(): v for k, v in row.items()}
                freq_val   = safe_strip(nr.get("FREQ/MODE/QAM PL:ABH"))
                date_val   = safe_strip(nr.get("DATE"))
                time_val   = safe_strip(nr.get("TIME"))
                snr_val    = safe_strip(nr.get("SNR"))
                audiook_val= safe_strip(nr.get("AUDIOOK"))
                doppler_val= safe_strip(nr.get("DOPPLER"))
                delay_val  = safe_strip(nr.get("DELAY"))

                if not freq_mode_info and freq_val:
                    freq_mode_info = freq_val
                if not date_info and date_val:
                    date_info = date_val

                if not all([time_val, snr_val, audiook_val, doppler_val, delay_val]):
                    continue
                try:
                    t = datetime.strptime(time_val, "%H:%M:%S.%f")
                    snr     = float(snr_val)
                    audiook = float(audiook_val)
                    doppler = float(doppler_val)
                    delay   = float(delay_val)
                    x_time.append(t)
                    y_snr.append(snr)
                    y_audiook.append(audiook)
                    y_doppler.append(doppler)
                    y_delay.append(delay)
                except ValueError:
                    continue

        if not x_time:
            messagebox.showwarning("Keine Daten",
                "Keine gültigen Plot-Daten in der CSV-Datei.")
            return

        # Info befüllen
        parts = freq_mode_info.split("/") if freq_mode_info else []
        info["frequency"]  = (parts[0].strip() + " kHz") if parts else "–"
        info["mode_bw"]    = "/".join(parts[1:]).strip() if len(parts) > 1 else "–"
        info["date"]       = date_info or "–"
        info["label"]      = freq_mode_info or "–"
        # Statistik
        if y_snr:
            info["snr_max"] = f"{max(y_snr):.2f} dB"
            info["snr_min"] = f"{min(y_snr):.2f} dB"
            info["snr_avg"] = f"{sum(y_snr)/len(y_snr):.2f} dB"
        if y_delay:
            info["delay_max"] = f"{max(y_delay):.2f} ms"
            info["delay_min"] = f"{min(y_delay):.2f} ms"
            info["delay_avg"] = f"{sum(y_delay)/len(y_delay):.2f} ms"
        if y_doppler:
            info["dop_max"] = f"{max(y_doppler):.2f} Hz"
            info["dop_min"] = f"{min(y_doppler):.2f} Hz"
            info["dop_avg"] = f"{sum(y_doppler)/len(y_doppler):.2f} Hz"
        if y_audiook:
            pct = sum(1 for v in y_audiook if v > 0) / len(y_audiook) * 100
            info["decoded_audio"] = f"{pct:.2f} %"
        # Runtime
        if len(x_time) >= 2:
            delta = x_time[-1] - x_time[0]
            mins  = int(delta.total_seconds() // 60)
            info["runtime"] = f"{mins//60} h {mins%60} min"

        update_info_labels()
        draw_plot()

    except FileNotFoundError:
        messagebox.showerror("Dateifehler", "Datei nicht gefunden.")
    except Exception as e:
        messagebox.showerror("Fehler", f"Fehler:\n{e}")

# ── Menü-Aktionen ─────────────────────────────────────────────────────────────
def new_file():
    global x_time, y_snr, y_audiook, y_doppler, y_delay
    x_time, y_snr, y_audiook, y_doppler, y_delay = [], [], [], [], []
    draw_plot()

def open_txt():
    fp = filedialog.askopenfilename(
        filetypes=[("Textdateien","*.txt"),("Alle Dateien","*.*")])
    if fp:
        show_text_window()
        with open(fp,"r",encoding="utf-8") as f:
            text_widget.delete("1.0",tk.END)
            text_widget.insert(tk.END, f.read())

def save_file():
    if not text_widget:
        return
    fp = filedialog.asksaveasfilename(
        defaultextension=".txt",
        filetypes=[("Textdateien","*.txt"),("Alle Dateien","*.*")])
    if fp:
        with open(fp,"w",encoding="utf-8") as f:
            f.write(text_widget.get("1.0",tk.END))

def show_about():
    messagebox.showinfo("Über","DRM Monitor\nCSV Plot Tool\n© 2025")

def load_log():
    messagebox.showinfo("Load Log","Funktion folgt …")

def save_log():
    messagebox.showinfo("Save Log","Funktion folgt …")

def comp_log():
    messagebox.showinfo("Comp. Log","Funktion folgt …")

def forum():
    messagebox.showinfo("Forum","Funktion folgt …")

def screenshot():
    messagebox.showinfo("Screenshot","Funktion folgt …")

def show_logs():
    show_text_window()

def tx_sites():
    messagebox.showinfo("TX Sites","Funktion folgt …")

def auto_plot_toggle():
    messagebox.showinfo("Auto Plot","Funktion folgt …")

# ── Hauptfenster ──────────────────────────────────────────────────────────────
root = tk.Tk()
root.title("DRM Monitor – CSV Plot Tool")
root.geometry("1100x780")
root.configure(bg=BG_DARK)
root.minsize(900, 650)

style = ttk.Style()
style.theme_use("default")
style.configure("TFrame",        background=BG_DARK)
style.configure("Panel.TFrame",  background=BG_PANEL,  relief="flat")
style.configure("TLabel",        background=BG_PANEL,  foreground=FG_WHITE, font=("Courier New",8))
style.configure("Title.TLabel",  background=BG_PANEL,  foreground=FG_GRAY,  font=("Courier New",8))
style.configure("Value.TLabel",  background=BG_PANEL,  foreground=FG_WHITE, font=("Courier New",8,"bold"))
style.configure("Red.TLabel",    background=BG_PANEL,  foreground=COLOR_SNR,     font=("Courier New",8,"bold"))
style.configure("Blue.TLabel",   background=BG_PANEL,  foreground=COLOR_AUDIO,   font=("Courier New",8,"bold"))
style.configure("Green.TLabel",  background=BG_PANEL,  foreground=COLOR_DOPPLER, font=("Courier New",8,"bold"))
style.configure("Ocker.TLabel",  background=BG_PANEL,  foreground=COLOR_DELAY,   font=("Courier New",8,"bold"))
style.configure("Head.TLabel",   background=BG_PANEL,  foreground="#ffffff",     font=("Courier New",9,"bold"))
style.configure("TButton",       background="#3a3a3a",  foreground=FG_WHITE,
                                 font=("Courier New",8), relief="raised", padding=2)
style.map("TButton", background=[("active","#505050")])
style.configure("TCheckbutton",  background=BG_PANEL,  foreground=FG_WHITE, font=("Courier New",8))

# ── Menüleiste ────────────────────────────────────────────────────────────────
menu_bar = tk.Menu(root, bg=BG_PANEL, fg=FG_WHITE,
                   activebackground="#444", activeforeground="white")

file_menu = tk.Menu(menu_bar, tearoff=0, bg=BG_PANEL, fg=FG_WHITE,
                    activebackground="#555", activeforeground="white")
file_menu.add_command(label="Neu",              command=new_file)
file_menu.add_command(label="Öffnen (TXT)",     command=open_txt)
file_menu.add_command(label="CSV öffnen + Plot",command=open_csv_plot)
file_menu.add_command(label="Speichern",        command=save_file)
file_menu.add_separator()
file_menu.add_command(label="Beenden",          command=root.destroy)
menu_bar.add_cascade(label="Datei", menu=file_menu)

view_menu = tk.Menu(menu_bar, tearoff=0, bg=BG_PANEL, fg=FG_WHITE,
                    activebackground="#555", activeforeground="white")
view_menu.add_command(label="Log-Text anzeigen", command=show_text_window)
menu_bar.add_cascade(label="Ansicht", menu=view_menu)

help_menu = tk.Menu(menu_bar, tearoff=0, bg=BG_PANEL, fg=FG_WHITE,
                    activebackground="#555", activeforeground="white")
help_menu.add_command(label="Über", command=show_about)
menu_bar.add_cascade(label="Help", menu=help_menu)

root.config(menu=menu_bar)

# ── Haupt-Layout ──────────────────────────────────────────────────────────────
# Zeile 0: Top-Info-Leiste
# Zeile 1: Plot
# Zeile 2: Bottom-Leiste

root.rowconfigure(0, weight=0)
root.rowconfigure(1, weight=1)
root.rowconfigure(2, weight=0)
root.columnconfigure(0, weight=1)

# ──────────────────────────────────────────────────────────────────────────────
# TOP ROW  (Main Log  |  Statistik  |  DRM Modes Used)
# ──────────────────────────────────────────────────────────────────────────────
top_row = ttk.Frame(root, style="Panel.TFrame")
top_row.grid(row=0, column=0, sticky="ew", padx=2, pady=(2,0))
top_row.columnconfigure(0, weight=3)
top_row.columnconfigure(1, weight=4)
top_row.columnconfigure(2, weight=2)

def make_frame(parent, title, col, padx=(2,2), pady=2):
    outer = tk.Frame(parent, bg=BORDER)
    outer.grid(row=0, column=col, sticky="nsew", padx=padx, pady=pady)
    inner = tk.Frame(outer, bg=BG_PANEL)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    hdr = tk.Label(inner, text=title, bg=BG_FRAME, fg=FG_GRAY,
                   font=("Courier New",8,"bold"), anchor="w", padx=4)
    hdr.pack(fill="x")
    return inner

def row_kv(parent, key, val_text="–", val_style="Value.TLabel", r=0):
    """Gibt das Value-Label zurück, damit man es später aktualisieren kann."""
    f = tk.Frame(parent, bg=BG_PANEL)
    f.pack(fill="x", padx=4, pady=0)
    tk.Label(f, text=key, bg=BG_PANEL, fg=FG_GRAY,
             font=("Courier New",8), width=16, anchor="w").pack(side="left")
    lbl = tk.Label(f, text=val_text, bg=BG_PANEL, fg=FG_WHITE,
                   font=("Courier New",8,"bold"), anchor="w")
    lbl.pack(side="left")
    return lbl

# ── Main Log ──────────────────────────────────────────────────────────────────
fr_main = make_frame(top_row, "Main Log", 0)
lbl_label    = row_kv(fr_main, "Label:")
lbl_freq     = row_kv(fr_main, "Frequency:")
lbl_txloc    = row_kv(fr_main, "TX Location:")
lbl_date     = row_kv(fr_main, "Date:")
lbl_mode     = row_kv(fr_main, "Mode / BW:")
lbl_bitrate  = row_kv(fr_main, "Bitrate:")
lbl_srvchan  = row_kv(fr_main, "Service Channel:")
lbl_prot     = row_kv(fr_main, "Protection Level:")

# ── Statistik ─────────────────────────────────────────────────────────────────
fr_stat = make_frame(top_row, "Statistics", 1)

def stat_row(parent, key, lbl_max, lbl_min, lbl_avg, color):
    f = tk.Frame(parent, bg=BG_PANEL)
    f.pack(fill="x", padx=4, pady=0)
    tk.Label(f, text=key, bg=BG_PANEL, fg=color,
             font=("Courier New",8), width=10, anchor="w").pack(side="left")
    for tag, lbl_ref in [("Max:", lbl_max), ("Min:", lbl_min), ("Avg:", lbl_avg)]:
        tk.Label(f, text=tag, bg=BG_PANEL, fg=FG_GRAY,
                 font=("Courier New",8)).pack(side="left", padx=(6,0))
        lbl_ref.append(
            tk.Label(f, text="–", bg=BG_PANEL, fg=color,
                     font=("Courier New",8,"bold"), width=10, anchor="w")
        )
        lbl_ref[-1].pack(side="left")

# Decoded Audio + FAC CRC
f_dec = tk.Frame(fr_stat, bg=BG_PANEL)
f_dec.pack(fill="x", padx=4, pady=1)
tk.Label(f_dec, text="Decoded Audio:", bg=BG_PANEL, fg=FG_GRAY,
         font=("Courier New",8)).pack(side="left")
lbl_decoded = tk.Label(f_dec, text="–", bg=BG_PANEL, fg=COLOR_AUDIO,
                        font=("Courier New",8,"bold"))
lbl_decoded.pack(side="left", padx=8)
tk.Label(f_dec, text="FAC CRC:", bg=BG_PANEL, fg=FG_GRAY,
         font=("Courier New",8)).pack(side="left")
lbl_fac = tk.Label(f_dec, text="–", bg=BG_PANEL, fg=COLOR_AUDIO,
                    font=("Courier New",8,"bold"))
lbl_fac.pack(side="left", padx=4)

# SNR / Delay / Doppler Zeilen
snr_max_l, snr_min_l, snr_avg_l = [], [], []
del_max_l, del_min_l, del_avg_l = [], [], []
dop_max_l, dop_min_l, dop_avg_l = [], [], []
stat_row(fr_stat, "SNR (dB)",  snr_max_l, snr_min_l, snr_avg_l, COLOR_SNR)
stat_row(fr_stat, "Delay (ms)",del_max_l, del_min_l, del_avg_l, COLOR_DELAY)
stat_row(fr_stat, "Doppler",   dop_max_l, dop_min_l, dop_avg_l, COLOR_DOPPLER)

lbl_snr_max  = snr_max_l[0]; lbl_snr_min  = snr_min_l[0]; lbl_snr_avg  = snr_avg_l[0]
lbl_delay_max= del_max_l[0]; lbl_delay_min= del_min_l[0]; lbl_delay_avg= del_avg_l[0]
lbl_dop_max  = dop_max_l[0]; lbl_dop_min  = dop_min_l[0]; lbl_dop_avg  = dop_avg_l[0]

# ── DRM Modes Used ────────────────────────────────────────────────────────────
fr_drm = make_frame(top_row, "DRM Modes Used", 2)
lbl_drm = row_kv(fr_drm, "Mode:")
lbl_runtime = row_kv(fr_drm, "Runtime:")

# ──────────────────────────────────────────────────────────────────────────────
# PLOT-BEREICH
# ──────────────────────────────────────────────────────────────────────────────
plot_outer = tk.Frame(root, bg=BORDER)
plot_outer.grid(row=1, column=0, sticky="nsew", padx=2, pady=2)
plot_inner = tk.Frame(plot_outer, bg=BG_DARK)
plot_inner.pack(fill="both", expand=True, padx=1, pady=1)

fig = Figure(figsize=(12, 4.5), facecolor=BG_DARK)
fig.subplots_adjust(left=0.10, right=0.88, top=0.92, bottom=0.12)

ax_snr     = fig.add_subplot(111)
ax_frames  = ax_snr.twinx()
ax_doppler = ax_snr.twinx()

canvas = FigureCanvasTkAgg(fig, master=plot_inner)
canvas.get_tk_widget().pack(fill="both", expand=True)

# ──────────────────────────────────────────────────────────────────────────────
# BOTTOM ROW  (Miscellaneous | Auto Plot | TX Transmitter | Select Main Log | Update Files)
# ──────────────────────────────────────────────────────────────────────────────
bot_row = ttk.Frame(root, style="Panel.TFrame")
bot_row.grid(row=2, column=0, sticky="ew", padx=2, pady=(0,2))
for c in range(5):
    bot_row.columnconfigure(c, weight=1 if c < 4 else 0)

# ── Miscellaneous ─────────────────────────────────────────────────────────────
fr_misc = make_frame(bot_row, "Miscellaneous", 0)
lbl_misc_loc  = row_kv(fr_misc, "Location:")
lbl_misc_lat  = row_kv(fr_misc, "Latitude:")
lbl_misc_lon  = row_kv(fr_misc, "Longitude:")
lbl_misc_dist = row_kv(fr_misc, "Distance to TX:")
lbl_misc_az   = row_kv(fr_misc, "Az. to/from TX:")
lbl_misc_sw   = row_kv(fr_misc, "Software:", info["software"])

# ── Auto Plot ─────────────────────────────────────────────────────────────────
fr_auto = make_frame(bot_row, "Auto Plot", 1)
f_ap = tk.Frame(fr_auto, bg=BG_PANEL)
f_ap.pack(fill="x", padx=4, pady=2)
row_kv(fr_auto, "Interval:")
row_kv(fr_auto, "Refresh:")
row_kv(fr_auto, "Scroll:")
ap_var = tk.BooleanVar()
f_apb = tk.Frame(fr_auto, bg=BG_PANEL)
f_apb.pack(fill="x", padx=4, pady=2)
tk.Checkbutton(f_apb, text="Auto Plot", variable=ap_var, bg=BG_PANEL,
               fg=FG_WHITE, selectcolor=BG_DARK, activebackground=BG_PANEL,
               font=("Courier New",8), command=auto_plot_toggle).pack(side="left")

# ── Transmitter Site ──────────────────────────────────────────────────────────
fr_tx = make_frame(bot_row, "Transmitter Site", 2)
tx_listbox = tk.Listbox(fr_tx, bg="#111", fg=FG_WHITE,
                         font=("Courier New",8), height=4,
                         selectbackground="#445566", bd=0, highlightthickness=0)
tx_listbox.pack(fill="both", expand=True, padx=4, pady=2)
tx_listbox.insert(tk.END, "– keine Daten –")
ttk.Button(fr_tx, text="TX Sites", command=tx_sites).pack(pady=2)

# ── Select Main Log ───────────────────────────────────────────────────────────
fr_sel = make_frame(bot_row, "Select Main Log", 3)
sel_listbox = tk.Listbox(fr_sel, bg="#111", fg=COLOR_AUDIO,
                          font=("Courier New",8), height=4,
                          selectbackground="#334455", bd=0, highlightthickness=0)
sel_listbox.pack(fill="both", expand=True, padx=4, pady=2)
sel_listbox.insert(tk.END, "– keine Daten –")

f_sel_btns = tk.Frame(fr_sel, bg=BG_PANEL)
f_sel_btns.pack(fill="x", padx=4, pady=2)
ttk.Button(f_sel_btns, text="Forum",      command=forum,      width=8).pack(side="left", padx=1)
ttk.Button(f_sel_btns, text="Screenshot", command=screenshot,  width=10).pack(side="left", padx=1)
ttk.Button(f_sel_btns, text="Show Logs",  command=show_logs,   width=9).pack(side="left", padx=1)

# ── Update Files ──────────────────────────────────────────────────────────────
fr_upd = make_frame(bot_row, "Update Files", 4)
row_kv(fr_upd, "Logs:")
row_kv(fr_upd, "Size:")

f_upd_btns = tk.Frame(fr_upd, bg=BG_PANEL)
f_upd_btns.pack(fill="x", padx=4, pady=2)
ttk.Button(f_upd_btns, text="Load Log",  command=load_log, width=9).pack(pady=1, fill="x")
ttk.Button(f_upd_btns, text="Save Log",  command=save_log, width=9).pack(pady=1, fill="x")
ttk.Button(f_upd_btns, text="Main Log",  width=9).pack(pady=1, fill="x")
ttk.Button(f_upd_btns, text="Comp. Log", command=comp_log, width=9).pack(pady=1, fill="x")
ttk.Button(f_upd_btns, text="Update",    command=open_csv_plot, width=9).pack(pady=1, fill="x")

# ── Initialer Plot ────────────────────────────────────────────────────────────
draw_plot()
root.mainloop()
