[English](#english) | [한국어](#korean)

<a id="english"></a>

# Gemini Robotics Makerspace: Intelligent AI Robot Puppy

A hybrid robotics architecture combining cloud-based multimodal AI (Cortex) with high-speed local control loops (Reflex) for a companion robot puppy, created for the **Google AI + Live Labs, Gemini Playground (Gemini Robotics Makerspace)** booth.

---

## Architecture Overview

The system runs on a **Raspberry Pi 4B** linked to a **Roborobo Educational Robotics CPU Board** via bidirectional level shifters, providing real-time vision, voice interaction, emotional behavioral responses, and web-based telemetry HUD monitoring.

```text
+-----------------------------------------------------------------------------------+
|                                 CORTEX (Cloud AI)                                 |
|             Google Gemini API (gemini-robotics-er-1.6-preview / flash)            |
|       Bounding box vision, multi-object detection, emotional thought & audio       |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                              RASPBERRY PI 4B (Brain)                              |
|                                                                                   |
|  +-----------------------+  +----------------------+  +------------------------+  |
|  |   Reflex (Local CV)   |  | Auditory (Speech)    |  |  Virtual Odometry      |  |
|  |  OpenCV 30 FPS Face   |  | SpeechRecognition    |  |  Table edge Fail-Safe  |  |
|  |  Tracking & Alignment |  | Korean/English STT   |  |  Coordinate Tracker    |  |
|  +-----------------------+  +----------------------+  +------------------------+  |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  |                   Flask Web Dashboard & MJPEG Video Stream                  |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
                                         |
                                         v (GPIO Active-Low Open-Drain)
+-----------------------------------------------------------------------------------+
|                           ROBOROBO CPU BOARD & ACTUATORS                          |
|                     DC Motors / Level Shifter / Beeper / LED                      |
+-----------------------------------------------------------------------------------+
```

---

## Key Features

1. **Cortex Layer (Cloud Multimodal AI)**
   - Uses `gemini-robotics-er-1.6-preview` (with automatic fallback to `gemini-2.5-flash`) via the `google-genai` SDK.
   - Detects the owner, toys, food bowls, and objects using 2D normalized bounding boxes.
   - Generates emotional thoughts and triggers contextual behaviors (e.g., barking joyfully for toys, whiping/beeping for food).

2. **Reflex Layer (Local Face Tracking)**
   - High-speed OpenCV Haar Cascade face detection loop running at 30 FPS.
   - Distance-based proportional alignment: adjusts motor heading to keep the target centered and maintains a comfortable distance (moving forward if far, backward if too close).

3. **Auditory Layer (Voice Control)**
   - Listens to microphone audio via `SpeechRecognition` and `PyAudio`.
   - Supports bilingual voice commands in Korean and English (e.g., "이리와 / Come here", "인사 / Hello", "멈춰 / Stop").

4. **Odometry & Table Safety System**
   - Software-based dead-reckoning odometry to track virtual coordinates `(X, Y, Heading)`.
   - Fail-safe boundary detection to prevent the robot from falling off a `1200mm x 800mm` table surface.
   - Calculates cross-product directional vectors to steer back into safe bounds automatically.
   - Position uncertainty estimator triggers emergency stop when open-loop drift exceeds safe limits.

5. **Flask Telemetry HUD Dashboard**
   - Live dark-mode web monitoring dashboard served on port `5000`.
   - Real-time MJPEG video stream with bounding box overlays.
   - Interactive 2D table coordinate visualizer, CPU temperature gauge, and manual odometry reset controls.

---

## Directory Structure

```text
gemini-robotics-makerspace/
├── robot_puppy_core.py               # Main brain controller & Flask HUD web server
├── robot_controller.py               # Low-level GPIO motor control & odometry engine
├── check_env.py                      # Diagnostic tool for environment & Gemini API
├── requirements.txt                  # Python dependencies
├── .env.example                      # Environment variables template
├── gemini-structured-outputs-guide.md# Guide for Gemini Pydantic structured output migration
├── project-analysis-report.md        # Technical architecture analysis report
├── LICENSE                           # Open source MIT license
├── roborobo-codes/                   # Roborobo MCU firmware project files (.rpj)
│   ├── robo-raspi-ifelse.rpj
│   └── robo-raspi-ifelse-avoid.rpj
├── __tests_and_diagnostics/          # Hardware diagnostic scripts
│   ├── diagnose_pins.py              # GPIO pin tester
│   ├── test_motor.py                 # Motor direction test
│   ├── test_level_shifter.py         # Level shifter communication test
│   └── ...
└── docs/                             # Hardware & operating system technical documentation
    ├── auto-backup-n-saving-errors.txt
    ├── battery-capacity-plan.txt
    ├── camera-n-battery.txt
    ├── energy-save.txt
    └── overlay-filesystem.txt
```

---

## Hardware Setup & Pin Mapping

The Raspberry Pi (3.3V logic) communicates with the Roborobo CPU Board (5V logic) through a bidirectional level shifter using **Active-Low Open-Drain** signaling.

| Raspberry Pi Pin (BCM) | Function | Level Shifter | Roborobo CPU Input |
| :--- | :--- | :--- | :--- |
| **GPIO 17** | Forward (IN1) | Channel 1 | Motor Forward |
| **GPIO 27** | Turn Left (IN2) | Channel 2 | Motor Left |
| **GPIO 22** | Turn Right (IN3) | Channel 3 | Motor Right |
| **GPIO 23** | Backward (IN4) | Channel 4 | Motor Backward |
| **GND** | Common Ground | GND | GND |
| **5V / 3.3V** | Power Rail Reference | HV / LV | VCC |

---

## Prerequisites & Installation

1. **Hardware & System Prerequisites**:
   - Raspberry Pi 4B (2GB+ RAM recommended), USB Webcam, USB Microphone, Roborobo CPU Board with DC motors, Bidirectional Level Shifter.
   - Raspberry Pi OS (Debian 12 Bookworm / 11 Bullseye), Python 3.10 or higher.

2. **Clone and Install Dependencies**:
   ```bash
   git clone https://github.com/your-username/gemini-robotics-makerspace.git
   cd gemini-robotics-makerspace

   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **API Key Configuration**:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` to include your Gemini API key:
   ```env
   GEMINI_API_KEY=AIzaSyYourActualGeminiApiKeyHere
   ```

4. **Hardware & Environment Verification**:
   ```bash
   python3 check_env.py
   python3 __tests_and_diagnostics/diagnose_pins.py
   ```

5. **Running the Main Robot System**:
   ```bash
   python3 robot_puppy_core.py
   ```
   Access HUD Dashboard at: `http://<raspberry-pi-ip>:5000`

---

## Technical Documentation

- **[project-analysis-report.md](project-analysis-report.md)**: Detailed report on threading architecture, safety odometry mathematics, and cross-product recovery algorithms.
- **[gemini-structured-outputs-guide.md](gemini-structured-outputs-guide.md)**: Implementation guide for Pydantic schema enforcement on Gemini API responses.
- **[docs/](docs/)**: Operational guides covering Raspberry Pi overlay filesystems, battery power management, camera optimization, and automatic fail-safe recovery.

---

## License

This project is released under the [MIT License](LICENSE).

<div style="page-break-before: always;"></div>

---

[English](#english) | [한국어](#korean)

<a id="korean"></a>

# Gemini Robotics Makerspace: 지능형 AI 로봇 강아지

Google Cloud Gemini API와 라즈베리 파이 4B, 그리고 로보로보 교육용 키트 CPU 보드를 결합하여 구현한 지능형 로봇 강아지(Robotic Puppy) 코어 시스템입니다. **Google AI + Live Labs, Gemini Playground (Gemini Robotics Makerspace)** 부스 실제 시연용으로 제작되었습니다.

---

## 아키텍처 개요

시스템은 **라즈베리 파이 4B**를 두뇌로 삼아 양방향 레벨 시프터를 통해 **로보로보 CPU 보드**와 인터페이싱하며, 실시간 비전, 음성 인식, 감정 반응 동작, 그리고 웹 기반 텔레메트리 HUD 모니터링을 동시에 수행합니다.

```text
+-----------------------------------------------------------------------------------+
|                                 CORTEX (Cloud AI)                                 |
|             Google Gemini API (gemini-robotics-er-1.6-preview / flash)            |
|       바운딩 박스 인식, 다중 오브젝트 감지, 감정 독백(Thought) 도출 및 행동 결정   |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                              RASPBERRY PI 4B (두뇌)                               |
|                                                                                   |
|  +-----------------------+  +----------------------+  +------------------------+  |
|  |   Reflex (로컬 CV)    |  |  Auditory (청각)     |  |   Virtual Odometry     |  |
|  |  OpenCV 30 FPS 얼굴   |  | SpeechRecognition    |  |  테이블 경계 이탈 방지 |  |
|  |  추적 및 정렬 서보    |  | 한국어/영어 음성 인식|  |  가상 좌표 추적기      |  |
|  +-----------------------+  +----------------------+  +------------------------+  |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  |                 Flask 웹 대시보드 & MJPEG 비디오 스트리밍                   |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
                                         |
                                         v (GPIO Active-Low Open-Drain)
+-----------------------------------------------------------------------------------+
|                        ROBOROBO CPU BOARD & 액추에이터                            |
|                     DC 모터 / 레벨 시프터 / 부저 / LED                            |
+-----------------------------------------------------------------------------------+
```

---

## 주요 기능

1. **Cortex 레이어 (클라우드 인공지능)**
   - `google-genai` SDK를 통해 `gemini-robotics-er-1.6-preview` 모델을 가동하고 예외 발생 시 `gemini-2.5-flash`로 자동 대체(Fallback)됩니다.
   - 카메라 프레임에서 주인(Owner), 장난감, 밥그릇 등 주요 사물을 2D Bounding Box 단위로 감지합니다.
   - 로봇의 감정을 독백 형태의 Thought으로 생성하며, 장난감 감지 시 짖고 꼬리를 치거나 밥그릇 감지 시 소리를 내는 등 상호작용합니다.

2. **Reflex 레이어 (로컬 얼굴 추적)**
   - 30 FPS 주기의 OpenCV Haar Cascade 기반 로컬 얼굴 감지 및 정렬 루프.
   - 감지된 대상과의 거리에 따라 전진, 후진, 좌/우 회전 제어를 수행하여 주인을 화면 중앙에 고정하고 적정 거리를 유지합니다.

3. **Auditory 레이어 (음성 제어)**
   - `SpeechRecognition` 및 `PyAudio`를 활용하여 마이크 입력을 실시간 감지합니다.
   - 한국어 및 영어 음성 명령("이리와", "인사", "멈춰", "Come here", "Hello", "Stop")을 지원합니다.

4. **오도메트리 & 테이블 안전 시스템**
   - 센서가 라즈베리 파이에 직접 연결되지 않은 환경을 극복하기 위해 소프트웨어 기반 가상 좌표 추적 `(X, Y, Heading)`을 가동합니다.
   - `1200mm x 800mm` 테이블 경계 이탈 방지(Fail-Safe) 로직을 갖추어 경계 감지 시 외적(Cross Product)을 계산해 안전 구역으로 자동 복귀합니다.
   - 이동량/회전량 누적에 따른 불확실성이 한계를 초과하면 로봇을 정지시키고 Re-home을 요청합니다.

5. **Flask 텔레메트리 HUD 대시보드**
   - 포트 `5000`에서 가동되는 다크 모드 실시간 대시보드.
   - Bounding Box 오버레이가 적용된 MJPEG 비디오 스트리밍.
   - 인터랙티브 2D 테이블 맵, CPU 온도 게이지, 오도메트리 리셋 기능을 제공합니다.

---

## 디렉토리 구조

```text
gemini-robotics-makerspace/
├── robot_puppy_core.py               # 메인 두뇌 제어기 & Flask HUD 웹 서버
├── robot_controller.py               # 로컬 GPIO 모터 제어 & 오도메트리 엔진
├── check_env.py                      # 환경 및 Gemini API 통신 진단 도구
├── requirements.txt                  # 파이썬 의존성 패키지 명세
├── .env.example                      # 환경변수 템플릿
├── gemini-structured-outputs-guide.md# Gemini Pydantic 구조화 출력 전환 가이드
├── project-analysis-report.md        # 시스템 아키텍처 상세 분석 보고서
├── LICENSE                           # MIT 오픈소스 라이선스
├── roborobo-codes/                   # 로보로보 CPU 펌웨어 프로젝트 파일 (.rpj)
│   ├── robo-raspi-ifelse.rpj
│   └── robo-raspi-ifelse-avoid.rpj
├── __tests_and_diagnostics/          # 하드웨어 자가 진단 스크립트 모음
│   ├── diagnose_pins.py              # GPIO 핀 테스트
│   ├── test_motor.py                 # 모터 방향 테스트
│   ├── test_level_shifter.py         # 레벨 시프터 통신 테스트
│   └── ...
└── docs/                             # 카메라, 배터리, 오버레이 파일시스템 운영 문서
    ├── auto-backup-n-saving-errors.txt
    ├── battery-capacity-plan.txt
    ├── camera-n-battery.txt
    ├── energy-save.txt
    └── overlay-filesystem.txt
```

---

## 하드웨어 결선 및 핀 맵

라즈베리 파이(3.3V 논리레벨)와 로보로보 CPU 보드(5V 논리레벨)는 양방향 레벨 시프터를 거쳐 **Active-Low Open-Drain** 신호로 연결됩니다.

| 라즈베리 파이 핀 (BCM) | 기능 | 레벨 시프터 | 로보로보 CPU 입력 |
| :--- | :--- | :--- | :--- |
| **GPIO 17** | 전진 (IN1) | 채널 1 | 모터 전진 |
| **GPIO 27** | 좌회전 (IN2) | 채널 2 | 모터 좌회전 |
| **GPIO 22** | 우회전 (IN3) | 채널 3 | 모터 우회전 |
| **GPIO 23** | 후진 (IN4) | 채널 4 | 모터 후진 |
| **GND** | 공통 접지 | GND | GND |
| **5V / 3.3V** | 전원 레일 | HV / LV | VCC |

---

## 사전 요구 사항 및 설치 방법

1. **사전 요구 사항**:
   - 라즈베리 파이 4B (2GB RAM 이상 권장), USB 웹캠, USB 마이크, DC 모터가 포함된 로보로보 CPU 보드, 양방향 레벨 시프터.
   - Raspberry Pi OS (Debian 12 Bookworm / 11 Bullseye), Python 3.10 이상.

2. **저장소 클론 및 패키지 설치**:
   ```bash
   git clone https://github.com/your-username/gemini-robotics-makerspace.git
   cd gemini-robotics-makerspace

   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **API 키 설정**:
   ```bash
   cp .env.example .env
   ```
   `.env` 파일에 발급받은 Gemini API 키를 입력합니다:
   ```env
   GEMINI_API_KEY=본인의_gemini_api_key_입력
   ```

4. **환경 및 하드웨어 검증**:
   ```bash
   python3 check_env.py
   python3 __tests_and_diagnostics/diagnose_pins.py
   ```

5. **메인 로봇 시스템 가동**:
   ```bash
   python3 robot_puppy_core.py
   ```
   동일 네트워크상의 브라우저에서 HUD 대시보드에 접속합니다: `http://<라즈베리파이-IP>:5000`

---

## 기술 문서 안내

- **[project-analysis-report.md](project-analysis-report.md)**: 멀티스레딩 구조, 오도메트리 수학 공식을 다룬 시스템 분석 보고서.
- **[gemini-structured-outputs-guide.md](gemini-structured-outputs-guide.md)**: Gemini API 응답을 Pydantic 규격으로 강제하기 위한 가이드.
- **[docs/](docs/)**: 라즈베리 파이 오버레이 파일시스템, 전원 관리 및 카메라 관련 기술 문서.

---

## 라이선스

본 프로젝트는 [MIT License](LICENSE)에 따라 자유롭게 이용 및 수정이 가능합니다.
