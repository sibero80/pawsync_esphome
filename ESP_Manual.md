# ESP32­C3­SOLO­1 User Manual 

2.4 GHz Wi­Fi (802.11 b/g/n) and Bluetooth<sup>®</sup> 5 module Built around ESP32­C3 series of SoC, RISC­V single­core microprocessor 15 GPIOs 

On­borad PCB antenna 



Pre-release v0.5 Espressif Systems Copyright © 2022 



www.espressif.com 

## About This Document 

This user manual shows how to get started with the ESP32-C3-SOLO-1 module. 

### Document Updates 

Please always refer to the latest version on <u>https://www.espressif.com/en/support/download/documents.</u> 

### Revision History 

For revision history of this document, please refer to the last page. 

### Documentation Change Notification 

Espressif provides email notifications to keep you updated on changes to technical documentation. Please subscribe at <u>www.espressif.com/en/subscribe.</u> 

### Certification 

Download certificates for Espressif products from <u>www.espressif.com/en/certificates.</u> 

Contents 

## Contents 

|1|Overview|4|
|---|---|---|
|1.1|Module Overview|4|
|1.2|Pin Description|5|
|2|Get Started on ESP32­C3­SOLO­1|7|
|2.1|What You Need|7|
|2.2|Hardware Connection|7|
|2.3|Set up Development Environment|8|
||2.3.1<br>Install Prerequisites|8|
||2.3.2<br>Get ESP-IDF|8|
||2.3.3<br>Set up Tools|9|
||2.3.4<br>Set up Environment Variables|9|
|2.4|Create Your First Project|9|
||2.4.1<br>Start a Project|9|
||2.4.2<br>Connect Your Device|9|
||2.4.3<br>Configure|9|
||2.4.4<br>Build the Project|10|
||2.4.5<br>Flash onto the Device|11|
||2.4.6<br>Monitor|12|
|3|U.S. FCC Statement|14|
|4|IC Statement|18|
|5|Related Documentation and Resources|21|
|Re|vision History|22|



Espressif Systems 

3 

ESP32-C3-SOLO-1 User Manual v0.5 

1 Overview 

## 1 Overview 

### 1.1 Module Overview 

ESP32-C3-SOLO-1 is a generic Wi-Fi and Bluetooth LE module that has a rich set of peripherals. This module is an ideal choice for a wide variety of application scenarios such as smart home, wearable electronics, smart lighting, etc. 

Table 1: ESP32­C3­SOLO­1 Specifications 

|Categories|Parameters|Specifications|
|---|---|---|
|Wi-Fi|Protocols|802.11 b/g/n (up to 150 Mbps)|
||Frequency range|2412~2462 MHz|
|<sup>®</sup>|Protocols|Bluetooth<sup>® </sup>LE: Bluetooth 5 and Bluetooth mesh|
|Bluetooth|Radio|Class-1, class-2 and class-3 transmitter|
||Module interfaces|GPIO, SPI, UART, I2C, I2S, remote control peripheral,<br>LED PWM controller, general DMA controller, TWAI<sup>®</sup><br>controller (compatible with ISO 11898-1), temperature<br>sensor, SAR ADC|
||Integrated crystal|40 MHz crystal|
||Operating voltage/Power supply|3.0 V~3.6 V|
|Hardware|Operating current|Average: 80 mA|
||Minimum current delivered by power<br>supply|500 mA|
||Ambient temperature|–40 °C~+105 °C|
||Moisture sensitivity level (MSL)|Level 3|



Espressif Systems 

4 

ESP32-C3-SOLO-1 User Manual v0.5 

1 Overview 

### 1.2 Pin Description 



<!-- Start of picture text -->
Keepout Zone<br>1 GND GND 38<br>2 3V3 NC 37<br>3 EN NC 36<br>4 IO2 TXD0 35<br>5 IO3 RXD0 34<br>6 NC rif GND GND tt GND NC 33<br>7 NC rif GND GND39 tt GND NC 32<br>8 4~ IO0 rif LJ GND td GND tt ta GND NC L - 31<br>9 IO1 NC 30<br>10 NC NC 29<br>11 NC IO19 28<br>12 NC IO18 27<br>13 IO4 IO10 26<br>14 IO5 IO9 25<br>7 PIV PDT PST aaa 7<br>GND IO6 NC NC NC NC NC NC IO7 IO8<br>15 16 17 18 19 20 21 22 23 24<br><!-- End of picture text -->

