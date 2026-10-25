"""Calibrated tabletop geometry and image grounding; no model-produced coordinates."""

import time
import uuid
from pathlib import Path

import cv2
import numpy as np
from pydantic import Field, model_validator

from .contracts import Contract, PlacementZone, SceneObject, SceneObservation, Vector3


class Calibration(Contract):
    id: str
    camera_matrix: list[list[float]]
    distortion: list[float]
    camera_to_base: list[list[float]]
    table_z: float
    marker_corners: dict[int, list[list[float]]]
    zones: list[PlacementZone]

    @model_validator(mode="after")
    def matrices(self):
        k = np.asarray(self.camera_matrix)
        transform = np.asarray(self.camera_to_base)
        if (
            k.shape != (3, 3)
            or transform.shape != (4, 4)
            or not np.isfinite(k).all()
            or not np.isfinite(transform).all()
            or k[0, 0] <= 0
            or k[1, 1] <= 0
            or not np.allclose(transform[3], [0, 0, 0, 1])
            or not np.allclose(transform[:3, :3].T @ transform[:3, :3], np.eye(3), atol=1e-5)
            or not np.isclose(np.linalg.det(transform[:3, :3]), 1)
        ):
            raise ValueError("Invalid camera calibration")
        if len(self.marker_corners) < 2:
            raise ValueError("At least two workspace markers are required")
        for corners in self.marker_corners.values():
            if np.asarray(corners).shape != (4, 3) or not np.isfinite(corners).all():
                raise ValueError("Marker corners must be 4 finite XYZ points in robot_base")
        return self

    @classmethod
    def load(cls, path: Path):
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


class GlassesCalibration(Contract):
    camera_matrix: list[list[float]]
    distortion: list[float] = Field(min_length=4, max_length=14)
    image_size: tuple[int, int] = (640, 480)


