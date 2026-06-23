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
