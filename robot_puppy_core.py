#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
robot_puppy_core.py (Ultimate Premium Edition)
================================================================================
Intelligent robotic puppy core program integrating Gemini Robotics-ER 1.6 Preview
model with Raspberry Pi 4B.

- Cortex: Google Cloud Gemini Robotics-ER 1.6 Preview asynchronous object detection and high-level reasoning.
- Reflex: Local 30 FPS real-time owner face tracking (Gemini-guided) and direct DC motor tracking control.
- Auditory: voice commands recognized by Gemini audio (local VAD captures the spoken utterance) for simple motion control (come, stop, forward, backward, turn, spin).
- HUD Dashboard: Google AI Studio style premium dark-mode real-time web dashboard (Port 5000, 100% English, Inter font).
================================================================================
"""

import os
import sys
import math
import io
import wave
import asyncio

# 🛡️ Force UTF-8 encoding on stdout/stderr to prevent fatal UnicodeEncodeError crashes 
# when printing emojis (🤖, 🧸, 🔴) in background threads on remote Raspberry Pi terminals or SSH.
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ==========================================
# ⚙️ Load environment variables from .env file (python-dotenv preferred)
# ==========================================
def _load_env_file():
    """Load .env via python-dotenv; fall back to a minimal manual parser if unavailable."""
    try:
        from dotenv import load_dotenv
        load_dotenv()  # Existing real environment variables take precedence (override=False by default)
        print("ℹ️ [ENV] Environment variables loaded from .env via python-dotenv.")
        return
    except ImportError:
        print("⚠️ [ENV] python-dotenv not installed. Falling back to manual .env parsing.")

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
                            # setdefault keeps real environment variables authoritative, matching load_dotenv semantics
                            os.environ.setdefault(key, val)
        except Exception as e:
            print(f"⚠️ [ENV] Failed to parse .env file: {e}")

_load_env_file()

import time
import json
import threading
import random
import numpy as np
import cv2
from flask import Flask, Response, render_template_string, jsonify, request
from PIL import Image, ImageDraw, ImageFont

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
            self.abort_event = threading.Event()
            self.bark_time = 0.0  # [WOW EFFECT] Timestamp of last bark for visual dashboard flash
            # [ODO-SAFETY] mirror the real controller's fail-safe fields so the dashboard/vision hooks work in mock mode
            self.position_uncertainty = 0.0
            self.needs_rehome = False
        def reset_odometry(self, x=0.0, y=0.0, theta=90.0):
            self.x = x
            self.y = y
            self.theta = theta
            self.is_out_of_bounds = False
            # [ODO-SAFETY] clear drift estimate on re-home
            self.position_uncertainty = 0.0
            self.needs_rehome = False
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
            self.bark_time = time.time()
            print("[SOUND MOCK] 🐕 Happy Bark Bark!")
        def beep(self):
            print("[SOUND MOCK] 🔊 Beep!")
        def express_happy(self):
            print("[MOTION MOCK] 🕺 Joyful Tail-Wagging Dance!")
        def line_signal_active(self):
            return False
        def anchor_to_boundary_line(self):
            return False
    robot = MockRobotController()

# Voice commands are recognized by sending a short captured utterance to Gemini
# (audio understanding). SPEECH_AVAILABLE is finalized after the google-genai import below.
SPEECH_AVAILABLE = False

# Attempting google-genai initialization
GEMINI_AVAILABLE = False
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    genai = None
    types = None

# Voice recognition uses Gemini audio, so the auditory layer needs google-genai.
SPEECH_AVAILABLE = GEMINI_AVAILABLE

# Attempting Pydantic models initialization for Structured Outputs
PYDANTIC_AVAILABLE = False
if GEMINI_AVAILABLE:
    try:
        from pydantic import BaseModel, Field
        from typing import List, Optional
        
        class DetectedObject(BaseModel):
            box_2d: List[int] = Field(..., description="Normalized coordinates [ymin, xmin, ymax, xmax] on a 0 to 1000 integer scale.")
            label: str = Field(..., description="The label of the detected object.")

        class PuppyBrainResponse(BaseModel):
            owner_box: Optional[List[int]] = Field(None, description="[ymin, xmin, ymax, xmax] of the owner, or null/None if not spotted.")
            detected_objects: List[DetectedObject] = Field(default_factory=list, description="Up to 8 other detected objects.")
            thought: str = Field(..., description="A brief English thought explaining what you see and feel as a robotic puppy.")
        PYDANTIC_AVAILABLE = True
    except ImportError:
        PYDANTIC_AVAILABLE = False

# ==========================================
# 🎛️ Tunable Vision & Behavior Constants
# ==========================================
# Perception: Gemini Robotics-ER is the authority on who/where the target is; a local
# visual tracker follows that target smoothly between the ~1.5s Gemini verdicts.
GEMINI_LOST_VERDICTS = 2             # consecutive Gemini "no owner" verdicts before dropping the target
TRACKER_DOWNSCALE = 0.5             # run the local tracker on a downscaled frame to save Pi CPU (0.5 -> 320x240)
TRACKER_UPDATE_EVERY = 1            # run tracker.update() every N vision frames (raise if CPU is too high)

# Stale-anchor guard: a Gemini verdict describes a frame captured 1.5-3s earlier. If the
# robot turned/moved since, those box coordinates point at the WRONG place - anchoring
# the tracker there makes it track background and wander off. Verdicts that fail this
# freshness check are used only as "the owner exists" evidence, never as spatial anchors.
ANCHOR_MAX_TURN_DEG = 10.0           # max heading change since the frame was captured
ANCHOR_MAX_MOVE_MM = 50.0            # max position change since the frame was captured

# Sighting hold: when a verdict SEES a person but its coordinates are stale (the robot
# was moving), freeze and stare - the immediately re-triggered verdict is then captured
# while stationary, passes the freshness guard, and produces the actual lock-on.
# Without this the robot can look straight at a face and keep scanning past it.
SIGHTING_HOLD_S = 4.5                # long enough for one full Gemini capture+verdict cycle

ALIGN_LEFT_THRESHOLD = 0.43          # X ratio below which robot turns left (narrow center band for tighter centering)
ALIGN_RIGHT_THRESHOLD = 0.57         # X ratio above which robot turns right (widen back toward 0.35/0.65 if it hunts/oscillates)
DISTANCE_FAR_THRESHOLD = 0.32        # Height ratio below which robot moves forward
DISTANCE_CLOSE_THRESHOLD = 0.48      # Height ratio above which robot moves backward
EMERGENCY_EVADE_THRESHOLD = 0.60     # Height ratio above which emergency evasion triggers

FOLLOWING_LOST_GRACE_TICKS = 90      # Ticks to wait before FOLLOWING -> SEARCHING (~3s)
DOZING_TIMEOUT_TICKS = 1080          # Ticks of no detection before entering DOZING (~36s)

# When the locked owner briefly vanishes, fidget in place like a restless pet (short
# look-around bursts) instead of standing perfectly still, for a bit of personality.
# Each entry is (motor_action, ticks_to_hold); the sequence loops during the wait.
RESTLESS_FIDGET = [
    ("turn_left", 3), ("stop", 4), ("turn_right", 3), ("stop", 4),
    ("move_forward", 2), ("stop", 5), ("move_backward", 2), ("stop", 6),
]
FIDGET_START_TICKS = 12              # consecutive tracker-miss frames (~0.4s) before fidgeting kicks in;
                                     # brief one-frame dropouts keep the last motor command instead
                                     # (reacting instantly made following and fidgeting fight at frame rate)
TURN_REVERSE_DWELL_S = 0.15          # minimum time before an alignment turn may reverse direction (anti-chatter)

# Line-detect feedback (Roborobo board -> BCM 24): while HIGH the board's own reflex
# owns the motors; the Pi yields completely and anchors odometry to the marker line.
LINE_EVENT_GAP_S = 0.5               # gaps shorter than this merge into ONE event (observed 2ms re-trigger gaps)
LINE_YIELD_HOLD_S = 0.8              # keep yielding this long after the signal drops (let the reflex finish cleanly)

# When the owner is lost for good, drive back to the home base (0, 0) before resuming
# the scan, instead of searching from wherever it happened to lose track.
RETURN_HOME_ON_LOSS = True           # False -> keep the old in-place search-on-loss behavior
HOME_POSITION_TOLERANCE = 70.0       # mm from origin treated as "home reached"
HOME_HEADING_TOLERANCE = 18.0        # deg heading error above which we turn in place toward home first

OBJECT_STALE_TIMEOUT = 4.0           # Seconds before Gemini object overlays expire

VISION_LOOP_INTERVAL = 0.033         # ~30 FPS vision loop sleep (seconds)
GEMINI_POLL_INTERVAL = 1.5           # Gemini API polling interval (seconds)
STREAM_ENCODE_INTERVAL = 0.033       # ~30 FPS stream encoder sleep (seconds)
STREAM_SERVE_INTERVAL = 0.05         # ~20 FPS web streaming yield interval (seconds)

# ==========================================
# 🧠 Global system coordination state variables
# ==========================================
# Build tag printed at startup: bump when deploying so a stale copy on the Pi is
# immediately visible in the console (deployment-mismatch debugging).
CORE_BUILD = "2026-07-13g live-session persistence + anchor clamp"

CURRENT_STATE = "SEARCHING"          # SEARCHING, FOLLOWING, DANCED, STAY
RAW_FRAME = None                     # Real-time raw camera or simulation frame
STREAM_RESOLUTION = (512, 384)       # Dynamic web stream resolution
STREAM_JPEG_QUALITY = 58             # Dynamic web stream JPEG compression quality
LATEST_JPEG_BYTES = None             # High-speed encoded byte cache for real-time HD streaming
RUNNING = True                       # Multi-thread lifecycle holder
DETECTED_OBJECTS = []                # Real-time robotics pointer labels cache
LAST_DETECTION_TIME = 0.0            # Timestamp of the last object detection API update
DASHBOARD_OBJECTS = []               # Real-time normalized objects cache for HTML/CSS vector overlays

CAMERA_ACTIVE = False                # Flag indicating if the USB camera is active
LATEST_BBOX = None                   # Real-time cortex target bounding box (ymin, xmin, ymax, xmax)
LATEST_BBOX_SEQ = 0                   # Bumped by the Gemini thread on every verdict; vision thread consumes fresh ones
LATEST_BBOX_POSE = None               # (theta, x, y) of the robot when the verdict's frame was CAPTURED (stale-anchor guard)
OWNER_DESCRIPTION = "The primary human owner's face" # Owner characteristics description (used by the Gemini cortex to identify the person)
GEMINI_STATUS = "SIMULATION"         # Gemini API status: ACTIVE, SIMULATION, ERROR
LAST_THOUGHT = "System initialized. Standing by." # Live robot mind thoughts log cache


# Coordination and Synchronization primitives
gemini_trigger_event = threading.Event() # Event to trigger immediate Gemini API request
voice_abort_event = threading.Event()    # Set to cut short a running voice motor burst (new command preempts old)
gaze_start_time = 0.0                # Timestamp of when the local gaze inspection began

# Global lock and busy flags for thread safety and state coordination
state_lock = threading.Lock()
is_robot_busy = False                 # Flag to temporarily block control loop for emotional/vocal tasks
current_voice_intent = None           # Intent of the voice burst currently executing (None when idle)
autonomy_hold_until = 0.0             # Until this timestamp, autonomous driving is paused (set by voice commands)

# Background real-time camera byte/frame cache and dedicated lock
LATEST_CAMERA_FRAME = None
camera_lock = threading.Lock()

# Locks for frame/streaming byte synchronization
frame_lock = threading.Lock()         # Lock to protect RAW_FRAME reads/writes
jpeg_lock = threading.Lock()          # Lock to protect LATEST_JPEG_BYTES reads/writes

# Visual style resources (Google AI Studio technical colors)
COLOR_CYAN = (193, 172, 0)           # Cyan (#00acc1)
COLOR_WHITE = (255, 255, 255)

# ==========================================
# 📐 Google Robotics UI style rendering helper functions
# ==========================================
# Crisp anti-aliased TrueType label rendering (matches the Gemini Robotics
# point-to-object docs style, instead of the blocky OpenCV Hershey font).
_FONT_PATH_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
]
_FONT_CACHE = {}

def _get_label_font(size):
    """Returns a cached TrueType font at the given pixel size (falls back to PIL default)."""
    key = int(size)
    if key not in _FONT_CACHE:
        font = None
        for path in _FONT_PATH_CANDIDATES:
            if os.path.exists(path):
                try:
                    font = ImageFont.truetype(path, key)
                    print(f"✅ [FONT] Label font resolved: {path} @ {key}px")
                    break
                except Exception:
                    continue
        if font is None:
            # No TrueType font found. On a minimal Ubuntu image this yields a tiny
            # bitmap font (size ignored) -> install fonts: sudo apt install fonts-dejavu-core
            font = ImageFont.load_default()
            print("⚠️ [FONT] No TrueType font found; falling back to low-res bitmap. "
                  "Run: sudo apt install fonts-dejavu-core")
        _FONT_CACHE[key] = font
    return _FONT_CACHE[key]

def measure_label_pil(text, font_size):
    """Returns (width, height) in pixels for a label rendered at font_size."""
    font = _get_label_font(font_size)
    try:
        width = int(round(font.getlength(text)))
    except AttributeError:
        bbox = font.getbbox(text)
        width = bbox[2] - bbox[0]
    ascent, descent = font.getmetrics()
    return width, ascent + descent

def draw_label_pil(img, text, org, color_bgr, font_size):
    """Draws anti-aliased TrueType text onto a BGR OpenCV image in place.
    `org` is the top-left corner (x, y). Text blends over whatever is already
    drawn (e.g. the caption fill), so call this AFTER drawing the background.

    Only the small text bounding-box region is round-tripped through PIL (not the
    whole frame), to keep per-label cost low on the Raspberry Pi 4B / ARM."""
    font = _get_label_font(font_size)
    x, y = int(org[0]), int(org[1])
    text_w, text_h = measure_label_pil(text, font_size)

    h_img, w_img = img.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    # +2px margin so anti-aliased edges/descenders are not clipped
    x1, y1 = min(w_img, x + text_w + 2), min(h_img, y + text_h + 2)
    if x1 <= x0 or y1 <= y0:
        return  # fully off-screen, nothing to draw

    region = img[y0:y1, x0:x1]
    pil_region = Image.fromarray(cv2.cvtColor(region, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_region)
    color_rgb = (color_bgr[2], color_bgr[1], color_bgr[0])
    draw.text((x - x0, y - y0), text, font=font, fill=color_rgb)
    region[:] = cv2.cvtColor(np.array(pil_region), cv2.COLOR_RGB2BGR)

def draw_google_style_box(img, label, x, y, w, h, color):
    """Draws a technical design label box matching the Google AI Studio GUI."""
    cv2.rectangle(img, (x, y), (x + w, y + h), color, 2)
    font_size = 16
    pad_x, pad_y = 8, 5
    text_w, text_h = measure_label_pil(label, font_size)

    tab_x1, tab_y1 = x, y - text_h - pad_y * 2
    tab_x2, tab_y2 = x + text_w + pad_x * 2, y
    if tab_y1 < 0:
        tab_y1, tab_y2 = y, y + text_h + pad_y * 2

    cv2.rectangle(img, (tab_x1, tab_y1), (tab_x2, tab_y2), color, -1)
    draw_label_pil(img, label, (tab_x1 + pad_x, tab_y1 + pad_y), (255, 255, 255), font_size)

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

    font_size = 14
    pad_x, pad_y = 9, 5
    text_w, text_h = measure_label_pil(label, font_size)

    cap_h = text_h + pad_y * 2
    cap_w = text_w + pad_x * 2

    cap_x1 = cx + 8
    cap_y1 = cy - cap_h // 2
    cap_x2 = cap_x1 + cap_w
    cap_y2 = cy + cap_h // 2

    if cap_x2 > w_img:
        cap_x2 = cx - 8
        cap_x1 = cap_x2 - cap_w

    draw_rounded_rectangle(img, (cap_x1, cap_y1), (cap_x2, cap_y2), blue_color, thickness=-1, r=cap_h // 2)
    draw_label_pil(img, label, (cap_x1 + pad_x, cap_y1 + pad_y), (255, 255, 255), font_size)

    cv2.circle(img, (cx, cy), 6, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), 4, blue_color, -1, cv2.LINE_AA)

def create_simulated_frame(tick):
    """Virtual person detection simulation frame shown when the camera is inactive (640x480 VGA)"""
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    for i in range(0, 480, 60):
        cv2.line(img, (0, i), (640, i), (18, 19, 23), 1)
    for i in range(0, 640, 60):
        cv2.line(img, (i, 0), (i, 480), (18, 19, 23), 1)

    cx = int(320 + 160 * np.sin(tick * 0.04))
    cy = int(240 + 70 * np.cos(tick * 0.02))
    r = 60

    # Render a standard human face placeholder
    cv2.circle(img, (cx, cy), r, (75, 78, 84), -1)
    cv2.circle(img, (cx, cy), r, (110, 115, 122), 1)
    # Eyes
    cv2.circle(img, (cx - 18, cy - 12), 6, (255, 255, 255), -1)
    cv2.circle(img, (cx + 18, cy - 12), 6, (255, 255, 255), -1)
    # Smile
    cv2.ellipse(img, (cx, cy + 16), (16, 8), 0, 0, 180, (0, 0, 255), 4)

    cv2.putText(img, "SIMULATING EYE FEED: HUMAN FACE", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 105, 115), 1, cv2.LINE_AA)

    # Return mock face bounding box coordinates normalized to 0~1000 range
    ymin = int((cy - r) * 1000 / 480)
    xmin = int((cx - r) * 1000 / 640)
    ymax = int((cy + r) * 1000 / 480)
    xmax = int((cx + r) * 1000 / 640)
    
    mock_face_box = (cx - r, cy - r, r*2, r*2)
    return img, mock_face_box, [ymin, xmin, ymax, xmax]

def _restless_action(phase_tick):
    """Pick the current fidget motor action from RESTLESS_FIDGET for the given phase tick."""
    total = sum(d for _, d in RESTLESS_FIDGET)
    if total <= 0:
        return "stop"
    t = phase_tick % total
    acc = 0
    for action, d in RESTLESS_FIDGET:
        acc += d
        if t < acc:
            return action
    return "stop"

_tracker_type_logged = False

def _create_tracker():
    """Create the best available OpenCV single-object tracker, or None if none exists.
    Prefers CSRT (accurate) then KCF (fast); falls back to MIL (bundled with plain
    opencv-python) and to the legacy/contrib namespace. A fresh instance is returned
    per target, so call this again on every Gemini re-anchor."""
    global _tracker_type_logged

    def _made(name, ctor):
        global _tracker_type_logged
        if not _tracker_type_logged:
            _tracker_type_logged = True
            quality = "good" if ("CSRT" in name or "KCF" in name) else \
                      "WEAK fallback - install opencv-contrib-python for CSRT/KCF"
            print(f"[TRACKER] Using {name} ({quality}).")
        return ctor()

    for name in ("TrackerCSRT_create", "TrackerKCF_create", "TrackerMIL_create"):
        ctor = getattr(cv2, name, None)
        if ctor is not None:
            try:
                return _made(name, ctor)
            except Exception:
                pass
    legacy = getattr(cv2, "legacy", None)
    if legacy is not None:
        for name in ("TrackerCSRT_create", "TrackerKCF_create", "TrackerMOSSE_create"):
            ctor = getattr(legacy, name, None)
            if ctor is not None:
                try:
                    return _made("legacy." + name, ctor)
                except Exception:
                    pass
    if not _tracker_type_logged:
        _tracker_type_logged = True
        print("[TRACKER] No OpenCV tracker available - coasting on raw Gemini boxes only.")
    return None

def _norm_to_pixel_box(norm_box, w, h):
    """Convert a normalized [ymin, xmin, ymax, xmax] (0-1000 scale) box to pixel (x, y, w, h)."""
    ymin, xmin, ymax, xmax = norm_box
    ymin, ymax = min(ymin, ymax), max(ymin, ymax)
    xmin, xmax = min(xmin, xmax), max(xmin, xmax)
    x1 = int(xmin * w / 1000.0)
    y1 = int(ymin * h / 1000.0)
    x2 = int(xmax * w / 1000.0)
    y2 = int(ymax * h / 1000.0)
    return (x1, y1, max(1, x2 - x1), max(1, y2 - y1))

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
    
    tick = 0
    search_state_counter = 0
    owner_was_present = False

    evade_ticks = 0
    evade_dir = None
    following_lost_ticks = 0

    # Perception: Gemini Robotics-ER is the authority on the owner box; a local visual
    # tracker follows it smoothly between the ~1.5s Gemini verdicts.
    owner_track_box = None            # (x, y, w, h) current owner box in pixel coords, or None
    tracker = None                    # local OpenCV tracker following the owner between verdicts
    gemini_lost_count = 0             # consecutive Gemini "no owner" verdicts
    last_bbox_seq = -1                # last Gemini verdict sequence consumed

    # Alignment anti-chatter: remember the last steering turn so it cannot reverse
    # direction faster than TURN_REVERSE_DWELL_S (on-off motors flip-flop otherwise).
    last_turn_dir = None
    last_turn_time = 0.0

    # Line-detect feedback state (board reflex cooperation + odometry anchoring)
    line_last_high = 0.0              # last time the line signal was seen HIGH

    # Sighting hold: freeze-and-stare window after a stale person sighting (see SIGHTING_HOLD_S)
    sighting_hold_until = 0.0

    while RUNNING:
        # Update odometry coordinates on every 30 FPS tick to maintain smooth and up-to-date coordinate readings
        robot.update_odometry()

        tick += 1
        sim_bbox = None
        frame = None

        if CAMERA_ACTIVE:
            with camera_lock:
                if LATEST_CAMERA_FRAME is not None:
                    frame = LATEST_CAMERA_FRAME.copy()

            if frame is None:
                time.sleep(0.01)
                continue

            # [LIVE STREAM SAFETY] Immediately feed the raw camera frame so web streaming never freezes on early loop exits
            with frame_lock:
                RAW_FRAME = frame
        else:
            # Camera unavailable: the simulated frame provides a moving mock target box.
            frame, _mock_face_box, sim_bbox = create_simulated_frame(tick)
            # Periodically hide the mock target to exercise the loss / return-home behavior.
            if tick % 120 >= 90:
                sim_bbox = None

        # Dynamically capture actual frame dimensions (safest)
        h, w = frame.shape[:2]
        
        # ----------------------------------
        # 30 FPS Vision Alignment and Behavior Decision Logic (Cortex-Reflex Hybrid)
        # ----------------------------------
        # ── [ODO-SAFETY] FAIL-SAFE: odometry drift too large -> stop and request a physical re-home ──
        # When the position estimate is no longer trustworthy, steering "back to center" would rely on
        # a wrong estimate and could push the robot OFF the table, so we simply stop and wait for the
        # operator to re-center the robot and press Reset on the dashboard.
        if getattr(robot, 'needs_rehome', False):
            robot.abort_event.set()  # cancel any emotional expression in progress
            robot.stop()
            LAST_THOUGHT = "[SAFETY] Position estimate untrusted (odometry drift). Please re-center me and press Reset."
            with frame_lock:
                RAW_FRAME = frame
            time.sleep(VISION_LOOP_INTERVAL)
            continue
        # ── [/ODO-SAFETY] ──

        # 0-a. BOARD LINE-REFLEX COOPERATION (hardware boundary sensor - highest fidelity)
        # While the Roborobo board reports its black-marker reflex (BCM 24 HIGH), the
        # board owns the motors: we release all our pins (stop = High-Z) so its backup
        # maneuver runs unopposed, kill any voice burst/expression, and ANCHOR odometry
        # to the marker line (an absolute position fact). A short hold after the signal
        # drops prevents instantly driving back into the line.
        if robot.line_signal_active():
            if time.time() - line_last_high > LINE_EVENT_GAP_S:
                # New event (debounced against the observed millisecond re-trigger gaps)
                robot.abort_event.set()
                anchored = robot.anchor_to_boundary_line()
                print(f"[LINE] Boundary marker hit: yielding to board reflex "
                      f"({'odometry anchored' if anchored else 'uncertainty capped'}).")
            line_last_high = time.time()
            robot.stop()
            LAST_THOUGHT = "[Line Sensor] Boundary marker! Backing away (board reflex)..."
            with frame_lock:
                RAW_FRAME = frame
            time.sleep(VISION_LOOP_INTERVAL)
            continue
        elif time.time() - line_last_high < LINE_YIELD_HOLD_S:
            robot.stop()
            LAST_THOUGHT = "[Line Sensor] Reflex finished. Settling before resuming..."
            with frame_lock:
                RAW_FRAME = frame
            time.sleep(VISION_LOOP_INTERVAL)
            continue

        # 0. TABLE BOUNDARY SOFT SAFETY OVERRIDE
        # Same controller as return-home: turn toward the table center within a heading
        # DEADBAND, then DRIVE back inside. (The old sign-only left/right rule had no
        # deadband and no forward step: once the robot happened to face the center the
        # sign flipped every frame, chattering left/right forever while never actually
        # re-entering the safe area. is_safe_action explicitly allows forward moves
        # that reduce the boundary violation, so driving in is safe.)
        if robot.is_out_of_bounds:
            robot.abort_event.set()  # Preempt any in-progress emotional expression; safety takes priority
            desired = math.degrees(math.atan2(-robot.y, -robot.x))
            err = ((desired - robot.theta + 180) % 360) - 180
            if err > HOME_HEADING_TOLERANCE:
                robot.turn_left()
                LAST_THOUGHT = f"[Boundary Alert] Table edge! Turning toward center... (X={robot.x:.1f}, Y={robot.y:.1f})"
            elif err < -HOME_HEADING_TOLERANCE:
                robot.turn_right()
                LAST_THOUGHT = f"[Boundary Alert] Table edge! Turning toward center... (X={robot.x:.1f}, Y={robot.y:.1f})"
            else:
                robot.move_forward()
                LAST_THOUGHT = f"[Boundary Alert] Driving back toward table center... (X={robot.x:.1f}, Y={robot.y:.1f})"
            with frame_lock:
                RAW_FRAME = frame
            time.sleep(VISION_LOOP_INTERVAL)
            continue

        # 1. EMERGENCY EVADING STATE (Escape Maneuver when too close)
        if CURRENT_STATE == "EVADING":
            evade_ticks += 1
            # [ODO-SAFETY] Backward is the least-observable direction (no IR reaches the Pi and the
            # odometry drift there is unguarded), so keep the reverse burst SHORT and recover space
            # mostly by pivoting in place instead of driving blind.
            if evade_ticks < 10: # ~0.33s short back up (was 1s) to minimize blind reverse travel
                robot.move_backward()
                LAST_THOUGHT = f"Whoa, too close! Short back-up... ({evade_ticks}/10)"
            elif evade_ticks < 70: # ~1.9s pivot turn to open up space without driving blind
                if evade_dir == 'left':
                    robot.turn_left()
                else:
                    robot.turn_right()
                LAST_THOUGHT = f"Pivot turning {evade_dir} to find a safer direction... ({evade_ticks}/70)"
            else:
                robot.stop()
                with state_lock:
                    CURRENT_STATE = "SEARCHING"
                search_state_counter = 0
                evade_ticks = 0
                evade_dir = None
                LAST_THOUGHT = "Space cleared! Resuming search for my owner."
            with frame_lock:
                RAW_FRAME = frame
            time.sleep(VISION_LOOP_INTERVAL)
            continue

        target_center_x = None
        target_box = None
        # Voice-command hold: autonomous driving stays paused for a while after a voice
        # command so its result is not instantly overridden by tracking (VOICE > autonomy).
        autonomy_held = time.time() < autonomy_hold_until

        # ==========================================================
        # PERCEPTION: Gemini Robotics-ER = authority on the owner; local tracker = bridge
        # Gemini localizes the owner every ~1.5s and (re)anchors the tracker; the tracker
        # follows that SAME target every frame in between. New people cannot steal the lock
        # (the tracker follows the original); only a Gemini re-anchor changes the target.
        # ==========================================================
        visible = False   # is a valid owner box available THIS frame?

        if not CAMERA_ACTIVE:
            # Simulation: use the mock box directly as the owner box.
            owner_track_box = _norm_to_pixel_box(sim_bbox, w, h) if sim_bbox is not None else None
            visible = owner_track_box is not None
            tracker = None
        else:
            # (a) A fresh Gemini verdict re-anchors the owner and (re)initializes the tracker.
            with state_lock:
                cur_seq = LATEST_BBOX_SEQ
                cur_bbox = tuple(LATEST_BBOX) if LATEST_BBOX else None
                cur_pose = LATEST_BBOX_POSE
            anchored = False
            if cur_seq != last_bbox_seq:
                last_bbox_seq = cur_seq
                if cur_bbox:
                    gemini_lost_count = 0
                    # STALE-ANCHOR GUARD: only anchor if the robot has NOT turned/moved
                    # since the verdict's frame was captured (else the coordinates point
                    # at the wrong place and the tracker would latch onto background).
                    pose_fresh = True
                    if cur_pose is not None:
                        d_theta = abs(((robot.theta - cur_pose[0]) + 180.0) % 360.0 - 180.0)
                        d_move = math.hypot(robot.x - cur_pose[1], robot.y - cur_pose[2])
                        pose_fresh = d_theta <= ANCHOR_MAX_TURN_DEG and d_move <= ANCHOR_MAX_MOVE_MM
                    if pose_fresh:
                        owner_track_box = _norm_to_pixel_box(cur_bbox, w, h)
                        following_lost_ticks = 0
                        visible = True
                        anchored = True
                        # Tracker init only on SANE boxes: huge body-fusion boxes that
                        # span nearly the whole frame give the tracker nothing
                        # distinctive to lock onto. Without a tracker we simply coast on
                        # the Gemini box until the next fresh verdict re-centers it.
                        bx, by, bw, bh = owner_track_box
                        if bw < 0.85 * w and bh < 0.9 * h:
                            tracker = _create_tracker()
                            if tracker is not None:
                                try:
                                    ts = TRACKER_DOWNSCALE
                                    small = cv2.resize(frame, (int(w * ts), int(h * ts))) if ts != 1.0 else frame
                                    tracker.init(small, (int(bx * ts), int(by * ts), max(1, int(bw * ts)), max(1, int(bh * ts))))
                                except Exception:
                                    tracker = None
                        else:
                            tracker = None
                    else:
                        # Stale coordinates, but the SIGHTING itself is real: someone is
                        # nearby. If we have no lock yet, freeze and stare - the next
                        # verdict (triggered right now) will be captured while we are
                        # stationary and can anchor. Existing tracks stay untouched.
                        if owner_track_box is None:
                            sighting_hold_until = time.time() + SIGHTING_HOLD_S
                            gemini_trigger_event.set()
                            print("[VISION] Person sighted while moving: freezing for a steady look...")
                else:
                    gemini_lost_count += 1
                    if gemini_lost_count >= GEMINI_LOST_VERDICTS:
                        owner_track_box = None      # Gemini repeatedly finds no owner -> release
                        tracker = None
                        gemini_lost_count = 0
                        following_lost_ticks = 0
                        with state_lock:
                            CURRENT_STATE = "RETURNING" if RETURN_HOME_ON_LOSS else "SEARCHING"

            # (b) Between verdicts, follow the owner smoothly with the local tracker.
            if owner_track_box is not None and not anchored:
                if tracker is not None:
                    if tick % TRACKER_UPDATE_EVERY == 0:
                        try:
                            ts = TRACKER_DOWNSCALE
                            small = cv2.resize(frame, (int(w * ts), int(h * ts))) if ts != 1.0 else frame
                            ok, tbox = tracker.update(small)
                        except Exception:
                            ok, tbox = False, None
                        if ok and tbox is not None:
                            inv = 1.0 / TRACKER_DOWNSCALE
                            x, y, bw, bh = (int(v * inv) for v in tbox)
                            if bw > 0 and bh > 0:
                                owner_track_box = (x, y, bw, bh)
                                visible = True
                        # else: tracker lost this frame -> not visible (holding/grace handles it)
                    else:
                        visible = True              # skipped update tick: keep last box
                else:
                    visible = True                  # no tracker available: coast on last Gemini box

        # Emergency evade when the owner is right in front (only when actually visible).
        if owner_track_box is not None and visible:
            th_box = owner_track_box[3]
            if th_box / h > EMERGENCY_EVADE_THRESHOLD:
                robot.abort_event.set()  # Preempt emotional expression before emergency evade
                with state_lock:
                    CURRENT_STATE = "EVADING"
                evade_ticks = 0
                evade_dir = random.choice(['left', 'right'])
                robot.stop()
                LAST_THOUGHT = f"Whoa, target is too close (height ratio: {th_box / h:.2f})! Backing up and turning."
                with frame_lock:
                    RAW_FRAME = frame
                time.sleep(VISION_LOOP_INTERVAL)
                continue

        # Derive the motor target, or hold + fidget when the owner is momentarily out of view.
        if owner_track_box is not None:
            tx, ty, tw, th_box = owner_track_box
            if visible:
                following_lost_ticks = 0
                target_center_x = tx + tw // 2
                target_box = owner_track_box
                # On-screen annotation is handled solely by the dashboard's HTML/CSS
                # vector overlay (DASHBOARD_OBJECTS); nothing is burned into the frame.
            else:
                following_lost_ticks += 1
                if following_lost_ticks >= FOLLOWING_LOST_GRACE_TICKS:
                    # Owner gone for good -> release; fall through to return-home / search.
                    owner_track_box = None
                    tracker = None
                    following_lost_ticks = 0
                    with state_lock:
                        CURRENT_STATE = "RETURNING" if RETURN_HOME_ON_LOSS else "SEARCHING"
                else:
                    # Momentarily out of view. For BRIEF dropouts (a frame or two of
                    # tracker miss) leave the motors exactly as they are - reacting on
                    # every miss made following and fidgeting fight at frame rate,
                    # churning left/right pulses while the robot visibly stood still.
                    # Only after a sustained miss start the restless-pet fidget.
                    # Motors belong to a voice command / expression while is_robot_busy,
                    # and stay paused during a post-command hold (VOICE outranks fidgeting).
                    if (following_lost_ticks >= FIDGET_START_TICKS
                            and not is_robot_busy and not autonomy_held):
                        fidget = _restless_action(following_lost_ticks)
                        if fidget == "turn_left":
                            robot.turn_left()
                        elif fidget == "turn_right":
                            robot.turn_right()
                        elif fidget == "move_forward":
                            # Boundary-vetoed fidget steps degrade to a quiet stop
                            # instead of hammering blocked-move warnings.
                            if robot.is_safe_action('forward'):
                                robot.move_forward()
                            else:
                                robot.stop()
                        elif fidget == "move_backward":
                            if robot.is_safe_action('backward'):
                                robot.move_backward()
                            else:
                                robot.stop()
                        else:
                            robot.stop()
                        LAST_THOUGHT = f"Where did my owner go? Fidgeting and looking around... ({following_lost_ticks}/{FOLLOWING_LOST_GRACE_TICKS})"
                    with frame_lock:
                        RAW_FRAME = frame
                    time.sleep(VISION_LOOP_INTERVAL)
                    continue

        # Real-time motor command determination and transmission
        if target_center_x is not None:
            # (loss hysteresis is managed by the owner track-ID logic above)
            with state_lock:
                was_dozing = (CURRENT_STATE == "DOZING")
                CURRENT_STATE = "FOLLOWING"
            
            # Joy expression only when the motors are free: a running voice command or
            # post-command hold outranks it (re-fires on a later frame once released).
            if (was_dozing or not owner_was_present) and not is_robot_busy and not autonomy_held:
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
                with frame_lock:
                    RAW_FRAME = frame
                time.sleep(VISION_LOOP_INTERVAL)
                continue
                
            if not is_robot_busy and autonomy_held:
                # Voice hold: keep tracking visually but do not drive.
                robot.stop()
                LAST_THOUGHT = f"[Voice] Holding position as commanded ({autonomy_hold_until - time.time():.0f}s)..."
            elif not is_robot_busy and target_box is not None:
                bx, by, bw, bh = target_box
                box_height_ratio = bh / h
                
                if box_height_ratio > DISTANCE_CLOSE_THRESHOLD:
                    # [SAFETY SPACE RECOVERY] If the object/owner is too close, prioritize backing up 
                    # regardless of left/right deviation to prevent sweep collisions during turns.
                    robot.move_backward()
                    LAST_THOUGHT = f"Target is too close (height ratio: {box_height_ratio:.2f}). Stopping and backing up a little..."
                elif target_center_x < w * ALIGN_LEFT_THRESHOLD:
                    # Anti-chatter: do not reverse an opposite turn issued a moment ago.
                    if last_turn_dir != 'right' or time.time() - last_turn_time >= TURN_REVERSE_DWELL_S:
                        robot.turn_left()
                        last_turn_dir, last_turn_time = 'left', time.time()
                        LAST_THOUGHT = f"Tracking target on the left (dist ratio: {box_height_ratio:.2f}). Steering left."
                elif target_center_x > w * ALIGN_RIGHT_THRESHOLD:
                    if last_turn_dir != 'left' or time.time() - last_turn_time >= TURN_REVERSE_DWELL_S:
                        robot.turn_right()
                        last_turn_dir, last_turn_time = 'right', time.time()
                        LAST_THOUGHT = f"Tracking target on the right (dist ratio: {box_height_ratio:.2f}). Steering right."
                else:
                    if box_height_ratio < DISTANCE_FAR_THRESHOLD:
                        # Approaching may be vetoed by the table boundary (owner standing
                        # beyond the edge). Check first instead of ramming move_forward()
                        # every frame, which spams blocked-warnings and looks stuck.
                        if robot.is_safe_action('forward'):
                            robot.move_forward()
                            LAST_THOUGHT = f"Target centered but far away (dist ratio: {box_height_ratio:.2f}). Approaching."
                        else:
                            robot.stop()
                            LAST_THOUGHT = "Owner is beyond my table edge. Waiting here at the boundary."
                    else:
                        robot.stop()
                        LAST_THOUGHT = f"Target centered at comfortable distance (dist ratio: {box_height_ratio:.2f}). Staying."
        else:
            # If we were actively following the owner, do not drop back to SEARCHING immediately.
            # Give a grace period to wait for reappearance (hysteresis).
            if CURRENT_STATE == "FOLLOWING":
                following_lost_ticks += 1
                if following_lost_ticks < FOLLOWING_LOST_GRACE_TICKS:
                    if not is_robot_busy:  # do not stomp a running voice command
                        robot.stop()
                        LAST_THOUGHT = f"Target temporarily lost. Waiting for reappearance... ({following_lost_ticks}/{FOLLOWING_LOST_GRACE_TICKS})"
                    with frame_lock:
                        RAW_FRAME = frame
                    time.sleep(VISION_LOOP_INTERVAL)
                    continue
                else:
                    following_lost_ticks = 0

            # Voice hold: no autonomous return-home / scanning while a commanded
            # position is being held (safety overrides above still apply).
            if autonomy_held and not is_robot_busy:
                robot.stop()
                LAST_THOUGHT = f"[Voice] Holding position as commanded ({autonomy_hold_until - time.time():.0f}s)..."
                with frame_lock:
                    RAW_FRAME = frame
                time.sleep(VISION_LOOP_INTERVAL)
                continue

            # Sighting hold: a stale verdict saw a person - freeze and stare so the
            # re-triggered verdict is captured while stationary and can lock on.
            if time.time() < sighting_hold_until and not is_robot_busy:
                robot.stop()
                LAST_THOUGHT = "I think I saw someone! Holding still to get a good look..."
                with frame_lock:
                    RAW_FRAME = frame
                time.sleep(VISION_LOOP_INTERVAL)
                continue

            # Owner lost: drive back to the home base (0, 0) before resuming the scan.
            if CURRENT_STATE == "RETURNING" and not is_robot_busy:
                owner_was_present = False
                home_dist = math.hypot(robot.x, robot.y)
                if home_dist <= HOME_POSITION_TOLERANCE:
                    robot.stop()
                    with state_lock:
                        CURRENT_STATE = "SEARCHING"
                    search_state_counter = 0
                    LAST_THOUGHT = "Back at home base. Watching for my owner again."
                else:
                    desired = math.degrees(math.atan2(-robot.y, -robot.x))
                    err = ((desired - robot.theta + 180) % 360) - 180
                    if err > HOME_HEADING_TOLERANCE:
                        robot.turn_left()
                        LAST_THOUGHT = f"Lost my owner. Turning toward home base... (dist {home_dist:.0f} mm)"
                    elif err < -HOME_HEADING_TOLERANCE:
                        robot.turn_right()
                        LAST_THOUGHT = f"Lost my owner. Turning toward home base... (dist {home_dist:.0f} mm)"
                    else:
                        robot.move_forward()
                        LAST_THOUGHT = f"Lost my owner. Returning to home base... (dist {home_dist:.0f} mm)"
                with frame_lock:
                    RAW_FRAME = frame
                time.sleep(VISION_LOOP_INTERVAL)
                continue

            owner_was_present = False

            if not is_robot_busy:
                search_state_counter += 1
                
                # Sleep Timeout: If nothing detected for DOZING_TIMEOUT_TICKS, enter DOZING sleep mode
                if search_state_counter >= DOZING_TIMEOUT_TICKS:
                    with state_lock:
                        CURRENT_STATE = "DOZING"
                    robot.stop()
                    LAST_THOUGHT = "Dozing off... Restfully sleeping. Waiting for my owner's face to wake me up!"
                else:
                    with state_lock:
                        CURRENT_STATE = "SEARCHING"
                    # STOP-AND-SCAN search, matched to the Gemini verdict cadence: short
                    # ~40 deg sweep, then a ~2s PAUSE. The stale-anchor guard only
                    # accepts verdicts captured while the camera was steady, so these
                    # pauses are what actually produce lock-ons. (Continuous sweeping
                    # never yields a fresh anchor and the robot could not lock on.)
                    seg = (search_state_counter // 114) % 6
                    t_in = search_state_counter % 114
                    sweeping = t_in < 54            # 54 ticks ~= 1.8s ~= 40 deg at 22.5 deg/s
                    if seg <= 2:
                        if sweeping:
                            robot.turn_left()
                            LAST_THOUGHT = "Scanning left in short steps..."
                        else:
                            robot.stop()
                            LAST_THOUGHT = "Holding still so my cloud brain gets a steady look..."
                    elif seg == 3:
                        if t_in < 30:
                            robot.move_forward()
                            LAST_THOUGHT = "Roaming forward to explore for my owner..."
                        else:
                            robot.stop()
                            LAST_THOUGHT = "Pausing and watching..."
                    else:
                        if sweeping:
                            robot.turn_right()
                            LAST_THOUGHT = "Scanning right in short steps..."
                        else:
                            robot.stop()
                            LAST_THOUGHT = "Holding still so my cloud brain gets a steady look..."
                    
        # ----------------------------------
        # 📐 Google Robotics-ER 1.6 multi-object rendering (stale pointer prevention and timeout filter)
        # ----------------------------------
        # Object annotations are rendered ONLY by the dashboard's HTML/CSS vector overlay
        # (via DASHBOARD_OBJECTS below) - nothing is burned into the video frames. The
        # is_moving / staleness gates still control WHEN overlay data is published, so
        # stale pointers do not float across the screen while the robot is driving.
        is_moving = (robot.last_action not in ['stop', None])

        with state_lock:
            current_detected_objects = list(DETECTED_OBJECTS)
            last_det_time = LAST_DETECTION_TIME

        # 📐 Compute normalized coordinates for high-fidelity HTML/CSS vector overlays
        global DASHBOARD_OBJECTS
        temp_dash_objects = []
        
        # 1. Active tracked target
        active_box = target_box if target_box is not None else owner_track_box
        if active_box is not None:
            ax, ay, aw, ah_box = active_box
            # Normalize to 0-1000 scale
            a_ymin = int(ay * 1000 / h)
            a_xmin = int(ax * 1000 / w)
            a_ymax = int((ay + ah_box) * 1000 / h)
            a_xmax = int((ax + aw) * 1000 / w)
            
            # HUD honesty: only call it "Active" when the owner is actually seen THIS
            # frame (target_box set). A remembered-but-unseen track (holding/coasting)
            # shows as a dimmer "Last Seen" pointer without the cyan lock box.
            if target_box is not None:
                lbl, box_type = "Owner (Active)", "active"
            else:
                lbl, box_type = "Owner (Last Seen)", "holding"
            temp_dash_objects.append({
                "label": lbl,
                "box_2d": [a_ymin, a_xmin, a_ymax, a_xmax],
                "type": box_type
            })
            
        # 2. Secondary detected objects
        if not is_moving and (time.time() - last_det_time < OBJECT_STALE_TIMEOUT):
            for obj in current_detected_objects:
                box = obj.get("box_2d")
                label = obj.get("label", "object")
                if box and len(box) == 4:
                    oymin, oxmin, oymax, oxmax = box
                    if label.lower() not in OWNER_DESCRIPTION.lower() and label.lower() not in ["owner", "face", "person"]:
                        temp_dash_objects.append({
                            "label": label.title(),
                            "box_2d": [oymin, oxmin, oymax, oxmax],
                            "type": "cortex"
                        })
                        
        with state_lock:
            DASHBOARD_OBJECTS = temp_dash_objects
            
        with frame_lock:
            RAW_FRAME = frame
        time.sleep(VISION_LOOP_INTERVAL) # Approx 30fps loop

# ==========================================
# Thread 2: Voice Command Thread (Auditory) - local VAD + Gemini audio recognition
# ==========================================
# Audio capture + voice-activity-detection (VAD) tunables. A short spoken utterance is
# captured locally, then sent to Gemini for command recognition.
VOICE_SAMPLE_RATE = 16000            # preferred mic sample rate (falls back to the device native rate)
# VAD thresholds are AUTO-CALIBRATED at startup from ~1s of ambient noise; the factors
# below scale that ambient level, with absolute floors for very quiet rooms.
VOICE_START_FACTOR = 3.5             # speech starts when RMS exceeds ambient * this factor
VOICE_STOP_FACTOR = 1.8              # a chunk counts as silence when RMS falls below ambient * this
VOICE_RMS_FLOOR_START = 300          # lower bound for the start threshold
VOICE_RMS_FLOOR_STOP = 180           # lower bound for the end-of-speech threshold
VOICE_RMS_START_MAX = 9000           # upper bound for the start threshold: motor noise must never push the trigger above reachable speech levels (observed speech peaks 5000-12000)
VOICE_SILENCE_CHUNKS = 8             # consecutive quiet chunks (~64ms each) that end an utterance (~0.5s)
VOICE_PREROLL_CHUNKS = 4             # chunks (~0.26s) kept from BEFORE the trigger so the first syllable is not clipped
VOICE_MIN_MS = 250                   # ignore utterances shorter than this (clicks/noise)
VOICE_MAX_MS = 2600                  # hard cap on a single utterance (commands are single short words; a low cap also cuts latency in noisy rooms where trailing silence is never detected)
VOICE_COOLDOWN_S = 1.0               # minimum gap between accepted commands
# After a voice command finishes, autonomous driving (following/search/fidget/return)
# stays PAUSED so the commanded result visibly sticks instead of being instantly
# overridden by tracking. "come" releases the hold (it means: resume following me).
VOICE_AUTONOMY_HOLD_S = 8.0          # hold after motion commands (forward/backward/left/right/spin)
VOICE_STAY_HOLD_S = 25.0             # hold after "stop" (stay put like a trained dog; "come" releases early)
VOICE_GEMINI_MODEL = "gemini-2.5-flash"  # audio-capable model for the legacy capture-and-classify fallback

# Gemini Live API (persistent WebSocket, server-side VAD): primary voice path.
# gemini-3.1-flash-live-preview accepts this key but is AUDIO-response-only (a TEXT
# session is rejected with code 1007), so we connect with AUDIO modality, enable
# input_audio_transcription, and match the USER's Korean transcript locally with
# _match_voice_intent. The model's (tiny) audio replies are discarded.
# Set env VOICE_LIVE_MODEL to force a different model first.
VOICE_LIVE_MODELS = (
    "gemini-3.1-flash-live-preview",
)
VOICE_LIVE_MAX_FAILURES = 3          # consecutive connect failures before falling back to the legacy path

# Korean command word(s) -> intent. Gemini returns an intent token directly; this table
# also backs a text-fallback match on the transcript.
VOICE_COMMANDS = [
    (["이리와"], "come"),          # come here
    (["멈춰", "정지"], "stop"),   # stop
    (["돌아"], "spin"),           # spin / turn around
    (["앞으로"], "forward"),      # forward
    (["뒤로"], "backward"),       # backward
    (["왼쪽으로"], "left"),       # turn left
    (["오른쪽으로"], "right"),    # turn right
]

# Motor burst durations in seconds (each command moves briefly then auto-stops). Tune on-device.
# CALIBRATED speeds: linear ~260 mm/s (2026-07-12), angular ~22.5 deg/s (2026-07-13:
# a 4.0s spin rotated 90 deg). FORWARD=1.5s ~= 390 mm, COME=2.2s ~= 570 mm,
# BACKWARD=1.2s ~= 310 mm, TURN=2.2s ~= 50 deg, SPIN=8.0s ~= 180 deg (turn around).
CMD_BURST_COME = 2.2
CMD_BURST_FORWARD = 1.5
CMD_BURST_BACKWARD = 1.2
CMD_BURST_TURN = 2.2
CMD_BURST_SPIN = 8.0


VOICE_INTENTS = {intent for _words, intent in VOICE_COMMANDS}  # valid intent tokens

# Wake word: the robot's name. Commands must be addressed to the robot ("토토 앞으로")
# so command words inside normal conversation never trigger motion. Emergency stop
# ("멈춰"/"정지") is exempt and works without the wake word.
# Includes common STT variants of the made-up name (the transcriber has no dictionary
# entry for "토토" and often writes a sound-alike instead).
WAKE_WORDS = ["토토", "또또", "토도", "도도", "또토", "toto"]

def _match_voice_intent(text):
    """Map recognized text to a command intent.
    - Bare intent tokens from the legacy classifier (e.g. "forward") keep working.
    - Korean transcripts require the WAKE WORD ("토토"); the command is matched on the
      text AFTER the name, so natural phrasing like "토토 앞으로 가" works and command
      words inside unrelated conversation are ignored.
    - Safety exception: a short bare "멈춰"/"정지" stops the robot without the name.
    Spaces are ignored throughout (STT may tokenize syllables with spaces)."""
    if not text:
        return None
    norm = text.strip().lower().replace(" ", "")

    # Legacy classifier path: a short bare intent token ("forward", "stop", ...).
    if len(norm) <= 8:
        for it in VOICE_INTENTS:
            if it in norm:
                return it
        # Emergency stop works without the wake word (short, deliberate utterance only).
        if "멈춰" in norm or "정지" in norm:
            return "stop"

    # Wake-word path: find the robot's name, then match the command in what follows.
    # When several command words appear ("오른쪽으로 돌아" = turn right), the EARLIEST
    # one in the phrase wins - in Korean commands the head word comes first.
    for wake in WAKE_WORDS:
        idx = norm.find(wake)
        if idx != -1:
            rest = norm[idx + len(wake):]
            best = None  # (position, -word_length, intent): leftmost, then longest word
            for words, intent in VOICE_COMMANDS:
                for w in words:
                    wn = w.replace(" ", "")
                    p = rest.find(wn)
                    if p != -1 and (best is None or (p, -len(wn)) < (best[0], best[1])):
                        best = (p, -len(wn), intent)
            return best[2] if best else None  # None: addressed to the robot, but no command followed
    return None


def _voice_sleep(duration):
    """Interruptible burst sleep. Returns False (early) if the burst is preempted:
    voice_abort_event = a newer voice command takes over; robot.abort_event = a safety
    override (boundary / evade / re-home) has claimed the motors."""
    end = time.time() + duration
    while time.time() < end:
        if voice_abort_event.is_set() or robot.abort_event.is_set():
            return False
        time.sleep(0.05)
    return True


def _run_voice_action(intent):
    """Execute one voice command as a short motor burst, interlocked via is_robot_busy.
    Priority: SAFETY > VOICE > autonomous behaviors. The burst yields immediately to
    safety overrides and to a newer voice command (see _voice_sleep)."""
    global is_robot_busy, LAST_THOUGHT, current_voice_intent, autonomy_hold_until
    with state_lock:
        is_robot_busy = True
        current_voice_intent = intent
    robot.abort_event.clear()  # meaningful within this action: set again only by safety (or preemption)
    try:
        if intent == "stop":
            robot.stop()
            LAST_THOUGHT = "[Voice] Stop. Holding still."
            _voice_sleep(0.8)
        elif intent == "come":
            LAST_THOUGHT = "[Voice] Coming! Resuming owner tracking."
            gemini_trigger_event.set()  # fresh owner fix so following approaches the right spot
            robot.move_forward(); _voice_sleep(CMD_BURST_COME)
        elif intent == "forward":
            LAST_THOUGHT = "[Voice] Moving forward."
            robot.move_forward(); _voice_sleep(CMD_BURST_FORWARD)
        elif intent == "backward":
            LAST_THOUGHT = "[Voice] Moving backward."
            robot.move_backward(); _voice_sleep(CMD_BURST_BACKWARD)
        elif intent == "left":
            LAST_THOUGHT = "[Voice] Turning left."
            robot.turn_left(); _voice_sleep(CMD_BURST_TURN)
        elif intent == "right":
            LAST_THOUGHT = "[Voice] Turning right."
            robot.turn_right(); _voice_sleep(CMD_BURST_TURN)
        elif intent == "spin":
            direction = random.choice(["left", "right"])
            LAST_THOUGHT = f"[Voice] Spinning around ({direction})."
            if direction == "left":
                robot.turn_left()
            else:
                robot.turn_right()
            _voice_sleep(CMD_BURST_SPIN)
    finally:
        # End with motors stopped, UNLESS a safety override owns them now (it will
        # keep issuing its own commands; stomping it even for one frame is worse).
        if not robot.abort_event.is_set():
            robot.stop()
            # Pause autonomous driving so the commanded result visibly sticks.
            # "come" means "resume following me" -> releases any hold instead.
            if intent == "stop":
                autonomy_hold_until = time.time() + VOICE_STAY_HOLD_S
            elif intent == "come":
                autonomy_hold_until = 0.0
            else:
                autonomy_hold_until = time.time() + VOICE_AUTONOMY_HOLD_S
        with state_lock:
            is_robot_busy = False
            current_voice_intent = None


def _pcm_to_wav(pcm_bytes, rate=VOICE_SAMPLE_RATE):
    """Wrap raw 16-bit mono PCM in a WAV container and return the bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


