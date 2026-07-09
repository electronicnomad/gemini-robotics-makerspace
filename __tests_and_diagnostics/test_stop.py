import time
import RPi.GPIO as GPIO

PIN_FORWARD = 17
PIN_LEFT = 27
PIN_RIGHT = 22
PIN_BACK = 23

pins = [PIN_FORWARD, PIN_LEFT, PIN_RIGHT, PIN_BACK]

try:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    print('1. 모든 핀을 3.3V(HIGH) 출력 상태로 강제 고정합니다. (플로팅 방지 -> 완전 정지!)')
    for pin in pins:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.HIGH)

    time.sleep(2)

    print('2. 전진 모터 동작! (Forward 핀을 0V로 만듦)')
    GPIO.output(PIN_FORWARD, GPIO.LOW)
    time.sleep(2)

    print('3. 전진 모터 정지! (Forward 핀에 3.3V 전기를 강제로 쏩니다!)')
    GPIO.output(PIN_FORWARD, GPIO.HIGH)
    time.sleep(2)

    print('4. 좌회전 모터 동작! (Left 핀 0V)')
    GPIO.output(PIN_LEFT, GPIO.LOW)
    time.sleep(2)

    print('5. 좌회전 모터 정지!')
    GPIO.output(PIN_LEFT, GPIO.HIGH)
    time.sleep(1)

    print('6. 후진 모터 동작! (Left 핀 0V)')
    GPIO.output(PIN_BACK, GPIO.LOW)
    time.sleep(2)

    print('7. 후진 모터 정지!')
    GPIO.output(PIN_BACK, GPIO.HIGH)
    time.sleep(1)

except Exception as e:
    print(f'오류: {e}')
finally:
    for pin in pins:
        # 프로그램을 종료해도 모터가 멋대로 돌지 않도록 계속 3.3V를 유지합니다.
        GPIO.output(pin, GPIO.HIGH)
    # GPIO.cleanup()을 하면 핀이 다시 플로팅 상태(IN)가 되어 로봇이 미쳐 날뛸 수 있으므로 생략합니다.
    print('테스트 완료 - 이제 로봇이 완벽하게 멈춰있어야 합니다.')
