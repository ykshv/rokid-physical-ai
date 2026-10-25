# Calibration and perception

## Equipment

Use a fixed RealSense D435i with unobstructed view of the work surface, a rigidly mounted robot, two or more `DICT_4X4_50` markers around the workspace, and separate lightweight opaque objects. Transparent, reflective, deformable and tightly touching objects are outside the initial segmentation scope.

Calibration and frame acquisition are operator actions. Keep calibration files outside the repository. Do not publish serial numbers, local addresses or camera recordings in issues.

## Coordinate chain

1. Calibrate the glasses' exact capture resolution and sensor orientation with at least 15 varied ChArUco views. `calibrate_intrinsics` rejects RMS error above one pixel.
2. Obtain RGB intrinsics for the aligned RealSense stream. RGB and depth must have matching dimensions.
3. Measure at least four non-collinear correspondences between camera coordinates and the robot base. `rigid_transform` rejects residuals above 5 mm.
4. Measure workspace-marker corners and placement zones in the same base frame. Record the table height and a calibration ID.
5. Verify a fresh marker observation against the stored camera transform before publishing a calibrated scene.

`Calibration` and `GlassesCalibration` in the perception module define the file formats. All metric values are metres. `camera_to_base` is a rigid 4×4 transform. `marker_corners` contains four XYZ corners per marker, in the detector's corner order. Glasses calibration uses the raw camera stream; the client deliberately does not guess phone-style rotation.

Export the JSON Schemas with `uv run rokid-agent schemas --output dist/schemas`. Calibrate from deliberately collected ChArUco images with `rokid-agent calibrate-intrinsics --images <LOCAL_IMAGE_DIRECTORY> --output <NEW_CALIBRATION_JSON> --square-size <MEASURED_METRES>`. The default board is 7×5 squares with marker side 70% of square side; specify `--columns` and `--rows` to match the printed board. The command refuses to replace an existing calibration file.

The producer segments objects above the known table plane and tracks IDs between observations. A material scene change updates the revision. The first-person image is registered using workspace markers, and candidate IDs are projected into that view. If markers cannot be registered, the agent cannot authorize a visually grounded action.

## Run the camera producer

Install the optional camera dependency on the Python 3.14 controller environment and select one known camera explicitly:

```sh
uv sync --extra realsense
uv run python -m rokid_physical_ai.camera_worker --calibration <WORKSPACE_JSON> --serial <CAMERA_SERIAL>
```

Set `ROBOT_GATEWAY_URL`, `ROBOT_GATEWAY_CA`, and the producer-only `ROBOT_PERCEPTION_TOKEN`. Synchronize the agent and controller clocks. The gateway rejects stale scenes; the camera process does not write video to disk.

Recalibrate after moving the camera, table markers, robot base, or changing capture geometry. A successful geometric fit is necessary but does not replace the physical grasp and stop checks.