Figure 1: Pin Layout 

The module has 39 pins. See pin definitions in Table 2. 

For peripheral pin configurations, please refer to <u>ESP32-C3 Datasheet.</u> 

Table 2: Pin Definitions 

|Name|No.|Type|Function|
|---|---|---|---|
|GND|1, 15, 38,<br>39|P|Ground|
|3V3|2|P|Power supply|



Cont’d on next page 

Espressif Systems 

5 

ESP32-C3-SOLO-1 User Manual v0.5 

1 Overview 

Table 2 – cont’d from previous page 

|Name|No.|Type|Function|
|---|---|---|---|
|EN|3|I|High: on, enables the chip.<br>Low: off, the chip powers off.<br>Note: Do not leave the EN pin floating.|
|IO2|4|I/O/T|GPIO2, ADC1_CH2, FSPIQ<br>Internally pulled up|
|IO3|5|I/O/T|GPIO3, ADC1_CH3|
||6-7,<br>10-12,|||
|NC|17-22,<br>29-33,<br>36-37|—|NC|
|IO0|8|I/O/T|GPIO0, ADC1_CH0, XTAL_32K_P|
|IO1|9|I/O/T|GPIO1, ADC1_CH1, XTAL_32K_N|
|IO4|13|I/O/T|GPIO4, ADC1_CH4, FSPIHD, MTMS|
|IO5|14|I/O/T|GPIO5, ADC2_CH0, FSPIWP, MTDI|
|IO6|16|I/O/T|GPIO6, FSPICLK, MTCK|
|IO7|23|I/O/T|GPIO7, FSPID, MTDO|
|IO8|24|I/O/T|GPIO8<br>Internally pulled up|
|IO9|25|I/O/T|GPIO9|
|IO10|26|I/O/T|GPIO10, FSPICS0|
|IO18|27|I/O/T|GPIO18, USB_D-, U1RXD (user specified)|
|IO19|28|I/O/T|GPIO19, USB_D+, U1TXD (user specified)|
|RXD0|34|I/O/T|GPIO20, U0RXD|
|TXD0|35|I/O/T|GPIO21, U0TXD|



> 1 P: power supply; I: input; O: output; T: high impedance. 

Espressif Systems 

6 

ESP32-C3-SOLO-1 User Manual v0.5 

2 Get Started on ESP32-C3-SOLO-1 

## 2 Get Started on ESP32­C3­SOLO­1 

### 2.1 What You Need 

To develop applications for ESP32-C3-SOLO-1 module you need: 

- 1 x ESP32-C3-SOLO-1 module 

- 1 x Espressif RF testing board 

- 1 x USB-to-Serial board 

- 1 x Micro-USB cable 

- 1 x PC running Linux 

In this user guide, we take Linux operating system as an example. For more information about the configuration on Windows and macOS, please refer to <u>ESP-IDF Programming Guide.</u> 

### 2.2 Hardware Connection 

1. Solder the ESP32-C3-SOLO-1 module to the RF testing board as shown in Figure 2. 



<!-- Start of picture text -->
© Jat et) FO<br>ate<br><!-- End of picture text -->

Figure 2: Hardware Connection 

2. Connect the RF testing board to the USB-to-Serial board via TXD, RXD, and GND. 

3. Connect the USB-to-Serial board to the PC. 

4. Connect the RF testing board to the PC or a power adapter to enable 5 V power supply, via the Micro-USB cable. 

5. During download, connect IO0 to GND via a jumper. Then, turn ”ON” the testing board. 

6. Download firmware into flash. For details, see the sections below. 

Espressif Systems 

7 

ESP32-C3-SOLO-1 User Manual v0.5 

2 Get Started on ESP32-C3-SOLO-1 

7. After download, remove the jumper on IO0 and GND. 

8. Power up the RF testing board again. ESP32-C3-SOLO-1 will switch to working mode. The chip will read programs from flash upon initialization. 

Note: 

IO0 is internally logic high. If IO0 is set to pull-up, the Boot mode is selected. If this pin is pull-down or left floating, the Download mode is selected. 

### 2.3 Set up Development Environment 

The Espressif IoT Development Framework (ESP-IDF for short) is a framework for developing applications based on the Espressif chips. Users can develop applications with ESP chips in Windows/Linux/macOS based on ESP-IDF. Here we take Linux operating system as an example. 

#### 2.3.1 Install Prerequisites 

