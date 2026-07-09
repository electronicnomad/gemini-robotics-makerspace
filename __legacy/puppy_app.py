import cv2
import time
import threading
import re
import os
import math
import speech_recognition as sr
from flask import Flask, Response, render_template_string
from google import genai
from PIL import Image

# ==========================================
# Configurations
# ==========================================
# Gemini API Key (환경 변수 또는 여기에 직접 입력)
API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY") 
MODEL_NAME = 'gemini-robotics-er-1.6-preview'
OWNER_DESCRIPTION = "A person with glasses"

app = Flask(__name__)

# ==========================================
# Global States
# ==========================================
latest_frame = None
latest_overlay_frame = None
latest_bbox = None
is_robot_busy = False # 감정 표현 등으로 바쁜 상태인지 여부

# 로봇 컨트롤러 초기화 (이제 GPIO 제어 방식을 사용합니다)
from robot_controller import RobotController
robot = RobotController()

# Gemini 클라이언트 초기화
client = genai.Client(api_key=API_KEY)

# ==========================================
# 1. Camera Capture & Control Loop
# ==========================================
def capture_and_control_loop():
    global latest_frame, latest_overlay_frame, latest_bbox, is_robot_busy
    
    # USB 카메라 초기화 (0번 또는 1번 포트)
    cap = cv2.VideoCapture(0) 
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    
    if not cap.isOpened():
        print("Error: Could not open USB camera.")
        return

    owner_was_present = False
    search_state_counter = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            continue
            
        latest_frame = frame.copy()
        overlay_frame = frame.copy()
        
        # Update odometry coordinates on every tick to maintain accurate virtual coordinate tracking
        robot.update_odometry()
        
        # ==========================================
        # 🛡️ TABLE BOUNDARY SOFT SAFETY OVERRIDE
        # ==========================================
        if robot.is_out_of_bounds:
            rad = math.radians(robot.theta)
            # Calculate cross product to determine whether table center (0,0) is to robot's left or right
            cross_product = robot.x * math.sin(rad) - robot.y * math.cos(rad)
            if cross_product > 0:
                robot.turn_left()
                cv2.putText(overlay_frame, f"[Boundary Alert] Steering left to recover center... (X={robot.x:.1f}, Y={robot.y:.1f})", 
                            (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            else:
                robot.turn_right()
                cv2.putText(overlay_frame, f"[Boundary Alert] Steering right to recover center... (X={robot.x:.1f}, Y={robot.y:.1f})", 
                            (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            latest_overlay_frame = overlay_frame
            time.sleep(0.03)
            continue
        
        # 감정 표현 중이면 이동 제어를 건너뛰고 화면만 업데이트
        if is_robot_busy:
            cv2.putText(overlay_frame, "Happy! Found Owner!", (20, 30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            latest_overlay_frame = overlay_frame
            time.sleep(0.03)
            continue

        # Bounding Box가 존재하면 로봇을 제어하고 화면에 표시
        if latest_bbox:
            # 주인을 새로 발견한 순간
            if not owner_was_present:
                print("Owner found! Expressing happiness.")
                owner_was_present = True
                search_state_counter = 0
                
                def happy_action():
                    global is_robot_busy
                    is_robot_busy = True
                    robot.express_happy()
                    is_robot_busy = False
                
                # 감정 표현은 별도 스레드에서 실행하여 영상 스트리밍을 차단하지 않게 함
                threading.Thread(target=happy_action, daemon=True).start()
                continue
                
            ymin, xmin, ymax, xmax = latest_bbox
            h, w = overlay_frame.shape[:2]
            
            # 0~1000 정규화된 좌표를 픽셀 단위로 변환
            x1 = int(xmin * w / 1000)
            y1 = int(ymin * h / 1000)
            x2 = int(xmax * w / 1000)
            y2 = int(ymax * h / 1000)
            
            # 사각형과 텍스트 그리기
            cv2.rectangle(overlay_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(overlay_frame, f"Owner: {OWNER_DESCRIPTION}", (x1, max(y1-10, 0)), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                        
            # 로봇 행동 제어 (x축 중심을 기준으로 따라가기)
            center_x = (x1 + x2) / 2
            
            if center_x < w * 0.35:     # 주인이 화면 왼쪽(35% 지점보다 좌측)에 있을 때
                robot.turn_left()
            elif center_x > w * 0.65:   # 주인이 화면 오른쪽(65% 지점보다 우측)에 있을 때
                robot.turn_right()
            else:                       # 주인이 중앙에 있을 때
                robot.move_forward()
        else:
            owner_was_present = False
            # 대상을 찾지 못했으면 탐색 행동 (주위 둘러보기)
            search_state_counter += 1
            if search_state_counter % 60 < 20: 
                # 30fps 기준 20프레임 (약 0.6초) 좌회전
                robot.turn_left()
            elif search_state_counter % 60 < 40:
                # 20프레임 우회전
                robot.turn_right()
            else:
                # 20프레임 정지
                robot.stop()
                
            cv2.putText(overlay_frame, "Searching for owner...", (20, 30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
            
        latest_overlay_frame = overlay_frame
        time.sleep(0.03) # 약 30fps

# ==========================================
# 2. Gemini API Vision Analysis Loop
# ==========================================
def analyze_frame_loop():
    global latest_frame, latest_bbox
    while True:
        if latest_frame is not None:
            try:
                # OpenCV 프레임(BGR)을 PIL 이미지(RGB)로 변환
                img_rgb = cv2.cvtColor(latest_frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(img_rgb)
                
                # 프롬프트: 대상을 찾고 0~1000 좌표를 반환
                prompt = (
                    f"다음 대상을 이미지에서 찾아주세요: '{OWNER_DESCRIPTION}'. "
                    f"대상이 있다면 Bounding Box 좌표를 [ymin, xmin, ymax, xmax] 형식(0~1000 정규화)으로만 반환해 주세요. "
                    f"대상이 없다면 빈 문자열을 반환하세요."
                )

                # Gemini API 호출 (Robotics 모델 사용)
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=[pil_img, prompt]
                )
                
                # 정규식을 통해 [ymin, xmin, ymax, xmax] 추출
                match = re.search(r'\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]', response.text)
                if match:
                    latest_bbox = [int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))]
                else:
                    latest_bbox = None

            except Exception as e:
                print(f"Gemini API Error: {e}")
                
        # API 호출 빈도 조절 (딜레이 및 과금 방지)
        time.sleep(1.5) 

# ==========================================
# 3. Audio Recognition Loop
# ==========================================
def audio_recognition_loop():
    recognizer = sr.Recognizer()
    
    # Dynamically find the integrated USB microphone (camera mic)
    try:
        mic_names = sr.Microphone.list_microphone_names()
        print(f"[Audio] Available microphone names: {mic_names}")
        target_idx = None
        for idx, name in enumerate(mic_names):
            name_lower = name.lower()
            if any(k in name_lower for k in ["usb", "camera", "webcam"]):
                target_idx = idx
                print(f"🎤 [Audio] Selected USB/Camera microphone: '{name}' (Index {idx})")
                break
        
        # Fallback to other microphones if USB/Camera not found
        if target_idx is None:
            for idx, name in enumerate(mic_names):
                name_lower = name.lower()
                if any(k in name_lower for k in ["mic", "input", "capture"]):
                    target_idx = idx
                    print(f"🎤 [Audio] Selected fallback microphone: '{name}' (Index {idx})")
                    break
                    
        if target_idx is not None:
            mic = sr.Microphone(device_index=target_idx)
        else:
            mic = sr.Microphone()
            print("⚠️ [Audio] No USB/Camera microphone found. Using default microphone.")
    except Exception as e:
        mic = sr.Microphone()
        print(f"⚠️ [Audio] Error listing microphones ({e}). Using default microphone.")
    
    while True:
        try:
            with mic as source:
                # 주변 소음 수준에 맞게 임계값 조정
                recognizer.adjust_for_ambient_noise(source, duration=1)
                print("Listening for voice commands...")
                # 음성 감지
                audio = recognizer.listen(source, timeout=5, phrase_time_limit=5)
            
            try:
                # 구글 음성 인식 엔진을 이용해 텍스트로 변환
                text = recognizer.recognize_google(audio, language='ko-KR')
                print(f"[Audio] Heard: {text}")
                
                if "안녕" in text or "이리와" in text or "강아지" in text:
                    print("--> Action: Bark")
                    robot.bark()
                elif "멈춰" in text or "그만" in text:
                    print("--> Action: Stop command heard")
                    robot.stop()
                    
            except sr.UnknownValueError:
                pass # 음성을 이해할 수 없음
            except sr.RequestError as e:
                print(f"[Audio] Google Speech API Error: {e}")
                
        except Exception as e:
            # 타임아웃 등의 에러는 무시하고 다시 시도
            time.sleep(1)

# ==========================================
# 4. Flask Web Streaming
# ==========================================
def generate_mjpeg():
    global latest_overlay_frame
    while True:
        if latest_overlay_frame is not None:
            is_success, buffer = cv2.imencode(".jpg", latest_overlay_frame)
            if is_success:
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.05)

@app.route('/')
def index():
    return render_template_string('''
        <html>
            <head>
                <title>Puppy Robot Monitor</title>
                <style>
                    body { text-align: center; font-family: sans-serif; background-color: #222; color: #fff; }
                    h1 { margin-top: 20px; }
                    img { max-width: 100%; height: auto; border: 2px solid #555; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
                    .info { margin-top: 10px; color: #aaa; }
                </style>
            </head>
            <body>
                <h1>Puppy Robot Monitor</h1>
                <div class="info">Model: {{ model_name }} | Target: {{ target }}</div>
                <br>
                <img src="/video_feed" />
            </body>
        </html>
    ''', model_name=MODEL_NAME, target=OWNER_DESCRIPTION)

@app.route('/video_feed')
def video_feed():
    # multipart/x-mixed-replace를 이용해 이미지를 지속적으로 업데이트하는 MJPEG 스트림
    return Response(generate_mjpeg(), mimetype='multipart/x-mixed-replace; boundary=frame')

# ==========================================
# Main
# ==========================================
if __name__ == '__main__':
    print("Starting Puppy Robot System...")
    
    # 3개의 스레드를 데몬으로 실행 (메인 프로세스 종료 시 자동 종료)
    threading.Thread(target=capture_and_control_loop, daemon=True).start()
    threading.Thread(target=analyze_frame_loop, daemon=True).start()
    threading.Thread(target=audio_recognition_loop, daemon=True).start()
    
    # Flask 서버 시작 (외부 랩탑에서 접근 가능하도록 host='0.0.0.0' 설정)
    # Raspberry Pi의 IP 주소를 브라우저에 입력하여 접속 (예: http://192.168.0.x:5000)
    print("Web monitor running at: http://<Raspberry-Pi-IP>:5000")
    app.run(host='0.0.0.0', port=5000, threaded=True, debug=False)
