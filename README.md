## DRMLogPlotter - rebuild  

#### Information: Version 1.28 released.  



......................................................................................

It started as an experiment in programming with AI.  

Now, it is an excellent piece of software that is very easy to get up and running:  

-  "DRMLogPlotter rebuild" visualizes log files created by the free DRM (Digital Radio Mondiale) software decoder, DReaM.

- Simply download DRMLogPlotter.exe and DRMLogPlotter_Audio.exe and copy them into a new directory—for example,  
C:\DRMLogPlotter.

- There is no installation required.

- No .dll files need to be registered.

 - Everything is completely new.  



- Just set DRMLogPlotter.exe to "Run as administrator" in the compatibility settings.  
- That’s all there is to it!  

- After launching the program, set the directory path for the DReaM decoder software and the Hamlib parameters for (if you have) the remote receiver.  

- No remote RX available? No problem. All other features still work with Dream.

You're all set.
Have fun experimenting!

...


#### This rebuild is based on the original DRM Log Plotter.  

(Click on the images to enlarge them...)  


<img width="993" height="618" alt="Original_ DRMLogPlotter " src="https://github.com/user-attachments/assets/a610350e-d9df-481b-a0e2-c12e9e471306" />


Unfortunately, the source code for the original is unavailable.
Consequently, it was no longer possible to incorporate new ideas into the existing program.
Many ideas in the original were excellent.
Some of those ideas were not carried over into *dlp*.  


#### About the program:

DRM Log Plotter (old and the new rebuild-experimental) reads and visualizes log files created by the free DRM (Digital Radio Mondiale) software decoder, DReaM.
It plots the following data from a DReaM log session:

- Blue line   =  Decoded Audio (0 – 100%)
- Red line    =  SNR — Signal-to-Noise Ratio (dB)
- Green line  =  Doppler spread (Hz)
- Ochre line  =  Delay spread (ms)

<img width="1271" height="739" alt="Main GUI" src="https://github.com/user-attachments/assets/f832bb95-c2d7-495c-8ced-f9226f5f0616" />




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


<img width="775" height="733" alt="Dream-Start and Timer-Event" src="https://github.com/user-attachments/assets/8c0f739e-6325-4e02-bf64-0b53be377207" />





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

<img width="1002" height="667" alt="Radio List 1" src="https://github.com/user-attachments/assets/97da899e-8bc5-47c4-9ebb-c11dcb25e4c0" />







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