To compile with ESP-IDF you need to get the following packages: 

- CentOS 7: 

1 sudo yum install git wget flex bison gperf python cmake ninja-build ccache dfuutil 

- Ubuntu and Debian (one command breaks into two lines): 

1 sudo apt-get install git wget flex bison gperf python python-pip pythonsetuptools cmake 

   - 2 ninja-build ccache libffi-dev libssl-dev dfu-util 

- Arch: 

   - 1 sudo pacman -S --needed gcc git make flex bison gperf python-pip cmake ninja ccache dfu-util 

Note: 

- This guide uses the directory ~/esp on Linux as an installation folder for ESP-IDF. 

- Keep in mind that ESP-IDF does not support spaces in paths. 

#### 2.3.2 Get ESP­IDF 

To build applications for ESP32-C3-SOLO-1 module, you need the software libraries provided by Espressif in <u>ESP-IDF repository.</u> 

To get ESP-IDF, create an installation directory (~/esp) to download ESP-IDF to and clone the repository with ‘git clone’: 

- 1 mkdir -p ~/esp 

- 2 cd ~/esp 

- 3 git clone --recursive https://github.com/espressif/esp-idf.git 

Espressif Systems 

8 

ESP32-C3-SOLO-1 User Manual v0.5 

2 Get Started on ESP32-C3-SOLO-1 

ESP-IDF will be downloaded into ~/esp/esp-idf. Consult <u>ESP-IDF Versions</u> for information about which ESP-IDF version to use in a given situation. 

#### 2.3.3 Set up Tools 

Aside from the ESP-IDF, you also need to install the tools used by ESP-IDF, such as the compiler, debugger, Python packages, etc. ESP-IDF provides a script named ’install.sh’ to help set up the tools in one go. 

- 1 cd ~/esp/esp-idf 

- 2 ./install.sh 

#### 2.3.4 Set up Environment Variables 

The installed tools are not yet added to the PATH environment variable. To make the tools usable from the command line, some environment variables must be set. ESP-IDF provides another script ’export.sh’ which does that. In the terminal where you are going to use ESP-IDF, run: 

- 1 . $HOME/esp/esp-idf/export.sh 

Now everything is ready, you can build your first project on ESP32-C3-SOLO-1 module. 

### 2.4 Create Your First Project 

#### 2.4.1 Start a Project 

Now you are ready to prepare your application for ESP32-C3-SOLO-1 module. You can start with <u>get-started/hello_world</u> project from <u>examples directory</u> in ESP-IDF. 

Copy get-started/hello_world to ~/esp directory: 

- 1 cd ~/esp 

- 2 cp -r $IDF_PATH/examples/get-started/hello_world . 

There is a range of <u>example projects</u> in the examples directory in ESP-IDF. You can copy any project in the same way as presented above and run it. It is also possible to build examples in-place, without copying them first. 

#### 2.4.2 Connect Your Device 

Now connect your ESP32-C3-SOLO-1 module to the computer and check under what serial port the module is visible. Serial ports in Linux start with ‘/dev/tty’ in their names. Run the command below two times, first with the board unplugged, then with plugged in. The port which appears the second time is the one you need: 

- 1 ls /dev/tty* 

Note: 

Keep the port name handy as you will need it in the next steps. 

#### 2.4.3 Configure 

Navigate to your ‘hello_world’ directory from Step 2.4.1. Start a Project, set ESP32-C3 as the target and run the project configuration utility ‘menuconfig’. 

Espressif Systems 

9 

ESP32-C3-SOLO-1 User Manual v0.5 

2 Get Started on ESP32-C3-SOLO-1 

- 1 cd ~/esp/hello_world 

- 2 idf.py set-target esp32c3 

- 3 idf.py menuconfig 

Setting the target with ‘idf.py set-target esp32c3’ should be done once, after opening a new project. If the project contains some existing builds and configuration, they will be cleared and initialized. The target may be saved in environment variable to skip this step at all. See <u>Selecting the Target</u> for additional information. 

If the previous steps have been done correctly, the following menu appears: 



<!-- Start of picture text -->
SOK tool configuratian ---><br>Bultd type ---><br>Applicatlon manager ---><br>Bootloader confilg ---><br>Security features  ---><br>Serial flasher config =--2<br>Partttlon Table ---><br>Compiter options ---><br>Component config =--><br>Compatlbility options ---><br>[F] Toggle sh elp mod C) Toggle show-nane mode A] Toggle show-all a<br><!-- End of picture text -->

