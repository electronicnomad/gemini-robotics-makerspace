import serial
import time

ports = ['/dev/ttyUSB0', '/dev/ttyACM0']
baudrates = [9600, 57600, 115200]

def try_send(data):
    for baud in baudrates:
        for port in ports:
            try:
                s = serial.Serial()
                s.port = port
                s.baudrate = baud
                s.timeout = 0.5
                # DTR 끄기 (보드 리셋 방지 - 다운로드 모드 진입 방지)
                s.dtr = False
                s.open()
            except Exception:
                continue
            
            print(f'Testing {port} at {baud} baud')
            
            # Format 1: Raw byte
            s.write(bytes([data]))
            
            # Format 2: ROBOTIS style (AA 55 or FF 55)
            s.write(bytearray([0xFF, 0x55, data, ~data & 0xFF, 0x00]))
            s.write(bytearray([0xAA, data, ~data & 0xFF]))
            s.write(bytearray([0x55, data, ~data & 0xFF]))
            
            # Format 3: simple [data, ~data]
            s.write(bytearray([data, ~data & 0xFF]))
            
            # Format 4: [0xFF, data]
            s.write(bytearray([0xFF, data]))
            
            time.sleep(0.5)
            s.close()

print('Brute forcing 전진 (1) 명령...')
try_send(1)
print('Brute forcing 좌회전 (3) 명령...')
try_send(3)
print('Brute forcing 정지 (0) 명령...')
try_send(0)
print('Done.')
