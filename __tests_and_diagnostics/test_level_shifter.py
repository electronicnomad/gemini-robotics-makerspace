import time
import RPi.GPIO as GPIO

PIN_FORWARD = 17

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(PIN_FORWARD, GPIO.OUT)

try:
    print('=== 레벨 시프터 신호 점검 테스트 ===')
    print('Ctrl+C를 누르면 종료됩니다.')
    while True:
        print('\n[정지 신호] GPIO 17 -> HIGH (3.3V 출력)')
        print('  -> (예상) 로보로보 정지!')
        print('  -> 테스터기가 있다면: 파이 핀은 3.3V, 시프터 HV1 핀은 5V가 나와야 정상')
        GPIO.output(PIN_FORWARD, GPIO.HIGH)
        time.sleep(5)
        
        print('\n[동작 신호] GPIO 17 -> LOW (0V 출력)')
        print('  -> (예상) 로보로보 전진!')
        print('  -> 테스터기가 있다면: 파이 핀은 0V, 시프터 HV1 핀은 0V가 나와야 정상')
        GPIO.output(PIN_FORWARD, GPIO.LOW)
        time.sleep(5)
except KeyboardInterrupt:
    pass
finally:
    GPIO.output(PIN_FORWARD, GPIO.HIGH)
    GPIO.cleanup()
    print('\n테스트 종료.')
