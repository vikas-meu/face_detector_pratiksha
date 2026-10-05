"""
Start menu for every app in this project.

    python main.py                    -> show the menu
    python main.py 2                  -> start app number 2 straight away
    python main.py --download-models  -> download every model file (the setup scripts do this)
"""

import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

APPS = [
    ("Face Detector", "registers your face as MASTER, everyone else is NOT MASTER", "face_detector.py"),
    ("Air Draw", "paint on the screen with your index finger", "air_draw.py"),
    ("Robot Mimic", "a 3D robot copies your body and chats with you", "robot_mimic.py"),
]


def download_all_models():
    try:
        import air_draw
        import face_detector
        import robot_mimic
    except SystemExit:
        sys.exit(1)  # the module already printed what is missing
    face_detector.download_models()
    air_draw.download_models()
    robot_mimic.download_models()
    print("All models are ready.")


def run_app(number, extra_args=()):
    name, _, script = APPS[number - 1]
    print(f"\nStarting {name}...  (close its window or press 'q' to come back here)\n")
    subprocess.call([sys.executable, os.path.join(BASE_DIR, script), *extra_args], cwd=BASE_DIR)


def show_menu():
    while True:
        print("\n" + "=" * 60)
        print("   OpenCV + MediaPipe Playground")
        print("=" * 60)
        for i, (name, description, _) in enumerate(APPS, 1):
            print(f"   {i}. {name:<14} - {description}")
        print("   q. Quit")
        print("=" * 60)
        try:
            choice = input("Choose an app (1-3) and press Enter: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if choice in ("q", "quit", "exit"):
            return
        if choice.isdigit() and 1 <= int(choice) <= len(APPS):
            run_app(int(choice))
        else:
            print("Please type 1, 2, 3 or q.")


def main():
    args = sys.argv[1:]
    if "--download-models" in args:
        download_all_models()
    elif args and args[0].isdigit() and 1 <= int(args[0]) <= len(APPS):
        run_app(int(args[0]), args[1:])
    else:
        show_menu()


if __name__ == "__main__":
    main()
