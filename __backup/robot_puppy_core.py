#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
robot_puppy_core.py (Ultimate Premium Edition)
================================================================================
Intelligent robotic puppy core program integrating Gemini Robotics-ER 1.6 Preview
model with Raspberry Pi 4B.

- Cortex: Google Cloud Gemini Robotics-ER 1.6 Preview asynchronous object detection and high-level reasoning.
- Reflex: Local 30 FPS real-time owner face tracking (Gemini-guided) and direct DC motor tracking control.
- Auditory: speech_recognition-based vocal commands (supports "Hello", "Come", "Stop", etc. with real-time response).
- HUD Dashboard: Google AI Studio style premium dark-mode real-time web dashboard (Port 5000, 100% English, Inter font).
================================================================================
"""

import os
import sys

# ==========================================
# ⚙️ Load environment variables manually from .env file (if exists)
# ==========================================
if os.path.exists(".env"):
    try:
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        if key.startswith("export "):
                            key = key[7:].strip()
                        val = parts[1].strip().strip('"').strip("'")
                        os.environ[key] = val
                        print(f"ℹ️ [ENV] Loaded environment variable: {key}")
    except Exception as e:
        print(f"⚠️ [ENV] Failed to parse .env file: {e}")
import time
import json
import threading
import random
import numpy as np
import cv2
import re
from flask import Flask, Response, render_template_string, jsonify
from PIL import Image

# ==========================================
# 🔇 Mute ALSA & Jack audio warning logs (CTypes)
# ==========================================
try:
    from ctypes import CFUNCTYPE, c_char_p, c_int, cdll
    def py_error_handler(filename, line, function, err, fmt):
        pass
    ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)
    c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
    asound = cdll.LoadLibrary('libasound.so.2')
    asound.snd_lib_error_set_handler(c_error_handler)
except Exception:
    pass

from contextlib import contextmanager

@contextmanager
def ignore_stderr():
    """Temporarily redirect stderr (FD 2) to devnull to suppress PortAudio/ALSA/JACK C-level warnings."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stderr = os.dup(2)
        sys.stderr.flush()
        os.dup2(devnull, 2)
        os.close(devnull)
        try:
            yield
        finally:
            os.dup2(old_stderr, 2)
            os.close(old_stderr)
    except Exception:
        yield


# Global guard to check if RPi.GPIO is available
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

# ==========================================
# 🔌 Hardware compatibility guard and robot controller import
# ==========================================
try:
    from robot_controller import RobotController
    robot = RobotController()
    print("✅ [HARDWARE] RobotController successfully initialized.")
except Exception as e:
    import traceback
    print("❌ [HARDWARE] Failed to initialize RobotController. Traceback:")
    traceback.print_exc()
    # Fallback Mock Controller
    class MockRobotController:
        def __init__(self):
            print("⚠️ [HARDWARE] Running with MockRobotController.")
            self.last_action = None
            self.x = 0.0
            self.y = 0.0
            self.theta = 90.0
            self.is_out_of_bounds = False
        def reset_odometry(self, x=0.0, y=0.0, theta=90.0):
            self.x = x
            self.y = y
            self.theta = theta
            self.is_out_of_bounds = False
            print(f"[DRIVE MOCK] 🔄 Reset Odometry to: X={self.x}, Y={self.y}, Theta={self.theta}°")
        def update_odometry(self):
            pass
        def move_forward(self):
            self.last_action = 'forward'
            print("[DRIVE MOCK] ⬆️ Forward")
        def move_backward(self):
            self.last_action = 'backward'
            print("[DRIVE MOCK] ⬇️ Backward")
        def turn_left(self):
            self.last_action = 'left'
            print("[DRIVE MOCK] ⬅️ Turn Left")
        def turn_right(self):
            self.last_action = 'right'
            print("[DRIVE MOCK] ➡️ Turn Right")
        def stop(self):
            self.last_action = 'stop'
            print("[DRIVE MOCK] ⏹️ Stop")
        def bark(self):
            print("[SOUND MOCK] 🐕 Happy Bark Bark!")
        def beep(self):
            print("[SOUND MOCK] 🔊 Beep!")
        def express_happy(self):
            print("[MOTION MOCK] 🕺 Joyful Tail-Wagging Dance!")
    robot = MockRobotController()

# Attempting Speech Recognition initialization
SPEECH_AVAILABLE = False
try:
    import speech_recognition as sr
    SPEECH_AVAILABLE = True
    print("✅ [AUDITORY] SpeechRecognition package loaded successfully.")
except ImportError:
    sr = None
    print("⚠️ [AUDITORY] SpeechRecognition package not found. Vocal interaction disabled.")

# Attempting google-genai initialization
GEMINI_AVAILABLE = False
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    genai = None
    types = None

# ==========================================
# 🧠 Global system coordination state variables
# ==========================================
CURRENT_STATE = "SEARCHING"          # SEARCHING, FOLLOWING, DANCED, STAY
LAST_THOUGHT = "Searching for the owner according to the camera scan schedule..."
RAW_FRAME = None                     # Real-time raw camera or simulation frame
LATEST_JPEG_BYTES = None             # High-speed encoded byte cache for real-time HD streaming
RUNNING = True                       # Multi-thread lifecycle holder
DETECTED_OBJECTS = []                # Real-time robotics pointer labels cache
LAST_DETECTION_TIME = 0.0            # Timestamp of the last object detection API update
CAMERA_ACTIVE = False                # Flag indicating if the USB camera is active
LATEST_BBOX = None                   # Real-time cortex target bounding box (ymin, xmin, ymax, xmax)
OWNER_DESCRIPTION = "A person" # Owner characteristics description
GEMINI_STATUS = "SIMULATION"         # Gemini API status: ACTIVE, SIMULATION, ERROR

# Coordination and Synchronization primitives
gemini_trigger_event = threading.Event() # Event to trigger immediate Gemini API request
gaze_start_time = 0.0                # Timestamp of when the local gaze inspection began

# Global lock and busy flags for thread safety and state coordination
state_lock = threading.Lock()
is_robot_busy = False                 # Flag to temporarily block control loop for emotional/vocal tasks

# Background real-time camera byte/frame cache and dedicated lock
LATEST_CAMERA_FRAME = None
camera_lock = threading.Lock()

# Visual style resources (Google AI Studio technical colors)
COLOR_CYAN = (193, 172, 0)           # Cyan (#00acc1)
COLOR_WHITE = (255, 255, 255)

# ==========================================
# 📐 Google Robotics UI style rendering helper functions
# ==========================================
def draw_google_style_box(img, label, x, y, w, h, color):
    """Draws a technical design label box matching the Google AI Studio GUI."""
    cv2.rectangle(img, (x, y), (x + w, y + h), color, 2)
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.45
    thickness = 1
    (text_w, text_h), _ = cv2.getTextSize(label, font, font_scale, thickness)
    
    tab_x1, tab_y1 = x, y - text_h - 12
    tab_x2, tab_y2 = x + text_w + 14, y
    if tab_y1 < 0:
        tab_y1, tab_y2 = y, y + text_h + 12
        text_y = y + text_h + 6
    else:
        text_y = y - 6
        
    cv2.rectangle(img, (tab_x1, tab_y1), (tab_x2, tab_y2), color, -1)
    cv2.putText(img, label, (x + 7, text_y), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)

def draw_rounded_rectangle(img, pt1, pt2, color, thickness=-1, r=10):
    """Draws a sophisticated rounded rectangle (caption flag) using OpenCV."""
    x1, y1 = pt1
    x2, y2 = pt2
    x1, x2 = min(x1, x2), max(x1, x2)
    y1, y2 = min(y1, y2), max(y1, y2)
    w = x2 - x1
    h = y2 - y1
    r = min(r, w // 2, h // 2)
    if r <= 0:
        cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)
        return

    if thickness < 0:
        cv2.rectangle(img, (x1 + r, y1), (x2 - r, y2), color, -1)
        cv2.rectangle(img, (x1, y1 + r), (x2, y2 - r), color, -1)
        cv2.circle(img, (x1 + r, y1 + r), r, color, -1, cv2.LINE_AA)
        cv2.circle(img, (x2 - r, y1 + r), r, color, -1, cv2.LINE_AA)
        cv2.circle(img, (x1 + r, y2 - r), r, color, -1, cv2.LINE_AA)
        cv2.circle(img, (x2 - r, y2 - r), r, color, -1, cv2.LINE_AA)
    else:
        cv2.line(img, (x1 + r, y1), (x2 - r, y1), color, thickness, cv2.LINE_AA)
        cv2.line(img, (x1 + r, y2), (x2 - r, y2), color, thickness, cv2.LINE_AA)
        cv2.line(img, (x1, y1 + r), (x1, y2 - r), color, thickness, cv2.LINE_AA)
        cv2.line(img, (x2, y1 + r), (x2, y2 - r), color, thickness, cv2.LINE_AA)
        cv2.ellipse(img, (x1 + r, y1 + r), (r, r), 180, 0, 90, color, thickness, cv2.LINE_AA)
        cv2.ellipse(img, (x2 - r, y1 + r), (r, r), 270, 0, 90, color, thickness, cv2.LINE_AA)
        cv2.ellipse(img, (x1 + r, y2 - r), (r, r), 90, 0, 90, color, thickness, cv2.LINE_AA)
        cv2.ellipse(img, (x2 - r, y2 - r), (r, r), 0, 0, 90, color, thickness, cv2.LINE_AA)

