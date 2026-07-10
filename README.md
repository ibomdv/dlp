### drmlogplotter - rebuild - experimental (v.0.99c)


This rebuild is based on the original DRM Log Plotter.

<img width="993" height="618" alt="Original_ DRMLogPlotter " src="https://github.com/user-attachments/assets/a610350e-d9df-481b-a0e2-c12e9e471306" />


Unfortunately, the source code for the original is unavailable.
Consequently, it was no longer possible to incorporate new ideas into the existing program.
Many ideas in the original were excellent.
Some of those ideas were not carried over into *dlp*.

#### About the program:

DRM Log Plotter (old and the new rebuild-experimental) reads and visualizes log files created by the free DRM (Digital Radio Mondiale) software decoder, DReaM.
It plots the following data from a DReaM log session:

Blue line   =  Decoded Audio (0 – 100%)
Red line    =  SNR — Signal-to-Noise Ratio (dB)
Green line  =  Doppler spread (Hz)
Ochre line  =  Delay spread (ms)


<img width="1267" height="744" alt="DRMLogPlotter-experimental" src="https://github.com/user-attachments/assets/5445cd2b-ddfd-4002-ab58-a00f57dd9e57" />


##### New ideas:
One new idea was the ability to launch the DReaM decoder software from within *dlp*— either manually or via a timer event. 
There is also a convenient option to enter the logging frequency; 
this is written to the *dream.ini* file before DReaM is started remotely.
The logging flag is also set based on the input and reset when DReaM stops.
The auto-plot function can be triggered manually or via a timer event.


<img width="649" height="521" alt="Dream-Start Schedule - Window" src="https://github.com/user-attachments/assets/7235b32b-b752-4c6e-934c-5a03296daadf" />



Another new idea is the ability to connect the RX (transceiver) to *dlp* via Hamlib/RigCTL.
The Icom IC-7300 and IC-705 allow the receiver's IF output to be fed to the PC sound card via a USB cable.
This ensures DReaM receives the perfect signal. Timer events allow for convenient control of the transceiver, DReaM, and *dlp*.
The ability to connect an SDR radio is also an interesting feature; the software FLrig can serve as a bridge here if necessary.

Status LEDs were introduced to provide the user with an overview of whether all functions are operating correctly.


<img width="758" height="709" alt="Dream and Receiver Configuration" src="https://github.com/user-attachments/assets/9d2233ea-61d1-4529-a47f-da4dadbba1f5" />



#### Special to this Version ( 07.July 2026 )

The next idea was to incorporate information into the analysis that isn't directly available in the DReaM decoder software's logs—specifically, details regarding the audio codec, audio mode, and protection level.

Modifying the original DReaM code (C++) to extract this information directly from the program is highly challenging, even with AI assistance.
In this case, it was impossible.

However, the AI ​​came up with a different idea—one that takes a bit of lateral thinking:

Capture the missing information from the DReaM station label on the PC screen and save it as a new, additional .json file in the DReaM folder!

<img width="504" height="293" alt="DReaM-Label-Information" src="https://github.com/user-attachments/assets/87201b2e-45d1-4ac7-8fc3-22b71f33bbe4" />

The rebuilt DRMLogPlotter automatically detects both the existing and the new log files and displays the information in the main GUI.
In the latest version, this works very well across Python, Windows 11, and Linux (Ubuntu/Linux Mint).

<img width="433" height="167" alt="Main Log with Audio Codec" src="https://github.com/user-attachments/assets/6bd1ee1e-7e0a-413f-88ce-f039ca1f4bc6" />


##### The code:

I am not a programmer.
This was an attempt to create code using nothing but AI.
I chose Python because the code is easy for many users to understand.
This code can also be compiled for all common operating systems.

#### Update from 07. July 2026
This update brings improvements, fixes, and new features!

The most significant new feature is as follows: When you launch the DReaM decoder software via `drmlogplotter_v.0.99c`,
a new function comes into play. This function reads the DReaM label from the PC screen 30 seconds
after startup and adds the missing audio code information to the DReaM log.
In the process, a new file—`DreamAudio.json`—is written to the DReaM folder. `drmlogplotter_v.0.99c`
then reads this new file and displays the information within the "Main Log" section
of the main GUI.

#### Updates:

- RX/TX Distance and AZ Calculation -
Should now display the same result as the original `drmlogplotter`.

- Main GUI -> LED 3 -
An additional LED has been added to the main GUI to provide a visual indicator for DReaM logs.

