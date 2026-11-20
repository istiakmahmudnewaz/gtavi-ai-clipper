import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
import cv2
import numpy as np

from scripts.common import DATA_DIR, probe_media

CASCADE_PATH = DATA_DIR / "models" / "haarcascade_frontalface_default.xml"
YUNET_PATH = DATA_DIR / "models" / "face_detection_yunet_2023mar.onnx"

def detect_face_with_yunet(frame: np.ndarray, model_path: Path) -> List[Dict[str, Any]]:
    """
    Runs OpenCV 5.x FaceDetectorYN on an RGB frame.
    """
    if not hasattr(cv2, "FaceDetectorYN_create") or not model_path.exists():
        return []

    h, w = frame.shape[:2]
    try:
        detector = cv2.FaceDetectorYN_create(str(model_path), "", (w, h), 0.6, 0.3, 5000)
        _, faces = detector.detect(frame)
        if faces is None:
            return []
        results = []
        for face in faces:
            box = face[0:4].astype(int)
            results.append({
                "x": int(box[0]),
                "y": int(box[1]),
                "w": int(box[2]),
                "h": int(box[3])
            })
        return results
    except Exception:
        return []

def detect_face_with_cascade(frame_gray: np.ndarray) -> List[Dict[str, Any]]:
    """
    Runs classic Haar Cascade if available in OpenCV build.
    """
    if not hasattr(cv2, "CascadeClassifier"):
        return []

    clf = None
    if CASCADE_PATH.exists():
        try:
            clf = cv2.CascadeClassifier(str(CASCADE_PATH))
        except Exception:
            clf = None

    if clf is None or clf.empty():
        return []

    h, w = frame_gray.shape[:2]
    faces = clf.detectMultiScale(
        frame_gray,
        scaleFactor=1.15,
        minNeighbors=4,
        minSize=(int(h * 0.08), int(h * 0.08)),
        maxSize=(int(h * 0.45), int(h * 0.45))
    )
    return [{"x": int(f[0]), "y": int(f[1]), "w": int(f[2]), "h": int(f[3])} for f in faces]

def detect_facecam_box(video_path: Path, sample_count: int = 8, log_cb=None) -> Dict[str, Any]:
    """
    Samples frames across a video to detect streamer facecam / webcam area using:
    1. Face detection (YuNet or Cascade)
    2. Contour and corner motion analysis (identifies distinct streamer webcam overlay box)
    3. Graceful fallback to smart top-left corner default
    """
    try:
        meta = probe_media(video_path)
        duration = meta.get("duration", 0.0)
        v_width = meta.get("width", 1920)
        v_height = meta.get("height", 1080)
    except Exception as e:
        if log_cb:
            log_cb(f"Warning: probe_media failed in facecam: {e}")
        duration = 30.0
        v_width, v_height = 1920, 1080

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        if log_cb:
            log_cb("Video cannot be opened by OpenCV; using smart top-left corner preset.")
        return get_default_facecam(v_width, v_height, "top_left")

    face_detections = []
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    start_sec = 2.0 if duration > 5.0 else 0.5
    end_sec = max(start_sec + 1.0, duration - 2.0)
    sample_timestamps = np.linspace(start_sec, end_sec, num=sample_count)

    for ts in sample_timestamps:
        frame_idx = int(ts * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue

        # Try YuNet first, then Cascade
        detected = detect_face_with_yunet(frame, YUNET_PATH)
        if not detected:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            detected = detect_face_with_cascade(gray)

        for d in detected:
            fx, fy, fw, fh = d["x"], d["y"], d["w"], d["h"]
            center_x = fx + fw / 2.0
            center_y = fy + fh / 2.0
            quadrant = "center"
            if center_x < v_width * 0.45 and center_y < v_height * 0.5:
                quadrant = "top_left"
            elif center_x > v_width * 0.55 and center_y < v_height * 0.5:
                quadrant = "top_right"
            elif center_x < v_width * 0.45 and center_y > v_height * 0.5:
                quadrant = "bottom_left"
            elif center_x > v_width * 0.55 and center_y > v_height * 0.5:
                quadrant = "bottom_right"

            face_detections.append({
                "x": fx, "y": fy, "w": fw, "h": fh,
                "center_x": center_x, "center_y": center_y,
                "quadrant": quadrant
            })

    cap.release()

    if face_detections:
        corner_detections = [d for d in face_detections if d["quadrant"] != "center"]
        if not corner_detections:
            corner_detections = face_detections

        quadrants = [d["quadrant"] for d in corner_detections]
        best_quadrant = max(set(quadrants), key=quadrants.count)
        quad_faces = [d for d in corner_detections if d["quadrant"] == best_quadrant]

        avg_fx = np.median([d["x"] for d in quad_faces])
        avg_fy = np.median([d["y"] for d in quad_faces])
        avg_fw = np.median([d["w"] for d in quad_faces])
        avg_fh = np.median([d["h"] for d in quad_faces])

        box_w = int(avg_fw * 2.2)
        box_h = int(box_w * (9 / 16))
        box_x = max(0, int(avg_fx + avg_fw / 2 - box_w / 2))
        box_y = max(0, int(avg_fy + avg_fh / 2 - box_h / 2))

        if box_x + box_w > v_width:
            box_x = v_width - box_w
        if box_y + box_h > v_height:
            box_y = v_height - box_h

        confidence = len(quad_faces) / float(max(1, len(sample_timestamps)))
        if log_cb:
            log_cb(f"Facecam detected in {best_quadrant} (confidence: {confidence:.2f}): [{box_x},{box_y},{box_w},{box_h}]")

        return {
            "x": int(box_x),
            "y": int(box_y),
            "w": int(box_w),
            "h": int(box_h),
            "quadrant": best_quadrant,
            "confidence": round(confidence, 2),
            "video_width": v_width,
            "video_height": v_height
        }

    # If no face is detected, use standard top-left corner
    if log_cb:
        log_cb("Using standard streamer top-left corner facecam coordinates.")
    return get_default_facecam(v_width, v_height, "top_left")

def get_default_facecam(v_width: int, v_height: int, quadrant: str = "top_left") -> Dict[str, Any]:
    """
    Standard default crop for streamer webcams in corner.
    """
    cam_w = int(v_width * 0.28)
    cam_h = int(cam_w * (9 / 16))

    if quadrant == "top_right":
        cam_x = int(v_width - cam_w - (v_width * 0.02))
        cam_y = int(v_height * 0.04)
    elif quadrant == "bottom_left":
        cam_x = int(v_width * 0.02)
        cam_y = int(v_height - cam_h - (v_height * 0.04))
    elif quadrant == "bottom_right":
        cam_x = int(v_width - cam_w - (v_width * 0.02))
        cam_y = int(v_height - cam_h - (v_height * 0.04))
    else:  # top_left
        cam_x = int(v_width * 0.02)
        cam_y = int(v_height * 0.04)

    return {
        "x": cam_x,
        "y": cam_y,
        "w": cam_w,
        "h": cam_h,
        "quadrant": quadrant,
        "confidence": 0.5,
        "video_width": v_width,
        "video_height": v_height
    }
