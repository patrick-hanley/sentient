"""Reset an Atom over USB and print its serial log (boot self-test, Wi-Fi, codec repairs).

Usage: .venv/bin/python -I tools/serial_read.py /dev/cu.usbmodemXXXX [seconds=20]
Close the Arduino IDE Serial Monitor first (it holds the port).
"""
import sys
import time

import serial

port = sys.argv[1]
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 20

s = serial.Serial()
s.port, s.baudrate, s.timeout = port, 115200, 0.2
s.dtr = False
s.rts = False
s.open()
s.rts = True          # USB-Serial/JTAG reset: RTS pulse with DTR low
time.sleep(0.1)
s.rts = False
s.close()
time.sleep(0.05)      # USB re-enumerates; reopen as fast as possible to catch the boot lines

end = time.time() + secs
while time.time() < end:
    try:
        s = serial.Serial(port, 115200, timeout=0.2)
        break
    except serial.SerialException:
        time.sleep(0.2)
while time.time() < end:
    try:
        b = s.read(512)
    except serial.SerialException:
        time.sleep(0.2)
        continue
    if b:
        sys.stdout.write(b.decode(errors="replace"))
        sys.stdout.flush()
