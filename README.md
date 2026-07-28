## DRMLogPlotter - rebuild  

# Version 1.10 is released

##### Update 28.July.2026 see below  

Please also note the very important information regarding the operation of the individual files on Windows, Linux (AMD), and Raspberry Pi (ARM).

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




<img width="649" height="521" alt="Dream-Start Schedule - Window" src="https://github.com/user-attachments/assets/7235b32b-b752-4c6e-934c-5a03296daadf" />  

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



  
#### Update 20.July 2026

Version 1.00 has been released.

New improvements have been implemented in the code!

- Main GUI -> Main Plot Window  
The display and analysis of the green Doppler line should now closely match the original DRMLogPlotter.

- Main GUI -> DRM Mode Used  
The DRM mode analysis has been further refined.

- Set Event -> Dream Start & Schedule Dialog  
The "midnight logic" has been completely overhauled.
Timer events should now start correctly even after midnight.

- Main GUI -> Frame Color  
Color settings for the frame and scale display in the main plot window have been optimized for the "Gray" theme.

- Setup -> Basic Setup Parameters -> Dream and Receiver Configuration  
The "Hamlib NET rigctl" transceiver/RX selection should now work successfully with rigctl servers.

Once you have selected "Hamlib NET rigctl" from the Hamlib list, DRMLogPlotter continuously communicates with a rigctl server.  

  

Successful connections via selection from the Hamlib list using USB or network connectivity have been confirmed:  

- Icom IC-7300
- Icom IC-705
- Yaesu FT-891 (RX modified for DRM)
- Kenwood TS-2000 (RX modified for DRM)
- AirSpy with plugin (simulates Kenwood TS-2000)
- SDRPlay RSPDuo with SDR++ Software (rigctl server)
  
Hope it works for you, too  


##### For more information on past updates, please refer to the "Update-Information.pdf"  




### Quick Start:


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


#### Python:
Copy all 3 (!) Python files into the same directory.
Do the same for drmtransmittersite.txt and drmlogplotter_help.txt.




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
