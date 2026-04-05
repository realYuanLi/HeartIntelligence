"""
Transform exercise images from photos to styled stick figures using MediaPipe pose detection.
Preserves motion correctness while removing copyrightable elements.
"""

import cv2
import mediapipe as mp
import numpy as np
import os
import sys
from pathlib import Path

from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    PoseLandmarker,
    PoseLandmarkerOptions,
    PoseLandmark,
)

# Path to the pose landmarker model
MODEL_PATH = str(Path(__file__).parent / 'pose_landmarker_heavy.task')

# Color palette (BGR) - body-part based coloring
COLORS = {
    'head':      (80, 80, 80),       # dark gray
    'torso':     (180, 100, 50),     # blue-ish
    'left_arm':  (50, 160, 80),      # green
    'right_arm': (50, 160, 80),      # green
    'left_leg':  (60, 100, 200),     # orange-ish
    'right_leg': (60, 100, 200),     # orange-ish
}

BG_COLOR = (250, 250, 250)     # off-white background
JOINT_COLOR = (60, 60, 60)     # dark gray joints
OUTLINE_COLOR = (40, 40, 40)   # outline for body

# Landmark indices (from PoseLandmark enum)
NOSE = PoseLandmark.NOSE
LEFT_EYE_INNER = PoseLandmark.LEFT_EYE_INNER
LEFT_EAR = PoseLandmark.LEFT_EAR
RIGHT_EAR = PoseLandmark.RIGHT_EAR
LEFT_SHOULDER = PoseLandmark.LEFT_SHOULDER
RIGHT_SHOULDER = PoseLandmark.RIGHT_SHOULDER
LEFT_ELBOW = PoseLandmark.LEFT_ELBOW
RIGHT_ELBOW = PoseLandmark.RIGHT_ELBOW
LEFT_WRIST = PoseLandmark.LEFT_WRIST
RIGHT_WRIST = PoseLandmark.RIGHT_WRIST
LEFT_HIP = PoseLandmark.LEFT_HIP
RIGHT_HIP = PoseLandmark.RIGHT_HIP
LEFT_KNEE = PoseLandmark.LEFT_KNEE
RIGHT_KNEE = PoseLandmark.RIGHT_KNEE
LEFT_ANKLE = PoseLandmark.LEFT_ANKLE
RIGHT_ANKLE = PoseLandmark.RIGHT_ANKLE
LEFT_HEEL = PoseLandmark.LEFT_HEEL
RIGHT_HEEL = PoseLandmark.RIGHT_HEEL
LEFT_FOOT_INDEX = PoseLandmark.LEFT_FOOT_INDEX
RIGHT_FOOT_INDEX = PoseLandmark.RIGHT_FOOT_INDEX
LEFT_PINKY = PoseLandmark.LEFT_PINKY
RIGHT_PINKY = PoseLandmark.RIGHT_PINKY
LEFT_INDEX = PoseLandmark.LEFT_INDEX
RIGHT_INDEX = PoseLandmark.RIGHT_INDEX
LEFT_THUMB = PoseLandmark.LEFT_THUMB
RIGHT_THUMB = PoseLandmark.RIGHT_THUMB

# Define skeleton connections grouped by body part
SKELETON = {
    'torso': [
        (LEFT_SHOULDER, RIGHT_SHOULDER),
        (LEFT_SHOULDER, LEFT_HIP),
        (RIGHT_SHOULDER, RIGHT_HIP),
        (LEFT_HIP, RIGHT_HIP),
    ],
    'left_arm': [
        (LEFT_SHOULDER, LEFT_ELBOW),
        (LEFT_ELBOW, LEFT_WRIST),
    ],
    'right_arm': [
        (RIGHT_SHOULDER, RIGHT_ELBOW),
        (RIGHT_ELBOW, RIGHT_WRIST),
    ],
    'left_leg': [
        (LEFT_HIP, LEFT_KNEE),
        (LEFT_KNEE, LEFT_ANKLE),
    ],
    'right_leg': [
        (RIGHT_HIP, RIGHT_KNEE),
        (RIGHT_KNEE, RIGHT_ANKLE),
    ],
}

