import argparse
import cv2
import math
import platform
import numpy as np

# O driver de input será inicializado em tempo de execução pelo
# `setup_input_driver(platform_choice)` com base no flag passado.
input_driver = None

def setup_input_driver(platform_choice: str | None):
    """Inicializa `input_driver` com base na plataforma desejada.

    platform_choice: 'auto'|'linux'|'windows'|'mac' or None -> 'auto'
    """
    global input_driver
    choice = (platform_choice or "auto").lower()
    if choice == "auto":
        sys_platform = platform.system().lower()
        if "windows" in sys_platform:
            choice = "windows"
        elif "darwin" in sys_platform or "mac" in sys_platform:
            choice = "mac"
        else:
            choice = "linux"

    # Prefer pydirectinput for better game compatibility on Windows/Linux
    if choice in ("windows", "linux"):
        try:
            import pydirectinput as _drv
            input_driver = _drv
            print(f"[INFO] Usando pydirectinput para {choice}.")
            return
        except Exception:
            pass

    # Fallback para pyautogui (especialmente em macOS)
    try:
        import pyautogui as _drv
        input_driver = _drv
        print(f"[INFO] Usando pyautogui para {choice} (fallback).")
        input_driver.PAUSE = 0
        input_driver.FAILSAFE = True
    except Exception:
        print("[ERRO] Nenhum driver de input disponível (pydirectinput/pyautogui).")
        input_driver = None

try:
    import mediapipe as mp
    print(mp.__version__)
    # if hasattr(mp, "solutions"):

    mp_solutions = mp.solutions
    # else:
    #     # Alguns empacotamentos colocam o módulo em mediapipe.python
    #     from mediapipe.python import solutions as mp_solutions
except ImportError:
    print("\n[ERRO] MediaPipe não encontrado.")
    print("Execute: pip install mediapipe")
    exit(1)
except AttributeError:
    try:
        from mediapipe.python import solutions as mp_solutions
    except Exception:
        print("\n[ERRO] não foi possível inicializar o MediaPipe.")
        exit(1)

# --- CONFIGURAÇÃO ---
CONFIG = {
    "KEY_MAP": {
        "WALK": ["w"],
        "RUN": ["shift", "w"],
        "CROUCH": ["ctrl"]

    },
    "THRESHOLDS": {
        "WALK": 0.015,
        "RUN": 0.045,
        "CROUCH_RATIO": 0.15,
        "INCLINE_ANGLE_DEGREES": 30
    },
    "VECTOR_MOUSE": {
        "TOGGLE_KEY": "m",
        "AIM_KEY": "n",        # alterna a perspectiva de mira: camera <-> screen
        "CALIBRATE_KEY": "c",  # CALIBRA o centro de mira (camera): ponto vermelho atual vira origem
        "AIM_REFERENCE": "camera",  # 'camera' = ponto vermelho no frame | 'screen' = cursor vs centro da tela
        "DEAD_ZONE": 0.06,     # fracao do raio maximo do frame (centro->canto) da zona morta
        "MIN_SPEED": 8,        # px/frame minimos fora da zona morta
        "MAX_SPEED": 60,       # px/frame maximos quando o ponto esta na borda do frame
        "CURVE": 1.5,          # expoente da rampa (1.0 = linear, >1 = aceleracao no fim)
        "SMOOTHING": 0.15      # suavizacao exponencial da velocidade (0..1)
    },
    "INPUT_ENABLED": True,
    "PAUSE_KEY": "p"       # pausa/retoma a simulacao de teclado/mouse (P)
}

