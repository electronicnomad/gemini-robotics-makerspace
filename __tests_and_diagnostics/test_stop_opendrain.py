import time
import RPi.GPIO as GPIO

PIN_FORWARD = 17
PIN_LEFT = 27
PIN_RIGHT = 22
PIN_SOUND = 23

pins = [PIN_FORWARD, PIN_LEFT, PIN_RIGHT, PIN_SOUND]

def set_all_stop():
    """모든 핀을 INPUT(입력) 모드로 전환하고, 
    라즈베리파이 자체의 내부 풀업(PUD_UP)을 강제로 켜서 누설 전류를 원천 차단합니다.
    이렇게 하면 전압이 완벽한 5V HIGH로 치솟으며 즉각 정지합니다."""
    print("⏹️ 모든 핀 INPUT 및 내부 풀업(PUD_UP) 활성화 (누설 전류 완벽 차단!)")
    for pin in pins:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def set_pin_active_low(active_pin):
    """특정 핀만 OUTPUT 모드로 변경한 뒤 LOW(0V)로 내려 동작 신호를 줍니다.
    나머지 핀은 INPUT 및 PUD_UP 모드를 보존하여 완벽한 정지 전압을 유지합니다."""
    for pin in pins:
        if pin == active_pin:
            # 동작시킬 핀은 풀업 해제 후 OUTPUT LOW
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW)
        else:
            # 대기할 핀들은 확실하게 INPUT 및 내부 풀업 유지
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

try:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    print('=== [Open-Drain 방식] 신호 및 정지 제어 점검 ===')
    
    # 1. 초기 상태: 모두 끊어서 정지 유도
    set_all_stop()
    print('1. 초기 대기 상태 (2초) - 로봇이 완전히 멈춰 있어야 합니다.')
    time.sleep(2)

    # 2. 전진 구동 (PIN_FORWARD 만 0V로 내림)
    print('\n2. 전진 모터 동작 시작! (FORWARD 핀 -> OUTPUT LOW / 0V)')
    set_pin_active_low(PIN_FORWARD)
    time.sleep(3)

    # 3. 전진 정지 테스트 (모든 핀을 INPUT으로 끊음)
    print('\n3. [중요] 전진 모터 정지 명령! (모든 핀 INPUT 모드로 전환)')
    set_all_stop()
    print('   -> 이때 모터가 칼같이 정지해야 정상입니다! (3초 대기)')
    time.sleep(3)

    # 4. 좌회전 구동 (PIN_LEFT 만 0V로 내림)
    print('\n4. 좌회전 모터 동작 시작! (LEFT 핀 -> OUTPUT LOW / 0V)')
    set_pin_active_low(PIN_LEFT)
    time.sleep(3)

    # 5. 최종 정지
    print('\n5. 최종 정지 명령! (모든 핀 INPUT 모드로 전환)')
    set_all_stop()
    print('   -> 로봇이 완벽하게 정지해 있어야 합니다. (2초 후 종료)')
    time.sleep(2)

except Exception as e:
    print(f'오류 발생: {e}')
finally:
    set_all_stop()
    print('\n테스트 완료. 모든 핀이 안전한 INPUT(정지) 상태로 유지됩니다.')
