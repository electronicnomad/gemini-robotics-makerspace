import time
import RPi.GPIO as GPIO

PIN_FORWARD = 17
PIN_LEFT = 27
PIN_RIGHT = 22
PIN_SOUND = 23

pins = [PIN_FORWARD, PIN_LEFT, PIN_RIGHT, PIN_SOUND]

try:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    print('1. 모든 핀을 INPUT(플로팅) 상태로 초기화하여 선이 빠진 것과 똑같이 만듭니다.')
    for pin in pins:
        # PUD_OFF로 파이 내부의 풀다운 저항을 꺼버립니다. (먹통 현상 해결!)
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_OFF)

    time.sleep(2)

    print('2. 전진 모터 동작! (Forward 핀만 0V로 만듦)')
    GPIO.setup(PIN_FORWARD, GPIO.OUT)
    GPIO.output(PIN_FORWARD, GPIO.LOW)
    time.sleep(2)

    print('3. 전진 모터 정지! (Forward 핀을 다시 플로팅으로 변경)')
    # 다시 선을 뺀 것처럼 만듭니다. (3.3V 한계 우회!)
    GPIO.setup(PIN_FORWARD, GPIO.IN, pull_up_down=GPIO.PUD_OFF)
    time.sleep(2)

    print('4. 좌회전 모터 동작! (Left 핀을 0V로 만듦)')
    GPIO.setup(PIN_LEFT, GPIO.OUT)
    GPIO.output(PIN_LEFT, GPIO.LOW)
    time.sleep(2)

    print('5. 좌회전 모터 정지!')
    GPIO.setup(PIN_LEFT, GPIO.IN, pull_up_down=GPIO.PUD_OFF)

except Exception as e:
    print(f'오류: {e}')
finally:
    for pin in pins:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_OFF)
    GPIO.cleanup()
    print('테스트 완료')
