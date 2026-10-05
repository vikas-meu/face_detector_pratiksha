"""
Robot Mimic: a 3D robot copies your whole body in real time (MediaPipe pose
detection) and chats with you about what you're doing.

Stand back so the camera can see as much of your body as possible, then move!
The robot reacts when you wave, raise your hands, do a T-pose, clap, squat or lean.

Mouse / keys:
    drag on the robot -> rotate the 3D view
    a / d             -> rotate the view left / right
    v                 -> reset the view
    s                 -> save a snapshot to the "output" folder
    q or ESC          -> quit
"""

import argparse
import math
import random
import sys
import time
from collections import deque
from types import SimpleNamespace

try:
    import cv2
    import numpy as np
    import mediapipe as mp
    from mediapipe.tasks.python import vision
except ImportError:
    print("A required package is missing. Run:  pip install -r requirements.txt")
    sys.exit(1)

from common import FrameClock, download_model, open_camera, save_image, window_closed

MODEL = (
    "pose_landmarker_full.task",
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
)

VIEW_W, VIEW_H = 640, 480
VISIBLE = 0.5      # landmarks less certain than this are ignored
SMOOTHING = 0.5    # 0 = raw (jittery), closer to 1 = smoother but laggier

# Pose landmark numbers (see https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker)
NOSE, L_EAR, R_EAR = 0, 7, 8
L_SH, R_SH, L_EL, R_EL, L_WR, R_WR = 11, 12, 13, 14, 15, 16
L_INDEX, R_INDEX = 19, 20
L_HIP, R_HIP, L_KNEE, R_KNEE, L_ANK, R_ANK = 23, 24, 25, 26, 27, 28
L_FOOT, R_FOOT = 31, 32

SKELETON = [
    (L_SH, R_SH), (L_SH, L_EL), (L_EL, L_WR), (R_SH, R_EL), (R_EL, R_WR),
    (L_SH, L_HIP), (R_SH, R_HIP), (L_HIP, R_HIP), (L_HIP, L_KNEE), (L_KNEE, L_ANK),
    (R_HIP, R_KNEE), (R_KNEE, R_ANK), (L_ANK, L_FOOT), (R_ANK, R_FOOT), (L_EAR, NOSE), (NOSE, R_EAR),
]

# Robot body sizes in metres. The robot keeps these proportions whatever your size.
TORSO = 0.50
SHOULDER_HALF = 0.20
HIP_HALF = 0.11
NECK = 0.08
HEAD_HALF = (0.12, 0.13, 0.11)
UPPER_ARM, FOREARM = 0.28, 0.26
THIGH, SHIN = 0.42, 0.42
FOOT_DROP = 0.07  # ankle height above the floor

# Colours (BGR)
BODY = (205, 195, 185)
DARK = (95, 88, 82)
ACCENT = (40, 140, 255)
EYE = (255, 235, 90)
ANTENNA_ON, ANTENNA_OFF = (60, 60, 255), (40, 40, 120)

X_AXIS = np.array([1.0, 0.0, 0.0])
Y_AXIS = np.array([0.0, 1.0, 0.0])
Z_AXIS = np.array([0.0, 0.0, 1.0])
LIGHT_DIR = np.array([-0.4, 0.75, 0.55]) / np.linalg.norm([-0.4, 0.75, 0.55])


def download_models():
    return download_model(*MODEL)


def create_landmarker(running_mode=vision.RunningMode.VIDEO):
    options = vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=download_models()),
        running_mode=running_mode,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    return vision.PoseLandmarker.create_from_options(options)


def landmarks_from_result(result):
    """Turn a MediaPipe result into (33x3 points in metres, visibilities), or (None, None).

    Points use Y up and Z towards the camera, centred on the hips.
    """
    if not result.pose_world_landmarks:
        return None, None
    world = result.pose_world_landmarks[0]
    points = np.array([(lm.x, -lm.y, -lm.z) for lm in world])
    visibility = np.array([lm.visibility or 0.0 for lm in result.pose_landmarks[0]])
    return points, visibility


# ---------------------------------------------------------------- geometry

