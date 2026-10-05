"""
Face Detector with Master Face recognition (OpenCV + Python).

When the webcam starts you get 5 seconds to register your face. That face
becomes the "master face": from then on it gets a GREEN box labelled MASTER,
and every other face gets a RED box labelled NOT MASTER.

Usage:
    python face_detector.py                    -> webcam (registers a master face on first run)
    python face_detector.py --register         -> webcam, register a new master face
    python face_detector.py --image photo.jpg  -> check the faces in a photo
    python face_detector.py --video clip.mp4   -> check the faces in a video file
    python face_detector.py --download-models  -> only download the model files

Webcam / video keys:
    q or ESC -> quit
    s        -> save a snapshot to the "output" folder
    r        -> register a new master face (webcam only)
"""

import argparse
import os
import sys
import time

try:
    import cv2
    import numpy as np
except ImportError:
    print("OpenCV is not installed. Run:  pip install -r requirements.txt")
    sys.exit(1)

from common import BASE_DIR, OUTPUT_DIR, download_model, open_camera, save_image, window_closed

# Hide OpenCV's harmless internal warnings so the console stays readable
try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except AttributeError:
    pass


MASTER_DIR = os.path.join(BASE_DIR, "master")
MASTER_IMAGE = os.path.join(MASTER_DIR, "master_face.jpg")
MASTER_FEATURES = os.path.join(MASTER_DIR, "master_features.npy")