Figure 3: Project Configuration ­ Home Window 

The colors of the menu could be different in your terminal. You can change the appearance with the option ‘-฀-style’฀. Please run ‘idf.py menuconfig -฀-help’฀for further information. 

#### 2.4.4 Build the Project 

Build the project by running: 

- 1 idf.py build 

This command will compile the application and all ESP-IDF components, then it will generate the bootloader, partition table, and application binaries. 

- 1 $ idf.py build 

- 2 Running cmake in directory /path/to/hello_world/build 

- 3 Executing ”cmake -G Ninja --warn-uninitialized /path/to/hello_world”... 

- 4 Warn about uninitialized values. 

- 5 -- Found Git: /usr/bin/git (found version ”2.17.0”) 

- 6 -- Building empty aws_iot component due to configuration 

- 7 -- Component names: ... 

- 8 -- Component paths: ... 

- 9 

- 10 ... (more lines of build system output) 

11 

Espressif Systems 

10 

ESP32-C3-SOLO-1 User Manual v0.5 

2 Get Started on ESP32-C3-SOLO-1 

- 12 [527/527] Generating hello-world.bin 

- 13 esptool.py v2.3.1 

- 14 

- 15 Project build complete. To flash, run this command: 

- 16 ../../../components/esptool_py/esptool/esptool.py -p (PORT) -b 921600 write_flash --flash_ mode dio 

- 17 --flash_size detect --flash_freq 40m 0x10000 build/hello-world.bin build 0x1000 

- 18 build/bootloader/bootloader.bin 0x8000 build/partition_table/partition-table.bin 

- 19 or run ’idf.py -p PORT flash’ 

If there are no errors, the build will finish by generating the firmware binary .bin file. 

#### 2.4.5 Flash onto the Device 

Flash the binaries that you just built onto your ESP32-C3-SOLO-1 module by running: 

- 1 idf.py -p PORT [-b BAUD] flash 

Replace PORT with your module‘s serial port name from Step: Connect Your Device. 

You can also change the flasher baud rate by replacing BAUD with the baud rate you need. The default baud rate is 460800. 

For more information on idf.py arguments, see <u>idf.py.</u> 

###### Note: 

The option ‘flash‘ automatically builds and flashes the project, so running ‘idf.py build‘ is not necessary. 

- 1 

2 esptool.py --chip esp32c3 -p /dev/ttyUSB0 -b 460800 --before=default_reset --after =hard_reset write_flash --flash_mode dio --flash_freq 80m --flash_size 2MB 0x 8000 partition_table/partition-table.bin 0x0 bootloader/bootloader.bin 0x10000 hello-world.bin 3 esptool.py v3.0 4 Serial port /dev/ttyUSB0 5 Connecting.... 6 Chip is ESP32-C3 7 Features: Wi-Fi 8 Crystal is 40MHz 9 MAC: 7c:df:a1:40:02:a4 10 Uploading stub... 11 Running stub... 12 Stub running... 13 Changing baud rate to 460800 14 Changed. 15 Configuring flash size... 16 Compressed 3072 bytes to 103... 17 Writing at 0x00008000... (100 %) 18 Wrote 3072 bytes (103 compressed) at 0x00008000 in 0.0 seconds (effective 4238.1 kbit/s)... 19 Hash of data verified. 

Espressif Systems 

11 

ESP32-C3-SOLO-1 User Manual v0.5 

2 Get Started on ESP32-C3-SOLO-1 

> 20 Compressed 18960 bytes to 11311... 21 Writing at 0x00000000... (100 %) 22 Wrote 18960 bytes (11311 compressed) at 0x00000000 in 0.3 seconds (effective 584.9 kbit/s)... 23 Hash of data verified. 24 Compressed 145520 bytes to 71984... 25 Writing at 0x00010000... (20 %) 26 Writing at 0x00014000... (40 %) 27 Writing at 0x00018000... (60 %) 28 Writing at 0x0001c000... (80 %) 29 Writing at 0x00020000... (100 %) 30 Wrote 145520 bytes (71984 compressed) at 0x00010000 in 2.3 seconds (effective 504.4 kbit/s)... 31 Hash of data verified. 32 33 Leaving... 34 Hard resetting via RTS pin... 35 Done 

If everything goes well, the “hello_world” application starts running after you remove the jumper on IO0 and GND, and re-power up the testing board. 

