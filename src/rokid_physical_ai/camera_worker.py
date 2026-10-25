"""Explicitly started RGB-D producer; never saves camera frames."""

import argparse
import os
import ssl
import time
from pathlib import Path

import cv2
import httpx
import numpy as np

from .perception import Calibration, GlassesCalibration, TabletopPerception, locate_board


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--serial", required=True, help="Select one known RealSense camera")
    args = parser.parse_args()
    import pyrealsense2 as rs

    calibration = Calibration.load(args.calibration)
    perception = TabletopPerception(calibration)
    intrinsics = GlassesCalibration(
        camera_matrix=calibration.camera_matrix, distortion=calibration.distortion
    )
    url = os.environ["ROBOT_GATEWAY_URL"]
    if not url.startswith("https://"):
        raise ValueError("HTTPS required")
    tls = ssl.create_default_context(cafile=os.environ["ROBOT_GATEWAY_CA"])
    pipeline, config = rs.pipeline(), rs.config()
    config.enable_device(args.serial)
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
    profile = pipeline.start(config)
    scale = profile.get_device().first_depth_sensor().get_depth_scale()
    align = rs.align(rs.stream.color)
    try:
        with httpx.Client(
            base_url=url,
            verify=tls,
            timeout=2,
            headers={"Authorization": "Bearer " + os.environ["ROBOT_PERCEPTION_TOKEN"]},
        ) as client:
            while True:
                frames = align.process(pipeline.wait_for_frames(2000))
                rgb = np.asanyarray(frames.get_color_frame().get_data())
                depth = np.asanyarray(frames.get_depth_frame().get_data()) * scale
                observation = perception.observe(rgb, depth)
                valid = False
                try:
                    rvec, tvec = locate_board(rgb, intrinsics, calibration)
                    measured = np.eye(4)
                    measured[:3, :3] = cv2.Rodrigues(rvec)[0]
                    measured[:3, 3] = tvec.flatten()
                    expected = np.linalg.inv(np.asarray(calibration.camera_to_base))
                    valid = (
                        np.linalg.norm(measured[:3, 3] - expected[:3, 3]) < 0.005
                        and np.linalg.norm(measured[:3, :3] - expected[:3, :3]) < 0.025
                    )
                except ValueError:
                    valid = False
                observation = observation.model_copy(update={"calibrated": valid})
                response = client.post("/v1/scene", json=observation.model_dump())
                response.raise_for_status()
                time.sleep(0.15)
    finally:
        pipeline.stop()


if __name__ == "__main__":
    main()