def draw_google_robotics_pointer(img, label, xmin, ymin, xmax, ymax):
    """Draws a Google Robotics-ER 1.6-style circular center pointer and rounded caption flag."""
    h_img, w_img, _ = img.shape
    px_min = int(xmin * w_img / 1000.0)
    py_min = int(ymin * h_img / 1000.0)
    px_max = int(xmax * w_img / 1000.0)
    py_max = int(ymax * h_img / 1000.0)
    
    px_min = max(0, min(w_img - 1, px_min))
    px_max = max(0, min(w_img - 1, px_max))
    py_min = max(0, min(h_img - 1, py_min))
    py_max = max(0, min(h_img - 1, py_max))
    
    cx = (px_min + px_max) // 2
    cy = (py_min + py_max) // 2
    blue_color = (255, 102, 43)
    
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.35
    thickness = 1
    (text_w, text_h), _ = cv2.getTextSize(label, font, font_scale, thickness)
    
    cap_h = text_h + 10
    cap_w = text_w + 14
    
    cap_x1 = cx + 8
    cap_y1 = cy - cap_h // 2
    cap_x2 = cap_x1 + cap_w
    cap_y2 = cy + cap_h // 2
    
    if cap_x2 > w_img:
        cap_x2 = cx - 8
        cap_x1 = cap_x2 - cap_w
        
    draw_rounded_rectangle(img, (cap_x1, cap_y1), (cap_x2, cap_y2), blue_color, thickness=-1, r=cap_h // 2)
    cv2.putText(img, label, (cap_x1 + 7, cy + text_h // 2 - 1), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
    
    cv2.circle(img, (cx, cy), 6, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), 4, blue_color, -1, cv2.LINE_AA)

def create_simulated_frame(tick):
    """Virtual object/person detection simulation frame shown when the camera is inactive (640x480 VGA)"""
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    for i in range(0, 480, 60):
        cv2.line(img, (0, i), (640, i), (18, 19, 23), 1)
    for i in range(0, 640, 60):
        cv2.line(img, (i, 0), (i, 480), (18, 19, 23), 1)
        
    cx = int(320 + 160 * np.sin(tick * 0.04))
    cy = int(240 + 70 * np.cos(tick * 0.02))
    r = 60
    
    cv2.circle(img, (cx, cy), r, (75, 78, 84), -1)
    cv2.circle(img, (cx, cy), r, (110, 115, 122), 1)
    cv2.circle(img, (cx - 18, cy - 12), 6, (255, 255, 255), -1)
    cv2.circle(img, (cx + 18, cy - 12), 6, (255, 255, 255), -1)
    cv2.ellipse(img, (cx, cy + 16), (16, 8), 0, 0, 180, (0, 0, 255), 4)
    
    cv2.putText(img, "SIMULATING ACTIVE EYE FEED (VGA)", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 105, 115), 1, cv2.LINE_AA)
    
    # Return mock face bounding box coordinates normalized to 0~1000 range
    ymin = int((cy - r) * 1000 / 480)
    xmin = int((cx - r) * 1000 / 640)
    ymax = int((cy + r) * 1000 / 480)
    xmax = int((cx + r) * 1000 / 640)
    
    mock_face_box = (cx - r, cy - r, r*2, r*2)
    return img, mock_face_box, [ymin, xmin, ymax, xmax]

# ==========================================
# 📹 Thread 0: Background camera frame capture thread (Zero Latency)
# ==========================================
def camera_capture_thread():
    global LATEST_CAMERA_FRAME, RUNNING, CAMERA_ACTIVE
    
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    
    if not cap.isOpened():
        print("❌ [CAMERA] Failed to open USB camera. Running in Simulation Mode.")
        CAMERA_ACTIVE = False
        return
        
    print("✅ [CAMERA] Background capture thread initialized successfully (640x480 VGA).")
    CAMERA_ACTIVE = True
    
    while RUNNING:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.01)
            continue
            
        with camera_lock:
            LATEST_CAMERA_FRAME = frame
            
    cap.release()

