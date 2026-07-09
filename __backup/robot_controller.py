import time
import math

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO module not found. Running in MOCK mode.")

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
        
        # Max allowed coordinates for the robot center
        x_limit = max(0.0, 0.5 * self.TABLE_WIDTH - x_extent - self.SAFETY_MARGIN)
        y_limit = max(0.0, 0.5 * self.TABLE_DEPTH - y_extent - self.SAFETY_MARGIN)
        
        return x_limit, y_limit

    def reset_odometry(self, x=0.0, y=0.0, theta=90.0):
        """Resets the accumulated coordinates back to initial or specified values."""
        self.x = x
        self.y = y
        self.theta = theta
        self.last_update_time = time.time()
        self.is_out_of_bounds = False
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
        elif self.last_action == 'backward':
            rad = math.radians(self.theta)
            self.x -= self.SPEED_LINEAR * dt * math.cos(rad)
            self.y -= self.SPEED_LINEAR * dt * math.sin(rad)
        elif self.last_action == 'left':
            self.theta = (self.theta + self.SPEED_ANGULAR * dt) % 360
        elif self.last_action == 'right':
            self.theta = (self.theta - self.SPEED_ANGULAR * dt) % 360

        # Boundary clamping to prevent coordinates from expanding to infinity
        x_limit, y_limit = self.get_bounds_at_heading(self.theta)
        
        # Check if we are currently out of bounds
        if abs(self.x) > x_limit or abs(self.y) > y_limit:
            self.is_out_of_bounds = True
        else:
            self.is_out_of_bounds = False

    def is_safe_action(self, action):
        """Predicts the next coordinate step and returns whether it keeps the robot within safe boundaries."""
        self.update_odometry() # Bring coordinates up to date
        
        if action not in ['forward', 'backward']:
            return True # Turning is always allowed to allow the robot to steer back to safety

        rad = math.radians(self.theta)
        next_x = self.x
        next_y = self.y
        dt_pred = 0.1 # Predict 100ms into the future

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
        time.sleep(1)
        self.stop()
        
    def beep(self):
        print('[GPIO] 🔊 Beep signal received (Roborobo buzzer sound is bypassed)')
        time.sleep(0.5)
        self.stop()

    def express_happy(self):
        print('[GPIO] 🐶 Initiating happy expression motion')
        self.bark()
        for _ in range(2):
            self.turn_left()
            time.sleep(0.2)
            self.turn_right()
            time.sleep(0.2)
        self.stop()


