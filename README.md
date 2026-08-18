## DRMLogPlotter - rebuild  



...


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


<img width="1303" height="719" alt="Main-GUI  - Version 1 22" src="https://github.com/user-attachments/assets/036a0223-0cea-43df-9af6-96a585c7faa0" />



#### The Code:

I am not a programmer.
This was an attempt to create code using nothing but AI.
I chose Python because the code is easy for many users to understand.
This code can also be compiled for all common operating systems.  


##### New ideas:

1) You can launch the DReaM decoder software from within DRMLogPlotter-rebuild.

2) You can launch DReaM while simultaneously generating a log at the correct logging frequency.

3) You can launch DReaM via a timer event.

4) You can launch DReaM via a timer event with logging and automatic live graph generation enabled.  
A connection to the receiver is not strictly necessary up to this point.

5) You can connect your RX/TRX to DRMLogPlotter via USB or a network connection.

6) This allows you to remotely tune your receiver to a specific frequency.

7) You can use a timer event to change the receiver frequency at a time of your choice and launch DReaM with or without logging.  


  
##### But step by step:

One new idea was the ability to launch the DReaM decoder software from within *dlp*— either manually or via a timer event. 
There is also a convenient option to enter the logging frequency; 
this is written to the *dream.ini* file before DReaM is started remotely.
The logging flag is also set based on the input and reset when DReaM stops.
The auto-plot function can be triggered manually or via a timer event.


<img width="780" height="690" alt="Dream Start and schedule" src="https://github.com/user-attachments/assets/5552254a-4c73-4b73-9601-3e8a1a3097fe" />




Another new idea is the ability to connect the RX (transceiver) to *dlp* via Hamlib/RigCTL.

For example, with the Icom IC-7300 and IC-705, the receiver's IF output can be routed to the PC sound card via a USB cable.
This ensures DReaM receives the perfect signal. Timer events allow for convenient control of the transceiver, DReaM, and *dlp*.
The ability to connect an SDR radio is also an interesting feature; the software FLrig can serve as a bridge here if necessary.

Older devices can also be controlled remotely. Please also note the tip below, which describes how the "FLRig" program can act as a bridge.

Status LEDs were introduced to provide the user with an overview of whether all functions are operating correctly.  


<img width="758" height="786" alt="Dream and RX Config - new - b" src="https://github.com/user-attachments/assets/d7f69535-3789-41e7-af34-d26c4c0a4da7" />




The next idea was to incorporate information into the analysis that isn't directly available in the DReaM decoder software's logs—specifically, details regarding the audio codec, audio mode, and protection level.

Modifying the original DReaM code (C++) to extract this information directly from the program is highly challenging, even with AI assistance.
In this case, it was impossible.

However, the AI ​​came up with a different idea—one that takes a bit of lateral thinking:

Capture the missing information from the DReaM station label on the PC screen and save it as a new, additional .json file in the DReaM folder!

<img width="504" height="293" alt="DReaM-Label-Information" src="https://github.com/user-attachments/assets/87201b2e-45d1-4ac7-8fc3-22b71f33bbe4" />

The rebuilt DRMLogPlotter automatically detects both the existing and the new log files and displays the information in the main GUI.
In the latest version, this works very well across Python, Windows 11, and Linux (Ubuntu/Linux Mint).

<img width="433" height="167" alt="Main Log with Audio Codec" src="https://github.com/user-attachments/assets/6bd1ee1e-7e0a-413f-88ce-f039ca1f4bc6" />



  

#### New DRM-Radio-List View  

  <img width="1179" height="729" alt="Radio-List neu 2" src="https://github.com/user-attachments/assets/fecb464d-20b5-47f7-bdb2-5818304163ff" />




### Update: Version 1.26 has been released (August 18, 2026)
(Raspberry Pi - Version is still 1.22 at the moment)  

- A UTC clock has been added to the main GUI.
- In the "Radio List" dialog (which includes a Dream startup option), the directory path for the .ini file is hidden after 6 seconds.



#### Update: Version 1.25 is released (16. August 2026)
(Raspberry Pi - Version is still 1.22 at the moment)  

- The update improves operation with DReaM software!


