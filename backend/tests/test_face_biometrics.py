from __future__ import annotations

import numpy as np

from app.services.face_biometrics import OpenCvFaceRecognizer


class _FakeCv2:
    ROTATE_90_COUNTERCLOCKWISE = 0
    ROTATE_180 = 1
    ROTATE_90_CLOCKWISE = 2

    @staticmethod
    def rotate(frame: np.ndarray, code: int) -> np.ndarray:
        turns = {0: 1, 1: 2, 2: 3}[code]
        return np.rot90(frame, turns).copy()


class _LandscapeOnlyDetector:
    def __init__(self) -> None:
        self.input_size = (0, 0)

    def setInputSize(self, size: tuple[int, int]) -> None:  # noqa: N802 - OpenCV API name
        self.input_size = size

    def detect(self, frame: np.ndarray):
        height, width = frame.shape[:2]
        if height > width:
            return None, None
        face = np.array([[10, 10, 20, 25, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.95]], dtype=np.float32)
        return None, face


def test_document_face_detection_retries_sideways_pixels_without_exif() -> None:
    recognizer = OpenCvFaceRecognizer()
    recognizer._cv2 = _FakeCv2()
    recognizer._detector = _LandscapeOnlyDetector()
    portrait_frame = np.zeros((100, 60, 3), dtype=np.uint8)

    rotated, faces, degrees = recognizer._detect_with_document_orientation_retry(portrait_frame, "document")

    assert rotated.shape[:2] == (60, 100)
    assert faces is not None and len(faces) == 1
    assert degrees == 90


def test_selfie_face_detection_does_not_retry_orientation() -> None:
    recognizer = OpenCvFaceRecognizer()
    recognizer._cv2 = _FakeCv2()
    recognizer._detector = _LandscapeOnlyDetector()
    portrait_frame = np.zeros((100, 60, 3), dtype=np.uint8)

    unchanged, faces, degrees = recognizer._detect_with_document_orientation_retry(portrait_frame, "selfie")

    assert unchanged.shape == portrait_frame.shape
    assert faces is None
    assert degrees == 0