def unit(v, fallback):
    n = np.linalg.norm(v)
    return v / n if n > 1e-6 else np.asarray(fallback, dtype=float)


def orthogonal(v, axis, fallback):
    """Part of v at right angles to axis, as a unit vector."""
    return unit(v - np.dot(v, axis) * axis, fallback)


def build_robot_pose(P, vis):
    """Work out where every robot joint goes, copying the directions of your limbs."""
    def seen(*ids):
        return P is not None and all(vis[i] > VISIBLE for i in ids)

    up, side = Y_AXIS, X_AXIS
    if seen(L_SH, R_SH):
        sh_mid = (P[L_SH] + P[R_SH]) / 2
        if seen(L_HIP, R_HIP):
            up = unit(sh_mid - (P[L_HIP] + P[R_HIP]) / 2, Y_AXIS)
        side = orthogonal(P[R_SH] - P[L_SH], up, X_AXIS)
    fwd = unit(np.cross(side, up), Z_AXIS)
    facing = P[NOSE] - (P[L_SH] + P[R_SH]) / 2 if seen(NOSE, L_SH, R_SH) else Z_AXIS
    if np.dot(fwd, facing) < 0:
        fwd = -fwd

    pelvis = np.zeros(3)
    chest = pelvis + up * TORSO

    arms = []
    for sign, (sh, el, wr, idx) in ((-1, (L_SH, L_EL, L_WR, L_INDEX)), (1, (R_SH, R_EL, R_WR, R_INDEX))):
        shoulder = chest + side * sign * SHOULDER_HALF
        rest = unit(-up + side * sign * 0.25, -Y_AXIS)
        upper_dir = unit(P[el] - P[sh], rest) if seen(sh, el) else rest
        elbow = shoulder + upper_dir * UPPER_ARM
        fore_dir = unit(P[wr] - P[el], upper_dir) if seen(el, wr) else upper_dir
        wrist = elbow + fore_dir * FOREARM
        hand_dir = unit(P[idx] - P[wr], fore_dir) if seen(wr, idx) else fore_dir
        arms.append((shoulder, elbow, wrist, hand_dir))

    flat_fwd = unit(fwd * [1, 0, 1], Z_AXIS)
    legs = []
    for sign, (hp, kn, an, ft) in ((-1, (L_HIP, L_KNEE, L_ANK, L_FOOT)), (1, (R_HIP, R_KNEE, R_ANK, R_FOOT))):
        hip = pelvis + side * sign * HIP_HALF
        thigh_dir = unit(P[kn] - P[hp], -Y_AXIS) if seen(hp, kn) else -Y_AXIS
        knee = hip + thigh_dir * THIGH
        shin_dir = unit(P[an] - P[kn], thigh_dir) if seen(kn, an) else thigh_dir
        ankle = knee + shin_dir * SHIN
        foot_dir = unit((P[ft] - P[an]) * [1, 0.3, 1], flat_fwd) if seen(an, ft) else flat_fwd
        legs.append([hip, knee, ankle, foot_dir])

    head_up, head_side, head_fwd = up, side, fwd
    if seen(L_EAR, R_EAR, L_SH, R_SH):
        ear_mid = (P[L_EAR] + P[R_EAR]) / 2
        head_up = unit(ear_mid - (P[L_SH] + P[R_SH]) / 2, up)
        head_side = orthogonal(P[R_EAR] - P[L_EAR], head_up, side)
        head_fwd = unit(np.cross(head_side, head_up), fwd)
        facing = P[NOSE] - ear_mid if seen(NOSE) else fwd
        if np.dot(head_fwd, facing) < 0:
            head_fwd = -head_fwd
    head_center = chest + head_up * (NECK + HEAD_HALF[1])

    # Stand the robot on the floor: lift everything so the lowest foot touches y = 0
    lift = Y_AXIS * (FOOT_DROP - min(leg[2][1] for leg in legs))
    arms = [(s + lift, e + lift, w + lift, h) for s, e, w, h in arms]
    legs = [(h + lift, k + lift, a + lift, f) for h, k, a, f in legs]

    return SimpleNamespace(
        pelvis=pelvis + lift, chest=chest + lift, up=up, side=side, fwd=fwd,
        head_center=head_center + lift, head_up=head_up, head_side=head_side, head_fwd=head_fwd,
        arms=arms, legs=legs,
    )