- Main GUI -> DReaM Stop Button -
A new button has been added to the "Update Files" section, allowing the user to stop
DReaM Remote quickly, easily, and correctly via `drmlogplotter`. This function ensures
that various settings in `Dream.ini` are correctly reset.

- Main GUI -> Main Log Section -
Result displays for Audio Code / Prot. Level and Audio Mode have been added.

- Main GUI -> DRM Mode Used Section -
DReaM log glitches should no longer generate phantom modes.

- Main GUI -> Select Main Log - 
The tabular display of logs in DReaM is now better organized.

- Main GUI -> AutoPlot - 
The minimum interval time is now 5 seconds.

- Main GUI -> AutoPlot -
If you run AutoPlot (manually or via a timer event) and Dream Log stops correctly via drmlogplotter, then AutoPlot checks for 15 seconds longer to see if a Dream Log is still running. This was exactly how it worked in the original version.

- Main GUI -> Line Plot - 
The "Delay" line is now finer and less bright, resulting in a more balanced visual appearance.

- Main GUI -> Line Plot - 
The "Doppler" line is now slightly brighter.

- Main GUI –> Line Plot
The priority for the plotting process is now: 1) SNR, 2) Audio, 3) Doppler, 4) Delay.

- "Basic Setup Parameters" Dialog ->
The window layout has been improved, and "Set" buttons have been added to make it more intuitive for the user.

- "Dream and Receiver Configuration" Dialog ->
Input handling for the paths required to access Dream remotely via drmlogplotter has been optimized.
This input method works equally well on Windows 11, Ubuntu, and Linux Mint. Also new "Set" button has been implemented.

- Help Text File ->
The help text has been expanded and the sections reorganized for better clarity.

- drmtransmittersites.txt -> 
You can use your existing transmitter sites file from the original drmlogplotter with the new dlp-experimental version as well.

- Python ->
A new third file has been created to support the program's workflow in Python.
Therefore, all three files must be placed in the same directory.

- Linux binaries (startup issues) ->
The compilation process has been optimized; consequently, `DreamLogPlotter.bin` and `DreamAudio.bin` should now be able to run from the same directory on Linux.

- Windows 11 -> 
There are now two `.exe` files that must be placed together in the same directory.

- Python/Linux/Windows 11 ->
Additionally, place the files `drmtransmittersites.txt` and `drmlogplotter_help.txt` in this same directory.

- AppImage ->
The AppImage contains all components. You can find the "Screenshot" and "Logs" folders, as well as `drmplotter_cfg.json`, at
`/home/pc/.local/share/drmlogplotter`. 
In your file manager, go to View -> "Show Hidden Files" click yes to locate the `.local` folder within your "pc" directory.

#### Quick Start (update 07.July 2026):

#### Windows 10/11 –>

No installation is required. Create a new directory under C:\, e.g., named `drmlogplotter`.
Copy both `.exe` files, as well as `drmtransmittersites.txt` and `drmlogplotter_help.txt`, into this new directory.
##### Important for Windows 10/11: Run the `drm_log_plotter.exe` file as an administrator. Otherwise, `drmlogplotter` cannot access the DReaM decoder software directory!
After launching `drmlogplotter`, the `.json` file and the `Screenshots` and `Logfiles` folders will be created there.
The new folders are created when the respective function is used for the first time.

#### Linux 

##### AppImage:
1) Use the AppImage and follow the instructions in the help text.
You can find the "Screenshot" and "Logs" folders, as well as `drmplotter_cfg.json`, at `/home/pc/.local/share/drmlogplotter`.
In this folder copy also "drmtransmittersites.txt" and drmlogplotter_help.txt.

##### Linux Bin:
2) The `DRMLogplotter.bin` and the `DRMLogPlotter_Audio.bin` can be copied to a directory and folder of your choice.
It will then operate from that directory.
Also, copy the files `drmtransmittersite.txt` and `drmlogplotter_help.txt` into the same directory.
You can find the "Screenshot" and "Logs" folders, as well as `drmplotter_cfg.json` here.
In principle, the process is the same as on Windows 10/11.

#### Python:
3) Copy all 3 (!) Python files into the same directory.
Do the same for drmtransmittersite.txt and drmlogplotter_help.txt.
*****************************************************************************

My respectful thoughts go out to the developer of the original DRMLogPlotter Terje Isberg, who worked on it from 2007 to 2022.