class MovementState:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.active_keys = set()
        self.active_mouse_buttons = set()

    def press_key(self, key: str):
        if not self.enabled:
            return
        input_driver.keyDown(key)
        self.active_keys.add(key)

    def release_key(self, key: str):
        if not self.enabled:
            return
        input_driver.keyUp(key)
        self.active_keys.discard(key)

    def press_mouse(self, button: str):
        if not self.enabled:
            return
        input_driver.mouseDown(button=button)
        self.active_mouse_buttons.add(button)

    def release_mouse(self, button: str):
        if not self.enabled:
            return
        input_driver.mouseUp(button=button)
        self.active_mouse_buttons.discard(button)

    def sync(self, desired_keys, desired_mouse_buttons):
        for key in tuple(self.active_keys):
            if key not in desired_keys:
                self.release_key(key)
        for key in desired_keys:
            if key not in self.active_keys:
                self.press_key(key)

        for button in tuple(self.active_mouse_buttons):
            if button not in desired_mouse_buttons:
                self.release_mouse(button)
        for button in desired_mouse_buttons:
            if button not in self.active_mouse_buttons:
                self.press_mouse(button)

    def release_all(self):
        for key in tuple(self.active_keys):
            self.release_key(key)
        for button in tuple(self.active_mouse_buttons):
            self.release_mouse(button)