#### 2.4.6 Monitor 

To check if “hello_world” is indeed running, type ‘idf.py -p PORT monitor‘ (Do not forget to replace PORT with your serial port name). 

This command launches the IDF Monitor application: 

- 1 $ idf.py -p /dev/ttyUSB0 monitor 

- 2 Running idf_monitor in directory [...]/esp/hello_world/build 

- 3 Executing ”python [...]/esp-idf/tools/idf_monitor.py -b 115200 [...]/esp/hello_world/build /hello-world.elf”... 

- 4 --- idf_monitor on /dev/ttyUSB0 115200 --- 

- 5 --- Quit: Ctrl+] | Menu: Ctrl+T | Help: Ctrl+T followed by Ctrl+H --- 

- 6 ets Jun 8 2016 00:22:57 

- 7 

- 8 rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT) 

- 9 ets Jun 8 2016 00:22:57 

- 10 ... 

After startup and diagnostic logs scroll up, you should see “Hello world!” printed out by the application. 

- 1 ... 

- 2 Hello world! 

- 3 Restarting in 10 seconds... 

- 4 This is esp32c3 chip with 1 CPU core, WiFi/BLE 

- 5 Restarting in 9 seconds... 

- 6 Restarting in 8 seconds... 

- 7 Restarting in 7 seconds... 

To exit IDF monitor use the shortcut Ctrl+]. 

Espressif Systems 

12 

ESP32-C3-SOLO-1 User Manual v0.5 

2 Get Started on ESP32-C3-SOLO-1 

That’s all what you need to get started with ESP32-C3-SOLO-1 module! Now you are ready to try some other <u>examples</u> in ESP-IDF, or go right to developing your own applications. 

Espressif Systems 

13 

ESP32-C3-SOLO-1 User Manual v0.5 

3 U.S. FCC Statement 

## 3 U.S. FCC Statement 

The device complies with KDB 996369 D03 OEM Manual v01. Below are integration instructions for host product manufacturers according to the KDB 996369 D03 OEM Manual v01. 

##### List of Applicable FCC Rules 

FCC Part 15 Subpart C 15.247 

##### Specific Operational Use Conditions 

The module has WiFi and BLE functions. 

- Operation Frequency: 

   - WiFi: 2412 ~ 2462 MHz 

   - Bluetooth: 2402 ~ 2480 MHz 

- Number of Channel: 

   - WiFi: 11 

   - Bluetooth: 40 

- Modulation: 

   - WiFi: DSSS; OFDM 

   - Bluetooth: GFSK 

- Type: On-board PCB antenna 

- Gain: 3.26 dBi Max 

The module can be used for IoT applications with a maximum 3.26 dBi antenna. The host manufacturer installing this module into their product must ensure that the final composite product complies with the FCC requirements by a technical assessment or evaluation to the FCC rules, including the transmitter operation. The host manufacturer has to be aware not to provide information to the end user regarding how to install or remove this RF module in the user’s manual of the end product which integrates this module. The end user manual shall include all required regulatory information/warning as show in this manual. 

##### Limited Module Procedures 

Not applicable. The module is a single module and complies with the requirement of FCC Part 15.212. 

##### Trace Antenna Designs 

Not applicable. The module has its own antenna, and does not need a host’s printed board microstrip trace antenna, etc. 

##### RF Exposure Considerations 

The module must be installed in the host equipment such that at least 20cm is maintained between the antenna and users’ body; and if RF exposure statement or module layout is changed, then the host product manufacturer 

Espressif Systems 

14 

ESP32-C3-SOLO-1 User Manual v0.5 

3 U.S. FCC Statement 

required to take responsibility of the module through a change in FCC ID or new application. The FCC ID of the module cannot be used on the final product. In these circumstances, the host manufacturer will be responsible for re-evaluating the end product (including the transmitter) and obtaining a separate FCC authorization. 

##### Antennas 

Antenna specification are as follows: 

- Type: On-board PCB antenna 

- Gain: 3.26 dBi 

This device is intended only for host manufacturers under the following conditions: 

- The transmitter module may not be co-located with any other transmitter or antenna. 

- The module shall be only used with the external antenna(s) that has been originally tested and certified with this module. 

- The antenna must be either permanently attached or employ a ‘unique’ antenna coupler. 

