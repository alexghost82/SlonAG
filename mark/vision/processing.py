"""Vision Runtime — detection and OCR processing.

Provides pluggable backends for object detection, person detection,
and OCR. Each backend has a ``can_run`` check so the runtime can
gracefully disable capabilities when dependencies are missing.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from mark.vision.types import Bbox, DetectionKind, DetectionResult


class DetectionBackend(ABC):
    """Abstract base for detection backends."""

    @staticmethod
    def can_run() -> bool:
        return False

    @abstractmethod
    def detect(self, frame: bytes, width: int, height: int) -> list[DetectionResult]:
        ...


class OCRBackend(ABC):
    """Abstract base for OCR backends."""

    @staticmethod
    def can_run() -> bool:
        return False

    @abstractmethod
    def ocr(self, frame: bytes, width: int, height: int) -> list[dict[str, Any]]:
        ...


# ── Dummy backends (always available) ──────────────────────────────

class DummyObjectDetector(DetectionBackend):
    @staticmethod
    def can_run() -> bool:
        return False

    def detect(self, frame: bytes, width: int, height: int) -> list[DetectionResult]:
        return []


class DummyPersonDetector(DetectionBackend):
    @staticmethod
    def can_run() -> bool:
        return False

    def detect(self, frame: bytes, width: int, height: int) -> list[DetectionResult]:
        return []


class DummyOCR(OCRBackend):
    @staticmethod
    def can_run() -> bool:
        return False

    def ocr(self, frame: bytes, width: int, height: int) -> list[dict[str, Any]]:
        return []


# ── OpenCV person detector ───────────────────────────────────────

class OpenCVPersonDetector(DetectionBackend):
    """OpenCV HOG-based person detector."""

    _hog = None

    @staticmethod
    def can_run() -> bool:
        if OpenCVPersonDetector._hog is None:
            try:
                import cv2  # type: ignore
                OpenCVPersonDetector._hog = cv2.HOGDescriptor()
                OpenCVPersonDetector._hog.setSVMDetector(
                    cv2.HOGDescriptor_getDefaultPeopleDetector())
            except Exception:
                OpenCVPersonDetector._hog = False
        return OpenCVPersonDetector._hog is not False

    def detect(self, frame: bytes, width: int, height: int) -> list[DetectionResult]:
        if not self.can_run():
            return []
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
            img = cv2.imdecode(np.frombuffer(frame, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                return []
            rects, weights = OpenCVPersonDetector._hog.detectMultiScale(img)
            results: list[DetectionResult] = []
            for (x, y, w, h), score in zip(rects, weights):
                conf = float(max(score, 0.0))
                results.append(DetectionResult(
                    kind=DetectionKind.PERSON, label="person",
                    confidence=conf,
                    bbox=Bbox(x_min=x / width, y_min=y / height,
                              x_max=(x + w) / width, y_max=(y + h) / height),
                ))
            return results
        except Exception:
            return []


class OpenCVObjectDetector(DetectionBackend):
    """OpenCV cascade-based object detector."""

    def __init__(self, cascade_paths: list[str] | None = None) -> None:
        self.cascade_paths = cascade_paths or []
        self._cascades: list[Any] = []

    @staticmethod
    def can_run() -> bool:
        try:
            import cv2  # type: ignore
            return True
        except Exception:
            return False

    def _ensure_loaded(self) -> None:
        if self._cascades:
            return
        try:
            import cv2  # type: ignore
            for p in self.cascade_paths:
                try:
                    c = cv2.CascadeClassifier(p)
                    if not c.empty:
                        self._cascades.append(c)
                except Exception:
                    pass
        except Exception:
            pass

    def detect(self, frame: bytes, width: int, height: int) -> list[DetectionResult]:
        self._ensure_loaded()
        if not self._cascades:
            return []
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
            img = cv2.imdecode(np.frombuffer(frame, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                return []
            results: list[DetectionResult] = []
            for c in self._cascades:
                rects = c.detectMultiScale(img, scaleFactor=1.1, minNeighbors=3)
                for (x, y, w, h) in rects:
                    results.append(DetectionResult(
                        kind=DetectionKind.OBJECT, label="detected_object",
                        confidence=0.8,
                        bbox=Bbox(x_min=x / width, y_min=y / height,
                                  x_max=(x + w) / width, y_max=(y + h) / height),
                    ))
            return results
        except Exception:
            return []


# ── Tesseract OCR ────────────────────────────────────────────────

class TesseractOCR(OCRBackend):
    """Tesseract OCR backend."""

    _tesseract = None

    @staticmethod
    def can_run() -> bool:
        if TesseractOCR._tesseract is None:
            try:
                import pytesseract  # type: ignore
                TesseractOCR._tesseract = pytesseract
            except Exception:
                TesseractOCR._tesseract = False
        return TesseractOCR._tesseract is not False

    def ocr(self, frame: bytes, width: int, height: int) -> list[dict[str, Any]]:
        if not self.can_run():
            return []
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
            img = cv2.imdecode(np.frombuffer(frame, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                return []
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            boxes = self._tesseract.image_to_boxes(gray)  # type: ignore
            if boxes is None:
                return []
            lines = boxes.strip().split("\n")
            results: list[dict[str, Any]] = []
            for line in lines:
                parts = line.split()
                if len(parts) >= 5:
                    char = parts[0]
                    l, t, r, b = int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
                    results.append({
                        "text": char,
                        "confidence": 0.9,
                        "bbox": {
                            "x_min": l / width, "y_min": 1 - t / height,
                            "x_max": r / width, "y_max": 1 - b / height,
                        },
                    })
            return results
        except Exception:
            return []


# ── Backend resolver ─────────────────────────────────────────────

def build_person_detector() -> DetectionBackend:
    if OpenCVPersonDetector.can_run():
        return OpenCVPersonDetector()
    return DummyPersonDetector()


def build_object_detector(paths: list[str] | None = None) -> DetectionBackend:
    if OpenCVObjectDetector.can_run():
        return OpenCVObjectDetector(paths)
    return DummyObjectDetector()


def build_ocr() -> OCRBackend:
    if TesseractOCR.can_run():
        return TesseractOCR()
    return DummyOCR()


def detect_capabilities(frame: bytes, width: int, height: int) -> dict[str, bool]:
    """Return a dict of capability → enabled."""
    return {
        "object_detection": OpenCVObjectDetector.can_run(),
        "person_detection": OpenCVPersonDetector.can_run(),
        "ocr": TesseractOCR.can_run(),
    }
