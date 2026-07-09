import time
import math
import threading

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO module not found. Running in MOCK mode.")

# ============================================================================
# 🧭 [ODO-SAFETY] ODOMETRY-BASED TABLE-EDGE SAFETY  (SOFTWARE-ONLY FALLBACK)
# ----------------------------------------------------------------------------
# The Raspberry Pi has NO access to the robot's IR sensors — they are wired only
# to the Roborobo CPU board. So the ONLY protection against driving off the
# table edge is this dead-reckoning odometry estimate. Being open-loop (no
# encoders / IMU / IR feedback), its error grows without bound over time, so
# this subsystem is designed to FAIL SAFE (stop + request a physical re-home)
# before the drift becomes dangerous, rather than to be perfectly accurate.
#
# ⚠️  REMOVAL / REPLACEMENT GUIDE — when real IR / cliff sensors reach the Pi:
#   • Quick disable:  set ODOMETRY_SAFETY_ENABLED = False below. Every guard in
#     this file then becomes a no-op (is_out_of_bounds stays False,
#     is_safe_action returns True, needs_rehome stays False), so the robot
#     relies entirely on the new sensors.
#   • Full removal:   delete every block fenced by  "[ODO-SAFETY]" ...
#     "[/ODO-SAFETY]"  markers (grep for the tag), then reimplement
#     is_out_of_bounds / is_safe_action from the IR sensor readings.
ODOMETRY_SAFETY_ENABLED = False
# [/ODO-SAFETY]