# Hand/foot detail connections
EXTREMITIES = {
    'left_arm': [
        (LEFT_WRIST, LEFT_PINKY),
        (LEFT_WRIST, LEFT_INDEX),
        (LEFT_WRIST, LEFT_THUMB),
    ],
    'right_arm': [
        (RIGHT_WRIST, RIGHT_PINKY),
        (RIGHT_WRIST, RIGHT_INDEX),
        (RIGHT_WRIST, RIGHT_THUMB),
    ],
    'left_leg': [
        (LEFT_ANKLE, LEFT_HEEL),
        (LEFT_HEEL, LEFT_FOOT_INDEX),
        (LEFT_ANKLE, LEFT_FOOT_INDEX),
    ],
    'right_leg': [
        (RIGHT_ANKLE, RIGHT_HEEL),
        (RIGHT_HEEL, RIGHT_FOOT_INDEX),
        (RIGHT_ANKLE, RIGHT_FOOT_INDEX),
    ],
}


def get_landmark_point(landmark, w, h):
    """Convert normalized landmark to pixel coordinates."""
    return int(landmark.x * w), int(landmark.y * h)


def estimate_head_center_and_radius(landmarks, w, h):
    """Estimate head position and size from face landmarks."""
    nose = landmarks[NOSE]
    left_ear = landmarks[LEFT_EAR]
    right_ear = landmarks[RIGHT_EAR]
    left_shoulder = landmarks[LEFT_SHOULDER]
    right_shoulder = landmarks[RIGHT_SHOULDER]

    nose_pt = get_landmark_point(nose, w, h)

    ear_dist = np.sqrt(
        ((left_ear.x - right_ear.x) * w) ** 2 +
        ((left_ear.y - right_ear.y) * h) ** 2
    )
    shoulder_dist = np.sqrt(
        ((left_shoulder.x - right_shoulder.x) * w) ** 2 +
        ((left_shoulder.y - right_shoulder.y) * h) ** 2
    )

    radius = max(int(ear_dist * 0.55), int(shoulder_dist * 0.22), 15)
    center = (nose_pt[0], nose_pt[1] - int(radius * 0.3))

    return center, radius


