import logging
import time

import serial.tools.list_ports

logger = logging.getLogger(__name__)

# Potential baud rates for Yipwip P-Plus
baud_rates = [115200, 57600, 38400, 9600, 460800]
version_cmd = b'\xFE\x00\x21\x02\x23'

def find_radio_path(vid=None, pid=None, serial_number=None):
    """
    Finds the device path for a radio based on hardware identifiers.
    """
    ports = serial.tools.list_ports.comports()

    for port in ports:
        # Match by Serial Number (most reliable if multiple same-model radios are used)
        if serial_number and port.serial_number == serial_number:
            return port.device

        # Match by VID and PID
        if vid and pid and port.vid == vid and port.pid == pid:
            return port.device

    return None


def detect_baud_rate(port):
    for baud in baud_rates:
        logger.info(f"Trying {baud} baud...")
        with serial.Serial(port, baud, timeout=1) as ser:
            ser.reset_input_buffer()
            ser.write(version_cmd)
            time.sleep(0.5)
            response = ser.readall()

            if len(response) > 0:
                logger.info(f"Success! Detected baud rate: {baud}")
                return baud
    return None
