import time
import RPi.GPIO as GPIO

PIN_FORWARD = 17
PIN_LEFT = 27
PIN_RIGHT = 22
PIN_SOUND = 23

pins = [PIN_FORWARD, PIN_LEFT, PIN_RIGHT, PIN_SOUND]

def set_all_stop():
    """[Active-High 정지] 모든 핀에 0V (LOW) 전기를 적극적으로 출력하여 완전히 끕니다.
    로보로보 보드는 0V가 들어오면 스위치를 '뗀 것(OFF)'으로 인식하므로 즉각 정지합니다."""
    print("⏹️ 모든 핀 LOW (0V) 출력 -> 물리적 완전 정지")
    for pin in pins:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)

def set_pin_active_high(active_pin):
    """[Active-High 구동] 특정 핀에만 3.3V (HIGH -> 시프터 거쳐 5V) 전기를 공급하여 동작시킵니다.
    나머지 핀은 0V (LOW)를 유지하여 꺼진 상태로 둡니다."""
    for pin in pins:
        GPIO.setup(pin, GPIO.OUT)
        if pin == active_pin:
            GPIO.output(pin, GPIO.HIGH)
        else:
            GPIO.output(pin, GPIO.LOW)

try:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    print('=== [Active-High 방식] 정방향 신호 및 정지 제어 검증 ===')
    
    # 1. 초기 상태: 모두 0V로 정지 유도
    set_all_stop()
    print('1. 초기 대기 상태 (2초) - 로봇이 미동도 없이 정지해 있어야 정상입니다.')
    time.sleep(2)

    # 2. 전진 구동 (PIN_FORWARD 에 3.3V -> 5V 인가)
    print('\n2. 전진 모터 동작 시작! (FORWARD 핀 -> HIGH / 5V 출력)')
    set_pin_active_high(PIN_FORWARD)
    time.sleep(3)

    # 3. 전진 정지 테스트 (다시 모든 핀 0V로 내림)
    print('\n3. [★핵심] 전진 모터 정지 명령! (모든 핀 LOW / 0V 출력)')
    set_all_stop()
    print('   -> 이때 모터가 칼같이 정지해야 정상입니다! (3초 대기)')
    time.sleep(3)

    # 4. 좌회전 구동 (PIN_LEFT 에 3.3V -> 5V 인가)
    print('\n4. 좌회전 모터 동작 시작! (LEFT 핀 -> HIGH / 5V 출력)')
    set_pin_active_high(PIN_LEFT)
    time.sleep(3)

    # 5. 최종 정지
    print('\n5. 최종 정지 명령! (모든 핀 LOW / 0V 출력)')
    set_all_stop()
    print('   -> 로봇이 완벽하게 정지해 있어야 합니다. (2초 후 종료)')
    time.sleep(2)

except Exception as e:
    print(f'오류 발생: {e}')
finally:
    set_all_stop()
    print('\n테스트 완료. 모든 핀이 안전한 LOW(정지) 상태로 유지됩니다.')