# The model's spoken replies are discarded (we only consume the input transcription),
# so instruct it to answer as briefly as possible to minimize wasted audio tokens.
LIVE_VOICE_SYSTEM_INSTRUCTION = (
    "You are the silent listening ear of a pet robot's voice command system. "
    "You never chat. Reply to every input with the single word: ok")


def _dispatch_voice_text(text, state, source="voice"):
    """Shared command dispatch for both voice paths (Live streaming and legacy capture).
    Applies intent matching, cooldown, the same-intent guard and priority preemption
    (SAFETY > VOICE > autonomy), then launches the motor burst in its own thread.
    `state` carries `last_cmd_time` between calls."""
    intent = _match_voice_intent(text)
    print(f"[AUDITORY] {source} -> '{text}' -> {intent}")
    if intent is None:
        return False
    now = time.time()
    if now - state.get("last_cmd_time", 0.0) < VOICE_COOLDOWN_S:
        print(f"[AUDITORY] Skipped '{intent}' (cooldown).")
        return False
    # Do not RESTART the same action that is already running (prevents e.g. a
    # repeated "spin" from preempting and endlessly re-spinning). "stop" is exempt.
    if is_robot_busy and intent == current_voice_intent and intent != "stop":
        print(f"[AUDITORY] '{intent}' already running; repeat ignored.")
        return False
    state["last_cmd_time"] = now

    # Preempt whatever the robot is doing (except safety overrides, which are
    # frame-driven in the vision loop and always outrank voice).
    if is_robot_busy:
        robot.abort_event.set()   # break out of an emotional expression (express_happy honors this)
        voice_abort_event.set()   # cut short a running voice burst
        t0 = time.time()
        while is_robot_busy and time.time() - t0 < 2.0:
            time.sleep(0.05)
        voice_abort_event.clear()
        if is_robot_busy:
            print("[AUDITORY] Previous action did not yield in time; command skipped.")
            return False

    print(f"--> Voice command: {intent}")
    threading.Thread(target=_run_voice_action, args=(intent,), daemon=True).start()
    return True