# ---------------------------------------------------------------- 3D renderer

def scale_color(color, k):
    return tuple(int(min(255, max(0, c * k))) for c in color)


class Renderer:
    """A tiny 3D engine: shaded polygons drawn back-to-front with OpenCV."""

    def __init__(self, width, height):
        self.w, self.h = width, height
        self.focal = height * 1.45
        self.distance = 3.9
        self.target = np.array([0.0, 0.95, 0.0])
        self.reset_view()
        top, bottom = np.array([70, 45, 30]), np.array([25, 18, 15])
        ramp = np.linspace(0, 1, height)[:, None, None]
        self.background = (top * (1 - ramp) + bottom * ramp).astype(np.uint8).repeat(width, axis=1)

    def reset_view(self):
        self.yaw, self.pitch = 0.0, 0.12

    def rotate(self, d_yaw, d_pitch=0.0):
        self.yaw += d_yaw
        self.pitch = float(np.clip(self.pitch + d_pitch, -0.05, 1.2))

    def begin(self):
        cy, sy, cp, sp = math.cos(self.yaw), math.sin(self.yaw), math.cos(self.pitch), math.sin(self.pitch)
        ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
        self.rot = rx @ ry
        self.cam_pos = self.rot.T @ np.array([0, 0, self.distance]) + self.target
        self.items = []

    def project(self, points):
        pc = (np.atleast_2d(points) - self.target) @ self.rot.T
        z = np.maximum(self.distance - pc[:, 2], 1e-3)
        uv = np.stack([self.w / 2 + self.focal * pc[:, 0] / z, self.h / 2 - self.focal * pc[:, 1] / z], axis=1)
        return uv, z

    def depth(self, point):
        return float(self.project(point)[1][0])

    def polygon(self, points, normal, color, depth=None, shade=True):
        points = np.asarray(points, dtype=float)
        if np.dot(normal, self.cam_pos - points.mean(axis=0)) <= 0:
            return  # facing away from the camera
        uv, z = self.project(points)
        if shade:
            color = scale_color(color, 0.4 + 0.6 * max(0.0, float(np.dot(normal, LIGHT_DIR))))
        self.items.append((z.mean() if depth is None else depth, "poly", uv, color))

    def sphere(self, center, radius, color):
        uv, z = self.project(center)
        self.items.append((z[0], "sphere", uv[0], self.focal * radius / z[0], color))

    def box(self, center, axes, half, color):
        for i in range(3):
            j, k = (i + 1) % 3, (i + 2) % 3
            for s in (-1, 1):
                c = center + axes[i] * half[i] * s
                a, b = axes[j] * half[j], axes[k] * half[k]
                self.polygon([c + a + b, c + a - b, c - a - b, c - a + b], axes[i] * s, color)

    def limb(self, start, end, radius, color, sides=8):
        axis = unit(end - start, Y_AXIS)
        u = orthogonal(X_AXIS if abs(axis[0]) < 0.9 else Y_AXIS, axis, Z_AXIS)
        v = np.cross(axis, u)
        angles = np.linspace(0, 2 * math.pi, sides, endpoint=False)
        ring = [radius * (math.cos(t) * u + math.sin(t) * v) for t in angles]
        for i in range(sides):
            o1, o2 = ring[i], ring[(i + 1) % sides]
            self.polygon([start + o1, start + o2, end + o2, end + o1], unit(o1 + o2, u), color)
        self.polygon([end + o for o in ring], axis, color)
        self.polygon([start + o for o in ring], -axis, color)

    def decal(self, center, x_axis, y_axis, normal, half_w, half_h, color, parent):
        """A flat sticker on a face (eyes, mouth...), always drawn just after that face."""
        pts = [center + x_axis * half_w + y_axis * half_h, center + x_axis * half_w - y_axis * half_h,
               center - x_axis * half_w - y_axis * half_h, center - x_axis * half_w + y_axis * half_h]
        self.polygon(pts, normal, color, depth=self.depth(parent) - 1e-4, shade=False)

    def draw(self, shadow_at=None):
        img = self.background.copy()

        floor = np.array([[-2, 0, -2], [2, 0, -2], [2, 0, 2], [-2, 0, 2]], dtype=float)
        uv, _ = self.project(floor)
        cv2.fillPoly(img, [uv.astype(np.int32)], (48, 40, 36), cv2.LINE_AA)
        for t in np.arange(-2, 2.01, 0.25):
            for a, b in (([t, 0, -2], [t, 0, 2]), ([-2, 0, t], [2, 0, t])):
                uv, _ = self.project(np.array([a, b], dtype=float))
                cv2.line(img, tuple(uv[0].astype(int)), tuple(uv[1].astype(int)), (75, 65, 58), 1, cv2.LINE_AA)

        if shadow_at is not None:
            angles = np.linspace(0, 2 * math.pi, 32, endpoint=False)
            ring = np.stack([shadow_at[0] + 0.38 * np.cos(angles), np.full(32, 0.002),
                             shadow_at[2] + 0.28 * np.sin(angles)], axis=1)
            uv, _ = self.project(ring)
            cv2.fillPoly(img, [uv.astype(np.int32)], (28, 23, 20), cv2.LINE_AA)

        # Painter's algorithm: far things first, near things on top
        for item in sorted(self.items, key=lambda it: it[0], reverse=True):
            if item[1] == "poly":
                pts = np.round(item[2] * 16).astype(np.int32)
                cv2.fillPoly(img, [pts], item[3], cv2.LINE_AA, shift=4)
                cv2.polylines(img, [pts], True, scale_color(item[3], 0.7), 1, cv2.LINE_AA, shift=4)
            else:
                _, _, (u, v), r, color = item
                c, r16 = (int(u * 16), int(v * 16)), max(int(r * 16), 16)
                cv2.circle(img, c, r16, scale_color(color, 0.7), -1, cv2.LINE_AA, shift=4)
                cv2.circle(img, (c[0] - r16 // 4, c[1] - r16 // 4), r16 * 11 // 20, color, -1, cv2.LINE_AA, shift=4)
                cv2.circle(img, c, r16, scale_color(color, 0.45), 1, cv2.LINE_AA, shift=4)
        return img


def draw_robot(r, pose, now, talking):
    side, up, fwd = pose.side, pose.up, pose.fwd

    # Body
    r.box(pose.pelvis + up * 0.03, (side, up, fwd), (HIP_HALF + 0.06, 0.07, 0.10), DARK)
    bottom, top = 0.10, TORSO + 0.03
    torso_c = pose.pelvis + up * (bottom + top) / 2
    torso_half = (SHOULDER_HALF - 0.03, (top - bottom) / 2, 0.11)
    r.box(torso_c, (side, up, fwd), torso_half, BODY)
    front = torso_c + fwd * (torso_half[2] + 0.002)
    glow = 0.75 + 0.25 * math.sin(now * 3)
    r.decal(front + up * 0.08, side, up, fwd, 0.08, 0.05, scale_color(ACCENT, glow), front)
    for s in (-1, 0, 1):
        r.decal(front - up * 0.06 + side * s * 0.05, side, up, fwd, 0.015, 0.015, EYE if s == 0 else DARK, front)

    # Head
    hc, hs, hu, hf = pose.head_center, pose.head_side, pose.head_up, pose.head_fwd
    r.limb(pose.chest, hc - hu * HEAD_HALF[1] * 0.8, 0.045, DARK)
    r.box(hc, (hs, hu, hf), HEAD_HALF, BODY)
    face = hc + hf * (HEAD_HALF[2] + 0.002)
    eye_h = 0.004 if now % 4 < 0.15 else 0.022  # blink every 4 seconds
    for s in (-1, 1):
        r.decal(face + hs * s * 0.05 + hu * 0.03, hs, hu, hf, 0.028, eye_h, EYE, face)
    mouth_h = 0.008 + (0.02 * abs(math.sin(now * 14)) if talking else 0.0)
    r.decal(face - hu * 0.065, hs, hu, hf, 0.05, mouth_h, DARK, face)
    for s in (-1, 1):
        r.limb(hc + hs * s * HEAD_HALF[0], hc + hs * s * (HEAD_HALF[0] + 0.03), 0.045, ACCENT)
    head_top = hc + hu * HEAD_HALF[1]
    r.limb(head_top, head_top + hu * 0.12, 0.01, DARK)
    r.sphere(head_top + hu * 0.12, 0.028, ANTENNA_ON if int(now * 2) % 2 else ANTENNA_OFF)

    # Arms
    for shoulder, elbow, wrist, hand_dir in pose.arms:
        r.sphere(shoulder, 0.07, ACCENT)
        r.limb(shoulder, elbow, 0.045, BODY)
        r.sphere(elbow, 0.05, DARK)
        r.limb(elbow, wrist, 0.04, BODY)
        r.sphere(wrist, 0.035, DARK)
        hy = hand_dir
        hx = orthogonal(side, hy, orthogonal(X_AXIS, hy, Z_AXIS))
        r.box(wrist + hy * 0.065, (hx, hy, np.cross(hx, hy)), (0.045, 0.06, 0.025), ACCENT)

    # Legs
    for hip, knee, ankle, foot_dir in pose.legs:
        r.sphere(hip, 0.075, DARK)
        r.limb(hip, knee, 0.065, BODY)
        r.sphere(knee, 0.06, ACCENT)
        r.limb(knee, ankle, 0.055, BODY)
        r.sphere(ankle, 0.045, DARK)
        fx = unit(np.cross(Y_AXIS, foot_dir), X_AXIS)
        fy = np.cross(foot_dir, fx)
        r.box(ankle + foot_dir * 0.05 - Y_AXIS * 0.035, (fx, fy, foot_dir), (0.055, 0.035, 0.11), DARK)


# ---------------------------------------------------------------- chat bot

LINES = {
    "hello": ["Hi! I'm ROBO. Move and I'll copy you!", "Hello, human! Let's dance."],
    "away": ["Hello? Where did you go?", "Step in front of the camera so I can see you!"],
    "wave": ["Hi there! *waves back*", "Hello to you too!", "Nice wave! Beep boop!"],
    "hands_up": ["Hands up! Woohoo!", "Yay! Celebration time!", "Did we just win?!"],
    "t_pose": ["T-pose! Very robot-like.", "Perfect T-pose. Ready for take-off!"],
    "clap": ["Clap clap! Thank you, thank you.", "Are you clapping for me?"],
    "squat": ["Squat time! Feel the burn!", "Nice squat! My knees are hydraulic."],
    "one_up": ["Yes? You have a question?", "Pick me! Pick me!"],
    "lean": ["Whoa, careful, don't fall over!", "Leaning... leaning... still standing!"],
    "idle": ["Try waving at me!", "Raise both hands!", "Can you do a T-pose?", "Try a squat!",
             "Clap your hands!", "I copy every move you make."],
}
TYPING_SPEED = 40  # characters per second


def count_swings(history, min_move=0.04):
    """How many times a hand changed direction left/right (for detecting a wave)."""
    swings, direction, extreme = 0, 0, history[0][1] if history else 0.0
    for _, x in history:
        if direction <= 0 and x > extreme + min_move:
            swings += direction < 0
            direction, extreme = 1, x
        elif direction >= 0 and x < extreme - min_move:
            swings += direction > 0
            direction, extreme = -1, x
        elif (direction > 0 and x > extreme) or (direction < 0 and x < extreme):
            extreme = x
    return swings


def knee_angle(P, hip, knee, ankle):
    a, b = P[hip] - P[knee], P[ankle] - P[knee]
    cos = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)
    return math.degrees(math.acos(np.clip(cos, -1, 1)))


class ChatBot:
    def __init__(self):
        self.message = ""
        self.message_time = -100.0
        self.busy_until = 0.0
        self.last_topic = None
        self.last_seen = time.time()
        self.log = deque(maxlen=3)
        self.wrist_history = {L_WR: deque(), R_WR: deque()}

    def say(self, topic, now):
        if now < self.busy_until:
            return
        if topic == self.last_topic and topic != "idle" and now - self.message_time < 6:
            return
        options = [line for line in LINES[topic] if line != self.message] or LINES[topic]
        self.message = random.choice(options)
        self.message_time = now
        self.busy_until = now + 3.0
        self.last_topic = topic
        self.log.append(self.message)

    def talking(self, now):
        return now - self.message_time < len(self.message) / TYPING_SPEED + 0.3

    def visible_text(self, now):
        if now - self.message_time > 6:
            return ""
        return self.message[: int((now - self.message_time) * TYPING_SPEED)]

    def update(self, P, vis, now):
        if P is None:
            if now - self.last_seen > 2.5 and self.last_topic != "away":
                self.say("away", now)
            return
        self.last_seen = now
        if self.last_topic in (None, "away"):
            self.say("hello", now)
            return
        topic = self.detect(P, vis, now)
        if topic:
            self.say(topic, now)
        elif now - self.message_time > 9:
            self.say("idle", now)

    def detect(self, P, vis, now):
        def seen(*ids):
            return all(vis[i] > VISIBLE for i in ids)

        waving = False
        for wr, sh in ((L_WR, L_SH), (R_WR, R_SH)):
            history = self.wrist_history[wr]
            if seen(wr, sh) and P[wr][1] > P[sh][1]:
                history.append((now, P[wr][0]))
            else:
                history.clear()
            while history and now - history[0][0] > 1.5:
                history.popleft()
            waving = waving or count_swings(history) >= 2

        hands_up = [seen(wr, NOSE) and P[wr][1] > P[NOSE][1] + 0.05 for wr in (L_WR, R_WR)]
        t_pose = all(seen(sh, wr) and abs(P[wr][1] - P[sh][1]) < 0.12 and abs(P[wr][0] - P[sh][0]) > 0.4
                     for sh, wr in ((L_SH, L_WR), (R_SH, R_WR)))
        clap = (seen(L_WR, R_WR, NOSE, L_HIP) and np.linalg.norm(P[L_WR] - P[R_WR]) < 0.15
                and P[L_HIP][1] < P[L_WR][1] < P[NOSE][1])
        squat = (seen(L_HIP, L_KNEE, L_ANK, R_HIP, R_KNEE, R_ANK)
                 and knee_angle(P, L_HIP, L_KNEE, L_ANK) < 115 and knee_angle(P, R_HIP, R_KNEE, R_ANK) < 115)
        lean = False
        if seen(L_SH, R_SH, L_HIP, R_HIP):
            spine = (P[L_SH] + P[R_SH]) / 2 - (P[L_HIP] + P[R_HIP]) / 2
            lean = math.atan2(abs(spine[0]), spine[1]) > math.radians(20)

        if waving:
            return "wave"
        if all(hands_up):
            return "hands_up"
        if t_pose:
            return "t_pose"
        if clap:
            return "clap"
        if squat:
            return "squat"
        if any(hands_up):
            return "one_up"
        if lean:
            return "lean"
        return None


def wrap_text(text, max_width, scale=0.55, thickness=1):
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if cv2.getTextSize(trial, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)[0][0] <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_speech_bubble(img, text, anchor):
    if not text:
        return
    scale, line_h, pad = 0.55, 22, 10
    lines = wrap_text(text, 230, scale)
    width = max(cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)[0][0] for line in lines) + pad * 2
    height = line_h * len(lines) + pad * 2 - 6
    ax, ay = int(anchor[0]), int(anchor[1])
    x = ax + 45 if ax + 45 + width < img.shape[1] - 5 else ax - 45 - width
    x = int(np.clip(x, 5, img.shape[1] - width - 5))
    y = int(np.clip(ay - height - 30, 40, img.shape[0] - height - 5))

    tail_x = x + 15 if x > ax else x + width - 15
    cv2.fillPoly(img, [np.array([[tail_x - 8, y + height - 1], [tail_x + 8, y + height - 1], [ax, ay - 10]])],
                 (255, 255, 255), cv2.LINE_AA)
    cv2.rectangle(img, (x, y), (x + width, y + height), (255, 255, 255), -1)
    cv2.rectangle(img, (x, y), (x + width, y + height), (180, 180, 180), 1)
    for i, line in enumerate(lines):
        cv2.putText(img, line, (x + pad, y + pad + 12 + i * line_h), cv2.FONT_HERSHEY_SIMPLEX, scale,
                    (40, 40, 40), 1, cv2.LINE_AA)


