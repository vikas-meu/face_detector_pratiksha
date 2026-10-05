"""
Air Draw: paint on the screen with your finger, using MediaPipe hand tracking.

Hand gestures:
    Index finger up              -> DRAW
    Index + middle finger up     -> MOVE without drawing, and pick tools from the top bar
    Fist / hand out of view      -> pause

Keys:
    q or ESC -> quit
    c        -> clear the drawing
    s        -> save the drawing to the "output" folder
    + / -    -> bigger / smaller brush
"""

import argparse
import sys

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
    "hand_landmarker.task",
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task",
)

TOOLBAR_HEIGHT = 80
SMOOTHING = 0.5  # 0 = no smoothing, closer to 1 = smoother but laggier
MIN_BRUSH, MAX_BRUSH = 4, 60

# Hand landmark numbers (see https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker)
WRIST = 0
THUMB_IP, THUMB_TIP = 3, 4
INDEX_MCP = 5
FINGERS = {  # name: (middle joint, tip)
    "index": (6, 8),
    "middle": (10, 12),
    "ring": (14, 16),
    "pinky": (18, 20),
}
PINKY_MCP = 17

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
]

# Toolbar buttons: (label, colour in BGR or None for actions)
BUTTONS = [
    ("Red", (60, 60, 230)),
    ("Orange", (40, 150, 255)),
    ("Yellow", (40, 230, 255)),
    ("Green", (80, 200, 60)),
    ("Blue", (230, 140, 40)),
    ("Purple", (200, 70, 160)),
    ("White", (245, 245, 245)),
    ("Eraser", None),
    ("Size -", None),
    ("Size +", None),
    ("Clear", None),
    ("Save", None),
]


def download_models():
    return download_model(*MODEL)


def create_landmarker():
    options = vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=download_models()),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.6,
        min_hand_presence_confidence=0.6,
        min_tracking_confidence=0.5,
    )
    return vision.HandLandmarker.create_from_options(options)


def fingers_up(points):
    """Return which fingers are stretched out. Works for any hand rotation."""
    def dist(a, b):
        return np.hypot(*(points[a] - points[b]))

    up = {name: dist(WRIST, tip) > dist(WRIST, pip) * 1.15 for name, (pip, tip) in FINGERS.items()}
    up["thumb"] = dist(THUMB_TIP, PINKY_MCP) > dist(THUMB_IP, PINKY_MCP) * 1.1
    return up


def button_rects(width):
    w = width / len(BUTTONS)
    return [(int(i * w), 0, int((i + 1) * w), TOOLBAR_HEIGHT) for i in range(len(BUTTONS))]