async def _live_voice_session(client, model_name, stream, chunk, dev_rate, state):
    """One Gemini Live session: stream mic PCM up, read the server's TRANSCRIPTION of
    the user's speech, and dispatch Korean command words locally. Returns True once a
    session was established (drops end the session cleanly and the caller reconnects);
    raises if the connection itself cannot be made."""
    config = {
        # This model only supports AUDIO responses; the replies are tiny ("ok") and
        # discarded. What we actually consume is the input transcription below.
        "response_modalities": ["AUDIO"],
        "system_instruction": {"parts": [{"text": LIVE_VOICE_SYSTEM_INSTRUCTION}]},
        "input_audio_transcription": {},
        # Sliding-window compression extends the session lifetime (fewer reconnects).
        "context_window_compression": {
            "trigger_tokens": 800000,
            "sliding_window": {"target_tokens": 10000},
        },
    }
    async with client.aio.live.connect(model=model_name, config=config) as session:
        print(f"[AUDITORY] Live session connected ({model_name}); streaming mic audio.")

        async def sender():
            mime = f"audio/pcm;rate={dev_rate}"
            while RUNNING:
                pcm = await asyncio.to_thread(stream.read, chunk, exception_on_overflow=False)
                await session.send_realtime_input(audio=types.Blob(data=pcm, mime_type=mime))

        async def receiver():
            # session.receive() is a PER-TURN iterator: it ends when one model turn
            # completes. Without this outer loop the whole session was torn down and
            # reconnected after EVERY utterance, leaving a 1-2s deaf gap each time
            # (observed as intermittent missed commands). Keep pulling turns from the
            # SAME session instead.
            while RUNNING:
                turn_text = ""
                async for message in session.receive():
                    if not RUNNING:
                        return
                    sc = getattr(message, "server_content", None)
                    if sc is None:
                        continue
                    # Accumulate the transcription of what the USER said this turn.
                    it = getattr(sc, "input_transcription", None)
                    if it is not None and getattr(it, "text", None):
                        turn_text += it.text
                    # Model audio replies in model_turn parts are intentionally ignored.
                    if getattr(sc, "turn_complete", False):
                        text = turn_text.strip()
                        turn_text = ""
                        if text:
                            # Dispatch in a worker thread: it may block up to ~2s on preemption.
                            await asyncio.to_thread(_dispatch_voice_text, text, state, "live transcript")

        try:
            tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                exc = t.exception()
                if exc is not None:
                    print(f"[AUDITORY] Live session dropped: {exc}; reconnecting.")
        except Exception as e:
            print(f"[AUDITORY] Live session error: {e}; reconnecting.")
        return True


