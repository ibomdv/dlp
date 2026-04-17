
# start....

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import csv
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib
matplotlib.use("TkAgg")

# Definitionen

def new_file():
    text.delete("1.0", tk.END)

def open_file():
    file_path = filedialog.askopenfilename(
        filetypes=[("Textdateien", "*.txt"), ("Alle Dateien", "*.*")]
    )
    if file_path:
        with open(file_path, "r", encoding="utf-8") as file:
            content = file.read()
            text.delete("1.0", tk.END)
            text.insert(tk.END, content)

def save_file():
    file_path = filedialog.asksaveasfilename(
        defaultextension=".txt",
        filetypes=[("Textdateien", "*.txt"), ("Alle Dateien", "*.*")]
    )
    if file_path:
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(text.get("1.0", tk.END))

def show_about():
    messagebox.showinfo("Über", "Texteditor + CSV Plot Tool")


#CSV Read ?
    
    
    
    

# Plot Fragezeichen
def open_csv_plot():
    file_path = filedialog.askopenfilename(
        filetypes=[("CSV Dateien", "*.csv"), ("Alle Dateien", "*.*")]
    )
    if not file_path:
        return

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Start der echten CSV finden (Header-Zeile)


    start_index = None
    for i, line in enumerate(lines):
        if "FREQ/MODE/QAM PL:ABH" in line:
            start_index = i
            break
    if start_index is None:
        messagebox.showerror("Fehler", "CSV Struktur nicht erkannt")
        return

    
        # Beispiel: Spalten anpassen!
     # Datenzeilen parsen (Tab-getrennt)
    for line in lines[start_index + 1:]:  # +1 um Header zu überspringen
        line = line.strip()
        if not line:
            continue
        
        # Tab oder mehrere Leerzeichen als Trennzeichen
        parts = line.split()
        
        # Mindestens 11 Spalten erwartet
        if len(parts) < 11:
            continue
 

            # Spalten: 0=FREQ, 1=DATE, 2=TIME, 3=SNR, 4=SYNC, 5=FAC, 6=MSC, 
            #          7=AUDIO, 8=AUDIOOK, 9=DOPPLER, 10=DELAY
            snr.append(float(row[3].replace(",", ".")))
            audiook.append(float(row[8].replace(",", ".")))
            doppler.append(float(row[9].replace(",", ".")))
            delay.append(float(row[10].replace(",", ".")))
    
    snr = []
    audiook = []
    doppler = []
    delay = []
      
    
    # PLOT NEU ZEICHNEN
    ax.clear()
    # Styling wieder setzen (wichtig nach clear!)
    ax.set_facecolor("black")
    ax.set_title("CSV Auswertung", color="cyan")
    ax.set_ylabel("SNR (dB)", color="red")
    ax.tick_params(axis='y', colors='red')
    ax.grid(True, color='green')
    # Linien
    ax.plot(snr, color="red", label="SNR")
    ax.plot(audiook, color="green", label="AUDIOOK")
    ax.plot(doppler, color="yellow", label="DOPPLER")
    ax.plot(delay, color="cyan", label="DELAY")
    ax.legend()
    canvas.draw()

########################## Plotter Fenster und Zuweisung #######################

# Hauptfenster
root = tk.Tk()
root.title("Mini Editor + Plot")
root.geometry("700x500")

style = ttk.Style()
style.theme_use("default")

menu_bar = tk.Menu(root)

# Datei-Menü
file_menu = tk.Menu(menu_bar, tearoff=0)
file_menu.add_command(label="Neu", command=new_file)
file_menu.add_command(label="Öffnen", command=open_file)

################ 🔥 NEU ################### Nachfolgendes hat die KI eingebaut #################

file_menu.add_command(label="CSV öffnen + Plot", command=open_csv_plot)

file_menu.add_command(label="Speichern", command=save_file)
file_menu.add_separator()
file_menu.add_command(label="Beenden", command=root.destroy)

menu_bar.add_cascade(label="Datei", menu=file_menu)

# Help-Menü
help_menu = tk.Menu(menu_bar, tearoff=0)
help_menu.add_command(label="Über", command=show_about)

menu_bar.add_cascade(label="Help", menu=help_menu)

root.config(menu=menu_bar)

# Textfeld
frame = ttk.Frame(root)
frame.pack(fill="both", expand=True)

scrollbar = ttk.Scrollbar(frame)
scrollbar.pack(side="right", fill="y")

text = tk.Text(frame, wrap="word", yscrollcommand=scrollbar.set)
text.pack(fill="both", expand=True)

scrollbar.config(command=text.yview)

# ---- Plot Frame ----
plot_frame = ttk.Frame(root, borderwidth=2, relief="groove")
plot_frame.pack(fill="both", expand=True)

fig = Figure(figsize=(8, 4), dpi=100)
ax = fig.add_subplot(111)

# Hintergrund schwarz
fig.patch.set_facecolor("#2b2b2b")
ax.set_facecolor("black")

# ---- Achsen Styling ----
ax.set_title("RX = TEST - ANTENNA = TEST", color="cyan", fontsize=10)

# Linke Achse (SNR)
ax.set_ylabel("SNR (dB)", color="red")
ax.set_ylim(0, 45)
ax.tick_params(axis='y', colors='red')

# Untere Achse (Zeit)
ax.set_xlim(0, 15)
ax.set_xlabel("")

# t(1) ... t(15)
xticks = list(range(16))
xticklabels = ["t(s)"] + [f"t({i})" for i in range(1,15)] + ["t(e)"]
ax.set_xticks(xticks)
ax.set_xticklabels(xticklabels, color="black", fontsize=8)

# ---- GRID wie im Bild ----
ax.grid(True, which='major', color='green', linestyle='-', linewidth=0.5)
ax.minorticks_on()
ax.grid(True, which='minor', color='green', linestyle=':', linewidth=0.3)

# ---- rechte Achse (z.B. Hz) ----
ax2 = ax.twinx()
ax2.set_ylim(0.1, 1)
ax2.set_ylabel("Hz", color="green")
ax2.tick_params(axis='y', colors='green')

# ---- zweite rechte Achse (Frames oben rechts) ----
ax3 = ax.twinx()
ax3.spines["right"].set_position(("outward", 40))
ax3.set_ylim(0, 1500)
ax3.tick_params(axis='y', colors='blue')
ax3.set_ylabel("Frames", color="blue")

# ---- Canvas ----
canvas = FigureCanvasTkAgg(fig, master=plot_frame)
canvas.draw()
canvas.get_tk_widget().pack(fill="both", expand=True)

root.mainloop()