## Update: 16. August 2026  

- Starting Dream with DRMLogPlotter

If a timer event is scheduled and the user manually starts Dream beforehand, a collision protection mechanism now intervenes:
1) The user is notified via a popup message.
2) One minute before the scheduled start time, the active manual session of Dream is terminated.
3) The timer event then starts correctly.
4) If the user deliberately starts Dream less than 60 seconds before the scheduled start time, 
the manual session is stopped one second prior to the timer event.
Two seconds later, the timer event starts correctly. 
5) Two new colors have been added to the radio list: Red = less than 15 minutes until the program starts. Blue = the frequency currently selected.
6) A time display in UTC format has been added.
7) Minor visual changes to the "Radio List" dialog. The display showing the directory path for radio_list.ini is no longer permanently visible.
8) The position and size of the "Dream-Start and Schedule" dialog window can now be freely adjusted.
Upon restarting DRMLogPlotter, the window opens with the settings last selected by the user.


## Update: 14. August 2026  

Update Information Version 1.24:
- All major dialog windows now save their size and last position on the PC screen.
This ensures the overall layout is immediately organized upon restarting.
- Timer event now supports 4 events.
- Timer event logic revised; should now run stably.
- Station list: Added a warning for events spanning the 00:00–24:00 time range; the end time must be set to 23:59.
- Station list: Double-clicking an entry copies it to the timer event.
- Auto-Plot: Now saves the last used interval. (Does not apply to timer events or log starts via the "Station List" button on the main interface).
- RX + Ant Info: Corrected input and processing logic for "RX+Ant Info"; buttons repositioned.
- All LED functions verified.
- Bug fix: The "Stop Dream" button displayed red text (indicating active Dream operation) even after Dream had been closed.
- Dream: No more conflicts when restarting while Dream is already running; a notification ("Stop Dream first") now appears.
- Corrected checkbox labels in all dialog windows.
- Fixed the checkbox for the edit function in the station list.
- Screenshot files are now saved in the same format as the original LogPlotter (13750-260730-1702-1756_Nickname.png).
- Corrected time and coordinate input functions for "TX-Site" and "Station List" (in the main interface and the DRM timer event dialog).
Clicking the button again no longer opens an unnecessary additional dialog window; ...instead, the dialog window closes upon the second click (toggle function).
- Plot window and main interface frame: The color of the gray frame in the main plot window has been optimized.
- Main interface plot window: The color of the audio line in the plot has been changed to a lighter shade. The line should now be clearly visible even in "Thin Mode."
- Editing the station list: The AutoTab function is now triggered during time entry as well.
- The "Compare-Log" function now uses the same colors as the original for the comparison (audio and SNR lines).
- The text display for the comparison ("Compare-Text") is now clearer and—as in the original version—is located at the bottom of the chart.
- Radio list and timer event: Clicking a row copies all necessary data into an available timer event row.
- Radio list and timer event: Collision check for start and stop times implemented.
If the end time is 00, the new start time is automatically set to 01.
- Radio list and timer event: All timer event rows can be programmed independently.
Clicking an event in the radio list automatically copies the data to an available row.
- Radio list dialog ("Main GUI"): Button layout rearranged.
- Radio list dialog ("Main GUI"): AutoPlot can now be started alongside a manual DReaM log start. Delay is approx. 30 seconds, as usual.


## Update: 09. August 2026 

The following improvements have been made:  

1) The radio list display has been optimized; column widths can now be adjusted individually.  
The program saves these settings and restores them after a restart.  
The selection radio buttons have been optimized; the list selection no longer reverts to "Default" but retains the last setting.  

2) The "DRM Radio List" button in the "Set-Event" dialog has been removed.  
The DRM radio list dialog window now features four buttons:  
Dream Start, Dream Stop, Start Dream with Log, and Close.  

3) You can now start logging immediately without having to switch back to the "Set-Event" dialog to select a frequency.  
Rigctl control has been improved: clicking a frequency in the radio list immediately sets it as the "log frequency" for Dream.  
Once logging is underway, you can close the dialog.  
After about a minute, the log can be manually selected in the main interface (GUI), and AutoPlot can be started.  
To stop logging, simply click "Stop Dream" in the main interface. It couldn't be easier.  