def _legacy_voice_loop(client, stream, chunk, dev_rate, state):
    """Fallback voice path: local energy-VAD captures an utterance, then a single
    generate_content call classifies it. Higher latency than Live but has no
    persistent-connection requirement."""
    global RUNNING

    # Auto-calibrate the VAD thresholds from ~1s of ambient room noise.
    ambient_samples = []
    for _ in range(16):
        try:
            d = stream.read(chunk, exception_on_overflow=False)
            s = np.frombuffer(d, dtype=np.int16)
            if s.size:
                ambient_samples.append(float(np.sqrt(np.mean(s.astype(np.float32) ** 2))))
        except Exception:
            pass
    # Use the QUIETEST quarter of the samples: calibration may run while the robot's
    # own motors are driving, and a mean would lock the trigger far above human speech.
    noise_floor = (sorted(ambient_samples)[max(0, len(ambient_samples) // 4 - 1)]
                   if ambient_samples else 0.0)
    rms_start = min(VOICE_RMS_START_MAX, max(VOICE_RMS_FLOOR_START, noise_floor * VOICE_START_FACTOR))
    rms_stop = max(VOICE_RMS_FLOOR_STOP, noise_floor * VOICE_STOP_FACTOR)
    print(f"[AUDITORY] Noise floor {noise_floor:.0f} -> speech starts above {rms_start:.0f}, silence below {rms_stop:.0f}.")
    print("[AUDITORY] Legacy voice loop started (local VAD + Gemini classification).")

    prompt = ("This is a short Korean voice command spoken to a pet robot named 토토 (Toto). "
              "The command is usually prefixed with the name, e.g. '토토 앞으로'; ignore the name. "
              "Reply with EXACTLY ONE token from this list and nothing else: "
              "forward, backward, left, right, stop, spin, come, none. "
              "The clip may contain only motor/fan noise or background sounds; if there "
              "is no CLEAR human speech matching one of these commands, reply none.")

    # Disable model thinking for this simple classification: cuts round-trip latency.
    try:
        reco_config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=0))
    except Exception:
        reco_config = None

    buffering = False
    voiced = bytearray()
    preroll = []                       # last few chunks before the trigger (protects the first syllable)
    silence = 0
    last_level_log = time.time()

    while RUNNING:
        try:
            data = stream.read(chunk, exception_on_overflow=False)
        except Exception:
            time.sleep(0.05)
            continue

        samples = np.frombuffer(data, dtype=np.int16)
        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) if samples.size else 0.0

        # (1) Voice-activity detection: wait for speech to start.
        if not buffering:
            if rms >= rms_start:
                buffering = True
                # Include the pre-roll so the utterance onset (below-threshold start of
                # the first syllable) is not clipped from the clip sent to Gemini.
                voiced = bytearray(b"".join(preroll))
                voiced.extend(data)
                preroll = []
                silence = 0
                print(f"[AUDITORY] Speech detected (rms {rms:.0f}), capturing...")
            else:
                preroll.append(data)
                if len(preroll) > VOICE_PREROLL_CHUNKS:
                    preroll.pop(0)
                # Continuously adapt the noise floor: snap DOWN instantly when the
                # room gets quiet (e.g. motors stop), creep UP slowly during noise.
                noise_floor = rms if rms < noise_floor else min(noise_floor * 1.005 + 1.0, rms)
                rms_start = min(VOICE_RMS_START_MAX, max(VOICE_RMS_FLOOR_START, noise_floor * VOICE_START_FACTOR))
                rms_stop = max(VOICE_RMS_FLOOR_STOP, noise_floor * VOICE_STOP_FACTOR)
            if not buffering and time.time() - last_level_log > 8.0:
                print(f"[AUDITORY] listening... level rms={rms:.0f} (speech trigger >= {rms_start:.0f})")
                last_level_log = time.time()
            continue

        # (2) Capturing an utterance: append until trailing silence or max length.
        voiced.extend(data)
        silence = silence + 1 if rms < rms_stop else 0
        utter_ms = 1000.0 * (len(voiced) / 2) / dev_rate
        if silence < VOICE_SILENCE_CHUNKS and utter_ms < VOICE_MAX_MS:
            continue

        # (3) Utterance complete -> reset capture state.
        pcm = bytes(voiced)
        buffering = False
        voiced = bytearray()
        silence = 0

        if utter_ms < VOICE_MIN_MS:
            print(f"[AUDITORY] Discarded {utter_ms:.0f} ms blip (below {VOICE_MIN_MS} ms).")
            continue
        # Pre-check the cooldown before spending an API call (dispatch re-checks it).
        if time.time() - state.get("last_cmd_time", 0.0) < VOICE_COOLDOWN_S:
            print("[AUDITORY] Skipped utterance (cooldown).")
            continue

        # (4) Recognize the command with Gemini audio understanding.
        try:
            wav = _pcm_to_wav(pcm, dev_rate)
            t_reco = time.time()
            response = client.models.generate_content(
                model=VOICE_GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=wav, mime_type="audio/wav"),
                    prompt,
                ],
                config=reco_config,
            )
            reco_s = time.time() - t_reco
            text = (response.text or "").strip()
        except Exception as e:
            print(f"[AUDITORY] Gemini audio recognition failed: {e}")
            continue

        _dispatch_voice_text(text, state, f"utterance ({utter_ms:.0f} ms, gemini {reco_s:.1f}s)")