As long as the conditions above are met, further transmitter test will not be required. However, the host manufacturer is still responsible for testing their end-product for any additional compliance requirements required with this module installed (for example, digital device emissions, PC peripheral requirements, etc.). 

##### Label and Compliance Information 

Host product manufacturers need to provide a physical or e-label stating “Contains FCC ID: 2AC7Z-ESPC3SOLO” with their finished product. 

Information on test modes and additional testing requirements 

- Operation Frequency: 

   - WiFi: 2412 ~ 2462 MHz 

   - Bluetooth: 2402 ~ 2480 MHz 

- Number of Channel: 

   - WiFi: 11 

   - Bluetooth: 40 

- Modulation: 

   - WiFi: DSSS; OFDM 

   - Bluetooth: GFSK 

Host manufacturer must perform test of radiated and conducted emission and spurious emission, etc., according to the actual test modes for a stand-alone modular transmitter in a host, as well as for multiple simultaneously transmitting modules or other transmitters in a host product. Only when all the test results of test modes comply with FCC requirements, then the end product can be sold legally. 

Espressif Systems 

15 

ESP32-C3-SOLO-1 User Manual v0.5 

3 U.S. FCC Statement 

##### Additional testing, Part 15 Subpart B compliant 

The modular transmitter is only FCC authorized for FCC Part 15 Subpart C 15.247 and that the host product manufacturer is responsible for compliance to any other FCC rules that apply to the host not covered by the modular transmitter grant of certification. If the grantee markets their product as being Part 15 Subpart B compliant (when it also contains unintentional-radiator digital circuity), then the grantee shall provide a notice stating that the final host product still requires Part 15 Subpart B compliance testing with the modular transmitter installed. 

This equipment has been tested and found to comply with the limits for a Class B digital device, pursuant to Part15 of the FCC Rules. These limits are designed to provide reasonable protection against harmful interference in a residential installation. This equipment generates, uses and can radiate radio frequency energy and, if not installed and used in accordance with the instructions, may cause harmful interference to radio communications. 

However, there is no guarantee that interference will not occur in a particular installation. If this equipment does cause harmful interference to radio or television reception, which can be determined by turning the equipment off and on, the user is encouraged to try to correct the interference by one of the following measures: 

- Reorient or relocate the receiving antenna. 

- Increase the separation between the equipment and receiver. 

- Connect the equipment into an outlet on a circuit different from that to which the receiver is connected. 

- Consult the dealer or an experienced radio/TV technician for help. 

This device complies with Part 15 of the FCC Rules. Operation is subject to the following two conditions: 

- This device may not cause harmful interference. 

- This device must accept any interference received, including interference that may cause undesired operation. 

Any changes or modifications not expressly approved by the party responsible for compliance could void the user’s authority to operate the equipment. 

This equipment complies with FCC RF radiation exposure limits set forth for an uncontrolled environment. This device and its antenna must not be co-located or operating in conjunction with any other antenna or transmitter. The antennas used for this transmitter must be installed to provide a separation distance of at least 20 cm from all persons and must not be co-located or operating in conjunction with any other antenna or transmitter. 

##### OEM Integration Instructions 

This device is intended only for OEM integrators under the following conditions: 

- The transmitter module may not be co-located with any other transmitter or antenna. 

- The module shall be only used with the external antenna(s) that has been originally tested and certified with this module. 

As long as the conditions above are met, further transmitter test will not be required. However, the OEM integrator is still responsible for testing their end-product for any additional compliance requirements required with this module installed (for example, digital device emissions, PC peripheral requirements, etc.). 

Espressif Systems 

16 

ESP32-C3-SOLO-1 User Manual v0.5 

3 U.S. FCC Statement 

##### Validity of Using the Module Certification 

In the event that these conditions cannot be met (for example certain laptop configurations or co-location with another transmitter), then the FCC authorization for this module in combination with the host equipment is no longer considered valid and the FCC ID of the module cannot be used on the final product. In these circumstances, the OEM integrator will be responsible for re-evaluating the end product (including the transmitter) and obtaining a separate FCC authorization. 

##### End Product Labeling 

The final end product must be labeled in a visible area with the following: “Contains Transmitter Module FCC ID: 2AC7Z-ESPC3SOLO”. 

Espressif Systems 

17 

ESP32-C3-SOLO-1 User Manual v0.5 

4 IC Statement 

## 4 IC Statement 

This device complies with Industry Canada’s licence-exempt RSSs. Operation is subject to the following two conditions: 

