FROM ros:jazzy-ros-base@sha256:103b6c417973394659af6804d4917cd489b91e5ed22eb7bef263025a3bed2410
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git pkg-config libcpp-httplib-dev libssl-dev nlohmann-json3-dev \
    ros-jazzy-moveit-ros-planning-interface ros-jazzy-tf2-geometry-msgs \
    ros-jazzy-ament-cmake-gtest python3-colcon-common-extensions
WORKDIR /ws
RUN git clone --filter=blob:none --no-checkout https://github.com/frankarobotics/franka_ros2.git /tmp/franka \
    && git -C /tmp/franka checkout 4acc05c01ebfcdf916ee6b3df966df0ad7b2f9ec -- franka_msgs \
    && mkdir -p src && cp -r /tmp/franka/franka_msgs src/ \
    && git clone --filter=blob:none --no-checkout https://github.com/xArm-Developer/xarm_ros2.git /tmp/xarm \
    && git -C /tmp/xarm checkout d837f2e17f7f36043103b367fca3af8172626245 -- xarm_msgs \
    && cp -r /tmp/xarm/xarm_msgs src/
COPY robot_gateway /ws/src/rokid_robot_gateway
RUN source /opt/ros/jazzy/setup.bash && colcon build \
    && source install/setup.bash && colcon test --packages-select rokid_robot_gateway \
    && colcon test-result --verbose
CMD ["bash", "-lc", "source /ws/install/setup.bash && ros2 run rokid_robot_gateway robot_gateway"]
