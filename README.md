# Rokid Physical AI

**Voice and gesture interface for robot arms, using Rokid smart glasses.**

Development preview. Independent implementation inspired by [EDITH](https://project-edith.github.io/); not affiliated with Rokid, Franka Robotics, UFACTORY, or the EDITH authors.

The intended interaction is simple: point at an object, say “put this there,” confirm the task by voice, and receive the robot's execution result through your glasses. A stock-firmware Android app connects to an agent on your computer. A separate robot gateway owns physical motion.

Reference profiles: Franka Research 3 with Franka Hand, and UFACTORY xArm6 with a parallel gripper. Physical hardware qualification is pending. Panda is not interchangeable with FR3.

**Status:** implementation and verification in progress; no physical manipulation, gaze tracking, or measured success rate is claimed.

[Documentation](https://ykshv.github.io/rokid-physical-ai/) · [License](LICENSE) · [EDITH paper](https://arxiv.org/abs/2606.10276)