def audio_recognition_thread():
    global RUNNING, LAST_THOUGHT, is_robot_busy

    if not SPEECH_AVAILABLE:
        print("[AUDITORY] google-genai unavailable. Voice recognition disabled.")
        return
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or api_key == "YOUR_API_KEY":
        print("[AUDITORY] GEMINI_API_KEY not set. Voice recognition disabled.")
        return
    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        print(f"[AUDITORY] Failed to initialize GenAI client for voice: {e}")
        return

    try:
        import pyaudio
        with ignore_stderr():
            pa = pyaudio.PyAudio()

        # Prefer the USB/camera microphone (same policy as the old recognizer); fall
        # back to the system default input device.
        dev_index = None
        dev_info = {}
        try:
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0 and any(
                        k in str(info.get("name", "")).lower() for k in ("usb", "camera", "webcam")):
                    dev_index, dev_info = i, info
                    break
            if dev_index is None:
                dev_info = pa.get_default_input_device_info()
                dev_index = int(dev_info["index"])
            print(f"[AUDITORY] Microphone: '{dev_info.get('name')}' (index {dev_index})")
        except Exception as e:
            print(f"[AUDITORY] Microphone scan failed ({e}); using default device.")
            dev_index = None

        # Open at 16 kHz if supported, else at the device native rate (the PCM mime
        # type / WAV header carries the actual rate, so Gemini handles either).
        stream = None
        chunk = 1024
        dev_rate = VOICE_SAMPLE_RATE
        native_rate = int(float(dev_info.get("defaultSampleRate", 44100) or 44100))
        for rate in (VOICE_SAMPLE_RATE, native_rate):
            try:
                chunk = max(256, int(rate * 0.064))  # ~64 ms of audio per chunk at any rate
                with ignore_stderr():
                    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=rate,
                                     input=True, input_device_index=dev_index,
                                     frames_per_buffer=chunk)
                    stream.start_stream()
                dev_rate = rate
                break
            except Exception:
                stream = None
        if stream is None:
            print("[AUDITORY] Failed to open microphone stream at 16000 or native rate. Voice disabled.")
            return
        print(f"[AUDITORY] Mic stream open at {dev_rate} Hz (chunk {chunk} frames).")
    except Exception as e:
        print(f"[AUDITORY] Failed to open microphone stream: {e}")
        return

    state = {"last_cmd_time": 0.0}

    # --- PRIMARY: Gemini Live API streaming (server VAD, ~1s command latency) ---
    live_models = []
    env_model = os.environ.get("VOICE_LIVE_MODEL")
    if env_model:
        live_models.append(env_model)
    live_models += [m for m in VOICE_LIVE_MODELS if m not in live_models]

    live_supported = hasattr(getattr(client, "aio", None), "live")
    if not live_supported:
        print("[AUDITORY] This google-genai version has no Live API support "
              "(pip install -U google-genai). Using legacy voice mode.")

    live_failures = 0
    while RUNNING and live_supported and live_failures < VOICE_LIVE_MAX_FAILURES:
        established = False
        for model_name in live_models:
            try:
                established = asyncio.run(
                    _live_voice_session(client, model_name, stream, chunk, dev_rate, state))
            except Exception as e:
                print(f"[AUDITORY] Live connect failed on '{model_name}': {e}")
                established = False
            if established:
                live_failures = 0
                break  # session ended (timeout/drop) -> outer loop reconnects
        if not established:
            live_failures += 1
            time.sleep(2.0)

    # --- FALLBACK: capture-and-classify (kept for offline-ish robustness) ---
    if RUNNING:
        print("[AUDITORY] Live API unavailable; falling back to capture-and-classify voice mode.")
        _legacy_voice_loop(client, stream, chunk, dev_rate, state)

    try:
        with ignore_stderr():
            stream.stop_stream(); stream.close(); pa.terminate()
    except Exception:
        pass