def locate_board(
    image: np.ndarray, intrinsics: GlassesCalibration, calibration: Calibration
) -> tuple[np.ndarray, np.ndarray]:
    if image.shape[1::-1] != intrinsics.image_size:
        raise ValueError("calibration_resolution_mismatch")
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50))
    corners, ids, _ = detector.detectMarkers(image)
    if ids is None:
        raise ValueError("workspace_markers_not_visible")
    object_points, pixels = [], []
    for marker, marker_id in zip(corners, ids.flatten(), strict=True):
        if int(marker_id) in calibration.marker_corners:
            object_points.extend(calibration.marker_corners[int(marker_id)])
            pixels.extend(marker.reshape(4, 2).tolist())
    if len(object_points) < 8:
        raise ValueError("insufficient_workspace_markers")
    points = np.asarray(object_points, np.float64)
    pixel_array = np.asarray(pixels, np.float64)
    k, d = np.asarray(intrinsics.camera_matrix), np.asarray(intrinsics.distortion)
    ok, rvec, tvec = cv2.solvePnP(points, pixel_array, k, d, flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        raise ValueError("workspace_pose_failed")
    projected, _ = cv2.projectPoints(points, rvec, tvec, k, d)
    error = np.linalg.norm(projected.reshape(-1, 2) - pixel_array, axis=1)
    if error.max() > 3:
        raise ValueError("workspace_reprojection_error")
    return rvec, tvec


def annotate_glasses(
    jpeg: bytes, scene: SceneObservation, intrinsics: GlassesCalibration, calibration: Calibration
) -> bytes:
    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("invalid_image")
    rvec, tvec = locate_board(image, intrinsics, calibration)
    candidates: list[SceneObject | PlacementZone] = [*scene.objects, *scene.zones]
    points = np.array([[c.center.x, c.center.y, c.center.z] for c in candidates])
    if len(points):
        projection, _ = cv2.projectPoints(
            points,
            rvec,
            tvec,
            np.asarray(intrinsics.camera_matrix),
            np.asarray(intrinsics.distortion),
        )
        for candidate, xy in zip(candidates, projection.reshape(-1, 2), strict=True):
            x, y = map(int, xy)
            if 0 <= x < image.shape[1] and 0 <= y < image.shape[0]:
                cv2.circle(image, (x, y), 5, (0, 255, 0), 2)
                cv2.putText(
                    image,
                    candidate.id,
                    (x + 6, y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 0),
                    1,
                    cv2.LINE_AA,
                )
    ok, result = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise ValueError("jpeg_encoding_failed")
    return result.tobytes()


class TabletopPerception:
    def __init__(self, calibration: Calibration):
        self.calibration = calibration
        self.previous: list[SceneObject] = []
        self.revision_objects: list[SceneObject] = []
        self.next_label = 1
        self.revision = uuid.uuid4().hex

    def observe(self, rgb: np.ndarray, depth_m: np.ndarray) -> SceneObservation:
        if rgb.shape[:2] != depth_m.shape or depth_m.ndim != 2:
            raise ValueError("aligned_rgb_depth_required")
        c = self.calibration
        k = np.asarray(c.camera_matrix)
        v, u = np.indices(depth_m.shape)
        z = depth_m.astype(np.float64)
        xyz = np.stack(((u - k[0, 2]) * z / k[0, 0], (v - k[1, 2]) * z / k[1, 1], z), axis=-1)
        t = np.asarray(c.camera_to_base)
        base = xyz @ t[:3, :3].T + t[:3, 3]
        height = base[:, :, 2] - c.table_z
        mask = (
            (z > 0.15)
            & (z < 2)
            & (height > 0.015)
            & (height < 0.15)
            & np.isfinite(base).all(axis=-1)
        ).astype(np.uint8)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        objects, used = [], set()
        for label in range(1, count):
            if stats[label, cv2.CC_STAT_AREA] < 100:
                continue
            points = base[labels == label]
            low, high = np.quantile(points, [0.02, 0.98], axis=0)
            center = (low + high) / 2
            size = high - low
            size[2] = high[2] - c.table_z
            center[2] = c.table_z + size[2] / 2
            if min(size[:2]) < 0.015 or max(size) > 0.15:
                continue
            position = Vector3(x=center[0], y=center[1], z=center[2])
            matches = [
                o for o in self.previous if o.id not in used and o.center.distance(position) < 0.025
            ]
            ident = (
                min(matches, key=lambda o: o.center.distance(position)).id
                if matches
                else "obj_" + uuid.uuid4().hex[:8]
            )
            used.add(ident)
            previous = next((o for o in self.previous if o.id == ident), None)
            spoken_label = previous.label if previous else str(self.next_label)
            if previous is None:
                self.next_label += 1
            objects.append(
                SceneObject(
                    id=ident,
                    label=spoken_label,
                    center=position,
                    size=Vector3(x=size[0], y=size[1], z=size[2]),
                    grasp_width=float(size[1]),
                )
            )
        old = {o.id: o for o in self.revision_objects}
        if len(old) != len(objects) or any(
            o.id not in old or o.center.distance(old[o.id].center) > 0.005 for o in objects
        ):
            self.revision = uuid.uuid4().hex
            self.revision_objects = objects
        self.previous = objects[:20]
        return SceneObservation(
            revision=self.revision,
            observed_at=time.time(),
            calibration_id=c.id,
            calibrated=True,
            objects=self.previous,
            zones=c.zones,
        )


def calibrate_intrinsics(
    images: list[Path], output: Path, squares: tuple[int, int], square_size: float
) -> None:
    board = cv2.aruco.CharucoBoard(
        squares,
        square_size,
        square_size * 0.7,
        cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),
    )
    detector = cv2.aruco.CharucoDetector(board)
    object_points, image_points, size = [], [], None
    for path in images:
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError(f"Cannot read {path.name}")
        if size and size != image.shape[1::-1]:
            raise ValueError("Calibration images must have one resolution")
        size = image.shape[1::-1]
        corners, ids, _, _ = detector.detectBoard(image)
        if ids is not None and len(ids) >= 8:
            obj = np.asarray(board.getChessboardCorners())[ids.flatten()].reshape(-1, 1, 3)
            img = corners
            object_points.append(obj)
            image_points.append(img)
    if len(object_points) < 15 or size is None:
        raise ValueError("Need 15 usable, varied calibration views")
    error, k, d, _, _ = cv2.calibrateCamera(object_points, image_points, size, None, None)
    if error > 1:
        raise ValueError(f"Calibration RMS {error:.2f}px exceeds 1px")
    result = GlassesCalibration(
        camera_matrix=k.tolist(), distortion=d.flatten().tolist(), image_size=size
    )
    output.write_text(result.model_dump_json(indent=2), encoding="utf-8")


def rigid_transform(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Solve camera-to-base registration from measured non-collinear correspondences."""
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 3:
        raise ValueError("Expected matching Nx3 correspondences")
    if len(source) < 4 or np.linalg.matrix_rank(source - source.mean(0)) < 2:
        raise ValueError("Need at least four non-collinear points")
    u, _, vt = np.linalg.svd((source - source.mean(0)).T @ (target - target.mean(0)))
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1] *= -1
        rotation = vt.T @ u.T
    translation = target.mean(0) - rotation @ source.mean(0)
    errors = np.linalg.norm(source @ rotation.T + translation - target, axis=1)
    if errors.max() > 0.005:
        raise ValueError("Registration error exceeds 5mm")
    result = np.eye(4)
    result[:3, :3], result[:3, 3] = rotation, translation
    return result