4) The visual appearance of the "TX-Site" and "Radio List" buttons in the main interface (on Windows 11) has been improved.  

5) SNR analysis has been further optimized.  
The red curve in the main plot window now evaluates SNR only while DReaM registers a sync pulse from the DRM radio signal. 
If decoding is interrupted—for example, due to signal fading—all curves drop to the zero line.  

6) The key windows now save their positions. Upon restarting the program, the windows return to their last saved locations.  

7) On Linux, the font has been changed from the Tkinter default to Arial. It now looks significantly better.  

8) Many other minor internal changes and improvements have also been implemented.  
9) The text and checkbox inputs have been optimized for "Zoom in" and "RX coordinates.  
" Unintentional, erroneous user input is now largely prevented.

11) The releases have been updated for Windows 11, Linux Mint/Ubuntu, and Raspberry Pi (ARM).

We are steadily approaching the final version...  



## Update: August 5, 2026
1) SDR-RX  
Frequency correction for rigctl and adjustment for the correct DRM logging frequency.  
If DRM reception must instead be performed using USB/LSB for instance, because the SDR software does not offer a DRM mode—
a correction function is available.  
The offset (e.g., + or - 5 kHz) is detected, and the correct logging frequency for the DReaM log is simultaneously passed on.   

2) DRM Radio List  
This feature has been added.  
The official DRMSchedule.ini file can now be loaded.  
Clicking an entry in the list causes DRMLogPlotter to switch to the desired frequency.  
If you use Hamlib-rigctl for your receiver, it will also automatically switch to the desired frequency.  
Even without remote RX control, the selected frequency is conveniently adopted as the log frequency.  
A display has been added to show the user the current DRM radio list.

4) The summary view has been optimized.  

5) The help text has been expanded and optimized.  

6) Minor optimizations have been made to the window hierarchy to improve clarity for the user.  

7) The main GUI view has been further optimized for Linux/Raspberry Pi.  










## Update 28.July 2026

You will find very important information below in QUICK-START regarding operation with the DRMLogPlotter-rebuild.
  
1) You can now also find a DRMLogPltoter.bin and an AppImage for Raspberry Pi OS "Trixie" under "Releases"!  
Initial tests have been successful.
2) An attempt was made to optimize reading the audio code information from the PC screen, though this remains experimental.  
3) The main GUI layout has been corrected for Linux (including AppImage and Raspberry Pi);  
it should now closely match the view in Windows 11.  
4) "x11/xwayland" and "Wayland" radio buttons have been added to the Basic Settings,  
with "x11/xwayland" selected by default.
5) This is also strictly experimental—an attempt to better understand the issues involved.

 
##### Other Updates see in .pdf



### Quick Start:  
Please also note the very important information regarding the operation of the individual files on Windows, Linux (AMD), and Raspberry Pi (ARM).

## Important Information!
  
#### Python:
Copy all 3 (!) Python files into the same directory.  
Copy the files drmtransmittersites.txt and drmlogplotter_help.txt into this directory as well.

#### Windows
Copy DRMLogPlotter.exe and DRMLogPlotter_Audio.exe  
into the same directory.  
DRMLogPlotter.exe should be run as administrator to ensure access to the DReaM directory.  
Copy the files drmtransmittersites.txt and drmlogplotter_help.txt into this directory as well.

#### Linux (should run on Linux Mint and Ubuntu)
Copy DRMLogPlotter_Linux and DRMLogPlotter_Audio_Linux  
into the same directory.  
Before launching for the first time, rename DRMLogPlotter_Audio_Linux to DRMLogPlotter_Audio.  
Copy the files drmtransmittersites.txt and drmlogplotter_help.txt into this directory as well.

#### Raspberry Pi
Copy DRMLogPlotter_Raspi and DRMLogPlotter_Audio_Raspi  
into the same directory.  
Before launching for the first time, rename DRMLogPlotter_Audio_Raspi to DRMLogPlotter_Audio.  
Copy the files drmtransmittersites.txt and drmlogplotter_help.txt into this directory as well.