- This device may not cause interference; and 

- This device must accept any interference, including interference that may cause undesired operation of the device. 

Le présent appareil est conforme aux CNR d’Industrie Canada applicables aux appareils radio exempts de licence. L’exploitation est autorisée aux deux conditions suivantes: 

- l’appareil ne doit pas produire de brouillage, et 

- l’utilisateur de l’appareil doit accepter tout brouillage radioélectrique subi, même si le brouillage est susceptible d’en compromettre le fonctionnement. 

##### Radiation Exposure Statement 

This equipment complies with IC radiation exposure limits set forth for an uncontrolled environment. This equipment should be installed and operated with minimum distance 20 cm between the radiator and your body. 

##### Déclaration d’exposition aux radiations: 

Cet équipement est conforme aux limites d’exposition aux rayonnements ISED établies pour un environnement non contrôlé. Cet équipement doit être installé et utilisé avec un minimum de 20 cm de distance entre la source de rayonnement et votre corps. 

##### RSS­247 Section 6.4 (5) 

The device could automatically discontinue transmission in case of absence of information to transmit, or operational failure. Note that this is not intended to prohibit transmission of control or signaling information or the use of repetitive codes where required by the technology. 

L’appareil peut interrompre automatiquement la transmission en cas d’absence d’informations à transmettre ou de panne opérationnelle. Notez que ceci n’est pas destiné à interdire la transmission d’informations de contrôle ou de signalisation ou l’utilisation de codes répétitifs lorsque cela est requis par la technologie. 

##### This device is intended only for OEM integrators under the following conditions (For module device use): 

- The antenna must be installed such that 20 cm is maintained between the antenna and users, and 

- The transmitter module may not be co-located with any other transmitter or antenna. 

As long as 2 conditions above are met, further transmitter test will not be required. However, the OEM integrator is still responsible for testing their end-product for any additional compliance requirements required with this module installed. 

Espressif Systems 

18 

ESP32-C3-SOLO-1 User Manual v0.5 

4 IC Statement 

Cet appareil est conçu uniquement pour les intégrateurs OEM dans les conditions suivantes (Pour utilisa­ tion de dispositif module): 

- L’antenne doit être installée de telle sorte qu’une distance de 20 cm est respectée entre l’antenne et les utilisateurs, et 

- Le module émetteur peut ne pas être coïmplanté avec un autre émetteur ou antenne. 

Tant que les 2 conditions ci-dessus sont remplies, des essais supplémentaires sur l’émetteur ne seront pas nécessaires. Toutefois, l’intégrateur OEM est toujours responsable des essais sur son produit final pour toutes exigences de conformité supplémentaires requis pour ce module installé. 

##### IMPORTANT NOTE: 

In the event that these conditions can not be met (for example certain laptop configurations or colocation with another transmitter), then the Canada authorization is no longer considered valid and the IC ID can not be used on the final product. In these circumstances, the OEM integrator will be responsible for re-evaluating the end product (including the transmitter) and obtaining a separate Canada authorization. 

##### NOTE IMPORTANTE: 

Dans le cas où ces conditions ne peuvent être satisfaites (par exemple pour certaines configurations d’ordinateur portable ou de certaines co-localisation avec un autre émetteur), l’autorisation du Canada n’est plus considéré comme valide et l’ID IC ne peut pas être utilisé sur le produit final. Dans ces circonstances, l’intégrateur OEM sera chargé de réévaluer le produit final (y compris l’émetteur) et l’obtention d’une autorisation distincte au Canada. 

##### End Product Labeling 

This transmitter module is authorized only for use in device where the antenna may be installed such that 20 cm may be maintained between the antenna and users. The final end product must be labeled in a visible area with the following: “Contains IC: 2AC7Z-ESPC3SOLO”. 

##### Plaque signalétique du produit final 

Ce module émetteur est autorisé uniquement pour une utilisation dans un dispositif où l’antenne peut être installée de telle sorte qu’une distance de 20cm peut être maintenue entre l’antenne et les utilisateurs. Le produit final doit être étiqueté dans un endroit visible avec l’inscription suivante: ”Contient des IC: 2AC7Z-ESPC3SOLO”. 

##### Manual Information to the End User 

The OEM integrator has to be aware not to provide information to the end user regarding how to install or remove this RF module in the user’s manual of the end product which integrates this module. The end user manual shall include all required regulatory information/warning as show in this manual. 

