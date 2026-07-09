import RPi.GPIO as GPIO
import time

# 앞서 성공하셨던 올바른 핀 번호를 사용합니다.
IN1_PIN = 17 # 전진

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

def setup_port():
    # 핀을 출력 모드로 설정하고 초기 상태를 HIGH(3.3V)로 만들어 모터를 '정지' 상태로 둡니다.
    GPIO.setup(IN1_PIN, GPIO.OUT)
    GPIO.output(IN1_PIN, GPIO.HIGH)

def press_port():
    # LOW(0V)를 출력하여 로보로보 센서를 '눌림' 상태로 만듭니다.
    GPIO.output(IN1_PIN, GPIO.LOW)

def release_port():
    # HIGH(3.3V)를 강제로 출력하여 로보로보 센서를 '떨어짐(정지)' 상태로 강제합니다.
    GPIO.output(IN1_PIN, GPIO.HIGH)

try:
    print('GPIO 모터 강제 정지 테스트를 시작합니다.')
    setup_port()
    time.sleep(1)
    
    print('모터를 2초간 회전시킵니다... (LOW 전송)')
    press_port()
    time.sleep(2)
    
    print('모터를 정지시킵니다!!! (HIGH 전송)')
    release_port()
    time.sleep(2)
    
    print('테스트 완료. 모터가 멈췄다면 성공입니다!')
finally:
    GPIO.cleanup()