#### AppImages-Linux
Copy DRMLogPlotter_Linux.AppImage and DRMLogPlotter_Audio_Linux  
into the same directory.  
Before launching for the first time, rename DRMLogPlotter_Audio_Linux to DRMLogPlotter_Audio.  
For drmtransmittersite.txt and drmlogplotter_help.txt see extra Information below.


#### AppImages-Raspberry Pi
Copy DRMLogPlotter_Raspi.AppImage and DRMLogPlotter_Audio_Raspi  
into the same directory.  
Before launching for the first time, rename DRMLogPlotter_Audio_Raspi to DRMLogPlotter_Audio.  
For drmtransmittersite.txt and drmlogplotter_help.txt see extra Information below.  


##### Additional information 

- Once you have selected the appropriate version for your OS, audio codec detection should also work.  
- The DReaM label window should remain fully visible on the screen for one minute.  
Naturally, this requires successful DRM radio reception.  
- The software checks for up to 3 minutes to see if it can read the information.  
- Testing was conducted using a Full HD screen resolution (1920 × 1080 pixels / 1080p), including on the Raspberry Pi.  
- During testing, it was noted that using turquoise text color in the DReaM label can be advantageous.  

It is all experimental, but it is very interesting to see how well it can work.





#### Windows 10/11 –>

No installation is required. Create a new directory under C:\, e.g., named `drmlogplotter`.
Copy both `.exe` files, as well as `drmtransmittersites.txt` and `drmlogplotter_help.txt`, into this new directory.
##### Important for Windows 10/11: Run the `drm_log_plotter.exe` file as an administrator. Otherwise, `drmlogplotter` cannot access the DReaM decoder software directory!
After launching `drmlogplotter`, the `.json` file and the `Screenshots` and `Logfiles` folders will be created there.
The new folders are created when the respective function is used for the first time.


#### Linux 

##### 1) AppImage:
Use the AppImage and follow the instructions in the help text.
You can find the "Screenshot" and "Logs" folders, as well as `drmplotter_cfg.json`,

##### at `/home/pc/.local/share/drmlogplotter`.

In this folder copy also "drmtransmittersites.txt" and drmlogplotter_help.txt.

##### 2) Linux Bin:
The `DRMLogplotter.bin` and the `DRMLogPlotter_Audio.bin` can be copied to a directory and folder of your choice.
It will then operate from that directory.
Also, copy the files `drmtransmittersite.txt` and `drmlogplotter_help.txt` into the same directory.
You can find the "Screenshot" and "Logs" folders, as well as `drmplotter_cfg.json` here.
In principle, the process is the same as on Windows 10/11.




### Additional note regarding remote connection:

If you encounter problems detecting the USB or network connection—which typically occur with older devices
or connections using adapters or virtual COM interfaces, try the following steps.
The excellent FLRig software could serve as a bridge between your RX/TRX and the DRMLogPlotter-rebuild.

https://sourceforge.net/projects/fldigi/files/

Download the software FLRig to your PC at your own risk, install it, and then restart the PC.
First, establish a connection between your RX/TRX and FLRig.


<img width="1102" height="350" alt="FLRig" src="https://github.com/user-attachments/assets/3b321af0-bd13-4e7e-a853-bf7c7586d51e" />


If FLRig successfully confirms the connection, the RX frequency, for example, will be visible in the FLRig GUI.
Once that is successful, check the "Client" setting.

<img width="674" height="311" alt="FLRig Client" src="https://github.com/user-attachments/assets/d6a41de4-9435-4f9f-a41d-4f159e6bbaef" />



Transfer the data to DRMLogPlotter.


In DRMLogPlotter, select "FLRig FLRIG" from the Hamlib list.
Save, close, and restart.


<img width="752" height="333" alt="DRMLogPlotter - Network" src="https://github.com/user-attachments/assets/b3c7f594-a6c9-450f-9bd6-da3f8d21ad53" />

Ideally, you should see an positiv "RX-Connect" status, and entering a
test frequency should cause the RX/TRX to switch to the desired frequency.


*****************************************************************************

My respectful thoughts go out to the developer of the original DRMLogPlotter Terje Isberg, who worked on it from 2007 to 2022.
