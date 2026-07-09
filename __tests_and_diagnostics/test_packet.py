import serial
import time
try:
    s = serial.Serial('/dev/ttyUSB0', 9600)
    print('Connected')
    # 1번 버튼 데이터 (0x01) 패킷 보내기
    # 예: AA 01 FE
    data = 1
    packet = bytearray([0xAA, data, ~data & 0xFF])
    s.write(packet)
    print(f'Sent {packet}')
    time.sleep(1)
    s.close()
except Exception as e:
    print(e)
