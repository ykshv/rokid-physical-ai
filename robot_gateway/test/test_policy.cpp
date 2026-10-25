#include <gtest/gtest.h>
#include <fstream>
#include "policy.hpp"
#include "journal.hpp"

TEST(Policy, RejectsNonfiniteCoordinates) {
  EXPECT_THROW(rokid::number(rokid::json("NaN")), std::runtime_error);
}
TEST(Policy, WorkspaceBoundsAreInclusive) {
  rokid::json point = {{"x", 0.2}, {"y", 0.0}, {"z", 0.1}};
  EXPECT_TRUE(rokid::inside(point, {0.2, -0.1, 0.0}, {0.5, 0.1, 0.2}));
  point["x"] = 0.19;
  EXPECT_FALSE(rokid::inside(point, {0.2, -0.1, 0.0}, {0.5, 0.1, 0.2}));
}

static rokid::json scene() {
  return rokid::json::parse(R"({"version":1,"frame_id":"robot_base","revision":"r1",
    "calibration_id":"c1","calibrated":true,"observed_at":100,
    "objects":[{"id":"cube","label":"cube","center":{"x":0.35,"y":0,"z":0.025},
      "size":{"x":0.04,"y":0.04,"z":0.05},"grasp_width":0.04}],
    "zones":[{"id":"tray","label":"tray","center":{"x":0.5,"y":0,"z":0},"radius":0.06}]})");
}
static rokid::json request(const rokid::json& s) {
  return {{"version",1}, {"expires_at",102}, {"scene",s},
    {"intent",{{"action","pick_place"}, {"scene_revision","r1"}, {"object_id","cube"}, {"destination_id","tray"}}}};
}
static void check(const rokid::json& command, const rokid::json& observation) {
  rokid::check_request(command, observation, 100.5, {0.25,-0.25,0}, {0.65,0.25,0.45}, 0.08);
}
TEST(Policy, AcceptsFreshIsolatedTask) {
  auto s = scene(); EXPECT_NO_THROW(check(request(s), s));
}
TEST(Policy, RejectsStaleSceneAndExpiredCommand) {
  auto s = scene(), r = request(s);
  s["observed_at"] = 90; EXPECT_THROW(check(r, s), std::runtime_error);
  s = scene(); r["expires_at"] = 99; EXPECT_THROW(check(r, s), std::runtime_error);
}
TEST(Policy, RejectsChangedCalibrationAndUnknownTarget) {
  auto s = scene(), r = request(s);
  r["scene"]["calibration_id"] = "other"; EXPECT_THROW(check(r, s), std::runtime_error);
  r = request(s); r["intent"]["object_id"] = "unknown"; EXPECT_THROW(check(r, s), std::runtime_error);
}
TEST(Policy, RejectsCrowdedDestinationAndWideGrasp) {
  auto s = scene(), r = request(s);
  auto other = s["objects"][0]; other["id"] = "other"; other["center"]["x"] = 0.5;
  s["objects"].push_back(other); EXPECT_THROW(check(r, s), std::runtime_error);
  s = scene(); s["objects"][0]["grasp_width"] = 0.08; EXPECT_THROW(check(r, s), std::runtime_error);
}
TEST(Policy, RejectsMalformedProducerScene) {
  auto s = scene(); s["calibrated"] = "yes";
  EXPECT_THROW(rokid::check_scene(s), std::runtime_error);
  s = scene(); s["zones"][0]["id"] = "cube";
  EXPECT_THROW(rokid::check_scene(s), std::runtime_error);
}

TEST(Policy, SharedSceneContractCases) {
  std::ifstream input(SCENE_FIXTURE_PATH);
  ASSERT_TRUE(input.good());
  auto fixture = rokid::json::parse(input);
  for (const auto& test : fixture.at("cases")) {
    SCOPED_TRACE(test.at("name").get<std::string>());
    auto observation = fixture.at("scene").patch(test.at("patch"));
    if (test.at("accepted").get<bool>()) EXPECT_NO_THROW(rokid::check_scene(observation));
    else EXPECT_ANY_THROW(rokid::check_scene(observation));
  }
}

TEST(Journal, FailedWriteNeverReportsSuccessfulExecution) {
  rokid::json record = {{"operation_id", "task"}, {"state", "executing"}};
  EXPECT_THROW(rokid::persist_operation_state(record, "succeeded", nullptr, [] {
    throw std::runtime_error("disk_full");
  }), std::runtime_error);
  EXPECT_EQ(record.at("state"), "uncertain");
  EXPECT_EQ(record.at("operation_id"), "task");
}

TEST(Journal, FailedWriteBeforeMotionRemainsUncertain) {
  rokid::json record = {{"operation_id", "task"}, {"state", "executing"}};
  EXPECT_THROW(rokid::persist_operation_state(record, "executing", nullptr, [] {
    throw std::runtime_error("directory_sync_failed");
  }), std::runtime_error);
  EXPECT_EQ(record.at("state"), "uncertain");
}

TEST(Journal, SuccessfulWriteRetainsTerminalResult) {
  rokid::json record = {{"operation_id", "task"}, {"state", "executing"}};
  bool persisted = false;
  rokid::persist_operation_state(record, "succeeded", nullptr, [&] { persisted = true; });
  EXPECT_TRUE(persisted);
  EXPECT_EQ(record.at("state"), "succeeded");
  EXPECT_TRUE(record.at("reason").is_null());
}
