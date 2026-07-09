import time
import sys

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

PIN_FORWARD = 17  # IN1
PIN_LEFT = 27     # IN2
PIN_RIGHT = 22    # IN3
PIN_BACKWARD = 23 # IN4

pins = {
    "FORWARD (IN1, 전진)": PIN_FORWARD,
    "LEFT (IN2, 좌회전)": PIN_LEFT,
    "RIGHT (IN3, 우회전)": PIN_RIGHT,
    "BACKWARD (IN4, 후진)": PIN_BACKWARD
}

def run_diagnostics():
    if not GPIO_AVAILABLE:
        print("❌ 오류: 이 스크립트는 라즈베리파이에서 직접 실행해야 합니다 (RPi.GPIO 모듈 없음).")
        sys.exit(1)

    print("==================================================")
    print("      🔍 로보로보 GPIO 제어 하드웨어 정밀 진단기      ")
    print("==================================================")
    print("이 도구는 하드웨어 결선과 보드 상태를 단계별로 검증합니다.")
    print("시작하기 전에 아래 사항을 반드시 확인해 주세요:")
    print("  1. 로보로보 CPU 보드의 USB 케이블이 PC에서 분리되었는가?")
    print("  2. 로보로보 CPU 보드의 전원이 켜져 있는가? (배터리 전원 ON)")
    print("  3. 로보로보 CPU 보드의 [START/RESET] 버튼을 눌렀는가?")
    print("  4. 레벨 시프터의 LV 측은 라즈베리파이, HV 측은 로보로보 입력(IN1~IN4)에 연결되었는가?")
    print("  5. 라즈베리파이와 로보로보 보드의 GND(그라운드)가 서로 연결되었는가?")
    print("==================================================")
    
    input("\n준비가 완료되었다면 [Enter] 키를 누르세요...")

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    # 1. 초기화 및 대기
    print("\n[Step 1] 모든 핀을 HIGH (3.3V) 출력으로 설정합니다.")
    print("  -> 기대 상태: 로봇이 완전히 멈춰 있어야 합니다.")
    for name, pin in pins.items():
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.HIGH)
    
    print("  -> 3초간 대기합니다. 로봇이 움직이는지 확인하세요.")
    time.sleep(3)

    # 2. 개별 핀 테스트
    for name, pin in pins.items():
        print(f"\n[Step 2] ➡️ {name} 테스트 시작")
        print(f"  -> {name} 핀을 LOW (0V)로 내립니다! (작동 신호)")
        print("  -> 기대 상태: 해당하는 모터가 회전하거나 소리가 나야 합니다.")
        
        GPIO.output(pin, GPIO.LOW)
        time.sleep(3)
        
        print(f"  -> {name} 핀을 다시 HIGH (3.3V)로 올립니다! (정지 신호)")
        print("  -> 기대 상태: 동작이 칼같이 멈춰야 합니다.")
        GPIO.output(pin, GPIO.HIGH)
        time.sleep(2)

    print("\n==================================================")
    print("진단 테스트 완료!")
    print("  - 만약 특정 단계에서 전혀 반응이 없었다면:")
    print("    1) CPU 보드의 START 버튼이 눌렸는지 꼭 확인하세요.")
    print("    2) 레벨 시프터의 전원(VCCA=3.3V, VCCB=5V, GND) 결선을 확인하세요.")
    print("    3) 라즈베리파이의 실제 배선 핀 번호(BCM 기준 17, 27, 22, 23)를 다시 확인하세요.")
    print("==================================================")

if __name__ == "__main__":
    try:
        run_diagnostics()
    except KeyboardInterrupt:
        print("\n사용자가 테스트를 중단했습니다.")
    finally:
        if GPIO_AVAILABLE:
            for pin in pins.values():
                GPIO.output(pin, GPIO.HIGH)
            print("\n모든 GPIO 핀을 안전하게 HIGH(정지) 상태로 유지한 채 종료합니다.")
