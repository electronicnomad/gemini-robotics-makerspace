#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
라인 감지 피드백 신호 (로보로보 -> 레벨시프터 -> Pi BCM 24) 수신 테스트.

사용법:
  python3 test_line_signal.py

확인 순서:
  1. 로보로보 전원 OFF 상태로 실행 -> LOW 로 안정되어 있어야 정상
     (HIGH 로 떠 있으면: 레벨시프터 풀업 때문. 로보로보 프로그램이 시작 시
      출력 포트를 LOW 로 초기화하면 해결됨)
  2. 로보로보 전원 ON, .rpj 프로그램 실행 -> 여전히 LOW 여야 정상
  3. 라인 센서를 검은 마커(또는 검은 테이프/손가락)로 가림
     -> 화면에 HIGH 전환 + 지속시간이 찍혀야 성공
"""
import time
import RPi.GPIO as GPIO

PIN_LINE_SIGNAL = 24   # BCM 24 (물리핀 18) - 레벨시프터 LV1 에서 들어오는 신호

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
# 내부 풀업/풀다운은 끕니다: 레벨시프터 모듈의 10k 풀업과 싸우지 않게 (PUD_OFF)
GPIO.setup(PIN_LINE_SIGNAL, GPIO.IN, pull_up_down=GPIO.PUD_OFF)

print('=' * 60)
print(f'라인 신호 모니터 시작 (BCM {PIN_LINE_SIGNAL}, 물리핀 18)')
print('Ctrl+C 로 종료. 라인 센서를 검은 마커 위에 올려 보세요.')
print('=' * 60)

last_level = GPIO.input(PIN_LINE_SIGNAL)
level_since = time.time()
edge_count = 0
last_status_print = 0.0

print(f'시작 레벨: {"HIGH (감지 중?)" if last_level else "LOW (정상 대기)"}')

try:
    while True:
        level = GPIO.input(PIN_LINE_SIGNAL)

        if level != last_level:
            now = time.time()
            held_ms = (now - level_since) * 1000.0
            edge_count += 1
            if level:
                print(f'[{time.strftime("%H:%M:%S")}] LOW -> HIGH : 라인 감지 시작! '
                      f'(직전 LOW 유지 {held_ms:.0f} ms, 누적 전환 {edge_count}회)')
            else:
                print(f'[{time.strftime("%H:%M:%S")}] HIGH -> LOW : 감지 종료. '
                      f'(HIGH 유지 {held_ms:.0f} ms, 누적 전환 {edge_count}회)')
            last_level = level
            level_since = now

        # 10초마다 살아있음 표시 (전환이 전혀 없을 때 배선 의심용)
        if time.time() - last_status_print > 10.0:
            print(f'  ... 대기 중 (현재 {"HIGH" if last_level else "LOW"}, '
                  f'유지 {time.time() - level_since:.0f}초, 전환 {edge_count}회)')
            last_status_print = time.time()

        time.sleep(0.002)   # 2ms 폴링: 190ms짜리 짧은 감지도 놓치지 않음

except KeyboardInterrupt:
    print(f'\n종료. 총 전환 {edge_count}회.')
finally:
    GPIO.cleanup(PIN_LINE_SIGNAL)