class RobotController:
    """
    RobotController: Communicates with the Roborobo kit CPU board using GPIO via level shifters.
    Raspberry Pi (3.3V) -> Level Shifter -> Roborobo (5V, Active-Low open-drain)
    Now enhanced with time-accumulated virtual coordinate tracking (Odometry) and safety boundaries.
    """
    def __init__(self):
        # BCM pin definitions (can be adjusted according to your hardware wiring)
        self.PIN_FORWARD = 17  # IN1: Forward
        self.PIN_LEFT = 27     # IN2: Turn Left
        self.PIN_RIGHT = 22    # IN3: Turn Right
        self.PIN_BACKWARD = 23 # IN4: Backward

        self.pins = [self.PIN_FORWARD, self.PIN_LEFT, self.PIN_RIGHT, self.PIN_BACKWARD]
        self.last_action = None

        # ==========================================
        # 📐 Odometry & Coordinate Tracking Parameters
        # ==========================================
        self.x = 0.0             # Real-time X coordinate in mm (starts at center of table)
        self.y = 0.0             # Real-time Y coordinate in mm (starts at center of table)
        self.theta = 90.0        # Real-time Heading angle in degrees (90 degrees = facing +Y, towards audience)
        self.last_update_time = time.time()

        # Actuator speeds (Default calibration values, customizable)
        self.SPEED_LINEAR = 120.0   # Linear speed: 120 mm/s
        self.SPEED_ANGULAR = 45.0   # Angular speed: 45 degrees/s

        # Physical dimensions matching the user setup
        self.ROBOT_WIDTH = 150.0    # Left-to-Right width in mm (narrow side)
        self.ROBOT_LENGTH = 250.0   # Front-to-Back length in mm (wide side)
        self.TABLE_WIDTH = 1200.0   # Table width in mm (X-axis: -600 to +600)
        self.TABLE_DEPTH = 800.0    # Table depth in mm (Y-axis: -400 to +400)
        self.SAFETY_MARGIN = 50.0   # Safety margin in mm from table edges

        self.is_out_of_bounds = False

        # ── [ODO-SAFETY] Drift-uncertainty & fail-safe parameters ───────────────
        # Open-loop odometry drifts without bound, so we track an estimated
        # position-uncertainty (mm) that GROWS with every move/turn and SHRINKS the
        # usable safe area. When it exceeds the limit the robot stops driving and
        # requests a physical re-home + reset_odometry(). All values are tunable.
        self.position_uncertainty = 0.0     # Accumulated position-error estimate (mm)
        self.UNCERTAINTY_PER_MM = 0.04      # Error added per mm travelled (~4% of distance)
        self.UNCERTAINTY_PER_DEG = 0.25     # Error (mm) added per degree turned (heading error later projects to position)
        self.UNCERTAINTY_LIMIT = 250.0      # Above this the estimate is untrusted -> fail-safe stop + re-home request
        self.needs_rehome = False           # True -> dashboard should ask the operator to re-center + reset
        # Conservative bias: treat the robot as travelling slightly faster than measured
        # so boundary checks trigger EARLY (always err toward "too close to the edge").
        self.SAFETY_SPEED_FACTOR = 1.15
        # ── [/ODO-SAFETY] ───────────────────────────────────────────────────────

        # Set by higher-level safety logic to preempt an in-progress emotional expression.
        self.abort_event = threading.Event()
        self.bark_time = 0.0  # [WOW EFFECT] Timestamp of last bark for visual dashboard flash

        if GPIO_AVAILABLE:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            
            # Configure all pins as INPUT with PUD_UP by default to maintain high-impedance 'STOP' state.
            for pin in self.pins:
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            print('✅ GPIO and Level Shifter mode successfully initialized (Open-Drain PUD_UP mode).')

    def get_bounds_at_heading(self, theta):
        """Calculates the safe coordinate boundaries for the robot center at a given heading (theta)."""
        rad = math.radians(theta)
        abs_cos = abs(math.cos(rad))
        abs_sin = abs(math.sin(rad))
        
        # Dynamic extent from the center of the robot
        x_extent = 0.5 * (self.ROBOT_WIDTH * abs_sin + self.ROBOT_LENGTH * abs_cos)
        y_extent = 0.5 * (self.ROBOT_WIDTH * abs_cos + self.ROBOT_LENGTH * abs_sin)

        # [ODO-SAFETY] Shrink the safe area by the growing drift-uncertainty, so the longer
        # we run without a re-home, the more cautious the boundary becomes.
        effective_margin = self.SAFETY_MARGIN + self.position_uncertainty
        # [/ODO-SAFETY]

        # Max allowed coordinates for the robot center
        x_limit = max(0.0, 0.5 * self.TABLE_WIDTH - x_extent - effective_margin)
        y_limit = max(0.0, 0.5 * self.TABLE_DEPTH - y_extent - effective_margin)

        return x_limit, y_limit

    def reset_odometry(self, x=0.0, y=0.0, theta=90.0):
        """Resets the accumulated coordinates back to initial or specified values."""
        self.x = x
        self.y = y
        self.theta = theta
        self.last_update_time = time.time()
        self.is_out_of_bounds = False
        # [ODO-SAFETY] A physical re-home is the only way to regain trust; clear the drift estimate.
        self.position_uncertainty = 0.0
        self.needs_rehome = False
        # [/ODO-SAFETY]
        print(f"[ODOMETRY] Coordinates manually reset to: X={self.x}, Y={self.y}, Theta={self.theta}°")

    def update_odometry(self):
        """Integrates motion over elapsed time to update the virtual (X, Y, theta) coordinates."""
        now = time.time()
        dt = now - self.last_update_time
        self.last_update_time = now

        if dt <= 0:
            return

        # Update coordinate values based on the active last_action
        if self.last_action == 'forward':
            rad = math.radians(self.theta)
            self.x += self.SPEED_LINEAR * dt * math.cos(rad)
            self.y += self.SPEED_LINEAR * dt * math.sin(rad)
            # [ODO-SAFETY] grow uncertainty with distance travelled
            self.position_uncertainty += self.UNCERTAINTY_PER_MM * self.SPEED_LINEAR * dt
        elif self.last_action == 'backward':
            rad = math.radians(self.theta)
            self.x -= self.SPEED_LINEAR * dt * math.cos(rad)
            self.y -= self.SPEED_LINEAR * dt * math.sin(rad)
            # [ODO-SAFETY] grow uncertainty with distance travelled
            self.position_uncertainty += self.UNCERTAINTY_PER_MM * self.SPEED_LINEAR * dt
        elif self.last_action == 'left':
            self.theta = (self.theta + self.SPEED_ANGULAR * dt) % 360
            # [ODO-SAFETY] heading error grows with every turn and later projects into position error
            self.position_uncertainty += self.UNCERTAINTY_PER_DEG * self.SPEED_ANGULAR * dt
        elif self.last_action == 'right':
            self.theta = (self.theta - self.SPEED_ANGULAR * dt) % 360
            # [ODO-SAFETY] heading error grows with every turn and later projects into position error
            self.position_uncertainty += self.UNCERTAINTY_PER_DEG * self.SPEED_ANGULAR * dt

        # ── [ODO-SAFETY] Boundary + fail-safe evaluation ────────────────────────
        if not ODOMETRY_SAFETY_ENABLED:
            # Odometry safety disabled (e.g. replaced by real IR sensors): never block.
            self.is_out_of_bounds = False
            self.needs_rehome = False
            return

        # Boundary clamping to prevent coordinates from expanding to infinity
        # (safe area is already shrunk by the accumulated uncertainty inside get_bounds_at_heading).
        x_limit, y_limit = self.get_bounds_at_heading(self.theta)

        # Check if we are currently out of bounds
        if abs(self.x) > x_limit or abs(self.y) > y_limit:
            self.is_out_of_bounds = True
        else:
            self.is_out_of_bounds = False

        # Fail-safe: once drift-uncertainty is too large, the estimate can no longer be
        # trusted to keep the robot on the table -> demand a physical re-home + reset.
        if self.position_uncertainty >= self.UNCERTAINTY_LIMIT:
            self.needs_rehome = True
        # ── [/ODO-SAFETY] ───────────────────────────────────────────────────────

    def is_safe_action(self, action):
        """Predicts the next coordinate step and returns whether it keeps the robot within safe boundaries."""
        self.update_odometry() # Bring coordinates up to date

        # [ODO-SAFETY] When disabled, defer entirely to the (future) IR sensors — allow everything.
        if not ODOMETRY_SAFETY_ENABLED:
            return True

        # [ODO-SAFETY] Trust exhausted: block all driving until a physical re-home + reset.
        if self.needs_rehome and action in ['forward', 'backward']:
            return False
        # [/ODO-SAFETY]

        if action not in ['forward', 'backward']:
            return True # Turning is always allowed to allow the robot to steer back to safety

        rad = math.radians(self.theta)
        next_x = self.x
        next_y = self.y
        # [ODO-SAFETY] Predict pessimistically: assume slightly more travel than measured (conservative bias).
        dt_pred = 0.1 * self.SAFETY_SPEED_FACTOR # Predict ~100ms ahead, conservatively inflated

        if action == 'forward':
            next_x += self.SPEED_LINEAR * dt_pred * math.cos(rad)
            next_y += self.SPEED_LINEAR * dt_pred * math.sin(rad)
        elif action == 'backward':
            next_x -= self.SPEED_LINEAR * dt_pred * math.cos(rad)
            next_y -= self.SPEED_LINEAR * dt_pred * math.sin(rad)

        x_limit, y_limit = self.get_bounds_at_heading(self.theta)

        # Block the movement only if it increases the out-of-bounds magnitude
        if abs(next_x) > x_limit and abs(next_x) > abs(self.x):
            return False
        if abs(next_y) > y_limit and abs(next_y) > abs(self.y):
            return False

        return True

    def _set_pin_low(self, active_pin):
        """Sets the selected pin to OUTPUT LOW (0V) to trigger active-low action, keeping all other pins on INPUT High-Z."""
        if not GPIO_AVAILABLE:
            return

        for pin in self.pins:
            if pin == active_pin:
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.LOW)  # Triggered (LOW: 0V)
            else:
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP) # High-Impedance (Disabled)

    def move_forward(self):
        self.update_odometry()
        if not self.is_safe_action('forward'):
            print(f"[ODOMETRY WARNING] 🛑 Forward move blocked! Boundary reached. (X={self.x:.1f}, Y={self.y:.1f})")
            self.stop()
            return

        if self.last_action == 'forward': return
        self.last_action = 'forward'
        print(f'[GPIO] ⬆️ Forward (X={self.x:.1f}, Y={self.y:.1f}, Angle={self.theta:.1f}°)')
        self._set_pin_low(self.PIN_FORWARD)

    def move_backward(self):
        self.update_odometry()
        if not self.is_safe_action('backward'):
            print(f"[ODOMETRY WARNING] 🛑 Backward move blocked! Boundary reached. (X={self.x:.1f}, Y={self.y:.1f})")
            self.stop()
            return

        if self.last_action == 'backward': return
        self.last_action = 'backward'
        print(f'[GPIO] ⬇️ Backward (X={self.x:.1f}, Y={self.y:.1f}, Angle={self.theta:.1f}°)')
        self._set_pin_low(self.PIN_BACKWARD)

    def turn_left(self):
        self.update_odometry()
        if self.last_action == 'left': return
        self.last_action = 'left'
        print(f'[GPIO] ⬅️ Turn Left (X={self.x:.1f}, Y={self.y:.1f}, Angle={self.theta:.1f}°)')
        self._set_pin_low(self.PIN_LEFT)

    def turn_right(self):
        self.update_odometry()
        if self.last_action == 'right': return
        self.last_action = 'right'
        print(f'[GPIO] ➡️ Turn Right (X={self.x:.1f}, Y={self.y:.1f}, Angle={self.theta:.1f}°)')
        self._set_pin_low(self.PIN_RIGHT)

    def stop(self):
        self.update_odometry()
        if self.last_action == 'stop': return
        self.last_action = 'stop'
        print(f'[GPIO] ⏹️ Stop (X={self.x:.1f}, Y={self.y:.1f}, Angle={self.theta:.1f}°)')
        if GPIO_AVAILABLE:
            for pin in self.pins:
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def bark(self):
        print('[GPIO] 🐕 Bark signal received (Roborobo buzzer sound is bypassed)')
        self.bark_time = time.time()  # Trigger visual flash effect on dashboard
        time.sleep(1)
        self.stop()
        
    def beep(self):
        print('[GPIO] 🔊 Beep signal received (Roborobo buzzer sound is bypassed)')
        time.sleep(0.5)
        self.stop()

    def express_happy(self):
        print('[GPIO] 🐶 Initiating happy expression motion')
        self.abort_event.clear()
        self.bark()
        for _ in range(2):
            if self.abort_event.is_set():
                print('[GPIO] ⚠️ Happy expression preempted by safety override.')
                break
            self.turn_left()
            time.sleep(0.2)
            if self.abort_event.is_set():
                print('[GPIO] ⚠️ Happy expression preempted by safety override.')
                break
            self.turn_right()
            time.sleep(0.2)
        self.stop()


