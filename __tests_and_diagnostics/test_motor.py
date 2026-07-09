import time
import RPi.GPIO as GPIO

PIN_FORWARD = 17

try:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    
    print('0. 초기화: HIGH(3.3V) 출력 -> 모터 정지 상태')
    GPIO.setup(PIN_FORWARD, GPIO.OUT)
    GPIO.output(PIN_FORWARD, GPIO.HIGH)
    time.sleep(2)
    
    print('1. 신호 연결: LOW(0V) 출력 -> 모터 회전 시작!')
    GPIO.output(PIN_FORWARD, GPIO.LOW)
    time.sleep(2)
    
    print('2. 신호 차단: HIGH(3.3V) 출력 -> 모터 정지!')
    GPIO.output(PIN_FORWARD, GPIO.HIGH)
except Exception as e:
    print(f'오류 발생: {e}')
finally:
    # 종료 시에도 확실하게 정지시키기 위해 HIGH 유지
    GPIO.output(PIN_FORWARD, GPIO.HIGH)
    print('테스트 종료.')
