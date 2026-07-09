import serial
import time
import sys

def test_protocols(port='/dev/ttyUSB0', baudrate=9600):
    try:
        ser = serial.Serial(port, baudrate, timeout=1)
        print(f"Connected to {port} at {baudrate} baud.")
    except Exception as e:
        print(f"Failed to connect: {e}")
        return

    # Button 1 is "Forward" in the Rogic program.
    CMD = 0x01
    
    # Generate various possible packet formats
    packets = {
        "Format 1 (AA 55 + cmd)": bytes([0xAA, 0x55, CMD]),
        "Format 2 (AA 55 + cmd + ~cmd)": bytes([0xAA, 0x55, CMD, (~CMD) & 0xFF]),
        "Format 3 (FF 55 + cmd + ~cmd)": bytes([0xFF, 0x55, CMD, (~CMD) & 0xFF]),
        "Format 4 (AA 55 + length + cmd)": bytes([0xAA, 0x55, 0x01, CMD]),
        "Format 5 (AA 55 + length + cmd + chksum)": bytes([0xAA, 0x55, 0x01, CMD, CMD]),
        "Format 6 (AA 55 + 04 + cmd + 00 + chksum)": bytes([0xAA, 0x55, 0x04, CMD, 0x00, CMD+4]),
        "Format 7 (Robotis RC-100)": bytes([0xFF, 0x55, CMD, (~CMD)&0xFF, 0x00, 0xFF]),
        "Format 8 (ASCII 1)": b"1",
        "Format 9 (ASCII F)": b"F",
        "Format 10 (Raw int string)": b"01",
        "Format 11 (AA 55 + cmd + 00)": bytes([0xAA, 0x55, CMD, 0x00]),
        "Format 12 (AA 55 + 00 + cmd)": bytes([0xAA, 0x55, 0x00, CMD]),
        "Format 13 (AA AA + cmd)": bytes([0xAA, 0xAA, CMD]),
        "Format 14 (55 55 + cmd)": bytes([0x55, 0x55, CMD])
    }

    print("Starting brute-force protocol test...")
    print("WARNING: Make sure the robot is safely placed (e.g., wheels off the ground)!")
    print("If the robot moves FORWARD, note the Format Number and press Ctrl+C.\n")
    
    time.sleep(3)

    for i in range(3): # Try 3 rounds
        for name, packet in packets.items():
            print(f"Sending {name}: {packet.hex()} ...")
            # Send the packet 3 times to ensure it is received
            for _ in range(3):
                ser.write(packet)
                time.sleep(0.1)
            
            # Wait to observe movement
            time.sleep(2.0)
            
            # Send STOP command in the same format just in case it moved
            stop_packet = bytearray(packet)
            if CMD in stop_packet:
                stop_packet[stop_packet.index(CMD)] = 0x00 # 0x00 is usually STOP
            ser.write(stop_packet)
            time.sleep(1.0)

    print("\nTest completed.")

if __name__ == "__main__":
    test_protocols()
