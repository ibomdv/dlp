import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import csv
import matplotlib.pyplot as plt
#from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
#from matplotlib.figure import Figure
#import pandas as pd


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

# 🔥 NEU: CSV laden + Plot
def open_csv_plot():
    file_path = filedialog.askopenfilename(
        filetypes=[("CSV Dateien", "*.csv"), ("Alle Dateien", "*.*")]
    )

    if not file_path:
        return

    snr = []
    audiook = []
    doppler = []
    delay = []



    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()





    # Start der echten CSV finden
    start_index = None
    for i, line in enumerate(lines):
        if "FREQ/MODE/QAM" in line:
            start_index = i
            break

    if start_index is None:
        messagebox.showerror("Fehler", "CSV Struktur nicht erkannt")
        return

    reader = csv.DictReader(lines[start_index:])

    for row in reader:
        try:
            snr.append(float(row["SNR"]))
            audiook.append(float(row["AUDIOOK"]))
            doppler.append(float(row["DOPPLER"]))
            delay.append(float(row["DELAY"]))
        except:
            continue

    # Plot anzeigen
    plt.figure("CSV Plot")

    plt.plot(snr, label="SNR")
    plt.plot(audiook, label="AUDIOOK")
    plt.plot(doppler, label="DOPPLER")
    plt.plot(delay, label="DELAY")

    plt.title("CSV Auswertung")
    plt.xlabel("Samples")
    plt.ylabel("Werte")
    plt.legend()
    plt.grid()



    plt.show()

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

# 🔥 NEU
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


root.mainloop()