# ==========================================
# 🧠 Thread 3: Cloud Google Gemini API Integration (Cortex)
# ==========================================
def gemini_brain_thread():
    global CURRENT_STATE, LAST_THOUGHT, RAW_FRAME, RUNNING, DETECTED_OBJECTS, LAST_DETECTION_TIME, CAMERA_ACTIVE, LATEST_BBOX, LATEST_BBOX_SEQ, LATEST_BBOX_POSE, is_robot_busy, GEMINI_STATUS
    
    api_key = os.environ.get("GEMINI_API_KEY")
    
    if not GEMINI_AVAILABLE or not api_key or api_key == "YOUR_API_KEY":
        print("⚠️ [CORTEX] Google GenAI SDK missing or invalid API Key. Running in Simulation Mind mode.")
        with state_lock:
            GEMINI_STATUS = "SIMULATION"
        
        simulated_minds_face = [
            "The owner is smiling and looking straight at me! Approaching cheerfully.",
            "I should stay loyal and keep watching the surroundings.",
            "Visual field is clear, searching for the owner's face presence.",
            "Auditory senses are focused on the surroundings waiting for a voice command."
        ]
        
        # Clarify in the console how to enable the real Gemini Cloud brain
        print("\n" + "="*80)
        print("💡 [CORTEX INFO] To enable the real Gemini Cloud brain (Cortex):")
        print("   1. Create a file named '.env' in this directory.")
        print("   2. Add your key inside: GEMINI_API_KEY=your_actual_api_key_here")
        print("="*80 + "\n")

        while RUNNING:
            time.sleep(3) # Faster updates in simulation for immediate feedback
            with frame_lock:
                has_frame = RAW_FRAME is not None
            if has_frame and RUNNING:
                import random
                with state_lock:
                    curr_desc = OWNER_DESCRIPTION

                thought = f"[AI SIMULATION] {random.choice(simulated_minds_face)} (Targeting: {curr_desc})"

                with state_lock:
                    LAST_THOUGHT = thought
                    # Clear fake multi-detection list in simulation mode
                    DETECTED_OBJECTS = []
                    LAST_DETECTION_TIME = 0.0
                print(f"[CORTEX SIMULATION] Description: {curr_desc} | Thought: {LAST_THOUGHT}")
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
    consecutive_failures = 0
    while RUNNING:
        # Dynamic prompt reconstruction based on current OWNER_DESCRIPTION
        with state_lock:
            curr_desc = OWNER_DESCRIPTION

        owner_prompt_segment = f"Locate the target owner, who is a person defined as: {curr_desc}."
        
        if PYDANTIC_AVAILABLE:
            prompt = f"You are the robotic puppy's brain. Analyze the camera image to track the owner ({curr_desc}), detect other surrounding toys or food objects, and generate a brief inner thought of yours."
        else:
            prompt = f"""
    You are the robotic puppy's brain. Based on the camera image:
    1. {owner_prompt_segment}
       - Find the bounding box of this target in the image.
       - If the target is present, detect it as the owner and output its bounding box in 'owner_box'.
       - If no such target is present, set 'owner_box' to null.
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
        clean_frame = None
        if CAMERA_ACTIVE:
            with camera_lock:
                if LATEST_CAMERA_FRAME is not None:
                    clean_frame = LATEST_CAMERA_FRAME.copy()
        if clean_frame is None:
            with frame_lock:
                clean_frame = RAW_FRAME.copy() if RAW_FRAME is not None else None
            
        if clean_frame is not None:
            snapshot_time = time.time()
            # Record the robot pose at CAPTURE time: the vision thread compares it with
            # the pose at verdict ARRIVAL to reject spatially-stale anchors.
            snapshot_pose = (robot.theta, robot.x, robot.y)
            ret, buffer = cv2.imencode('.jpg', clean_frame)
            if ret:
                image_bytes = buffer.tobytes()
                try:
                    model_name = 'gemini-robotics-er-1.6-preview'
                    config_obj = None
                    if PYDANTIC_AVAILABLE:
                        config_obj = types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=PuppyBrainResponse,
                            temperature=0.3
                        )
                        
                    try:
                        response = client.models.generate_content(
                            model=model_name,
                            contents=[
                                types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'),
                                prompt
                            ],
                            config=config_obj
                        )
                    except Exception as e_model:
                        print(f"⚠️ [CORTEX] Model '{model_name}' failed or restricted: {e_model}. Falling back to 'gemini-2.5-flash'...")
                        model_name = 'gemini-2.5-flash'
                        response = client.models.generate_content(
                            model=model_name,
                            contents=[
                                types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'),
                                prompt
                            ],
                            config=config_obj
                        )
                    
                    if PYDANTIC_AVAILABLE:
                        # Structured Outputs Mode (Pydantic parsed response)
                        brain_data = response.parsed
                        
                        valid_objects = []
                        for obj in brain_data.detected_objects:
                            valid_objects.append({
                                "box_2d": obj.box_2d,
                                "label": obj.label
                            })
                        with state_lock:
                            DETECTED_OBJECTS = valid_objects
                            LAST_DETECTION_TIME = time.time()
                        
                        owner_box = brain_data.owner_box
                        thought_text = brain_data.thought if brain_data.thought else "Monitoring environment."
                    else:
                        # Fallback Mode
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
                        with state_lock:
                            DETECTED_OBJECTS = valid_objects
                            LAST_DETECTION_TIME = time.time()
                        
                        owner_box = data.get("owner_box") or data.get("owner") or data.get("owner_bbox")
                        thought_text = data.get("thought", "Monitoring environment and target owner.")
                    
                    # 2. Update target owner box data with stale response safety check and robust scaling/fallbacks
                    if owner_box is None:
                        # Fallback: search for owner/person keywords in detected_objects to use as owner_box
                        for obj in valid_objects:
                            lbl = obj.get("label", "").lower()
                            keywords = ["person", "man", "woman", "owner", "face"]
                            if any(p in lbl for p in keywords):
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
                            LATEST_BBOX_POSE = snapshot_pose
                            LATEST_BBOX_SEQ += 1  # signal the vision thread that a fresh verdict is ready
                        
                        # 3. Record Cortex thought log
                        LAST_THOUGHT = thought_text
                    
                    consecutive_failures = 0
                    print(f"[CORTEX API] Model: {model_name} | Owner Spotted: {LATEST_BBOX is not None} (BBOX: {LATEST_BBOX}) | Objects: {len(valid_objects)} | Thought: {LAST_THOUGHT}")
                    
                    # 4. 🤖 Autonomous action reaction trigger (transforms object recognition into physical sound/motion)
                    # If toys or food are recognized, trigger corresponding natural puppy play/hungry reactions
                    if not is_robot_busy:
                        has_toy = any(kw in obj.get("label", "").lower() for obj in valid_objects for kw in ["toy", "ball", "frisbee", "doll"])
                        has_food = any(kw in obj.get("label", "").lower() for obj in valid_objects for kw in ["bowl", "cup", "food", "water", "snack"])
                        
                        if has_toy:
                            print("[CORTEX] Toy detected! Triggering happy toy-play reaction.")
                            with state_lock:
                                LAST_THOUGHT = "[Spotted Toy] " + thought_text
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
                            with state_lock:
                                LAST_THOUGHT = "[Spotted Food Bowl] " + thought_text
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
                    consecutive_failures += 1
                    print(f"[CORTEX API] Gemini API Exception: {e}")
                    with state_lock:
                        GEMINI_STATUS = "ERROR"
                        # Clear detected objects to fade out boxes during API exceptions or delays
                        DETECTED_OBJECTS = []
                        LAST_DETECTION_TIME = 0.0
                    
                    # Exponential backoff with jitter
                    retry_delay = min(2 ** consecutive_failures + random.uniform(0, 1), 30.0)
                    if consecutive_failures >= 3:
                        print(f"⚠️ [CORTEX] API failed {consecutive_failures} times consecutively. Backing off for {retry_delay:.2f}s...")
                    gemini_trigger_event.wait(timeout=retry_delay)
                    gemini_trigger_event.clear()
                    continue
                    
        # wait using the interruptible event wait to trigger instantly when entering the GAZING state.
        gemini_trigger_event.wait(timeout=GEMINI_POLL_INTERVAL)
        gemini_trigger_event.clear()

# ==========================================
# 🖼️ Thread 4: Background Streaming Encoder Thread for Web Streaming (CPU Optimization)
# ==========================================
def streaming_encoder_thread():
    global RAW_FRAME, LATEST_JPEG_BYTES, RUNNING
    print("✅ [STREAM ENCODER] Background streaming encoder thread started.")

    # Skip re-encoding when the source frame object has not changed since the last
    # pass (each vision/camera iteration publishes a NEW array object, so object
    # identity is a reliable and free "new frame?" check). Holding this reference
    # also prevents id reuse. Saves Pi CPU whenever the pipeline stalls or idles.
    last_encoded_frame = None

    while RUNNING:
        clean_frame = None
        source_ref = None
        with frame_lock:
            if RAW_FRAME is not None:
                source_ref = RAW_FRAME
                if source_ref is not last_encoded_frame:
                    clean_frame = RAW_FRAME.copy()

        # [STREAM FALLBACK] If RAW_FRAME is not available yet, directly fetch from live camera buffer
        if source_ref is None and LATEST_CAMERA_FRAME is not None:
            with camera_lock:
                source_ref = LATEST_CAMERA_FRAME
                if source_ref is not last_encoded_frame:
                    clean_frame = LATEST_CAMERA_FRAME.copy()

        if clean_frame is not None:
            try:
                # [DEMO-OPTIMIZED] Rescale and compress dynamically based on dashboard settings
                web_frame = cv2.resize(clean_frame, STREAM_RESOLUTION, interpolation=cv2.INTER_LINEAR)
                ret, jpeg_buffer = cv2.imencode('.jpg', web_frame, [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_JPEG_QUALITY])
                if ret:
                    with jpeg_lock:
                        LATEST_JPEG_BYTES = jpeg_buffer.tobytes()
                    last_encoded_frame = source_ref
            except Exception as e:
                print(f"⚠️ [STREAM ENCODER] Compression error: {e}")

        # Perform streaming-only encoding at approx 30 FPS using STREAM_ENCODE_INTERVAL
        time.sleep(STREAM_ENCODE_INTERVAL)

# ==========================================
# 🖥 Flask Web Monitoring Dashboard Resources and API
# ==========================================
app = Flask(__name__)

# Silence werkzeug per-request access logs ("GET /status HTTP/1.1" 200): the dashboard
# polls /status at 4 Hz, which would otherwise flood the console and bury the robot's
# own [AUDITORY]/[CORTEX]/[GPIO] logs. Errors are still printed.
import logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)

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
    last_sent = None          # bytes object identity of the last frame this client received
    last_sent_time = 0.0
    while True:
        bytes_to_yield = None
        with jpeg_lock:
            if LATEST_JPEG_BYTES is not None:
                bytes_to_yield = LATEST_JPEG_BYTES

        if bytes_to_yield is None:
            time.sleep(STREAM_SERVE_INTERVAL)
            continue
        # Send only NEW frames (browsers keep displaying the last MJPEG frame), with a
        # ~2s keepalive resend so proxies/clients do not treat the stream as dead.
        now = time.time()
        if bytes_to_yield is last_sent and now - last_sent_time < 2.0:
            time.sleep(STREAM_SERVE_INTERVAL)
            continue
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + bytes_to_yield + b'\r\n')
        last_sent = bytes_to_yield
        last_sent_time = now
        time.sleep(STREAM_SERVE_INTERVAL)  # Keep web streaming around 20 FPS using STREAM_SERVE_INTERVAL

@app.route('/video_feed')
def video_feed():
    return Response(generate_mjpeg_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/status')
def status():
    try:
        with state_lock:
            curr_state = CURRENT_STATE
            last_thought = LAST_THOUGHT
            gemini_status = GEMINI_STATUS
            dash_objects = list(DASHBOARD_OBJECTS)
            # Live object count: how many objects Gemini saw in its latest fresh pass
            # (independent of the pointer-hiding motion gate, so it stays meaningful
            # while the robot is driving).
            objects_seen = (len(DETECTED_OBJECTS)
                            if (time.time() - LAST_DETECTION_TIME) < OBJECT_STALE_TIMEOUT else 0)

        return jsonify({
            "state": curr_state,
            "thought": last_thought,
            "cpu_temp": get_cpu_temp(),
            "gemini_status": gemini_status,
            "detected_objects": dash_objects,
            "objects_seen": objects_seen,
            "is_moving": getattr(robot, 'last_action', None) not in ['stop', None],
            "x": round(getattr(robot, 'x', 0.0), 1),
            "y": round(getattr(robot, 'y', 0.0), 1),
            "theta": round(getattr(robot, 'theta', 0.0), 1),
            "is_out_of_bounds": getattr(robot, 'is_out_of_bounds', False),
            "position_uncertainty": round(getattr(robot, 'position_uncertainty', 0.0), 1),
            "needs_rehome": getattr(robot, 'needs_rehome', False),
            "is_barking": (time.time() - getattr(robot, 'bark_time', 0.0)) < 0.9
        })
    except Exception as e:
        print(f"❌ [API ERROR] Exception in /status route: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "state": "ERROR",
            "thought": f"[API Server Error] {str(e)}",
            "cpu_temp": 0.0,
            "gemini_status": "ERROR",
            "detected_objects": [],
            "objects_seen": 0,
            "is_moving": False,
            "x": 0.0, "y": 0.0, "theta": 0.0,
            "is_out_of_bounds": False,
            "position_uncertainty": 0.0,
            "needs_rehome": False,
            "is_barking": False
        })

@app.route('/reset_odometry', methods=['POST'])
def reset_odometry_route():
    robot.reset_odometry(0.0, 0.0, 90.0)
    return jsonify({
        "status": "success",
        "message": "Odometry coordinates manually reset to center (0, 0, 90°)."
    })

@app.route('/set_stream_quality', methods=['POST'])
def set_stream_quality_route():
    global STREAM_RESOLUTION, STREAM_JPEG_QUALITY
    data = request.get_json()
    width = int(data.get('width', 512))
    height = int(data.get('height', 384))
    quality = int(data.get('quality', 58))
    with jpeg_lock:
        STREAM_RESOLUTION = (width, height)
        STREAM_JPEG_QUALITY = quality
    return jsonify({"status": "success", "width": width, "height": height, "quality": quality})


HTML_DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gemini Robotics ER Live HUD</title>
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
            max-width: 1300px;
        }

        @media (min-width: 1400px) {
            .container {
                grid-template-columns: 1.35fr 1fr; /* Clean modern 2-column demo layout! */
                max-width: 1500px;
            }
        }

        @media (max-width: 1000px) {
            .container {
                grid-template-columns: 1fr;
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

        /* Scanning indicator + live object counter (inside the video frame) */
        #scan-indicator {
            position: absolute;
            top: 14px;
            right: 16px;
            z-index: 12;
            display: none;
            padding: 4px 10px;
            border-radius: 6px;
            background: rgba(5, 5, 8, 0.55);
            border: 1px solid rgba(0, 240, 255, 0.35);
            color: var(--accent-cyan);
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            pointer-events: none;
            animation: scan-pulse 1.1s ease-in-out infinite;
        }
        @keyframes scan-pulse {
            0%, 100% { opacity: 0.35; }
            50% { opacity: 1; }
        }
        #objects-badge {
            position: absolute;
            bottom: 14px;
            right: 16px;
            z-index: 12;
            padding: 4px 10px;
            border-radius: 6px;
            background: rgba(5, 5, 8, 0.55);
            border: 1px solid rgba(255, 255, 255, 0.14);
            color: #e8ecf1;
            font-size: 0.7rem;
            font-weight: 600;
            letter-spacing: 0.08em;
            pointer-events: none;
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
        .state-RETURNING {
            background-color: rgba(52, 168, 235, 0.05);
            color: #34a8eb;
            border-color: rgba(52,168,235,0.12);
            text-shadow: 0 0 15px rgba(52,168,235,0.2);
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

        /* Thoughts Chronological Timeline Stream (Newest at Top, No Scroll) */
        .timeline {
            display: flex;
            flex-direction: column;
            gap: 16px;
            position: relative;
            padding-left: 20px;
            margin-left: 10px;
            border-left: 1px solid rgba(255, 255, 255, 0.06);
            min-height: 120px;
            overflow: hidden;
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

        /* [ODO-SAFETY] Re-home warning: pulse the reset button when the position estimate is untrusted */
        .reset-btn.needs-attention {
            background: linear-gradient(135deg, rgba(255, 51, 102, 0.18) 0%, rgba(255, 92, 133, 0.18) 100%);
            color: #ff5c85;
            border-color: rgba(255, 51, 102, 0.55);
            animation: rehome-pulse 1.2s ease-in-out infinite;
        }
        @keyframes rehome-pulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(255, 51, 102, 0.45); }
            50%      { box-shadow: 0 0 16px 4px rgba(255, 51, 102, 0.35); }
        }
        /* [WOW EFFECT] 🐕 BARKING FLASH & POPUP EFFECT */
        @keyframes bark-flash {
            0%, 100% {
                box-shadow: inset 0 0 0 0 rgba(0, 240, 255, 0);
                filter: brightness(1);
            }
            50% {
                box-shadow: inset 0 0 80px 20px rgba(0, 240, 255, 0.45), inset 0 0 140px 40px rgba(124, 77, 255, 0.35);
                filter: brightness(1.2);
            }
        }
        body.bark-active {
            animation: bark-flash 0.3s ease-in-out infinite alternate !important;
            border: 4px solid var(--accent-cyan);
        }
        .bark-overlay {
            position: fixed;
            top: 24px;
            left: 50%;
            transform: translateX(-50%) scale(0);
            z-index: 10000;
            background: linear-gradient(135deg, #00f0ff 0%, #7c4dff 100%);
            color: #050508;
            font-weight: 800;
            font-size: 1.4rem;
            padding: 12px 28px;
            border-radius: 50px;
            box-shadow: 0 0 40px rgba(0, 240, 255, 0.9);
            pointer-events: none;
            transition: transform 0.25s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            display: flex;
            align-items: center;
            gap: 12px;
        }
        body.bark-active .bark-overlay {
            transform: translateX(-50%) scale(1);
        }
    </style>
</head>
<body>
    <div id="bark-overlay" class="bark-overlay">
        <span style="font-size: 1.8rem;">🐕</span>
        <span>WOOF! WOOF! BARKING!</span>
    </div>
    <header>
        <h1>Gemini <span>Robotics Demo</span></h1>
        <p>Embodied AI Puppy Robot Live Monitoring</p>
    </header>

    <div class="container">
        <!-- LEFT COLUMN: Live Video Stream & Position Reset Control -->
        <div class="panel" id="main-col">
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

                <!-- Scanning indicator: shown while driving (object labels return on pause) -->
                <div id="scan-indicator">SCANNING...</div>
                <!-- Live object counter: latest Gemini detection count, safe during motion -->
                <div id="objects-badge">OBJECTS SEEN: 0</div>

                <!-- 🎯 High-Fidelity HTML/CSS Vector Overlay layer -->
                <div id="vector-overlay-container" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 10;"></div>

                <img id="video-stream" src="/video_feed" alt="Robot Camera Stream">
            </div>

            <!-- [ODO-SAFETY] Re-home warning banner (shown when odometry drift makes the position untrusted) -->
            <div id="rehome-banner" style="display: none; margin-top: 16px; padding: 12px 16px; border-radius: 12px;
                 background: rgba(255, 51, 102, 0.12); border: 1px solid rgba(255, 51, 102, 0.45); color: #ff5c85;
                 font-size: 0.85rem; font-weight: 600; align-items: center; gap: 10px;">
                <span style="font-size: 1.1rem;">⚠️</span>
                <span id="rehome-banner-text">Odometry drift too high &mdash; position estimate untrusted. Re-center the robot and press <b>Reset Position</b>.</span>
            </div>

            <!-- Video Quality Preset & Reset Coordinates Controls -->
            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 24px; flex-wrap: wrap; gap: 12px;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 0.85rem; color: var(--text-muted); font-weight: 600; text-transform: uppercase;">⚡ Stream Preset:</span>
                    <select id="stream-quality-select" style="background: rgba(10, 11, 16, 0.8); color: #fff; border: 1px solid var(--card-border); padding: 8px 14px; border-radius: 12px; font-family: 'Inter', sans-serif; font-size: 0.85rem; outline: none; cursor: pointer;">
                        <option value="512,384,58">⚡ Speed (Fast & Smooth)</option>
                        <option value="640,480,75" selected>🌟 Standard (Balanced)</option>
                        <option value="800,600,85">💎 Better (High Clarity)</option>
                    </select>
                </div>
                <button id="reset-odometry-btn" class="reset-btn">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
                    Reset Position (0,0)
                </button>
            </div>

            <!-- Connected Hardware Diagnostics (Moved below Live Camera Stream) -->
            <div class="panel" style="margin-top: 24px;">
                <h3>Connected Hardware Diagnostics</h3>
                <div class="diag-list">
                    <div class="diag-item">
                        <span>📷  USB Camera Feed</span>
                        <div class="diag-status">
                            <span class="halo-dot {{ 'status-on' if camera_avail else 'status-sim' }}"></span>
                            <small>{{ 'Hardware Connected' if camera_avail else 'Simulation Mode' }}</small>
                        </div>
                    </div>
                    <div class="diag-item">
                        <span>🧠  Gemini Cloud Cortex API</span>
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
                        <span>🎙️  Vocal Microphone (STT)</span>
                        <div class="diag-status">
                            <span class="halo-dot {{ 'status-on' if speech_avail else 'status-sim' }}"></span>
                            <small>{{ 'Vocal Active' if speech_avail else 'Simulation Mode' }}</small>
                        </div>
                    </div>
                    <div class="diag-item">
                        <span>🌡️  Core CPU Temperature</span>
                        <div class="diag-status">
                            <span id="cpu-temp-halo" class="halo-dot status-on"></span>
                            <small id="cpu-temp-text">-- °C</small>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- RIGHT COLUMN: Mind Analytics & Extended Thoughts Timeline -->
        <div class="side-column" id="side-col">
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

            <!-- Brain Thoughts Timeline (Extended View) -->
            <div class="panel" style="flex: 1;">
                <h3>Gemini Brain Thoughts</h3>
                <div id="thoughts-timeline" class="timeline">
                    <div class="timeline-item active">
                        <div class="timeline-dot"></div>
                        <div class="timeline-text">Initializing live puppy robot monitoring modules...</div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // 🚨 Global Error HUD: Instantly display any dashboard JS error on the timeline for real-time debugging!
        window.onerror = function(message, source, lineno, colno, error) {
            console.error("Global JS Error:", message, "at line", lineno);
            const thoughtsTimeline = document.getElementById('thoughts-timeline');
            if (thoughtsTimeline) {
                const item = document.createElement('div');
                item.className = 'timeline-item active';
                item.style.border = '1px solid #ff3366';
                item.style.background = 'rgba(255, 51, 102, 0.1)';
                item.style.padding = '8px 12px';
                item.style.borderRadius = '8px';
                item.style.marginTop = '8px';
                item.innerHTML = `
                    <div class="timeline-dot" style="background-color: #ff3366; box-shadow: 0 0 10px #ff3366;"></div>
                    <div class="timeline-text" style="color: #ff5c85; font-family: monospace; font-size: 0.8rem; font-weight: 700;">[Dashboard JS Error] ${message} (Line ${lineno})</div>
                `;
                thoughtsTimeline.prepend(item);
            }
            return false;
        };

        let thoughtsHistory = [];
        const stateBadge = document.getElementById('state-badge');
        const timelineContainer = document.getElementById('thoughts-timeline');
        const overlayContainer = document.getElementById('vector-overlay-container');

        // 🎯 High-Fidelity HTML/CSS Vector Overlay renderer with ELEMENT REUSE:
        // positions glide via CSS transitions (smooth between polls) and objects that
        // vanish from the data fade out instead of blinking off.
        const overlayItems = new Map();   // key -> {el, missingSince}
        const OVERLAY_ANIM = 'left 0.25s linear, top 0.25s linear, width 0.25s linear, height 0.25s linear, opacity 0.3s ease';
        const OVERLAY_FADE_REMOVE_MS = 900;

        function overlayGet(key, create) {
            let item = overlayItems.get(key);
            if (!item) {
                const el = create();
                el.style.transition = OVERLAY_ANIM;
                el.style.opacity = '0';            // fades in on the next frame
                overlayContainer.appendChild(el);
                item = { el: el, missingSince: null };
                overlayItems.set(key, item);
            }
            item.missingSince = null;
            requestAnimationFrame(() => { item.el.style.opacity = '1'; });
            return item.el;
        }

        function renderOverlayObjects(detectedObjects) {
            if (!overlayContainer) return;
            const seen = new Set();
            const dup = {};

            (Array.isArray(detectedObjects) ? detectedObjects : []).forEach(obj => {
                if (!obj) return;
                const box = obj.box_2d;
                const label = obj.label || 'Object';
                const type = obj.type || 'cortex';
                if (!box || !Array.isArray(box) || box.length !== 4) return;

                const ymin = box[0], xmin = box[1], ymax = box[2], xmax = box[3];
                const cx_pct = (xmin + xmax) / 2 / 10;
                const cy_pct = (ymin + ymax) / 2 / 10;

                let key = type + ':' + label;
                dup[key] = (dup[key] || 0) + 1;    // disambiguate duplicate labels
                key += ':' + dup[key];

                // 1. Tech-style thin bounding box for the active target
                if (type === 'active') {
                    const bboxEl = overlayGet(key + ':box', () => {
                        const el = document.createElement('div');
                        el.style.position = 'absolute';
                        el.style.border = '2px solid var(--accent-cyan)';
                        el.style.borderRadius = '12px';
                        el.style.boxShadow = '0 0 15px rgba(0, 240, 255, 0.25), inset 0 0 15px rgba(0, 240, 255, 0.08)';
                        el.style.pointerEvents = 'none';
                        return el;
                    });
                    bboxEl.style.left = (xmin / 10) + '%';
                    bboxEl.style.top = (ymin / 10) + '%';
                    bboxEl.style.width = ((xmax - xmin) / 10) + '%';
                    bboxEl.style.height = ((ymax - ymin) / 10) + '%';
                    seen.add(key + ':box');
                }

                // 2. High-definition vector pointer (dot + label badge)
                const ptr = overlayGet(key + ':ptr', () => {
                    const el = document.createElement('div');
                    el.style.position = 'absolute';
                    el.style.display = 'flex';
                    el.style.alignItems = 'center';
                    el.style.gap = '8px';
                    el.style.pointerEvents = 'none';
                    el.style.transform = 'translate(-5px, -50%)'; // Perfect sub-pixel dot alignment

                    const dot = document.createElement('div');
                    dot.style.width = '10px';
                    dot.style.height = '10px';
                    dot.style.borderRadius = '50%';
                    dot.style.backgroundColor = (type === 'active') ? 'var(--accent-cyan)' : '#1a73e8';
                    dot.style.border = '2.5px solid #ffffff';
                    dot.style.boxShadow = '0 0 8px rgba(0,0,0,0.45)';
                    dot.style.flexShrink = '0';

                    const tag = document.createElement('div');
                    tag.style.backgroundColor = (type === 'active') ? 'rgba(0, 110, 120, 0.82)' : '#1a73e8';
                    tag.style.border = (type === 'active') ? '1px solid rgba(0, 240, 255, 0.35)' : '1px solid rgba(255,255,255,0.12)';
                    tag.style.color = '#ffffff';
                    tag.style.padding = '4px 10px';
                    tag.style.borderRadius = '6px';
                    tag.style.fontSize = '11px';
                    tag.style.fontWeight = '700';
                    tag.style.fontFamily = "'Inter', 'Outfit', system-ui, sans-serif";
                    tag.style.whiteSpace = 'nowrap';
                    tag.style.boxShadow = '0 4px 12px rgba(0,0,0,0.3)';
                    tag.style.textTransform = 'lowercase';
                    tag.style.backdropFilter = 'blur(4px)';
                    tag.style.webkitBackdropFilter = 'blur(4px)';
                    tag.style.letterSpacing = '0.02em';

                    el.appendChild(dot);
                    el.appendChild(tag);
                    return el;
                });
                ptr.style.left = cx_pct + '%';
                ptr.style.top = cy_pct + '%';
                ptr.lastElementChild.innerText = label;   // keep the badge text fresh on reuse
                seen.add(key + ':ptr');
            });

            // Fade out overlays that vanished from the data, then remove them.
            const now = performance.now();
            for (const [key, item] of overlayItems) {
                if (seen.has(key)) continue;
                if (item.missingSince === null) {
                    item.missingSince = now;
                    item.el.style.opacity = '0';
                } else if (now - item.missingSince > OVERLAY_FADE_REMOVE_MS) {
                    item.el.remove();
                    overlayItems.delete(key);
                }
            }
        }

        function updateTimeline(newThought) {
            if (!newThought) return;
            
            // Reconstruct timeline only if the thought changed
            if (thoughtsHistory.length === 0 || thoughtsHistory[thoughtsHistory.length - 1] !== newThought) {
                thoughtsHistory.push(newThought);
                if (thoughtsHistory.length > 12) { // [NO-SCROLL FIT] Store up to 12 recent thoughts to fit cleanly without scrollbar
                    thoughtsHistory.shift();
                }
                
                // Clear and render items (Newest at Top!)
                timelineContainer.innerHTML = '';
                thoughtsHistory.slice().reverse().forEach((thought, idx) => {
                    const isLatest = (idx === 0);
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

        setInterval(function() {
            fetch('/status')
                .then(res => res.json())
                .then(data => {
                    // Update state badge
                    stateBadge.innerText = "CURRENT STATE: " + data.state;
                    stateBadge.className = "status-badge state-" + data.state;
                    
                    // Render HTML/CSS Vector Overlays with infinite sharpness
                    renderOverlayObjects(data.detected_objects);

                    // Scanning indicator (labels hidden while driving) + live object counter
                    const scanEl = document.getElementById('scan-indicator');
                    if (scanEl) scanEl.style.display = data.is_moving ? 'block' : 'none';
                    const objBadge = document.getElementById('objects-badge');
                    if (objBadge && data.objects_seen !== undefined) {
                        objBadge.innerText = 'OBJECTS SEEN: ' + data.objects_seen;
                    }
                    
                    // Update thoughts stream timeline
                    updateTimeline(data.thought);
                    const rehomeBanner = document.getElementById('rehome-banner');
                    const rehomeText = document.getElementById('rehome-banner-text');
                    const rehomeBtn = document.getElementById('reset-odometry-btn');
                    if (rehomeBanner) {
                        if (data.needs_rehome) {
                            const unc = (data.position_uncertainty !== undefined) ? Math.round(data.position_uncertainty) : '?';
                            if (rehomeText) {
                                rehomeText.innerHTML = 'Odometry drift too high (uncertainty &asymp; ' + unc +
                                    ' mm) &mdash; position untrusted. Re-center the robot and press <b>Reset Position</b>.';
                            }
                            rehomeBanner.style.display = 'flex';
                            if (rehomeBtn) rehomeBtn.classList.add('needs-attention');
                        } else {
                            rehomeBanner.style.display = 'none';
                            if (rehomeBtn) rehomeBtn.classList.remove('needs-attention');
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

                    // [WOW EFFECT] Trigger Visual Flash & Badge when puppy barks
                    if (data.is_barking) {
                        document.body.classList.add('bark-active');
                    } else {
                        document.body.classList.remove('bark-active');
                    }
                })
                .catch(err => console.error("Error fetching status:", err));
        }, 250); // 4Hz polling: the HTML/CSS overlay is now the ONLY annotation layer, so a faster refresh keeps the boxes tracking smoothly (raise back to 500 if Pi load is a concern)

        // Auto-reconnect the MJPEG stream if it errors out (e.g. server restart);
        // without this the <img> freezes on a broken frame until a manual refresh.
        const videoStream = document.getElementById('video-stream');
        if (videoStream) {
            videoStream.onerror = function() {
                setTimeout(function() {
                    videoStream.src = '/video_feed?ts=' + Date.now();
                }, 2000);
            };
        }

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

        const qualitySelect = document.getElementById('stream-quality-select');
        if (qualitySelect) {
            qualitySelect.addEventListener('change', function() {
                const [w, h, q] = this.value.split(',').map(Number);
                fetch('/set_stream_quality', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ width: w, height: h, quality: q })
                })
                .then(res => res.json())
                .then(data => console.log("Stream quality updated:", data))
                .catch(err => console.error("Error setting stream quality:", err));
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
    print(f"    CORE BUILD: {CORE_BUILD}")
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
        print("\n⏹️ [SYSTEM] Initiating graceful shutdown...")
        RUNNING = False
        gemini_trigger_event.set() # Wake up Gemini thread from wait instantly
        
        # Stop the robot motors immediately
        robot.stop()
        
        # Wait for daemon threads to finish cleanly
        threads = [t_cam, t_vis, t_aud, t_gem, t_enc]
        for t in threads:
            if t.is_alive():
                t.join(timeout=3.0)
                
        # Clean up GPIO pins to prevent hardware pinning issues
        if GPIO_AVAILABLE:
            try:
                GPIO.cleanup()
                print("✅ [HARDWARE] GPIO pins successfully cleaned up.")
            except Exception as e:
                print(f"⚠️ [HARDWARE] GPIO cleanup failed: {e}")
                
        print("⏹️ [SYSTEM] AI puppy robot successfully stopped.")
        sys.exit(0)
