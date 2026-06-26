#### dlp - 

### drmlogplotter - rebuild - experimental

This rebuild is based on the original DRM Log Plotter.

Unfortunately, the source code for the original is unavailable.
Consequently, it was no longer possible to incorporate new ideas into the existing program.
Many ideas in the original were excellent.
Some of those ideas were not carried over into *dlp*.

About the program:
DRM Log Plotter reads and visualizes log files created by the free DRM (Digital Radio Mondiale) software decoder, DReaM.
It plots the following data from a DReaM log session:

Blue line   =  Decoded Audio (0 – 100%)
Red line    =  SNR — Signal-to-Noise Ratio (dB)
Green line  =  Doppler spread (Hz)
Ochre line  =  Delay spread (ms)

(see also the help text)

New ideas:
One new idea was the ability to launch the DReaM decoder software from within *dlp*— either manually or via a timer event. 
There is also a convenient option to enter the logging frequency; 
this is written to the *dream.ini* file before DReaM is started remotely.
The logging flag is also set based on the input and reset when DReaM stops.
The auto-plot function can be triggered manually or via a timer event.

Another new idea is the ability to connect the RX (transceiver) to *dlp* via Hamlib/RigCTL.
The Icom IC-7300 and IC-705 allow the receiver's IF output to be fed to the PC sound card via a USB cable.
This ensures DReaM receives the perfect signal. Timer events allow for convenient control of the transceiver, DReaM, and *dlp*.
The ability to connect an SDR radio is also an interesting feature; the software FLrig can serve as a bridge here if necessary.

Status LEDs were introduced to provide the user with an overview of whether all functions are operating correctly.

The code:
I am not a programmer.
This was an attempt to create code using nothing but AI.
I chose Python because the code is easy for many users to understand.
This code can also be compiled for all common operating systems.

#### Update 26.June 2026
Changes:
1) The AutoPlot logic for timer events has been revised. AutoPlot cannot be enabled if no log command has been entered.
2) The AutoPlot countdown for timer events has also been reduced to 20 seconds. This is the time DReaM requires for synchronization to the RX-Signal and start logging.
3) A new "Manage Dream Files" button opens the file explorer on Windows 11, Linux (Ubuntu/Mint), and macOS (the latter is untested).

### Quick Start:
Windows 10/11 – Nothing needs to be installed. Create a new directory under C:\, e.g., named `drmlogplotter`.
Copy the `.exe` file, `drmtransmittersites.txt`, and `drmlogplotter_help.txt` into this new directory.
##### Important for Windows 10/11: Run the .exe as administrator. Otherwise, the drmlogplotter cannot access the DReaM decoder software directory!
After launching `drmlogplotter-rebuild`, the `.json` file and the `Screenshots` and `Logfiles` folders will be created there.
The new folders are created upon the first use of the respective function.

Linux: 1) Use the AppImage and follow the instructions in the help text.
2) The .bin file can be copied into a new directory of your choice; the .bin file will then operate using that directory. 
Also copy the files drmtransmittersite.txt and drmlogplotter_help.txt into the same directory.
In principle, the process is the same as when running on Windows 10/11.