# ==========================================
# 📹 Thread 1: 30 FPS Vision Control Thread (Reflex)
# ==========================================
def vision_control_thread():
    global RAW_FRAME, CURRENT_STATE, RUNNING, CAMERA_ACTIVE, LATEST_BBOX, LAST_THOUGHT, is_robot_busy, LATEST_JPEG_BYTES
    
    cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml' if hasattr(cv2, 'data') else 'haarcascade_frontalface_default.xml'
    if not os.path.exists(cascade_path):
        cascade_path = 'haarcascade_frontalface_default.xml'
    face_cascade = cv2.CascadeClassifier(cascade_path)
    
    tick = 0
    search_state_counter = 0
    owner_was_present = False
    faces_cache = []
    
    # State tracking variables for gazing and evading sequences
    gaze_ticks = 0
    ignore_face_ticks = 0
    evade_ticks = 0
    evade_dir = None
    following_lost_ticks = 0
    
    while RUNNING:
        # Update odometry coordinates on every 30 FPS tick to maintain smooth and up-to-date coordinate readings
        robot.update_odometry()

        tick += 1
        faces = []
        sim_bbox = None
        frame = None
        
        if CAMERA_ACTIVE:
            with camera_lock:
                if LATEST_CAMERA_FRAME is not None:
                    frame = LATEST_CAMERA_FRAME.copy()
            
            if frame is None:
                time.sleep(0.01)
                continue
                
            # Detecting on every frame wastes massive CPU cycles and causes latency.
            # Detect once every 5 frames (~160ms interval) to keep CPU load near zero.
            if tick % 5 == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if not face_cascade.empty():
                    # Resize the 640x480 image to 0.5x to minimize calculations (face detection at 320x240).
                    small_gray = cv2.resize(gray, (320, 240), interpolation=cv2.INTER_NEAREST)
                    # Use smaller scaleFactor (1.05) and minNeighbors=3 to highly increase face detection sensitivity
                    # for people wearing glasses, as glasses frames can disrupt Haar-like eye/nose bridge patterns.
                    small_faces = face_cascade.detectMultiScale(small_gray, scaleFactor=1.05, minNeighbors=3, minSize=(30, 30))
                    faces_cache = []
                    for (sf_x, sf_y, sf_w, sf_h) in small_faces:
                        faces_cache.append((sf_x * 2, sf_y * 2, sf_w * 2, sf_h * 2))
            faces = faces_cache
        else:
            frame, mock_face_box, sim_bbox = create_simulated_frame(tick)
            # Update the Cortex BBOX for 90 frames in simulation to mimic the tracking behavior
            if tick % 120 < 90:
                LATEST_BBOX = sim_bbox
                faces = [mock_face_box]
            else:
                LATEST_BBOX = None
                faces = []
            
        # Dynamically capture actual frame dimensions (safest)
        h, w = frame.shape[:2]
        
        # ----------------------------------
        # 30 FPS Vision Alignment and Behavior Decision Logic (Cortex-Reflex Hybrid)
        # ----------------------------------
        # 0. TABLE BOUNDARY SOFT SAFETY OVERRIDE
        if robot.is_out_of_bounds:
            rad = math.radians(robot.theta)
            # Calculate cross product to determine whether center (0,0) is to robot's left or right
            cross_product = robot.x * math.sin(rad) - robot.y * math.cos(rad)
            if cross_product > 0:
                robot.turn_left()
                LAST_THOUGHT = f"[Boundary Alert] Table edge detected! Steering left to recover center... (X={robot.x:.1f}, Y={robot.y:.1f})"
            else:
                robot.turn_right()
                LAST_THOUGHT = f"[Boundary Alert] Table edge detected! Steering right to recover center... (X={robot.x:.1f}, Y={robot.y:.1f})"
            RAW_FRAME = frame
            time.sleep(0.033)
            continue

        if ignore_face_ticks > 0:
            ignore_face_ticks -= 1
            if len(faces) > 0:
                # Draw ignored strangers in grey to visually show they are skipped
                for (fx, fy, fw, fh) in faces:
                    draw_google_style_box(frame, f"stranger ignored ({ignore_face_ticks // 30 + 1}s)", fx, fy, fw, fh, (130, 135, 140))

        # 1. EMERGENCY EVADING STATE (Escape Maneuver when too close)
        if CURRENT_STATE == "EVADING":
            evade_ticks += 1
            if evade_ticks < 30: # 1 second back up
                robot.move_backward()
                LAST_THOUGHT = f"Whoa, too close! Backing up to make some space... ({evade_ticks}/30)"
            elif evade_ticks < 60: # 1 second pivot turn
                if evade_dir == 'left':
                    robot.turn_left()
                else:
                    robot.turn_right()
                LAST_THOUGHT = f"Pivot turning {evade_dir} to find a safer direction... ({evade_ticks}/60)"
            else:
                robot.stop()
                CURRENT_STATE = "SEARCHING"
                search_state_counter = 0
                evade_ticks = 0
                evade_dir = None
                LAST_THOUGHT = "Space cleared! Resuming search for my owner."
            RAW_FRAME = frame
            time.sleep(0.033)
            continue

        target_center_x = None
        target_box = None
        
        # Determine the primary active visual target bounding box
        temp_target_box = None
        if LATEST_BBOX:
            ymin, xmin, ymax, xmax = LATEST_BBOX
            # Ensure correct coordinate order (ascending) to prevent negative dimensions
            ymin, ymax = min(ymin, ymax), max(ymin, ymax)
            xmin, xmax = min(xmin, xmax), max(xmin, xmax)
            g_x1 = int(xmin * w / 1000.0)
            g_y1 = int(ymin * h / 1000.0)
            g_x2 = int(xmax * w / 1000.0)
            g_y2 = int(ymax * h / 1000.0)
            temp_target_box = (g_x1, g_y1, g_x2 - g_x1, g_y2 - g_y1)
        elif len(faces) > 0 and ignore_face_ticks <= 0:
            sorted_faces = sorted(faces, key=lambda f: f[2]*f[3], reverse=True)
            temp_target_box = sorted_faces[0]

        # Check for extreme closeness to trigger Evasion (safety escape)
        if temp_target_box is not None:
            tx, ty, tw, th_box = temp_target_box
            box_height_ratio = th_box / h
            if box_height_ratio > 0.60:
                CURRENT_STATE = "EVADING"
                evade_ticks = 0
                evade_dir = random.choice(['left', 'right'])
                robot.stop()
                LAST_THOUGHT = f"Whoa, target is too close (height ratio: {box_height_ratio:.2f})! Initiating emergency back up and random turn."
                RAW_FRAME = frame
                time.sleep(0.033)
                continue

        # 3. SEARCHING STATE Transition to FOLLOWING (Immediate Local Face Lock-On)
        if CURRENT_STATE == "SEARCHING" and len(faces) > 0 and ignore_face_ticks <= 0:
            with state_lock:
                CURRENT_STATE = "FOLLOWING"
                following_lost_ticks = 0
                LATEST_BBOX = None # Clear stale cortex bounding box to ensure fresh Gemini check
                gaze_start_time = time.time()
                gemini_trigger_event.set() # Trigger immediate Gemini API request
            robot.stop()
            LAST_THOUGHT = "Face spotted! Initiating immediate active tracking..."
            RAW_FRAME = frame
            time.sleep(0.033)
            continue

        # 4. Standard FOLLOWING / TRACKING State Logic
        if LATEST_BBOX:
            ymin, xmin, ymax, xmax = LATEST_BBOX
            # Ensure correct coordinate order (ascending) to prevent negative dimensions
            ymin, ymax = min(ymin, ymax), max(ymin, ymax)
            xmin, xmax = min(xmin, xmax), max(xmin, xmax)
            g_x1 = int(xmin * w / 1000.0)
            g_y1 = int(ymin * h / 1000.0)
            g_x2 = int(xmax * w / 1000.0)
            g_y2 = int(ymax * h / 1000.0)
            is_face_target = any(kw in OWNER_DESCRIPTION.lower() for kw in ["person", "man", "woman", "owner", "face", "glasses", "human"])
            
            matched_face = None
            if is_face_target and len(faces) > 0:
                min_dist = float('inf')
                gemini_cx = (g_x1 + g_x2) / 2
                gemini_cy = (g_y1 + g_y2) / 2
                for (fx, fy, fw, fh) in faces:
                    fcx = fx + (fw // 2)
                    fcy = fy + (fh // 2)
                    dist = np.sqrt((fcx - gemini_cx)**2 + (fcy - gemini_cy)**2)
                    if dist < min_dist:
                        min_dist = dist
                        matched_face = (fx, fy, fw, fh)
            
            if matched_face:
                fx, fy, fw, fh = matched_face
                target_center_x = fx + (fw // 2)
                target_box = (fx, fy, fw, fh)
                draw_google_style_box(frame, "owner (active - lock-on)", fx, fy, fw, fh, COLOR_CYAN)
            else:
                target_center_x = (g_x1 + g_x2) // 2
                target_box = (g_x1, g_y1, g_x2 - g_x1, g_y2 - g_y1)
                draw_google_style_box(frame, "owner (cortex - tracking)", g_x1, g_y1, g_x2 - g_x1, g_y2 - g_y1, COLOR_CYAN)
        
        elif len(faces) > 0 and ignore_face_ticks <= 0 and any(kw in OWNER_DESCRIPTION.lower() for kw in ["person", "man", "woman", "owner", "face", "glasses", "human"]):
            faces = sorted(faces, key=lambda f: f[2]*f[3], reverse=True)
            fx, fy, fw, fh = faces[0]
            target_center_x = fx + (fw // 2)
            target_box = (fx, fy, fw, fh)
            draw_google_style_box(frame, "owner (reflex - local)", fx, fy, fw, fh, (130, 135, 140))
            
        # Real-time motor command determination and transmission
        if target_center_x is not None:
            following_lost_ticks = 0 # Reset target-loss hysteresis
            was_dozing = (CURRENT_STATE == "DOZING")
            CURRENT_STATE = "FOLLOWING"
            
            if was_dozing or not owner_was_present:
                print("[VISION] Target newly spotted! Transitioning to active tracking and expressing joy.")
                owner_was_present = True
                search_state_counter = 0
                LAST_THOUGHT = "Owner spotted! Expressing joy to my best friend!"
                
                def happy_action():
                    global is_robot_busy
                    with state_lock:
                        is_robot_busy = True
                    try:
                        robot.express_happy()
                    finally:
                        with state_lock:
                            is_robot_busy = False
                
                threading.Thread(target=happy_action, daemon=True).start()
                continue
                
            if not is_robot_busy and target_box is not None:
                bx, by, bw, bh = target_box
                box_height_ratio = bh / h
                
                if target_center_x < w * 0.35:
                    robot.turn_left()
                    LAST_THOUGHT = f"Tracking target on the left (dist ratio: {box_height_ratio:.2f}). Steering left."
                elif target_center_x > w * 0.65:
                    robot.turn_right()
                    LAST_THOUGHT = f"Tracking target on the right (dist ratio: {box_height_ratio:.2f}). Steering right."
                else:
                    if box_height_ratio < 0.32:
                        robot.move_forward()
                        LAST_THOUGHT = f"Target centered but far away (dist ratio: {box_height_ratio:.2f}). Approaching."
                    elif box_height_ratio > 0.48:
                        robot.move_backward()
                        LAST_THOUGHT = f"Target centered but too close (dist ratio: {box_height_ratio:.2f}). Backing up."
                    else:
                        robot.stop()
                        LAST_THOUGHT = f"Target centered at comfortable distance (dist ratio: {box_height_ratio:.2f}). Staying."
        else:
            # If we were actively following the owner, do not drop back to SEARCHING immediately.
            # Give a 3-second grace period (90 ticks) to wait for reappearance (hysteresis).
            if CURRENT_STATE == "FOLLOWING":
                following_lost_ticks += 1
                if following_lost_ticks < 90:
                    robot.stop()
                    LAST_THOUGHT = f"Target temporarily lost. Waiting for reappearance... ({following_lost_ticks}/90)"
                    RAW_FRAME = frame
                    time.sleep(0.033)
                    continue
                else:
                    following_lost_ticks = 0
            
            owner_was_present = False
            
            if not is_robot_busy:
                search_state_counter += 1
                
                # Sleep Timeout: If nothing detected for 1080 frames (~36s), enter DOZING sleep mode
                if search_state_counter >= 1080:
                    CURRENT_STATE = "DOZING"
                    robot.stop()
                    LAST_THOUGHT = "Dozing off... Restfully sleeping. Waiting for my owner's face to wake me up!"
                else:
                    CURRENT_STATE = "SEARCHING"
                    cycle_tick = search_state_counter % 360
                    
                    if cycle_tick < 50:
                        robot.turn_left()
                        LAST_THOUGHT = "Slightly tilting left, scanning the environment..."
                    elif cycle_tick < 100:
                        robot.turn_right()
                        LAST_THOUGHT = "Curiously panning right, searching for movement..."
                    elif cycle_tick < 140:
                        robot.stop()
                        LAST_THOUGHT = "Standing alertly, sniffing the air for your scent..."
                    elif cycle_tick < 150:
                        robot.move_forward()
                        LAST_THOUGHT = "Taking an extremely tiny step forward to explore..."
                    elif cycle_tick < 190:
                        robot.stop()
                        LAST_THOUGHT = "Pausing and listening..."
                    elif cycle_tick < 230:
                        robot.turn_left()
                        LAST_THOUGHT = "Shuffling left to check my blind spot..."
                    elif cycle_tick < 240:
                        robot.move_backward()
                        LAST_THOUGHT = "Micro-stepping back to return to my safe center spot..."
                    elif cycle_tick < 270:
                        robot.stop()
                        LAST_THOUGHT = "Staying centered and safe on the table..."
                    elif cycle_tick < 320:
                        robot.turn_right()
                        LAST_THOUGHT = "Looking right again... Did I hear something?"
                    else:
                        robot.stop()
                        LAST_THOUGHT = "Taking a quiet breath, waiting patiently..."
                    
        # ----------------------------------
        # 📐 Google Robotics-ER 1.6 multi-object rendering (stale pointer prevention and timeout filter)
        # ----------------------------------
        # When wheels are moving or the camera is panning, 2D screen coordinate synchronization drifts.
        # To completely prevent stale dots from floating during motion, we only render object pointer
        # labels when the robot is stopped (last action is 'stop' or None) and the camera is steady.
        # Also, cache data older than 4 seconds without a Gemini update is automatically expired/hidden.
        is_moving = (robot.last_action not in ['stop', None])
        
        if not is_moving and (time.time() - LAST_DETECTION_TIME < 4.0):
            global DETECTED_OBJECTS
            for obj in DETECTED_OBJECTS:
                box = obj.get("box_2d")
                label = obj.get("label", "object")
                if box and len(box) == 4:
                    oymin, oxmin, oymax, oxmax = box
                    # Target owner is already clearly highlighted above, so only draw non-owner objects on the HUD
                    if label.lower() not in OWNER_DESCRIPTION.lower():
                        draw_google_robotics_pointer(frame, label, oxmin, oymin, oxmax, oymax)
                        
        RAW_FRAME = frame
        time.sleep(0.033) # Approx 30fps loop

# ==========================================
# 🎙️ Thread 2: SpeechRecognition Voice Recognition Thread (Auditory)
# ==========================================
def audio_recognition_thread():
    global RUNNING, LAST_THOUGHT, is_robot_busy
    
    if not SPEECH_AVAILABLE:
        print("⚠️ [AUDITORY] SpeechRecognition is unavailable. Auditory layer disabled.")
        return
        
    recognizer = sr.Recognizer()
    
    # Dynamically find the integrated USB microphone (camera mic)
    try:
        with ignore_stderr():
            mic_names = sr.Microphone.list_microphone_names()
        print(f"[AUDITORY] Available microphone names: {mic_names}")
        target_idx = None
        for idx, name in enumerate(mic_names):
            name_lower = name.lower()
            if any(k in name_lower for k in ["usb", "camera", "webcam"]):
                target_idx = idx
                print(f"🎤 [AUDITORY] Selected USB/Camera microphone: '{name}' (Index {idx})")
                break
        
        # Fallback to other microphones if USB/Camera not found
        if target_idx is None:
            for idx, name in enumerate(mic_names):
                name_lower = name.lower()
                if any(k in name_lower for k in ["mic", "input", "capture"]):
                    target_idx = idx
                    print(f"🎤 [AUDITORY] Selected fallback microphone: '{name}' (Index {idx})")
                    break
                    
        if target_idx is not None:
            with ignore_stderr():
                mic = sr.Microphone(device_index=target_idx)
        else:
            with ignore_stderr():
                mic = sr.Microphone()
            print("⚠️ [AUDITORY] No USB/Camera microphone found. Using default microphone.")
    except Exception as e:
        with ignore_stderr():
            mic = sr.Microphone()
        print(f"⚠️ [AUDITORY] Error listing microphones ({e}). Using default microphone.")
    
    print("✅ [AUDITORY] SpeechRecognition thread started.")
    
    while RUNNING:
        try:
            with ignore_stderr():
                opened_source = mic.__enter__()
            try:
                recognizer.adjust_for_ambient_noise(opened_source, duration=1)
                print("[AUDITORY] Listening for vocal commands...")
                audio = recognizer.listen(opened_source, timeout=4, phrase_time_limit=4)
            finally:
                with ignore_stderr():
                    mic.__exit__(None, None, None)
                
            try:
                # Step 1: Try parsing with Korean first
                text_ko = recognizer.recognize_google(audio, language='ko-KR').strip()
                print(f"[AUDITORY] Heard (KO): '{text_ko}'")
                text = text_ko.lower()
            except sr.UnknownValueError:
                try:
                    # Step 2: Fallback to English parsing on failure
                    text_en = recognizer.recognize_google(audio, language='en-US').strip()
                    print(f"[AUDITORY] Heard (EN): '{text_en}'")
                    text = text_en.lower()
                except sr.UnknownValueError:
                    continue
                    
            # Multi-language voice command routing and is_robot_busy interlocking to prevent thread racing
            if any(cmd in text for cmd in ["안녕", "반가워", "강아지", "hello", "hi", "puppy", "dog"]):
                print("--> Action triggered: Happy Bark")
                LAST_THOUGHT = "[Voice Command] Saying hello back! Barking happily."
                def vocal_bark_task():
                    global is_robot_busy
                    with state_lock:
                        is_robot_busy = True
                    try:
                        robot.bark()
                    finally:
                        with state_lock:
                            is_robot_busy = False
                threading.Thread(target=vocal_bark_task, daemon=True).start()
                
            elif any(cmd in text for cmd in ["이리와", "온", "come", "here"]):
                print("--> Action triggered: Come forward")
                LAST_THOUGHT = "[Voice Command] Approaching the owner."
                def vocal_come_task():
                    global is_robot_busy
                    with state_lock:
                        is_robot_busy = True
                    try:
                        robot.move_forward()
                        time.sleep(1.2)
                        robot.stop()
                    finally:
                        with state_lock:
                            is_robot_busy = False
                threading.Thread(target=vocal_come_task, daemon=True).start()
                
            elif any(cmd in text for cmd in ["멈춰", "정지", "그만", "stop", "halt", "quit"]):
                print("--> Action triggered: Stop")
                LAST_THOUGHT = "[Voice Command] Stopping all movements immediately."
                def vocal_stop_task():
                    global is_robot_busy
                    with state_lock:
                        is_robot_busy = True
                    try:
                        robot.stop()
                        time.sleep(1.0) # Maintain stopped state for 1 second for stabilization
                    finally:
                        with state_lock:
                            is_robot_busy = False
                threading.Thread(target=vocal_stop_task, daemon=True).start()
                
        except sr.RequestError as e:
            print(f"[AUDITORY ERROR] Google Speech API Error: {e}")
            time.sleep(2)
        except Exception as e:
            time.sleep(1)

# ==========================================
# 🧠 Thread 3: Cloud Google Gemini API Integration (Cortex)
# ==========================================
def gemini_brain_thread():
    global CURRENT_STATE, LAST_THOUGHT, RAW_FRAME, RUNNING, DETECTED_OBJECTS, LAST_DETECTION_TIME, CAMERA_ACTIVE, LATEST_BBOX, is_robot_busy, GEMINI_STATUS
    
    api_key = os.environ.get("GEMINI_API_KEY")
    
    if not GEMINI_AVAILABLE or not api_key or api_key == "YOUR_API_KEY":
        print("⚠️ [CORTEX] Google GenAI SDK missing or invalid API Key. Running in Simulation Mind mode.")
        with state_lock:
            GEMINI_STATUS = "SIMULATION"
        
        simulated_minds = [
            "The owner is smiling and looking straight at me! Approaching cheerfully.",
            "I should stay loyal and keep watching the surroundings.",
            "Visual field is clear, searching for the owner's presence.",
            "Auditory senses are focused on the surroundings waiting for a voice command."
        ]
        
        while RUNNING:
            time.sleep(6)
            if RAW_FRAME is not None and RUNNING:
                import random
                LAST_THOUGHT = "[AI SIMULATION] " + random.choice(simulated_minds)
                # Clear fake multi-detection list in simulation mode
                DETECTED_OBJECTS = []
                LAST_DETECTION_TIME = 0.0
        return

    try:
        client = genai.Client(api_key=api_key)
        print("✅ [CORTEX] Google GenAI Client initialized successfully.")
        with state_lock:
            GEMINI_STATUS = "ACTIVE"
    except Exception as e:
        print(f"⚠️ [CORTEX] Failed to initialize GenAI Client: {e}")
        with state_lock:
            GEMINI_STATUS = "ERROR"
        return

    # High-speed low-latency prompt designed to integrate both multi-object detection and owner localization
    prompt = f"""
    You are the robotic puppy's brain. Based on the camera image:
    1. Locate the target owner, who is defined as: {OWNER_DESCRIPTION}.
       - Find the bounding box of the person in the image.
       - If a person is present, detect them as the owner and output their bounding box in 'owner_box'.
       - If no person is present, set 'owner_box' to null.
    2. Detect up to 8 other notable surrounding objects (like toys, cups, food, bowls, books, keys, etc.) and provide their 2D bounding boxes and labels in 'detected_objects'.
    3. Generate a brief English thought explaining what you see and how you feel as a robotic puppy.
    
    CRITICAL COORDINATE RULES:
    All bounding box coordinates [ymin, xmin, ymax, xmax] must be normalized to a 0 to 1000 scale (integers from 0 to 1000).
    - ymin: top edge (0 to 1000)
    - xmin: left edge (0 to 1000)
    - ymax: bottom edge (0 to 1000)
    - xmax: right edge (0 to 1000)
    Do NOT use 0.0 to 1.0 decimals. Do NOT use absolute pixel coordinates. Always return integers from 0 to 1000.
    
    You must return a raw JSON object with the following structure:
    {{
      "owner_box": [ymin, xmin, ymax, xmax] or null,
      "detected_objects": [
        {{"box_2d": [ymin, xmin, ymax, xmax], "label": "object name"}}
      ],
      "thought": "Brief explanation of your puppy thought in English"
    }}
    
    Return ONLY the raw JSON block without markdown formatting or backticks.
    """

    while RUNNING:
        clean_frame = None
        if CAMERA_ACTIVE:
            with camera_lock:
                if LATEST_CAMERA_FRAME is not None:
                    clean_frame = LATEST_CAMERA_FRAME.copy()
        if clean_frame is None:
            clean_frame = RAW_FRAME.copy() if RAW_FRAME is not None else None
            
        if clean_frame is not None:
            snapshot_time = time.time()
            ret, buffer = cv2.imencode('.jpg', clean_frame)
            if ret:
                image_bytes = buffer.tobytes()
                try:
                    model_name = 'gemini-robotics-er-1.6-preview'
                    try:
                        response = client.models.generate_content(
                            model=model_name,
                            contents=[
                                types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'),
                                prompt
                            ]
                        )
                    except Exception as e_model:
                        print(f"⚠️ [CORTEX] Model '{model_name}' failed or restricted: {e_model}. Falling back to 'gemini-2.5-flash'...")
                        model_name = 'gemini-2.5-flash'
                        response = client.models.generate_content(
                            model=model_name,
                            contents=[
                                types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'),
                                prompt
                            ]
                        )
                    
                    result_text = response.text.strip()
                    if result_text.startswith("```"):
                        result_text = result_text.split("```")[1]
                        if result_text.startswith("json"):
                            result_text = result_text[4:]
                    
                    brace_start = result_text.find("{")
                    brace_end = result_text.rfind("}")
                    if brace_start != -1 and brace_end != -1:
                        result_text = result_text[brace_start:brace_end+1]
                            
                    data = json.loads(result_text.strip())
                    
                    # 1. Update multi-object data first (required for owner_box fallback)
                    raw_objects = data.get("detected_objects", [])
                    valid_objects = []
                    for obj in raw_objects:
                        if isinstance(obj, dict) and "box_2d" in obj and "label" in obj:
                            box = obj["box_2d"]
                            if box and isinstance(box, list) and len(box) == 4:
                                try:
                                    num_box = [float(v) for v in box]
                                    if max(num_box) <= 1.01:
                                        num_box = [int(v * 1000) for v in num_box]
                                    else:
                                        num_box = [int(v) for v in num_box]
                                    obj["box_2d"] = num_box
                                    valid_objects.append(obj)
                                except (ValueError, TypeError):
                                    pass
                    DETECTED_OBJECTS = valid_objects
                    LAST_DETECTION_TIME = time.time()
                    
                    # 2. Update target owner box data with stale response safety check and robust scaling/fallbacks
                    owner_box = data.get("owner_box") or data.get("owner") or data.get("owner_bbox")
                    if owner_box is None:
                        # Fallback: search for person/man/woman/owner in detected_objects to use as owner_box
                        for obj in valid_objects:
                            lbl = obj.get("label", "").lower()
                            if any(p in lbl for p in ["person", "man", "woman", "owner"]):
                                owner_box = obj.get("box_2d")
                                print(f"ℹ️ [CORTEX] owner_box was null, but found '{lbl}' in detected_objects. Fusing as owner_box!")
                                break

                    # Clean and validate owner_box
                    validated_box = None
                    if owner_box and isinstance(owner_box, list) and len(owner_box) == 4:
                        try:
                            num_box = [float(v) for v in owner_box]
                            if max(num_box) <= 1.01:
                                num_box = [int(v * 1000) for v in num_box]
                            else:
                                num_box = [int(v) for v in num_box]
                            validated_box = num_box
                        except (ValueError, TypeError):
                            pass

                    with state_lock:
                        GEMINI_STATUS = "ACTIVE"
                        if CURRENT_STATE == "GAZING" and snapshot_time < gaze_start_time:
                            print("[CORTEX] Discarding stale pre-gaze API response.")
                        else:
                            LATEST_BBOX = validated_box
                    
                    # 3. Record Cortex thought log
                    LAST_THOUGHT = data.get("thought", "Monitoring environment and target owner.")
                    
                    print(f"[CORTEX API] Model: {model_name} | Owner Spotted: {LATEST_BBOX is not None} (BBOX: {LATEST_BBOX}) | Objects: {len(valid_objects)} | Thought: {LAST_THOUGHT}")
                    
                    # 4. 🤖 Autonomous action reaction trigger (transforms object recognition into physical sound/motion)
                    # If toys or food are recognized, trigger corresponding natural puppy play/hungry reactions
                    if not is_robot_busy:
                        has_toy = any(kw in obj.get("label", "").lower() for obj in valid_objects for kw in ["toy", "ball", "frisbee", "doll"])
                        has_food = any(kw in obj.get("label", "").lower() for obj in valid_objects for kw in ["bowl", "cup", "food", "water", "snack"])
                        
                        if has_toy:
                            print("[CORTEX] Toy detected! Triggering happy toy-play reaction.")
                            LAST_THOUGHT = "[Spotted Toy] " + LAST_THOUGHT
                            def play_reaction_task():
                                global is_robot_busy
                                with state_lock:
                                    is_robot_busy = True
                                try:
                                    robot.bark()
                                    robot.turn_left()
                                    time.sleep(0.15)
                                    robot.turn_right()
                                    time.sleep(0.15)
                                    robot.stop()
                                finally:
                                    with state_lock:
                                        is_robot_busy = False
                            threading.Thread(target=play_reaction_task, daemon=True).start()
                            
                        elif has_food:
                            print("[CORTEX] Food/Bowl detected! Triggering curious whimper reaction.")
                            LAST_THOUGHT = "[Spotted Food Bowl] " + LAST_THOUGHT
                            def hungry_reaction_task():
                                global is_robot_busy
                                with state_lock:
                                    is_robot_busy = True
                                try:
                                    robot.beep()
                                finally:
                                    with state_lock:
                                        is_robot_busy = False
                            threading.Thread(target=hungry_reaction_task, daemon=True).start()
                        
                except Exception as e:
                    print(f"[CORTEX API] Gemini 1.6 API Exception: {e}")
                    with state_lock:
                        GEMINI_STATUS = "ERROR"
                    # Clear detected objects to fade out boxes during API exceptions or delays
                    DETECTED_OBJECTS = []
                    LAST_DETECTION_TIME = 0.0
                    
        # Increase the Cortex API polling interval to 1.5s to align dynamically with fast local steering,
        # using an interruptible event wait to trigger instantly when entering the GAZING state.
        gemini_trigger_event.wait(timeout=1.5)
        gemini_trigger_event.clear()

# ==========================================
# 🖼️ Thread 4: Background Streaming Encoder Thread for Web Streaming (CPU Optimization)
# ==========================================
def streaming_encoder_thread():
    global RAW_FRAME, LATEST_JPEG_BYTES, RUNNING
    print("✅ [STREAM ENCODER] Background streaming encoder thread started.")
    
    while RUNNING:
        if RAW_FRAME is not None:
            try:
                # No resize needed as camera is already 640x480 (VGA).
                # Directly encode the frame to JPEG to save substantial CPU cycles.
                ret, jpeg_buffer = cv2.imencode('.jpg', RAW_FRAME, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                if ret:
                    LATEST_JPEG_BYTES = jpeg_buffer.tobytes()
            except Exception as e:
                print(f"⚠️ [STREAM ENCODER] Compression error: {e}")
                
        # Perform streaming-only encoding at approx 30 FPS
        time.sleep(0.033)

# ==========================================
# 🖥 Flask Web Monitoring Dashboard Resources and API
# ==========================================
app = Flask(__name__)

def get_cpu_temp():
    """Reads the Raspberry Pi onboard SOC CPU temperature, with random fallback for simulation."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp_raw = float(f.read().strip())
            return round(temp_raw / 1000.0, 1)
    except Exception:
        import random
        return round(41.5 + random.uniform(-0.8, 0.8), 1)

def generate_mjpeg_stream():
    global LATEST_JPEG_BYTES
    while True:
        if LATEST_JPEG_BYTES is None:
            time.sleep(0.05)
            continue
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + LATEST_JPEG_BYTES + b'\r\n')
        time.sleep(0.05)  # Keep web streaming around 20 FPS to minimize network/browser rendering overhead

@app.route('/video_feed')
def video_feed():
    return Response(generate_mjpeg_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/status')
def status():
    return jsonify({
        "state": CURRENT_STATE,
        "thought": LAST_THOUGHT,
        "cpu_temp": get_cpu_temp(),
        "gemini_status": GEMINI_STATUS,
        "x": round(robot.x, 1),
        "y": round(robot.y, 1),
        "theta": round(robot.theta, 1),
        "is_out_of_bounds": robot.is_out_of_bounds
    })

@app.route('/reset_odometry', methods=['POST'])
def reset_odometry_route():
    robot.reset_odometry(0.0, 0.0, 90.0)
    return jsonify({
        "status": "success",
        "message": "Odometry coordinates manually reset to center (0, 0, 90°)."
    })

HTML_DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lyria | Gemini Robotics Live HUD</title>
    <!-- Premium Google Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-deep: #050508;
            --accent-cyan: #00f0ff;
            --accent-purple: #7c4dff;
            --text-main: #f0f2f5;
            --text-muted: #8e929e;
            --card-border: rgba(255, 255, 255, 0.08);
            --card-bg-glass: rgba(10, 11, 16, 0.6);
            --glow-cyan: rgba(0, 240, 255, 0.35);
            --glow-purple: rgba(124, 77, 255, 0.35);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg-deep);
            color: var(--text-main);
            font-family: 'Inter', sans-serif;
            letter-spacing: -0.02em;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            overflow-x: hidden;
            position: relative;
            padding: 40px 20px;
        }

        /* Ethereal Lyria Radial Gradients */
        body::before {
            content: "";
            position: absolute;
            top: -10%;
            left: -10%;
            width: 120%;
            height: 120%;
            background-image: 
                radial-gradient(circle at 15% 25%, rgba(124, 77, 255, 0.07) 0px, transparent 40%),
                radial-gradient(circle at 85% 75%, rgba(0, 240, 255, 0.07) 0px, transparent 40%);
            pointer-events: none;
            z-index: 0;
        }

        header {
            position: relative;
            z-index: 1;
            text-align: center;
            margin-bottom: 40px;
        }

        header h1 {
            font-size: 2.3rem;
            font-weight: 300;
            letter-spacing: -0.03em;
            color: #fff;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
        }

        header h1 span {
            font-weight: 600;
            background: linear-gradient(135deg, var(--accent-cyan) 0%, var(--accent-purple) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        header p {
            color: var(--text-muted);
            font-size: 0.85rem;
            font-weight: 500;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        .container {
            position: relative;
            z-index: 1;
            display: grid;
            grid-template-columns: 1.4fr 1fr;
            gap: 30px;
            width: 100%;
            max-width: 1200px;
        }

        @media (min-width: 1400px) {
            .container {
                grid-template-columns: 1fr 1.3fr 1fr; /* 3 Columns on 4K/wide monitors! */
                max-width: 1800px;
            }
        }

        @media (max-width: 1100px) {
            .container {
                grid-template-columns: 1fr;
            }
            #center-col {
                order: -1;
            }
        }

        .panel {
            background: var(--card-bg-glass);
            backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px);
            border: 1px solid var(--card-border);
            border-radius: 24px;
            padding: 30px;
            transition: all 0.5s cubic-bezier(0.16, 1, 0.3, 1);
            position: relative;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }

        .panel:hover {
            border-color: rgba(255, 255, 255, 0.15);
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
        }

        .panel h3 {
            font-size: 1rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-muted);
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .video-wrapper {
            position: relative;
            width: 100%;
            aspect-ratio: 4 / 3;
            border-radius: 16px;
            overflow: hidden;
            border: 1px solid rgba(255, 255, 255, 0.05);
            background-color: #000;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .video-wrapper img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }

        /* 📡 HUD Technical Overlays (Corner Brackets) */

        .corner-bracket {
            position: absolute;
            width: 24px;
            height: 24px;
            border-color: var(--accent-cyan);
            border-style: solid;
            opacity: 0.8;
            z-index: 6;
            pointer-events: none;
            filter: drop-shadow(0 0 6px var(--glow-cyan));
            transition: all 0.3s ease;
        }
        .top-left { top: 18px; left: 15px; border-width: 3px 0 0 3px; border-top-left-radius: 4px; }
        .top-right { top: 18px; right: 15px; border-width: 3px 3px 0 0; border-top-right-radius: 4px; }
        .bottom-left { bottom: 18px; left: 15px; border-width: 0 0 3px 3px; border-bottom-left-radius: 4px; }
        .bottom-right { bottom: 18px; right: 15px; border-width: 0 3px 3px 0; border-bottom-right-radius: 4px; }

        .live-badge {
            position: absolute;
            top: 20px;
            left: 20px;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(8px);
            padding: 6px 14px;
            border-radius: 30px;
            font-size: 0.75rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: #fff;
            letter-spacing: 0.05em;
            z-index: 10;
        }

        .live-dot {
            width: 6px;
            height: 6px;
            background-color: #ff3366;
            border-radius: 50%;
            box-shadow: 0 0 8px #ff3366;
            animation: pulse-dot 1.5s infinite;
        }

        @keyframes pulse-dot {
            0% { transform: scale(0.9); opacity: 0.6; }
            50% { transform: scale(1.2); opacity: 1; }
            100% { transform: scale(0.9); opacity: 0.6; }
        }

        .side-column {
            display: flex;
            flex-direction: column;
            gap: 30px;
        }

        /* Sleek Status Badge styling */
        .status-badge-container {
            margin-bottom: 5px;
        }

        .status-badge {
            font-size: 0.95rem;
            padding: 16px;
            border-radius: 16px;
            text-align: center;
            font-weight: 600;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
            box-shadow: inset 0 0 15px rgba(255,255,255,0.02);
            border: 1px solid transparent;
        }

        .state-SEARCHING { 
            background-color: rgba(229, 169, 60, 0.05); 
            color: #e5a93c; 
            border-color: rgba(229,169,60,0.12); 
            text-shadow: 0 0 15px rgba(229,169,60,0.2); 
        }
        .state-GAZING {
            background-color: rgba(255, 200, 0, 0.05);
            color: #ffc800;
            border-color: rgba(255,200,0,0.12);
            text-shadow: 0 0 15px rgba(255,200,0,0.2);
        }
        .state-FOLLOWING { 
            background-color: rgba(0, 240, 255, 0.05); 
            color: var(--accent-cyan); 
            border-color: rgba(0,240,255,0.12); 
            text-shadow: 0 0 15px rgba(0,240,255,0.2); 
        }
        .state-EVADING {
            background-color: rgba(255, 51, 102, 0.05);
            color: #ff3366;
            border-color: rgba(255,51,102,0.12);
            text-shadow: 0 0 15px rgba(255,51,102,0.2);
        }
        .state-DOZING {
            background-color: rgba(124, 77, 255, 0.05);
            color: #9d4edd;
            border-color: rgba(124,77,255,0.12);
            text-shadow: 0 0 15px rgba(124,77,255,0.2);
        }

        /* 🎛️ Motor Actuator Telemetry Vector Pad */
        .vector-pad {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 12px;
            padding: 10px 0;
        }
        .middle-row {
            display: flex;
            align-items: center;
            gap: 24px;
        }
        .dir-arrow {
            width: 48px;
            height: 48px;
            border-radius: 14px;
            border: 1px solid var(--card-border);
            background: rgba(255, 255, 255, 0.02);
            color: var(--text-muted);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.25rem;
            font-weight: bold;
            transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
        }
        .dir-arrow.active-forward {
            background-color: rgba(0, 240, 255, 0.08);
            color: var(--accent-cyan);
            border-color: var(--accent-cyan);
            box-shadow: 0 0 15px var(--glow-cyan);
            text-shadow: 0 0 8px var(--accent-cyan);
        }
        .dir-arrow.active-backward {
            background-color: rgba(124, 77, 255, 0.08);
            color: var(--accent-purple);
            border-color: var(--accent-purple);
            box-shadow: 0 0 15px var(--glow-purple);
            text-shadow: 0 0 8px var(--accent-purple);
        }
        .dir-arrow.active-turn {
            background-color: rgba(229, 169, 60, 0.08);
            color: #e5a93c;
            border-color: #e5a93c;
            box-shadow: 0 0 15px rgba(229, 169, 60, 0.3);
            text-shadow: 0 0 8px #e5a93c;
        }
        .dir-arrow.active-stop {
            background-color: rgba(255, 51, 102, 0.08);
            color: #ff3366;
            border-color: #ff3366;
            box-shadow: 0 0 15px rgba(255, 51, 102, 0.3);
            text-shadow: 0 0 8px #ff3366;
        }

        /* 🎙️ Animated Vocal Waveform */
        .vocal-visualizer {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 4px;
            height: 24px;
            margin-top: 15px;
        }
        .vocal-visualizer .bar {
            width: 3px;
            height: 100%;
            background-color: var(--accent-cyan);
            border-radius: 2px;
            animation: bounce-wave 1s ease-in-out infinite alternate;
        }
        .vocal-visualizer .bar-1 { animation-delay: 0.1s; }
        .vocal-visualizer .bar-2 { animation-delay: 0.3s; }
        .vocal-visualizer .bar-3 { animation-delay: 0.5s; height: 70%; }
        .vocal-visualizer .bar-4 { animation-delay: 0.2s; }
        .vocal-visualizer .bar-5 { animation-delay: 0.4s; }
        
        @keyframes bounce-wave {
            0% { transform: scaleY(0.2); }
            100% { transform: scaleY(1.0); }
        }

        /* Thoughts Chronological Timeline Stream */
        .timeline {
            display: flex;
            flex-direction: column;
            gap: 20px;
            position: relative;
            padding-left: 20px;
            margin-left: 10px;
            border-left: 1px solid rgba(255, 255, 255, 0.06);
            min-height: 120px;
        }

        .timeline-item {
            position: relative;
            font-size: 0.95rem;
            line-height: 1.5;
            color: var(--text-muted);
            transition: all 0.5s ease;
            opacity: 0.4;
            transform: scale(0.98);
            transform-origin: left;
        }

        .timeline-item.active {
            color: #fff;
            font-weight: 500;
            opacity: 1;
            transform: scale(1);
        }

        .timeline-dot {
            position: absolute;
            left: -25.5px;
            top: 7px;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.1);
            border: 2px solid var(--bg-deep);
            transition: all 0.5s ease;
        }

        .timeline-item.active .timeline-dot {
            background: var(--accent-cyan);
            box-shadow: 0 0 12px var(--accent-cyan);
        }

        /* Connected Diagnostics List */
        .diag-list {
            display: flex;
            flex-direction: column;
            gap: 16px;
        }

        .diag-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 0.95rem;
            color: var(--text-main);
            padding-bottom: 12px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.03);
        }

        .diag-item:last-child {
            border-bottom: none;
            padding-bottom: 0;
        }

        .diag-status {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.85rem;
            color: var(--text-muted);
        }

        /* Ring Halo Pulsating status dots */
        .halo-dot {
            position: relative;
            width: 8px;
            height: 8px;
            border-radius: 50%;
        }

        .halo-dot::after {
            content: "";
            position: absolute;
            top: -4px;
            left: -4px;
            width: 16px;
            height: 16px;
            border-radius: 50%;
            border: 1px solid currentColor;
            opacity: 0.8;
            animation: halo-pulse 2s cubic-bezier(0.16, 1, 0.3, 1) infinite;
        }

        .status-on {
            background-color: #00f0ff;
            color: #00f0ff;
            box-shadow: 0 0 10px #00f0ff;
        }

        .status-sim {
            background-color: #7c4dff;
            color: #7c4dff;
            box-shadow: 0 0 10px #7c4dff;
        }

        .status-err {
            background-color: #ff3366;
            color: #ff3366;
            box-shadow: 0 0 10px #ff3366;
        }

        @keyframes halo-pulse {
            0% { transform: scale(0.8); opacity: 0.8; }
            100% { transform: scale(1.6); opacity: 0; }
        }

        /* Premium Reset Button Styles */
        .reset-btn {
            background: linear-gradient(135deg, rgba(0, 240, 255, 0.1) 0%, rgba(124, 77, 255, 0.1) 100%);
            color: var(--accent-cyan);
            border: 1px solid rgba(0, 240, 255, 0.25);
            border-radius: 8px;
            padding: 10px 18px;
            font-family: 'Inter', sans-serif;
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 8px;
            box-shadow: 0 4px 15px rgba(0, 240, 255, 0.04);
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-top: 15px;
        }

        .reset-btn:hover {
            background: linear-gradient(135deg, var(--accent-cyan) 0%, var(--accent-purple) 100%);
            color: #bg-deep;
            color: #050508;
            border-color: transparent;
            box-shadow: 0 4px 20px var(--glow-cyan);
            transform: translateY(-2px);
        }

        .reset-btn:active {
            transform: translateY(0);
        }

        .reset-btn svg {
            transition: transform 0.6s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .reset-btn:hover svg {
            transform: rotate(360deg);
        }
    </style>
</head>
<body>
    <header>
        <h1>Gemini <span>Robotics Demo</span></h1>
        <p>Embodied AI Puppy Robot Live Monitoring</p>
    </header>

    <div class="container">
        <!-- LEFT COLUMN: Mind Analytics & Motor Telemetry -->
        <div class="side-column" id="left-col">
            <!-- Mind Analytics -->
            <div class="panel">
                <h3>Robot Mind Analytics</h3>
                <div class="status-badge-container">
                    <div id="state-badge" class="status-badge state-SEARCHING">CURRENT STATE: SEARCHING</div>
                </div>
                <!-- Interactive decorative speech wave -->
                <div class="vocal-visualizer">
                    <div class="bar bar-1"></div>
                    <div class="bar bar-2"></div>
                    <div class="bar bar-3"></div>
                    <div class="bar bar-4"></div>
                    <div class="bar bar-5"></div>
                </div>
            </div>

            <!-- Motor Telemetry Panel -->
            <div class="panel">
                <h3>Motor Actuator Telemetry</h3>
                <div class="vector-pad">
                    <div id="dir-forward" class="dir-arrow forward">▲</div>
                    <div class="middle-row">
                        <div id="dir-left" class="dir-arrow left">◀</div>
                        <div id="dir-stop" class="dir-arrow stop">■</div>
                        <div id="dir-right" class="dir-arrow right">▶</div>
                    </div>
                    <div id="dir-backward" class="dir-arrow backward">▼</div>
                </div>
            </div>
        </div>

        <!-- CENTER COLUMN: Live Video Panel with targeting bracket overlay & 2D Map -->
        <div class="panel" id="center-col">
            <h3>Live Camera Stream</h3>
            <div class="video-wrapper">
                <div class="live-badge">
                    <div class="live-dot"></div>
                    <span>LIVE HD</span>
                </div>
                
                <!-- 📡 HUD corner brackets -->
                <div class="corner-bracket top-left"></div>
                <div class="corner-bracket top-right"></div>
                <div class="corner-bracket bottom-left"></div>
                <div class="corner-bracket bottom-right"></div>

                <img src="/video_feed" alt="Robot Camera Stream">
            </div>

            <h3 style="margin-top: 30px; display: flex; align-items: center; gap: 8px;">
                <span>2D Arena Position Tracker</span>
                <span id="boundary-indicator" style="font-size: 0.75rem; font-weight: 600; padding: 2px 8px; border-radius: 4px; background: rgba(255, 51, 102, 0.1); color: #ff3366; border: 1px solid rgba(255, 51, 102, 0.2); text-transform: uppercase; display: none;">Boundary Alert</span>
            </h3>
            <div class="canvas-wrapper" style="position: relative; width: 100%; aspect-ratio: 12 / 8; border-radius: 16px; overflow: hidden; border: 1px solid var(--card-border); background-color: rgba(5, 5, 8, 0.8); display: flex; align-items: center; justify-content: center; padding: 12px; margin-top: 10px;">
                <canvas id="arena-map" style="width: 100%; height: 100%; display: block;"></canvas>
            </div>
            
            <!-- Reset Coordinates Control -->
            <div style="display: flex; justify-content: flex-end;">
                <button id="reset-odometry-btn" class="reset-btn">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
                    Reset Position (0,0)
                </button>
            </div>
        </div>

        <!-- RIGHT COLUMN: Thoughts Timeline & Hardware Diagnostics -->
        <div class="side-column" id="right-col">
            <!-- Brain Thoughts Timeline -->
            <div class="panel">
                <h3>Gemini Brain Thoughts</h3>
                <div id="thoughts-timeline" class="timeline">
                    <div class="timeline-item active">
                        <div class="timeline-dot"></div>
                        <div class="timeline-text">Initializing live puppy robot monitoring modules...</div>
                    </div>
                </div>
            </div>

            <!-- Hardware Diagnostics -->
            <div class="panel">
                <h3>Connected Hardware Diagnostics</h3>
                <div class="diag-list">
                    <div class="diag-item">
                        <span>📷 USB Camera Feed</span>
                        <div class="diag-status">
                            <span class="halo-dot {{ 'status-on' if camera_avail else 'status-sim' }}"></span>
                            <small>{{ 'Hardware Connected' if camera_avail else 'Simulation Mode' }}</small>
                        </div>
                    </div>
                    <div class="diag-item">
                        <span>🧠 Gemini Cloud Cortex API</span>
                        <div class="diag-status">
                            <span id="gemini-status-halo" class="halo-dot {{ 'status-on' if gemini_status == 'ACTIVE' else ('status-sim' if gemini_status == 'SIMULATION' else 'status-err') }}"></span>
                            <small id="gemini-status-text">
                                {% if gemini_status == 'ACTIVE' %}
                                    Cortex Active (Cloud)
                                {% elif gemini_status == 'SIMULATION' %}
                                    Simulation Mode (Local Only)
                                {% else %}
                                    API Error / Offline
                                {% endif %}
                            </small>
                        </div>
                    </div>
                    <div class="diag-item">
                        <span>⚡ Roborobo Open-Drain Interface</span>
                        <div class="diag-status">
                            <span class="halo-dot {{ 'status-on' if gpio_avail else 'status-sim' }}"></span>
                            <small>{{ 'Hardware Active' if gpio_avail else 'Simulation Mode' }}</small>
                        </div>
                    </div>
                    <div class="diag-item">
                        <span>🎙️ Vocal Microphone (STT)</span>
                        <div class="diag-status">
                            <span class="halo-dot {{ 'status-on' if speech_avail else 'status-sim' }}"></span>
                            <small>{{ 'Vocal Active' if speech_avail else 'Simulation Mode' }}</small>
                        </div>
                    </div>
                    <div class="diag-item">
                        <span>🌡️ Core CPU Temperature</span>
                        <div class="diag-status">
                            <span id="cpu-temp-halo" class="halo-dot status-on"></span>
                            <small id="cpu-temp-text">-- °C</small>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let thoughtsHistory = [];
        const stateBadge = document.getElementById('state-badge');
        const timelineContainer = document.getElementById('thoughts-timeline');

        function updateTimeline(newThought) {
            if (!newThought) return;
            
            // Reconstruct timeline only if the thought changed
            if (thoughtsHistory.length === 0 || thoughtsHistory[thoughtsHistory.length - 1] !== newThought) {
                thoughtsHistory.push(newThought);
                if (thoughtsHistory.length > 5) {
                    thoughtsHistory.shift();
                }
                
                // Clear and render items
                timelineContainer.innerHTML = '';
                thoughtsHistory.forEach((thought, idx) => {
                    const isLatest = (idx === thoughtsHistory.length - 1);
                    const item = document.createElement('div');
                    item.className = 'timeline-item' + (isLatest ? ' active' : '');
                    item.innerHTML = `
                        <div class="timeline-dot"></div>
                        <div class="timeline-text">${thought}</div>
                    `;
                    timelineContainer.appendChild(item);
                });
            }
        }

        function updateDriveVectors(thought) {
            // Reset arrows
            const arrows = {
                forward: document.getElementById('dir-forward'),
                backward: document.getElementById('dir-backward'),
                left: document.getElementById('dir-left'),
                right: document.getElementById('dir-right'),
                stop: document.getElementById('dir-stop')
            };
            
            for (let key in arrows) {
                if (arrows[key]) {
                    arrows[key].className = 'dir-arrow ' + key;
                }
            }
            
            if (!thought) return;
            const text = thought.toLowerCase();
            
            if (text.includes("steering left") || text.includes("tilting left") || text.includes("shuffling left") || text.includes("left")) {
                if (arrows.left) arrows.left.classList.add('active-turn');
            } else if (text.includes("steering right") || text.includes("panning right") || text.includes("looking right") || text.includes("right")) {
                if (arrows.right) arrows.right.classList.add('active-turn');
            } else if (text.includes("approaching") || text.includes("forward")) {
                if (arrows.forward) arrows.forward.classList.add('active-forward');
            } else if (text.includes("backing up") || text.includes("backward") || text.includes("back")) {
                if (arrows.backward) arrows.backward.classList.add('active-backward');
            } else {
                if (arrows.stop) arrows.stop.classList.add('active-stop');
            }
        }

        // ==========================================
        // 🎨 HTML5 Canvas 2D Arena Tracker Rendering
        // ==========================================
        const canvas = document.getElementById('arena-map');
        const ctx = canvas.getContext('2d');
        const boundaryIndicator = document.getElementById('boundary-indicator');

        function resizeCanvas() {
            if (!canvas) return;
            const rect = canvas.parentNode.getBoundingClientRect();
            canvas.width = rect.width * window.devicePixelRatio;
            canvas.height = rect.height * window.devicePixelRatio;
            ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
        }

        window.addEventListener('resize', resizeCanvas);
        resizeCanvas();

        function drawArena(x, y, theta, isOutOfBounds) {
            if (!canvas) return;
            const w = canvas.clientWidth;
            const h = canvas.clientHeight;
            
            // Clear canvas
            ctx.clearRect(0, 0, w, h);
            
            // Scale factor to map 1200x800 mm into canvas size (with 20px padding)
            const padding = 20;
            const scaleX = (w - padding * 2) / 1200;
            const scaleY = (h - padding * 2) / 800;
            const scale = Math.min(scaleX, scaleY);
            
            const centerX = w / 2;
            const centerY = h / 2;
            
            // 1. Draw Table Boundary (1200x800)
            ctx.strokeStyle = isOutOfBounds ? '#ff3366' : 'rgba(255, 255, 255, 0.15)';
            ctx.lineWidth = isOutOfBounds ? 3 : 2;
            ctx.fillStyle = 'rgba(10, 11, 16, 0.8)';
            
            const tableW = 1200 * scale;
            const tableH = 800 * scale;
            ctx.beginPath();
            if (ctx.roundRect) {
                ctx.roundRect(centerX - tableW / 2, centerY - tableH / 2, tableW, tableH, 12);
            } else {
                ctx.rect(centerX - tableW / 2, centerY - tableH / 2, tableW, tableH);
            }
            ctx.fill();
            ctx.stroke();
            
            // 2. Draw Table Grid Lines (every 100mm)
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.03)';
            ctx.lineWidth = 1;
            ctx.beginPath();
            for (let gx = -500; gx <= 500; gx += 100) {
                const lx = centerX + gx * scale;
                ctx.moveTo(lx, centerY - tableH / 2);
                ctx.lineTo(lx, centerY + tableH / 2);
            }
            for (let gy = -300; gy <= 300; gy += 100) {
                const ly = centerY - gy * scale; // Inverted Y!
                ctx.moveTo(centerX - tableW / 2, ly);
                ctx.lineTo(centerX + tableW / 2, ly);
            }
            ctx.stroke();
            
            // 3. Draw Safety Limit Boundary Box
            // Safe boundaries for center (x, y) at standard 90 degrees are:
            // x_limit = 600 - (150/2) - 50 = 475mm -> total width 950
            // y_limit = 400 - (250/2) - 50 = 225mm -> total height 450
            ctx.strokeStyle = 'rgba(0, 240, 255, 0.25)';
            ctx.setLineDash([4, 4]);
            ctx.lineWidth = 1;
            ctx.beginPath();
            const safeW = (1200 - (150 + 100)) * scale; // 950
            const safeH = (800 - (250 + 100)) * scale;  // 450
            if (ctx.roundRect) {
                ctx.roundRect(centerX - safeW / 2, centerY - safeH / 2, safeW, safeH, 8);
            } else {
                ctx.rect(centerX - safeW / 2, centerY - safeH / 2, safeW, safeH);
            }
            ctx.stroke();
            ctx.setLineDash([]); // Reset dash
            
            // 4. Draw Audience Side indicator
            ctx.fillStyle = 'rgba(255, 255, 255, 0.25)';
            ctx.font = '9px "Inter", sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('AUDIENCE VIEWPORT (1200 mm)', centerX, centerY + tableH / 2 - 8);
            
            // 5. Draw Robot (150x250 mm)
            const rx = centerX + x * scale;
            const ry = centerY - y * scale; // Inverted Y!
            const rw = 150 * scale; // Left/Right (width)
            const rl = 250 * scale; // Front/Back (length)
            
            ctx.save();
            ctx.translate(rx, ry);
            ctx.rotate(-theta * Math.PI / 180); // Inverted angle for Canvas coordinate system
            
            // Draw rotated robot body
            ctx.fillStyle = isOutOfBounds ? 'rgba(255, 51, 102, 0.15)' : 'rgba(0, 240, 255, 0.15)';
            ctx.strokeStyle = isOutOfBounds ? '#ff3366' : '#00f0ff';
            ctx.lineWidth = 2;
            ctx.beginPath();
            if (ctx.roundRect) {
                ctx.roundRect(-rl / 2, -rw / 2, rl, rw, 6);
            } else {
                ctx.rect(-rl / 2, -rw / 2, rl, rw);
            }
            ctx.fill();
            ctx.stroke();
            
            // Draw eyes/head indicating front (which is local +X side, pointing towards the target direction)
            ctx.fillStyle = isOutOfBounds ? '#ff3366' : '#00f0ff';
            ctx.beginPath();
            ctx.arc(rl / 2 - 10, -rw / 4, 3, 0, Math.PI * 2);
            ctx.arc(rl / 2 - 10, rw / 4, 3, 0, Math.PI * 2);
            ctx.fill();
            
            // Draw heading direction arrow
            ctx.strokeStyle = isOutOfBounds ? '#ff3366' : '#00f0ff';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(0, 0);
            ctx.lineTo(rl / 2 + 15, 0);
            ctx.lineTo(rl / 2 + 10, -5);
            ctx.moveTo(rl / 2 + 15, 0);
            ctx.lineTo(rl / 2 + 10, 5);
            ctx.stroke();
            
            ctx.restore();
            
            // 6. Draw coordinate overlay
            ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
            ctx.font = '10px "Inter", sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(`X: ${Math.round(x)} mm`, centerX - tableW / 2 + 12, centerY + tableH / 2 - 24);
            ctx.fillText(`Y: ${Math.round(y)} mm`, centerX - tableW / 2 + 12, centerY + tableH / 2 - 10);
            ctx.textAlign = 'right';
            ctx.fillText(`Angle: ${Math.round(theta)}°`, centerX + tableW / 2 - 12, centerY + tableH / 2 - 10);
        }

        setInterval(function() {
            fetch('/status')
                .then(res => res.json())
                .then(data => {
                    // Update state badge
                    stateBadge.innerText = "CURRENT STATE: " + data.state;
                    stateBadge.className = "status-badge state-" + data.state;
                    
                    // Update thoughts stream timeline
                    updateTimeline(data.thought);
                    
                    // Update Motor Drive Vector Indicators
                    updateDriveVectors(data.thought);

                    // Update 2D Canvas Arena Tracker
                    if (data.x !== undefined && data.y !== undefined && data.theta !== undefined) {
                        drawArena(data.x, data.y, data.theta, data.is_out_of_bounds);
                        if (boundaryIndicator) {
                            boundaryIndicator.style.display = data.is_out_of_bounds ? 'inline-block' : 'none';
                        }
                    }

                    // Update CPU Temperature
                    const cpuText = document.getElementById('cpu-temp-text');
                    const cpuHalo = document.getElementById('cpu-temp-halo');
                    if (cpuText && cpuHalo && data.cpu_temp !== undefined) {
                        cpuText.innerText = data.cpu_temp + " °C";
                        if (data.cpu_temp > 70) {
                            cpuHalo.style.backgroundColor = '#ff3366';
                            cpuHalo.style.color = '#ff3366';
                            cpuHalo.style.boxShadow = '0 0 10px #ff3366';
                        } else if (data.cpu_temp > 55) {
                            cpuHalo.style.backgroundColor = '#e5a93c';
                            cpuHalo.style.color = '#e5a93c';
                            cpuHalo.style.boxShadow = '0 0 10px #e5a93c';
                        } else {
                            cpuHalo.style.backgroundColor = '#00f0ff';
                            cpuHalo.style.color = '#00f0ff';
                            cpuHalo.style.boxShadow = '0 0 10px #00f0ff';
                        }
                    }

                    // Update Gemini Status
                    const geminiText = document.getElementById('gemini-status-text');
                    const geminiHalo = document.getElementById('gemini-status-halo');
                    if (geminiText && geminiHalo && data.gemini_status !== undefined) {
                        if (data.gemini_status === 'ACTIVE') {
                            geminiText.innerText = "Cortex Active (Cloud)";
                            geminiHalo.className = "halo-dot status-on";
                            geminiHalo.style.backgroundColor = "";
                            geminiHalo.style.color = "";
                            geminiHalo.style.boxShadow = "";
                        } else if (data.gemini_status === 'SIMULATION') {
                            geminiText.innerText = "Simulation Mode (Local Only)";
                            geminiHalo.className = "halo-dot status-sim";
                            geminiHalo.style.backgroundColor = "";
                            geminiHalo.style.color = "";
                            geminiHalo.style.boxShadow = "";
                        } else {
                            geminiText.innerText = "API Error / Offline";
                            geminiHalo.className = "halo-dot status-err";
                            geminiHalo.style.backgroundColor = "";
                            geminiHalo.style.color = "";
                            geminiHalo.style.boxShadow = "";
                        }
                    }
                })
                .catch(err => console.error("Error fetching status:", err));
        }, 200); // Polling running at 5Hz high speed for fluid radar synchronization

        // Reset Odometry Handler
        const resetBtn = document.getElementById('reset-odometry-btn');
        if (resetBtn) {
            resetBtn.addEventListener('click', function() {
                // Instantly spin svg for premium visual feedback
                const svg = resetBtn.querySelector('svg');
                if (svg) {
                    svg.style.transform = 'rotate(360deg)';
                }
                
                fetch('/reset_odometry', { method: 'POST' })
                    .then(res => res.json())
                    .then(data => {
                        console.log("Odometry reset response:", data);
                        // Restoring rotation delay to match premium experience
                        setTimeout(() => {
                            if (svg) svg.style.transform = 'rotate(0deg)';
                        }, 600);
                    })
                    .catch(err => {
                        console.error("Failed to reset odometry:", err);
                        alert("Error resetting coordinates!");
                    });
            });
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(
        HTML_DASHBOARD_TEMPLATE,
        camera_avail=CAMERA_ACTIVE,
        gpio_avail=GPIO_AVAILABLE,
        speech_avail=SPEECH_AVAILABLE,
        gemini_status=GEMINI_STATUS
    )

# ==========================================
# 🚀 Main Core Runtime Entry Point
# ==========================================
if __name__ == '__main__':
    print("==========================================================")
    print("🤖 GEMINI EMBEDDED AI ROBOT PUPPY STARTING...")
    print("==========================================================")
    
    t_cam = threading.Thread(target=camera_capture_thread)
    t_vis = threading.Thread(target=vision_control_thread)
    t_aud = threading.Thread(target=audio_recognition_thread)
    t_gem = threading.Thread(target=gemini_brain_thread)
    t_enc = threading.Thread(target=streaming_encoder_thread)
    
    t_cam.daemon = True
    t_vis.daemon = True
    t_aud.daemon = True
    t_gem.daemon = True
    t_enc.daemon = True
    
    t_cam.start()
    t_vis.start()
    t_aud.start()
    t_gem.start()
    t_enc.start()
    
    print("\n[PORTAL] Web Monitor Dashboard running on port 5000.")
    print("         Access live feed at: http://localhost:5000")
    print("==========================================================\n")
    
    try:
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    except KeyboardInterrupt:
        RUNNING = False
        robot.stop()
        print("\n⏹️ [SYSTEM] AI puppy robot manually stopped by the user.")
        sys.exit(0)