def render_stick_figure(image_path, output_path, pose_detector):
    """Detect pose and render a styled stick figure."""
    img = cv2.imread(image_path)
    if img is None:
        return False

    h, w = img.shape[:2]

    # MediaPipe new API uses mp.Image
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB))

    results = pose_detector.detect(mp_image)
    if not results.pose_landmarks or len(results.pose_landmarks) == 0:
        return False

    landmarks = results.pose_landmarks[0]  # first person detected

    # Check minimum landmark visibility
    key_indices = [LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP]
    visible_count = sum(1 for idx in key_indices if landmarks[idx].visibility > 0.3)
    if visible_count < 3:
        return False

    # Create output canvas
    canvas = np.full((h, w, 3), BG_COLOR, dtype=np.uint8)

    # Scale line thickness based on image size
    base_thickness = max(int(min(w, h) * 0.012), 3)
    joint_radius = max(int(base_thickness * 1.2), 4)
    extremity_thickness = max(int(base_thickness * 0.6), 2)

    # Draw body segments with outline + fill
    for part_name, connections in SKELETON.items():
        color = COLORS[part_name]
        for start_lm, end_lm in connections:
            s = landmarks[start_lm]
            e = landmarks[end_lm]
            if s.visibility < 0.3 or e.visibility < 0.3:
                continue
            pt1 = get_landmark_point(s, w, h)
            pt2 = get_landmark_point(e, w, h)
            cv2.line(canvas, pt1, pt2, OUTLINE_COLOR, base_thickness + 3, cv2.LINE_AA)
            cv2.line(canvas, pt1, pt2, color, base_thickness, cv2.LINE_AA)

    # Draw extremities (thinner)
    for part_name, connections in EXTREMITIES.items():
        color = COLORS[part_name]
        for start_lm, end_lm in connections:
            s = landmarks[start_lm]
            e = landmarks[end_lm]
            if s.visibility < 0.3 or e.visibility < 0.3:
                continue
            pt1 = get_landmark_point(s, w, h)
            pt2 = get_landmark_point(e, w, h)
            cv2.line(canvas, pt1, pt2, OUTLINE_COLOR, extremity_thickness + 2, cv2.LINE_AA)
            cv2.line(canvas, pt1, pt2, color, extremity_thickness, cv2.LINE_AA)

    # Draw joints
    all_joint_landmarks = set()
    for connections in SKELETON.values():
        for s, e in connections:
            all_joint_landmarks.add(s)
            all_joint_landmarks.add(e)
    for connections in EXTREMITIES.values():
        for s, e in connections:
            all_joint_landmarks.add(s)
            all_joint_landmarks.add(e)

    for lm_idx in all_joint_landmarks:
        lm = landmarks[lm_idx]
        if lm.visibility < 0.3:
            continue
        pt = get_landmark_point(lm, w, h)
        cv2.circle(canvas, pt, joint_radius + 1, OUTLINE_COLOR, -1, cv2.LINE_AA)
        cv2.circle(canvas, pt, joint_radius, JOINT_COLOR, -1, cv2.LINE_AA)

    # Draw head
    try:
        center, radius = estimate_head_center_and_radius(landmarks, w, h)
        cv2.circle(canvas, center, radius + 2, OUTLINE_COLOR, -1, cv2.LINE_AA)
        cv2.circle(canvas, center, radius, COLORS['head'], -1, cv2.LINE_AA)
        inner_r = max(int(radius * 0.7), 8)
        face_color = tuple(min(c + 40, 255) for c in COLORS['head'])
        cv2.circle(canvas, center, inner_r, face_color, -1, cv2.LINE_AA)
    except Exception:
        pass

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cv2.imwrite(output_path, canvas, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return True


def process_all(input_dir, output_dir, single_file=None):
    """Process all exercise images or a single file."""
    options = PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=MODEL_PATH),
        num_poses=1,
    )
    detector = PoseLandmarker.create_from_options(options)

    if single_file:
        rel = os.path.relpath(single_file, input_dir)
        out_path = os.path.join(output_dir, rel)
        success = render_stick_figure(single_file, out_path, detector)
        print(f"{'OK' if success else 'FAIL'}: {rel} -> {out_path}")
        detector.close()
        return

    # Collect all images
    images = []
    for root, dirs, files in os.walk(input_dir):
        for f in sorted(files):
            if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                images.append(os.path.join(root, f))

    total = len(images)
    success_count = 0
    fail_count = 0

    print(f"Processing {total} images...")

    for i, img_path in enumerate(images):
        rel = os.path.relpath(img_path, input_dir)
        out_path = os.path.join(output_dir, rel)

        success = render_stick_figure(img_path, out_path, detector)
        if success:
            success_count += 1
        else:
            fail_count += 1
            print(f"  FAIL: {rel}")

        if (i + 1) % 50 == 0 or (i + 1) == total:
            print(f"  Progress: {i+1}/{total} (OK: {success_count}, FAIL: {fail_count})")

    detector.close()
    print(f"\nDone! Success: {success_count}, Failed: {fail_count}")


if __name__ == '__main__':
    base = Path(__file__).resolve().parent.parent
    input_dir = base / 'resources' / 'exercises' / 'images'
    output_dir = base / 'resources' / 'exercises' / 'images_stickfigure'

    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        test_file = sys.argv[2] if len(sys.argv) > 2 else str(input_dir / 'Barbell_Curl' / '0.jpg')
        process_all(str(input_dir), str(output_dir), single_file=test_file)
    else:
        process_all(str(input_dir), str(output_dir))