##### Manuel d’information à l’utilisateur final 

L’intégrateur OEM doit être conscient de ne pas fournir des informations à l’utilisateur final quant à la façon d’installer ou de supprimer ce module RF dans le manuel de l’utilisateur du produit final qui intègre ce module. Le manuel 

Espressif Systems 

19 

ESP32-C3-SOLO-1 User Manual v0.5 

4 IC Statement 

de l’utilisateur final doit inclure toutes les informations réglementaires requises et avertissements comme indiqué dans ce manuel. 

Espressif Systems 

20 

ESP32-C3-SOLO-1 User Manual v0.5 

5 Related Documentation and Resources 

## 5 Related Documentation and Resources 

### Related Documentation 

- <u>ESP32-C3 Series Datasheet</u> – Specifications of the ESP32-C3 hardware. 

- <u>ESP32-C3 Technical Reference Manual</u> – Detailed information on how to use the ESP32-C3 memory and peripherals. 

- Certificates 

<u>https://espressif.com/en/support/documents/certificates</u> 

- Documentation Updates and Update Notification Subscription <u>https://espressif.com/en/support/download/documents</u> 

### Developer Zone 

- <u>ESP-IDF Programming Guide for ESP32-C3</u> – Extensive documentation for the ESP-IDF development framework. 

- ESP-IDF and other development frameworks on GitHub. <u>https://github.com/espressif</u> 

- ESP32 BBS Forum – Engineer-to-Engineer (E2E) Community for Espressif products where you can post questions, share knowledge, explore ideas, and help solve problems with fellow engineers. <u>https://esp32.com/</u> 

- The ESP Journal – Best Practices, Articles, and Notes from Espressif folks. <u>https://blog.espressif.com/</u> 

- See the tabs SDKs and Demos, Apps, Tools, AT Firmware. 

<u>https://espressif.com/en/support/download/sdks-demos</u> 

### Products 

- ESP32-C3 Series SoCs – Browse through all ESP32-C3 SoCs. <u>https://espressif.com/en/products/socs?id=ESP32-C3</u> 

- ESP32-C3 Series Modules – Browse through all ESP32-C3-based modules. <u>https://espressif.com/en/products/modules?id=ESP32-C3</u> 

- ESP32-C3 Series DevKits – Browse through all ESP32-C3-based devkits. 

- <u>https://espressif.com/en/products/devkits?id=ESP32-C3</u> 

- ESP Product Selector – Find an Espressif hardware product suitable for your needs by comparing or applying filters. <u>https://products.espressif.com/#/product-selector?language=en</u> 

### Contact Us 

- See the tabs Sales Questions, Technical Enquiries, Circuit Schematic & PCB Design Review, Get Samples (Online stores), Become Our Supplier, Comments & Suggestions. <u>https://espressif.com/en/contact-us/sales-questions</u> 

Espressif Systems 

21 

ESP32-C3-SOLO-1 User Manual v0.5 

Revision History 

## Revision History 

|Date|Version|Release notes|
|---|---|---|
|2022-07-11|v0.5|Preliminary release|



Espressif Systems 

22 

ESP32-C3-SOLO-1 User Manual v0.5 



www.espressif.com 

#### Disclaimer and Copyright Notice 

Information in this document, including URL references, is subject to change without notice. ALL THIRD PARTY’S INFORMATION IN THIS DOCUMENT IS PROVIDED AS IS WITH NO WARRANTIES TO ITS AUTHENTICITY AND ACCURACY. 

NO WARRANTY IS PROVIDED TO THIS DOCUMENT FOR ITS MERCHANTABILITY, NONINFRINGEMENT, FITNESS FOR ANY PARTICULAR PURPOSE, NOR DOES ANY WARRANTY OTHERWISE ARISING OUT OF ANY PROPOSAL, SPECIFICATION OR SAMPLE. 

All liability, including liability for infringement of any proprietary rights, relating to use of information in this document is disclaimed. No licenses express or implied, by estoppel or otherwise, to any intellectual property rights are granted herein. 

The Wi-Fi Alliance Member logo is a trademark of the Wi-Fi Alliance. The Bluetooth logo is a registered trademark of Bluetooth SIG. 

All trade names, trademarks and registered trademarks mentioned in this document are property of their respective owners, and are hereby acknowledged. 

Copyright © 2022 Espressif Systems (Shanghai) Co., Ltd. All rights reserved. 