class MotionController:
    def __init__(self, input_enabled=True):
        self.mp_pose = mp_solutions.pose
        self.pose = self.mp_pose.Pose(
            static_image_mode=False,
            model_complexity=1,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        self.state_machine = MovementState(enabled=input_enabled)
        self.input_enabled = input_enabled
        self.paused = False
        self.prev_center = None
        self.vector_mouse_enabled = False
        self.aim_reference = str(CONFIG["VECTOR_MOUSE"].get("AIM_REFERENCE", "camera")).lower()
        if self.aim_reference not in ("camera", "screen"):
            self.aim_reference = "camera"
        self.vec_has_target = False
        self.aim_center = None
        self.vec_ref_point = None
        self.vec_ref_max = 0.0
        self.vec_vel = [0.0, 0.0]
        self.vec_accum = [0.0, 0.0]
        self.vec_in_dead_zone = False

    def _find_color_target(self, frame):
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        red_mask1 = cv2.inRange(hsv, np.array([0, 120, 70]), np.array([10, 255, 255]))
        red_mask2 = cv2.inRange(hsv, np.array([170, 120, 70]), np.array([180, 255, 255]))
        orange_mask = cv2.inRange(hsv, np.array([10, 120, 70]), np.array([25, 255, 255]))
        red_mask = cv2.bitwise_or(red_mask1, red_mask2)
        mask = cv2.bitwise_or(red_mask, orange_mask)
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None, None, None
        best = max(contours, key=cv2.contourArea)
        if cv2.contourArea(best) < 150:
            return None, None, None
        x, y, w, h = cv2.boundingRect(best)
        center = (x + w // 2, y + h // 2)
        target_mask = mask[y:y + h, x:x + w]
        red_count = cv2.countNonZero(cv2.bitwise_and(red_mask[y:y + h, x:x + w], target_mask))
        orange_count = cv2.countNonZero(cv2.bitwise_and(orange_mask[y:y + h, x:x + w], target_mask))
        color_name = "red" if red_count >= orange_count else "orange"
        return center, color_name, (x, y, w, h)

    def _move_mouse_to_point(self, point, frame_width, frame_height):
        if not self.input_enabled or input_driver is None:
            return
        try:
            screen_width, screen_height = input_driver.size()
        except Exception:
            return
        x, y = point
        screen_x = int(x / frame_width * screen_width)
        screen_y = int(y / frame_height * screen_height)
        try:
            if hasattr(input_driver, "moveTo"):
                input_driver.moveTo(screen_x, screen_y)
            elif hasattr(input_driver, "move"):
                input_driver.move(screen_x, screen_y)
        except Exception:
            pass

    def _get_mouse_pos(self):
        try:
            return input_driver.position()
        except Exception:
            return None

    def _apply_relative_move(self, dx, dy):
        try:
            if hasattr(input_driver, "moveRel"):
                input_driver.moveRel(dx, dy)
            elif hasattr(input_driver, "move"):
                input_driver.move(dx, dy)
        except Exception:
            pass

    def _decay_velocity(self):
        smoothing = float(CONFIG["VECTOR_MOUSE"].get("SMOOTHING", 0.15))
        decay = 1.0 - min(1.0, max(0.0, smoothing))
        self.vec_vel[0] *= decay
        self.vec_vel[1] *= decay

    def _aim_hint(self):
        if self.aim_reference == "screen":
            return "cursor no centro"
        return ("ponto no centro calibrado" if self.aim_center is not None
                else "ponto no centro")

    def _vector_mouse_step(self, target_center, frame_width, frame_height):
        """Modo vetorial com perspectiva de mira configurável em runtime.

        'camera': o ponto vermelho deslocado do centro do frame define direcao e
                  velocidade da deriva relativa (moveRel). Acelera perto da borda
                  do frame; o cursor nunca sai da tela (fica preso na borda).
        'screen': o cursor efetivo (posicao na tela) funciona como joystick:
                  quanto mais longe do centro da tela, maior a deriva.
        """
        if not self.input_enabled or input_driver is None:
            return None

        pos = self._get_mouse_pos()
        if pos is None:
            return None
        try:
            screen_w, screen_h = input_driver.size()
            pos_x = pos.x if hasattr(pos, "x") else pos[0]
            pos_y = pos.y if hasattr(pos, "y") else pos[1]
        except Exception:
            return None

        vm = CONFIG["VECTOR_MOUSE"]
        dz_frac = float(vm.get("DEAD_ZONE", 0.06))
        min_speed = float(vm.get("MIN_SPEED", 8.0))
        max_speed = float(vm.get("MAX_SPEED", 60.0))
        curve = max(1.0, float(vm.get("CURVE", 1.5)))
        smoothing = min(1.0, max(0.0, float(vm.get("SMOOTHING", 0.15))))

        if self.aim_reference == "screen":
            # joystick: cursor relativo ao centro da tela
            ref_cx, ref_cy = screen_w / 2.0, screen_h / 2.0
            dx = pos_x - ref_cx
            dy = pos_y - ref_cy
            max_radius = math.hypot(ref_cx, ref_cy) or 1.0
            self.vec_has_target = True
        else:
            # camera: ponto vermelho relativo ao centro de mira (calibrado ou centro do frame)
            self.vec_has_target = target_center is not None
            if not self.vec_has_target:
                self.vec_in_dead_zone = True
                self._decay_velocity()
                return 0.0, 0.0, 0.0, 0.0, None
            if self.aim_center is not None:
                ref_cx, ref_cy = float(self.aim_center[0]), float(self.aim_center[1])
            else:
                ref_cx, ref_cy = frame_width / 2.0, frame_height / 2.0
            dx = target_center[0] - ref_cx
            dy = target_center[1] - ref_cy
            corners = (
                math.hypot(ref_cx, ref_cy),
                math.hypot(ref_cx - (frame_width - 1), ref_cy),
                math.hypot(ref_cx, ref_cy - (frame_height - 1)),
                math.hypot(ref_cx - (frame_width - 1), ref_cy - (frame_height - 1)),
            )
            max_radius = max(corners) or 1.0
            self.vec_ref_point = (ref_cx, ref_cy)
            self.vec_ref_max = max_radius

        speed = math.hypot(dx, dy)

        dz_px = dz_frac * max_radius
        self.vec_in_dead_zone = speed <= dz_px

        if self.vec_in_dead_zone:
            self._decay_velocity()
            return 0.0, 0.0, 0.0, 0.0, None

        # distancia normalizada (0..1) a partir do fim da zona morta
        norm = min(1.0, (speed - dz_px) / max(1.0, max_radius - dz_px))
        mag = min_speed + (max_speed - min_speed) * (norm ** curve)

        target_x = (dx / speed) * mag
        target_y = (dy / speed) * mag

        # suaviza a velocidade (EMA) e acumula a parte fracionaria
        self.vec_vel[0] += (target_x - self.vec_vel[0]) * smoothing
        self.vec_vel[1] += (target_y - self.vec_vel[1]) * smoothing

        self.vec_accum[0] += self.vec_vel[0]
        self.vec_accum[1] += self.vec_vel[1]

        move_x = int(self.vec_accum[0])
        move_y = int(self.vec_accum[1])

        self.vec_accum[0] -= move_x
        self.vec_accum[1] -= move_y

        # nao deixa o cursor sair da tela: preso na borda
        new_x = int(min(max(pos_x + move_x, 0), screen_w - 1))
        new_y = int(min(max(pos_y + move_y, 0), screen_h - 1))
        eff_x = new_x - pos_x
        eff_y = new_y - pos_y

        border_side = None
        if pos_x >= screen_w - 2 and target_x > 0:
            border_side = "direita"
        elif pos_x <= 1 and target_x < 0:
            border_side = "esquerda"
        elif pos_y >= screen_h - 2 and target_y > 0:
            border_side = "baixo"
        elif pos_y <= 1 and target_y < 0:
            border_side = "cima"

        if eff_x or eff_y:
            self._apply_relative_move(eff_x, eff_y)

        return dx, dy, speed, mag / max_speed, border_side

    def run(self):
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("[ERRO] Não foi possível abrir a webcam.")
            return

        print(f"--- Rodando no Python {platform.python_version()} ({platform.system()}) ---")

        try:
            while True:
                success, frame = cap.read()
                if not success:
                    break

                frame = cv2.flip(frame, 1)
                frame_height, frame_width = frame.shape[:2]
                box_margin = 40
                capture_box_start = (box_margin, box_margin)
                capture_box_end = (frame_width - box_margin, frame_height - box_margin)
                cv2.rectangle(frame, capture_box_start, capture_box_end, (255, 255, 0), 2)
                cv2.putText(frame, "Capture area", (box_margin + 5, box_margin - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pose_res = self.pose.process(rgb_frame)

                walk = run = crouch = False
                desired_keys = set()
                tracking_info = "Capturing: none"
                incline_label = "Incline: straight"
                target_info = "Target: none"

                target_center, target_color, target_box = self._find_color_target(frame)
                if target_center is not None:
                    target_info = f"Target: {target_color}"
                    color_draw = (0, 0, 255) if target_color == "red" else (0, 165, 255)
                    cv2.circle(frame, target_center, 12, color_draw, -1)
                    cv2.circle(frame, target_center, 20, color_draw, 2)
                    x, y, w, h = target_box
                    cv2.rectangle(frame, (x, y), (x + w, y + h), color_draw, 2)
                    cv2.putText(frame, target_info, (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color_draw, 2)
                    cv2.putText(frame, f"Pos: {target_center}", (target_center[0] + 15, target_center[1] + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color_draw, 2)
                    cv2.line(frame, (target_center[0] - 25, target_center[1]), (target_center[0] + 25, target_center[1]), color_draw, 1)
                    cv2.line(frame, (target_center[0], target_center[1] - 25), (target_center[0], target_center[1] + 25), color_draw, 1)
                    if not self.vector_mouse_enabled and not self.paused:
                        self._move_mouse_to_point(target_center, frame_width, frame_height)

                if pose_res.pose_landmarks:
                    tracking_info = "Capturing: body"
                    lms = pose_res.pose_landmarks.landmark
                    xs = [lm.x for lm in lms]
                    ys = [lm.y for lm in lms]
                    min_x, max_x = min(xs), max(xs)
                    min_y, max_y = min(ys), max(ys)
                    rect_start = (max(0, int(min_x * frame_width)), max(0, int(min_y * frame_height)))
                    rect_end = (min(frame_width - 1, int(max_x * frame_width)), min(frame_height - 1, int(max_y * frame_height)))
                    cv2.rectangle(frame, rect_start, rect_end, (0, 255, 255), 2)
                    cv2.putText(frame, "Body box", (rect_start[0], max(0, rect_start[1] - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

                    sh_l = lms[self.mp_pose.PoseLandmark.LEFT_SHOULDER]
                    sh_r = lms[self.mp_pose.PoseLandmark.RIGHT_SHOULDER]
                    hip_l = lms[self.mp_pose.PoseLandmark.LEFT_HIP]
                    hip_r = lms[self.mp_pose.PoseLandmark.RIGHT_HIP]

                    center_x = (sh_l.x + sh_r.x + hip_l.x + hip_r.x) / 4
                    center_y = (sh_l.y + sh_r.y + hip_l.y + hip_r.y) / 4

                    if self.prev_center is not None:
                        motion = math.hypot(center_x - self.prev_center[0], center_y - self.prev_center[1])
                        if motion > CONFIG["THRESHOLDS"]["RUN"]:
                            run = True
                        elif motion > CONFIG["THRESHOLDS"]["WALK"]:
                            walk = True

                    self.prev_center = (center_x, center_y)

                    dx = sh_r.x - sh_l.x
                    dy = sh_r.y - sh_l.y
                    angle_deg = abs(math.degrees(math.atan2(dy, dx))) if dx != 0 else 90.0
                    if angle_deg > CONFIG["THRESHOLDS"]["INCLINE_ANGLE_DEGREES"]:
                        if dy > 0:
                            incline_label = "Incline: right"
                            desired_keys.add("q")
                        else:
                            incline_label = "Incline: left"
                            desired_keys.add("e")
                    else:
                        incline_label = "Incline: straight"

                    if abs(((sh_l.y + sh_r.y) / 2) - ((hip_l.y + hip_r.y) / 2)) < CONFIG["THRESHOLDS"]["CROUCH_RATIO"]:
                        crouch = True

                if crouch:
                    desired_keys.update(CONFIG["KEY_MAP"]["CROUCH"])
                elif run:
                    desired_keys.update(CONFIG["KEY_MAP"]["RUN"])
                elif walk:
                    desired_keys.update(CONFIG["KEY_MAP"]["WALK"])

                if self.paused:
                    vector_label = "PAUSADO - tecle P para retomar"
                elif self.vector_mouse_enabled:
                    vec_border = None
                    vec_info = self._vector_mouse_step(target_center, frame_width, frame_height)
                    ref_tag = "camera" if self.aim_reference == "camera" else "screen"
                    origin = ""
                    if self.aim_reference == "camera" and self.aim_center is not None:
                        origin = f"[orig {int(self.aim_center[0])},{int(self.aim_center[1])}] "
                    if vec_info is not None:
                        vec_dx, vec_dy, vec_speed, vec_mag_norm, vec_border = vec_info
                        if not self.vec_has_target:
                            vector_label = f"Vector[{ref_tag}]: ponto vermelho nao detectado"
                        elif self.vec_in_dead_zone:
                            vector_label = f"Vector[{ref_tag}] {origin}: CENTRO (mantenha o {self._aim_hint()})"
                        elif vec_border is not None:
                            vector_label = f"Vector[{ref_tag}] {origin}: BORDA {vec_border} (cursor preso)"
                        else:
                            vector_label = f"Vector[{ref_tag}] {origin}: dx={vec_dx:+.0f} dy={vec_dy:+.0f} accel={int(vec_mag_norm * 100)}%"
                    else:
                        vector_label = f"Vector[{ref_tag}]: no input driver"

                    if input_driver is not None and self.vec_has_target:
                        vm = CONFIG["VECTOR_MOUSE"]
                        if self.aim_reference == "camera" and self.vec_ref_point is not None:
                            ref_c, ref_max = self.vec_ref_point, self.vec_ref_max
                        else:
                            ref_c = (frame_width / 2.0, frame_height / 2.0)
                            ref_max = math.hypot(frame_width / 2.0, frame_height / 2.0) or 1.0
                        dz_frame = float(vm.get("DEAD_ZONE", 0.06)) * ref_max
                        dz_center = (int(ref_c[0]), int(ref_c[1]))
                        dz_color = (0, 255, 0) if self.vec_in_dead_zone else (0, 0, 255)
                        cv2.circle(frame, dz_center, int(dz_frame), dz_color, 2)
                        cv2.circle(frame, dz_center, 3, dz_color, -1)
                        cv2.line(frame, (dz_center[0] - 8, dz_center[1]), (dz_center[0] + 8, dz_center[1]), dz_color, 1)
                        cv2.line(frame, (dz_center[0], dz_center[1] - 8), (dz_center[0], dz_center[1] + 8), dz_color, 1)
                        cv2.putText(frame, "Origem da mira", (dz_center[0] + 12, dz_center[1] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, dz_color, 2)
                        border_color = (0, 0, 255) if vec_border is not None else (0, 255, 0)
                        cv2.rectangle(frame, capture_box_start, capture_box_end, border_color, 2)
                        if vec_info is not None and not self.vec_in_dead_zone and vec_speed > 0:
                            arrow_len = (0.15 + 0.30 * vec_mag_norm) * frame_width
                            unit_x = vec_dx / vec_speed
                            unit_y = vec_dy / vec_speed
                            tip = (
                                int(dz_center[0] + unit_x * arrow_len),
                                int(dz_center[1] + unit_y * arrow_len)
                            )
                            cv2.arrowedLine(frame, dz_center, tip, (255, 0, 255), 3, tipLength=0.35)
                            cv2.putText(frame, f"Accel: {int(vec_mag_norm * 100)}%", (10, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)
                else:
                    vector_label = ""

                if not self.paused:
                    self.state_machine.sync(desired_keys, set())
                else:
                    self.state_machine.release_all()

                state_label = "IDLE"
                if crouch:
                    state_label = "CROUCH"
                elif run:
                    state_label = "RUN"
                elif walk:
                    state_label = "WALK"

                cv2.putText(frame, tracking_info, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                cv2.putText(frame, state_label, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                cv2.putText(frame, incline_label, (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                cv2.putText(frame, target_info, (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                mouse_label = "Mouse: VECTOR"
                if self.vector_mouse_enabled:
                    mouse_label += f" [{self.aim_reference.upper()}]"
                else:
                    mouse_label = "Mouse: TARGET"
                cv2.putText(frame, mouse_label, (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 255), 2)
                if vector_label:
                    cv2.putText(frame, vector_label, (10, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)
                if self.paused:
                    cv2.putText(frame, "PAUSED", (frame_width // 2 - 100, frame_height // 2), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (0, 0, 255), 5)
                    cv2.putText(frame, "tecle P para continuar", (frame_width // 2 - 140, frame_height // 2 + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                cv2.imshow("Motion Control", frame)

                key = cv2.waitKey(1) & 0xFF
                if key == ord(CONFIG["VECTOR_MOUSE"]["TOGGLE_KEY"]):
                    self.vector_mouse_enabled = not self.vector_mouse_enabled
                    self.vec_vel = [0.0, 0.0]
                    self.vec_accum = [0.0, 0.0]
                if key == ord(CONFIG["VECTOR_MOUSE"].get("AIM_KEY", "n")):
                    self.aim_reference = "screen" if self.aim_reference == "camera" else "camera"
                    self.vec_vel = [0.0, 0.0]
                    self.vec_accum = [0.0, 0.0]
                    print(f"[INFO] Mira vetorial: perspectiva {self.aim_reference.upper()}.")
                if key == ord(CONFIG["VECTOR_MOUSE"].get("CALIBRATE_KEY", "c")):
                    self.vec_vel = [0.0, 0.0]
                    self.vec_accum = [0.0, 0.0]
                    if self.aim_reference == "camera" and target_center is not None:
                        self.aim_center = (int(target_center[0]), int(target_center[1]))
                        print(f"[INFO] Centro de mira calibrado em {self.aim_center}.")
                    else:
                        self.aim_center = None
                        print("[INFO] Centro de mira resetado para o centro do frame.")
                if key == ord(CONFIG.get("PAUSE_KEY", "p")):
                    self.paused = not self.paused
                    self.state_machine.release_all()
                    self.prev_center = None
                    self.vec_vel = [0.0, 0.0]
                    self.vec_accum = [0.0, 0.0]
                    print(f"[INFO] {'PAUSADO' if self.paused else 'RETOMADO'} - simulacao de input {'desativada' if self.paused else 'ativa'}.")
                if key == 27:
                    break
        finally:
            self.state_machine.release_all()
            cap.release()
            cv2.destroyAllWindows()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Controle de movimentos via webcam com simulação de teclado/mouse.")
    parser.add_argument(
        "--disable-input",
        action="store_true",
        help="Desativa a simulação de teclado/mouse para apenas visualizar o reconhecimento de movimento."
    )
    parser.add_argument(
        "--platform",
        choices=["auto", "linux", "windows", "mac"],
        default="auto",
        help="Força o driver de input para 'linux'|'windows'|'mac' ou use 'auto' para detectar automaticamente."
    )
    args = parser.parse_args()

    input_enabled = not args.disable_input
    if not input_enabled:
        print("[INFO] Simulação de teclado/mouse desativada.")

    # Inicializa o driver de input conforme flag de plataforma
    setup_input_driver(args.platform)

    MotionController(input_enabled=input_enabled).run()