def draw_chat_log(img, log):
    for i, line in enumerate(list(log)[:-1][::-1]):
        y = img.shape[0] - 40 - i * 20
        cv2.putText(img, f"ROBO: {line}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1, cv2.LINE_AA)


def draw_skeleton(frame, result):
    if not result.pose_landmarks:
        return
    h, w = frame.shape[:2]
    lms = result.pose_landmarks[0]
    pts = {i: (int(lm.x * w), int(lm.y * h)) for i, lm in enumerate(lms) if (lm.visibility or 0) > VISIBLE}
    for a, b in SKELETON:
        if a in pts and b in pts:
            cv2.line(frame, pts[a], pts[b], (0, 255, 120), 3, cv2.LINE_AA)
    for i in {i for pair in SKELETON for i in pair}:
        if i in pts:
            cv2.circle(frame, pts[i], 5, (0, 140, 255), -1, cv2.LINE_AA)


def render_robot_view(renderer, P, vis, bot, now):
    pose = build_robot_pose(P, vis)
    renderer.begin()
    draw_robot(renderer, pose, now, bot.talking(now))
    view = renderer.draw(shadow_at=pose.pelvis)
    head_uv, _ = renderer.project(pose.head_center + pose.head_up * HEAD_HALF[1])
    draw_speech_bubble(view, bot.visible_text(now), head_uv[0])
    draw_chat_log(view, bot.log)
    return view


def main():
    parser = argparse.ArgumentParser(description="A 3D robot that copies your movements.")
    parser.add_argument("--camera", type=int, default=0, help="webcam index (default: 0)")
    parser.add_argument("--download-models", action="store_true", help="only download the model file")
    args = parser.parse_args()

    if args.download_models:
        download_models()
        print("Models are ready.")
        return

    landmarker = create_landmarker()
    cap = open_camera(args.camera, 640, 480)
    clock = FrameClock()
    renderer = Renderer(VIEW_W, VIEW_H)
    bot = ChatBot()
    smooth = None

    window = "Robot Mimic"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, VIEW_W * 2, VIEW_H)
    drag = {"pos": None}

    def on_mouse(event, x, y, flags, _):
        if event == cv2.EVENT_LBUTTONDOWN and x >= VIEW_W:
            drag["pos"] = (x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            drag["pos"] = None
        elif event == cv2.EVENT_MOUSEMOVE and drag["pos"] and flags & cv2.EVENT_FLAG_LBUTTON:
            renderer.rotate((x - drag["pos"][0]) * 0.01, (y - drag["pos"][1]) * 0.005)
            drag["pos"] = (x, y)

    cv2.setMouseCallback(window, on_mouse)
    print("Running... stand back so the camera sees your body. Press 'q' or ESC to quit.")

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Lost connection to webcam.")
            break
        frame = cv2.flip(frame, 1)  # mirror, so the robot moves like your reflection
        now = time.time()

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), clock.next())
        P, vis = landmarks_from_result(result)
        if P is None:
            smooth = None
        else:
            smooth = P if smooth is None else SMOOTHING * smooth + (1 - SMOOTHING) * P

        bot.update(smooth, vis, now)
        view = render_robot_view(renderer, smooth, vis, bot, now)

        draw_skeleton(frame, result)
        cam = cv2.resize(frame, (VIEW_W, VIEW_H))
        status = "Tracking you" if P is not None else "No person found - step back into view"
        cv2.putText(cam, status, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(view, "ROBO  (drag to rotate)", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(view, "a/d: rotate   v: reset view   s: snapshot   q: quit", (10, VIEW_H - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1, cv2.LINE_AA)
        combined = np.hstack([cam, view])

        cv2.imshow(window, combined)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("a"):
            renderer.rotate(-0.1)
        if key == ord("d"):
            renderer.rotate(0.1)
        if key == ord("v"):
            renderer.reset_view()
        if key == ord("s"):
            save_image(combined, "robot")
        if window_closed(window):
            break

    cap.release()
    landmarker.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