# Official OpenCV models: YuNet finds faces, SFace tells faces apart.
MODELS = {
    "detector": (
        "face_detection_yunet_2023mar.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    ),
    "recognizer": (
        "face_recognition_sface_2021dec.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    ),
}

REGISTER_SECONDS = 5
MIN_REGISTER_FRAMES = 5
DEFAULT_THRESHOLD = 0.363  # SFace's recommended cosine-similarity cut-off

GREEN = (0, 200, 0)
RED = (0, 0, 255)
YELLOW = (0, 220, 255)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


def download_models():
    """Download the model files once and return their local paths."""
    return {key: download_model(filename, url) for key, (filename, url) in MODELS.items()}


def normalize(vector):
    return vector / (np.linalg.norm(vector) + 1e-10)


class FaceEngine:
    def __init__(self, threshold):
        paths = download_models()
        self.detector = cv2.FaceDetectorYN.create(paths["detector"], "", (320, 320), 0.8, 0.3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(paths["recognizer"], "")
        self.threshold = threshold

    def detect(self, frame):
        """Return a list of faces. Each face is [x, y, w, h, 10 landmark values, score]."""
        h, w = frame.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(frame)
        return [] if faces is None else list(faces)

    def features(self, frame, face, with_mirror=False):
        """Return normalized 128-number "fingerprints" of a face."""
        aligned = self.recognizer.alignCrop(frame, face)
        crops = [aligned, cv2.flip(aligned, 1)] if with_mirror else [aligned]
        return [normalize(self.recognizer.feature(c).flatten()) for c in crops]

    def similarity(self, frame, face, master):
        return float(np.dot(self.features(frame, face)[0], master))


def load_master():
    if os.path.exists(MASTER_FEATURES):
        return np.load(MASTER_FEATURES)
    return None


def save_master(samples, face_crop):
    os.makedirs(MASTER_DIR, exist_ok=True)
    master = normalize(np.mean(samples, axis=0))
    np.save(MASTER_FEATURES, master)
    cv2.imwrite(MASTER_IMAGE, face_crop)
    print(f"Master face saved to {MASTER_IMAGE}")
    return master


def crop_face(frame, face, pad=0.25):
    x, y, w, h = face[:4]
    x1 = int(max(x - w * pad, 0))
    y1 = int(max(y - h * pad, 0))
    x2 = int(min(x + w * (1 + pad), frame.shape[1]))
    y2 = int(min(y + h * (1 + pad), frame.shape[0]))
    return frame[y1:y2, x1:x2].copy()


def draw_box(frame, face, color, label):
    x, y, w, h = [int(v) for v in face[:4]]
    cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    top = max(y - th - 10, 0)
    cv2.rectangle(frame, (x, top), (x + tw + 8, top + th + 10), color, -1)
    cv2.putText(frame, label, (x + 4, top + th + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.6, WHITE, 2)


def classify_and_draw(frame, faces, engine, master):
    """Label each face MASTER / NOT MASTER. Returns a list of (face, score or None)."""
    # Compute every score before drawing, so boxes don't leak into other face crops
    results = [(face, None if master is None else engine.similarity(frame, face, master)) for face in faces]
    for face, score in results:
        if score is None:
            draw_box(frame, face, YELLOW, "Face (no master yet)")
        elif score >= engine.threshold:
            draw_box(frame, face, GREEN, f"MASTER {score:.2f}")
        else:
            draw_box(frame, face, RED, f"NOT MASTER {score:.2f}")
    return results


def draw_banner(frame, text, color=WHITE):
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 32), BLACK, -1)
    cv2.putText(frame, text, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def draw_footer(frame, text):
    cv2.putText(frame, text, (10, frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)


def draw_center_message(frame, text, color):
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
    x = max((frame.shape[1] - tw) // 2, 0)
    y = frame.shape[0] // 2
    cv2.rectangle(frame, (x - 10, y - th - 12), (x + tw + 10, y + 12), BLACK, -1)
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)


def draw_master_thumbnail(frame, thumbnail):
    """Show the registered master face in the top-right corner."""
    if thumbnail is None:
        return
    th, tw = thumbnail.shape[:2]
    x, y = frame.shape[1] - tw - 10, 40
    if x < 0 or y + th + 18 > frame.shape[0]:
        return
    frame[y:y + th, x:x + tw] = thumbnail
    cv2.rectangle(frame, (x, y), (x + tw, y + th), GREEN, 2)
    cv2.putText(frame, "MASTER", (x, y + th + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, GREEN, 2)


def make_thumbnail(image, height=90):
    if image is None or image.size == 0:
        return None
    scale = height / image.shape[0]
    return cv2.resize(image, (max(int(image.shape[1] * scale), 1), height))


def run_image(path, engine, master):
    image = cv2.imread(path)
    if image is None:
        print(f"Could not open image: {path}")
        sys.exit(1)
    if master is None:
        print("No master face registered yet - run the webcam mode first to register one.")

    faces = engine.detect(image)
    results = classify_and_draw(image, faces, engine, master)
    print(f"Found {len(faces)} face(s) in {path}")
    for i, (_, score) in enumerate(results, 1):
        if score is not None:
            verdict = "MASTER" if score >= engine.threshold else "NOT MASTER"
            print(f"  Face {i}: {verdict} (similarity {score:.2f})")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    name, ext = os.path.splitext(os.path.basename(path))
    out_path = os.path.join(OUTPUT_DIR, f"{name}_faces{ext or '.jpg'}")
    cv2.imwrite(out_path, image)
    print(f"Result saved to {out_path}")

    # Shrink very large photos so the window fits on screen
    max_side = 1000
    h, w = image.shape[:2]
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        image = cv2.resize(image, (int(w * scale), int(h * scale)))

    cv2.imshow("Face Detector - press any key to close", image)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


def run_stream(source, engine, master, is_camera, force_register=False):
    cap = open_camera(source) if is_camera else cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"Could not open video: {source}")
        sys.exit(1)

    if not is_camera and master is None:
        print("No master face registered yet - run the webcam mode first to register one.")

    thumbnail = make_thumbnail(cv2.imread(MASTER_IMAGE)) if master is not None else None

    # Registration state
    registering = is_camera and (master is None or force_register)
    reg_start = time.time()
    reg_samples = []
    reg_frames = 0
    best_crop = (0.0, None)  # (detection score, face image)

    message, message_color, message_until = "", WHITE, 0.0
    fps = 0.0
    prev_time = time.time()
    window = "Face Detector"
    print("Running... press 'q' or ESC in the video window to quit.")

    while True:
        ok, frame = cap.read()
        if not ok:
            print("End of video." if not is_camera else "Lost connection to webcam.")
            break

        if is_camera:
            frame = cv2.flip(frame, 1)  # mirror view feels natural for webcams

        faces = engine.detect(frame)
        now = time.time()

        if registering:
            remaining = max(REGISTER_SECONDS - (now - reg_start), 0)
            if len(faces) == 1:
                face = faces[0]
                reg_samples.extend(engine.features(frame, face, with_mirror=True))
                reg_frames += 1
                if face[-1] > best_crop[0]:
                    best_crop = (face[-1], crop_face(frame, face))
                draw_box(frame, face, YELLOW, "Registering...")
                hint = "hold still, look at the camera"
            elif not faces:
                hint = "no face found - look at the camera"
            else:
                for face in faces:
                    draw_box(frame, face, RED, "Only one person!")
                hint = "only ONE person in the frame please"

            if remaining == 0:
                if reg_frames >= MIN_REGISTER_FRAMES:
                    master = save_master(reg_samples, best_crop[1])
                    thumbnail = make_thumbnail(best_crop[1])
                    registering = False
                    message, message_color, message_until = "Master face registered!", GREEN, now + 2
                else:
                    message, message_color, message_until = "Face not clear - trying again", RED, now + 2
                reg_start, reg_samples, reg_frames, best_crop = now, [], 0, (0.0, None)

            if registering:
                draw_banner(frame, f"REGISTERING MASTER FACE {remaining:.1f}s - {hint}", YELLOW)
        else:
            results = classify_and_draw(frame, faces, engine, master)
            masters = sum(1 for _, s in results if s is not None and s >= engine.threshold)
            draw_banner(frame, f"Faces: {len(faces)}   Master: {masters}   Others: {len(faces) - masters}   FPS: {fps:.0f}")
            draw_master_thumbnail(frame, thumbnail)

        if now < message_until:
            draw_center_message(frame, message, message_color)

        keys = "q: quit  s: snapshot" + ("  r: register new master" if is_camera else "")
        draw_footer(frame, keys)

        fps = 0.9 * fps + 0.1 * (1.0 / max(now - prev_time, 1e-6))
        prev_time = now

        cv2.imshow(window, frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("s"):
            save_image(frame, "snapshot")
        if key == ord("r") and is_camera:
            registering = True
            reg_start, reg_samples, reg_frames, best_crop = time.time(), [], 0, (0.0, None)
        if window_closed(window):
            break

    cap.release()
    cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description="Detect faces and recognise the master face with OpenCV.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--image", help="path to an image file")
    group.add_argument("--video", help="path to a video file")
    group.add_argument("--camera", type=int, default=0, help="webcam index (default: 0)")
    group.add_argument("--download-models", action="store_true", help="only download the model files")
    parser.add_argument("--register", action="store_true", help="register a new master face at start-up")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"match strictness, higher = stricter (default: {DEFAULT_THRESHOLD})")
    args = parser.parse_args()

    if args.download_models:
        download_models()
        print("Models are ready.")
        return

    engine = FaceEngine(args.threshold)
    master = load_master()

    if args.image:
        run_image(args.image, engine, master)
    elif args.video:
        run_stream(args.video, engine, master, is_camera=False)
    else:
        run_stream(args.camera, engine, master, is_camera=True, force_register=args.register)


if __name__ == "__main__":
    main()
