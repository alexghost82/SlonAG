"""Vision Runtime — production-grade bounded vision pipeline.

Public API
----------
- ``create_runtime(source_type, **src_kwargs)`` → ``VisionRuntime``
- ``create_vision_provider(source_type, **src_kwargs)`` → ``VisionProvider``
- ``VisionConfig`` — bounded configuration
- ``VisionRuntime``, ``VisionRuntimeStatus``, ``VisionAnalysis``
- All types from ``acta.vision.types``

Supported sources : ``image``, ``screenshot``, ``screen``, ``camera``, ``rtsp``.

Examples
--------
.. code-block:: python

    from acta.vision import create_runtime

    rt = create_runtime("rtsp", rtsp_url="rtsp://localhost:8554/live")
    ok = await rt.start("rtsp", rtsp_url="rtsp://localhost:8554/live")

    while rt.status().is_running:
        tracks = rt.get_present_tracks()
        events = await rt.get_recent_events(10)
        await asyncio.sleep(0.5)

    await rt.stop()
"""

from acta.vision.acquisition import (
    AcquisitionConfig,
    CameraSource,
    FrameSourceBase,
    ImageSource,
    RTSPSource,
    ScreenshotSource,
    ScreenSource,
)
from acta.vision.config import VisionConfig
from acta.vision.processing import (
    DetectionBackend,
    DetectionKind,
    DetectionResult,
    DummyObjectDetector,
    DummyOCR,
    DummyPersonDetector,
    OCRBackend,
    OpenCVObjectDetector,
    OpenCVPersonDetector,
    TesseractOCR,
    build_object_detector,
    build_ocr,
    build_person_detector,
    detect_capabilities,
)
from acta.vision.provider import (
    DEFAULT_KIND,
    DEFAULT_PRIVACY_PROFILE,
    PROVIDER_ID,
    UNTRUSTED_FENCE,
    UNTRUSTED_LABEL,
    VISION_KINDS,
    LocalVisionProvider,
    VisionProvider,
    VisionTaskRequest,
    create_vision_provider,
    register_factory,
    wrap_untrusted_image_text,
)
from acta.vision.queues import (
    BoundedDetectionQueue,
    BoundedEventQueue,
    BoundedFrameQueue,
    BoundedTrajectoryStore,
)
from acta.vision.runtime import VisionRuntime, create_runtime
from acta.vision.temporal import TemporalAnalyzer, TemporalState
from acta.vision.tracking import ObjectTracker
from acta.vision.types import (
    Bbox,
    DetectionKind,
    DetectionResult,
    Frame,
    FrameEvent,
    FrameSource,
    TrackEvent,
    TrackingState,
    TrajectoryPoint,
    VisionAnalysis,
    VisionRuntimeStatus,
)

__all__ = [
    "AcquisitionConfig",
    "Bbox",
    "BoundedDetectionQueue",
    "BoundedEventQueue",
    "BoundedFrameQueue",
    "BoundedTrajectoryStore",
    "CameraSource",
    "DetectionBackend",
    "DetectionKind",
    "DetectionResult",
    "DummyObjectDetector",
    "DummyOCR",
    "DummyPersonDetector",
    "Frame",
    "FrameEvent",
    "FrameSource",
    "FrameSourceBase",
    "ImageSource",
    "OpenCVObjectDetector",
    "OpenCVPersonDetector",
    "OCRBackend",
    "ObjectTracker",
    "RTSPSource",
    "ScreenshotSource",
    "ScreenSource",
    "TemporalAnalyzer",
    "TemporalState",
    "TesseractOCR",
    "TrackingState",
    "TrajectoryPoint",
    "TrackEvent",
    "VisionAnalysis",
    "VisionConfig",
    "VisionProvider",
    "VisionRuntime",
    "VisionRuntimeStatus",
    "build_object_detector",
    "build_ocr",
    "build_person_detector",
    "create_runtime",
    "create_vision_provider",
    "detect_capabilities",
    "DEFAULT_KIND",
    "DEFAULT_PRIVACY_PROFILE",
    "PROVIDER_ID",
    "UNTRUSTED_FENCE",
    "UNTRUSTED_LABEL",
    "VISION_KINDS",
    "LocalVisionProvider",
    "VisionTaskRequest",
    "wrap_untrusted_image_text",
    "register_factory",
]

# Auto-register so ``providers.registry.get("vision_local")`` works.
register_factory()