def draw_toolbar(frame, rects, color, eraser, brush, hovered):
    cv2.rectangle(frame, (0, 0), (frame.shape[1], TOOLBAR_HEIGHT), (40, 40, 40), -1)
    for i, ((label, button_color), (x1, y1, x2, y2)) in enumerate(zip(BUTTONS, rects)):
        pad = 6
        fill = button_color if button_color is not None else (90, 90, 90)
        cv2.rectangle(frame, (x1 + pad, y1 + pad), (x2 - pad, y2 - pad), fill, -1)

        selected = (label == "Eraser" and eraser) or (button_color is not None and not eraser and button_color == color)
        if selected:
            cv2.rectangle(frame, (x1 + 2, y1 + 2), (x2 - 2, y2 - 2), (255, 255, 255), 3)
        if i == hovered:
            cv2.rectangle(frame, (x1 + 2, y1 + 2), (x2 - 2, y2 - 2), (0, 255, 255), 2)

        text_color = (30, 30, 30) if button_color is not None and sum(button_color) > 450 else (255, 255, 255)
        scale = 0.45 if x2 - x1 < 110 else 0.55
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        cv2.putText(frame, label, ((x1 + x2 - tw) // 2, (y1 + y2 + th) // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, text_color, 1, cv2.LINE_AA)

    info = f"Brush: {brush}px"
    cv2.putText(frame, info, (10, TOOLBAR_HEIGHT + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)


def draw_hand(frame, points):
    for a, b in HAND_CONNECTIONS:
        cv2.line(frame, tuple(points[a].astype(int)), tuple(points[b].astype(int)), (200, 200, 200), 1, cv2.LINE_AA)
    for p in points:
        cv2.circle(frame, tuple(p.astype(int)), 3, (0, 180, 255), -1)


def overlay_canvas(frame, canvas):
    """Paint the drawing on top of the camera picture."""
    mask = canvas.any(axis=2)
    frame[mask] = canvas[mask]


def main():
    parser = argparse.ArgumentParser(description="Draw in the air with your finger.")
    parser.add_argument("--camera", type=int, default=0, help="webcam index (default: 0)")
    parser.add_argument("--download-models", action="store_true", help="only download the model file")
    args = parser.parse_args()

    if args.download_models:
        download_models()
        print("Models are ready.")
        return

    landmarker = create_landmarker()
    cap = open_camera(args.camera, 1280, 720)
    clock = FrameClock()

    canvas = None
    color = BUTTONS[0][1]
    eraser = False
    brush = 10
    smooth_tip = None
    prev_point = None
    last_button = None
    window = "Air Draw"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    print("Running... raise your index finger to draw. Press 'q' or ESC to quit.")

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Lost connection to webcam.")
            break
        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        if canvas is None or canvas.shape[:2] != (h, w):
            canvas = np.zeros_like(frame)
        rects = button_rects(w)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), clock.next())

        mode = "No hand - show your hand to the camera"
        hovered = None
        cursor = None
        if result.hand_landmarks:
            points = np.array([(lm.x * w, lm.y * h) for lm in result.hand_landmarks[0]])
            up = fingers_up(points)
            tip = points[FINGERS["index"][1]]
            smooth_tip = tip if smooth_tip is None else SMOOTHING * smooth_tip + (1 - SMOOTHING) * tip
            cursor = tuple(smooth_tip.astype(int))
            draw_hand(frame, points)

            drawing = up["index"] and not up["middle"] and not up["ring"] and not up["pinky"]
            selecting = up["index"] and up["middle"] and not up["ring"] and not up["pinky"]

            if selecting:
                mode = "MOVE / SELECT"
                prev_point = None
                if cursor[1] < TOOLBAR_HEIGHT:
                    hovered = next(i for i, (x1, _, x2, _) in enumerate(rects) if x1 <= cursor[0] < x2 or i == len(rects) - 1)
                    # Trigger a button only when the finger first enters it
                    if hovered != last_button:
                        label, button_color = BUTTONS[hovered]
                        if button_color is not None:
                            color, eraser = button_color, False
                        elif label == "Eraser":
                            eraser = True
                        elif label == "Size -":
                            brush = max(MIN_BRUSH, brush - 4)
                        elif label == "Size +":
                            brush = min(MAX_BRUSH, brush + 4)
                        elif label == "Clear":
                            canvas[:] = 0
                        elif label == "Save":
                            save_image(canvas, "drawing")
                last_button = hovered
            elif drawing:
                mode = "ERASING" if eraser else "DRAWING"
                last_button = None
                if prev_point is None:
                    # New stroke: start exactly at the fingertip, not where the smoothed cursor lags behind
                    smooth_tip = tip
                    cursor = tuple(tip.astype(int))
                if cursor[1] > TOOLBAR_HEIGHT:
                    if prev_point is not None:
                        if eraser:
                            cv2.line(canvas, prev_point, cursor, (0, 0, 0), brush * 3)
                        else:
                            cv2.line(canvas, prev_point, cursor, color, brush, cv2.LINE_AA)
                    prev_point = cursor
                else:
                    prev_point = None
            else:
                mode = "PAUSED - raise your index finger to draw"
                prev_point = None
                last_button = None
        else:
            smooth_tip = None
            prev_point = None
            last_button = None

        overlay_canvas(frame, canvas)
        draw_toolbar(frame, rects, color, eraser, brush, hovered)

        if cursor is not None:
            if eraser:
                cv2.circle(frame, cursor, brush * 3 // 2, (255, 255, 255), 2)
            else:
                cv2.circle(frame, cursor, max(brush // 2, 4), color, -1)
                cv2.circle(frame, cursor, max(brush // 2, 4) + 2, (255, 255, 255), 1)

        cv2.putText(frame, mode, (10, h - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        cv2.putText(frame, "1 finger: draw   2 fingers: move/select   c: clear   s: save   +/-: brush   q: quit",
                    (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

        cv2.imshow(window, frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("c"):
            canvas[:] = 0
        if key == ord("s"):
            save_image(canvas, "drawing")
        if key in (ord("+"), ord("=")):
            brush = min(MAX_BRUSH, brush + 2)
        if key in (ord("-"), ord("_")):
            brush = max(MIN_BRUSH, brush - 2)
        if window_closed(window):
            break

    cap.release()
    landmarker.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
