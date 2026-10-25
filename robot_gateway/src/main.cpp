#include <atomic>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <regex>
#include <thread>
#include <fcntl.h>
#include <unistd.h>

#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>
#include <std_srvs/srv/trigger.hpp>
#include <moveit/move_group_interface/move_group_interface.hpp>
#include <moveit/planning_scene_interface/planning_scene_interface.hpp>
#include <franka_msgs/action/grasp.hpp>
#include <franka_msgs/action/move.hpp>
#include <xarm_msgs/srv/gripper_move.hpp>
#include <xarm_msgs/srv/set_int16.hpp>
#include <geometry_msgs/msg/pose.hpp>
#include <moveit_msgs/msg/collision_object.hpp>
#include <moveit_msgs/msg/robot_trajectory.hpp>
#include <shape_msgs/msg/solid_primitive.hpp>
#include "policy.hpp"
// Include Eigen/MoveIt before the HTTP resolver headers, which expose an `_res` macro.
#include <httplib.h>
#include <openssl/crypto.h>
// libresolv exports this legacy DNS macro; use the ROS message constant below.
#ifdef ADD
#undef ADD
#endif

using namespace std::chrono_literals;
using rokid::json;

static double now_seconds() {
  return std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
}
static double steady_seconds() {
  return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}
static std::string env(const char* name) {
  auto value = std::getenv(name);
  if (!value || !*value) throw std::runtime_error(std::string("Missing environment: ") + name);
  return value;
}

class Gateway {
  rclcpp::Node::SharedPtr node_;
  moveit::planning_interface::MoveGroupInterface group_;
  moveit::planning_interface::PlanningSceneInterface planning_scene_;
  std::string robot_, base_, gripper_, agent_token_, perception_token_, journal_path_;
  std::vector<double> lo_, hi_;
  double width_, force_;
  bool qualified_;
  std::atomic<bool> armed_{false}, stopped_{true}, busy_{false};
  std::atomic<double> heartbeat_{0};
  std::mutex mutex_;
  json scene_, journal_ = json::object();
  std::jthread worker_, watchdog_;
  rclcpp::Service<std_srvs::srv::Trigger>::SharedPtr arm_service_;
  rclcpp::Service<std_srvs::srv::Trigger>::SharedPtr reconcile_service_;

  void save() {
    // Serialize before starting motion. Unfinished records are uncertain on restart.
    auto temp = journal_path_ + ".tmp";
    { std::ofstream out(temp); out.exceptions(std::ios::failbit | std::ios::badbit); out << journal_.dump(); }
    int fd = ::open(temp.c_str(), O_RDONLY);
    if (fd < 0) throw std::runtime_error("journal_open_failed");
    int synced = ::fsync(fd); ::close(fd);
    if (synced != 0) throw std::runtime_error("journal_sync_failed");
    std::filesystem::rename(temp, journal_path_);
    auto parent = std::filesystem::absolute(journal_path_).parent_path();
    fd = ::open(parent.c_str(), O_RDONLY | O_DIRECTORY);
    if (fd < 0) throw std::runtime_error("journal_directory_open_failed");
    synced = ::fsync(fd); ::close(fd);
    if (synced != 0) throw std::runtime_error("journal_directory_sync_failed");
  }
  bool authorized(const httplib::Request& request, bool perception = false) {
    auto expected = "Bearer " + (perception ? perception_token_ : agent_token_);
    auto actual = request.get_header_value("Authorization");
    return actual.size() == expected.size() &&
      CRYPTO_memcmp(actual.data(), expected.data(), expected.size()) == 0;
  }
  void running() {
    if (stopped_ || !armed_ || steady_seconds() - heartbeat_ > 2)
      throw std::runtime_error("motion_latched_or_heartbeat_lost");
  }
  template<class Service>
  auto call(const std::string& name, typename Service::Request::SharedPtr request) {
    auto client = node_->create_client<Service>(name);
    if (!client->wait_for_service(2s)) throw std::runtime_error("gripper_service_unavailable");
    auto future = client->async_send_request(request);
    auto deadline = std::chrono::steady_clock::now() + 15s;
    while (future.wait_for(50ms) != std::future_status::ready) {
      running();
      if (std::chrono::steady_clock::now() > deadline) throw std::runtime_error("gripper_timeout");
    }
    auto response = future.get();
    if (response->ret != 0) throw std::runtime_error("gripper_rejected");
    return response;
  }
  template<class Action>
  void action(const std::string& name, const typename Action::Goal& goal) {
    auto client = rclcpp_action::create_client<Action>(node_, name);
    if (!client->wait_for_action_server(2s)) throw std::runtime_error("gripper_action_unavailable");
    auto future = client->async_send_goal(goal);
    if (future.wait_for(2s) != std::future_status::ready) throw std::runtime_error("gripper_goal_timeout");
    auto handle = future.get();
    if (!handle) throw std::runtime_error("gripper_goal_rejected");
    auto result = client->async_get_result(handle);
    auto deadline = std::chrono::steady_clock::now() + 15s;
    try {
      while (result.wait_for(50ms) != std::future_status::ready) {
        running();
        if (std::chrono::steady_clock::now() > deadline) throw std::runtime_error("gripper_timeout");
      }
    } catch (...) { client->async_cancel_goal(handle); throw; }
    auto wrapped = result.get();
    if (wrapped.code != rclcpp_action::ResultCode::SUCCEEDED || !wrapped.result->success)
      throw std::runtime_error("gripper_failed");
  }
  void grip(double width, bool grasp) {
    running();
    if (robot_ == "fr3") {
      if (grasp) {
        franka_msgs::action::Grasp::Goal goal;
        goal.width = width; goal.speed = 0.02; goal.force = force_;
        goal.epsilon.inner = 0.005; goal.epsilon.outer = 0.005;
        action<franka_msgs::action::Grasp>(gripper_ + "/grasp", goal);
      } else {
        franka_msgs::action::Move::Goal goal;
        goal.width = width; goal.speed = 0.02;
        action<franka_msgs::action::Move>(gripper_ + "/move", goal);
      }
    } else {
      auto enable = std::make_shared<xarm_msgs::srv::SetInt16::Request>();
      enable->data = 1;
      call<xarm_msgs::srv::SetInt16>(gripper_ + "/set_gripper_enable", enable);
      auto request = std::make_shared<xarm_msgs::srv::GripperMove::Request>();
      request->pos = static_cast<float>(width / 0.085 * 850.0);
      request->wait = true; request->timeout = 10.0;
      call<xarm_msgs::srv::GripperMove>(gripper_ + "/set_gripper_position", request);
    }
  }
  geometry_msgs::msg::Pose pose(double x, double y, double z) {
    json p = {{"x", x}, {"y", y}, {"z", z}};
    if (!rokid::inside(p, lo_, hi_)) throw std::runtime_error("waypoint_outside_workspace");
    geometry_msgs::msg::Pose result;
    result.position.x = x; result.position.y = y; result.position.z = z;
    result.orientation.x = 1.0; result.orientation.w = 0.0;
    return result;
  }
  void move(const geometry_msgs::msg::Pose& target, bool vertical = false) {
    running();
    group_.setStartStateToCurrentState();
    group_.setPoseTarget(target);
    moveit::planning_interface::MoveGroupInterface::Plan plan;
    if (vertical) {
      moveit_msgs::msg::RobotTrajectory trajectory;
      if (group_.computeCartesianPath({target}, 0.005, trajectory, true) < 0.999)
        throw std::runtime_error("vertical_path_incomplete");
      plan.trajectory = trajectory;
    } else if (group_.plan(plan) != moveit::core::MoveItErrorCode::SUCCESS)
        throw std::runtime_error("planning_failed");
    running();
    if (group_.execute(plan) != moveit::core::MoveItErrorCode::SUCCESS)
      throw std::runtime_error("motion_execution_failed");
    running();
  }
  void perform(const json& request) {
    const auto& intent = request.at("intent");
    const auto scene = request.at("scene");
    auto object = rokid::find_id(scene.at("objects"), intent.at("object_id"));
    auto zone = rokid::find_id(scene.at("zones"), intent.at("destination_id"));
    auto p = rokid::xyz(object.at("center")), d = rokid::xyz(zone.at("center"));
    auto size = rokid::xyz(object.at("size"));
    double lift = std::max(p[2] + size[2] / 2, d[2] + size[2]) + 0.10;
    double grasp_width = rokid::number(object.at("grasp_width"));
    // The work table is operator-calibrated; observed objects enter MoveIt's collision world.
    std::vector<std::string> old_ids;
    for (const auto& name : planning_scene_.getKnownObjectNames())
      if (name.starts_with("observed_")) old_ids.push_back(name);
    if (!old_ids.empty()) planning_scene_.removeCollisionObjects(old_ids);
    std::vector<moveit_msgs::msg::CollisionObject> obstacles;
    for (const auto& observed : scene.at("objects")) {
      moveit_msgs::msg::CollisionObject obstacle;
      obstacle.header.frame_id = base_; obstacle.id = "observed_" + observed.at("id").get<std::string>();
      obstacle.operation = moveit_msgs::msg::CollisionObject::ADD;
      shape_msgs::msg::SolidPrimitive box;
      box.type = shape_msgs::msg::SolidPrimitive::BOX;
      auto dims = rokid::xyz(observed.at("size")), point = rokid::xyz(observed.at("center"));
      box.dimensions = {dims[0], dims[1], dims[2]};
      geometry_msgs::msg::Pose origin;
      origin.position.x = point[0]; origin.position.y = point[1]; origin.position.z = point[2];
      origin.orientation.w = 1.0;
      obstacle.primitives.push_back(box); obstacle.primitive_poses.push_back(origin);
      obstacles.push_back(obstacle);
    }
    if (!planning_scene_.applyCollisionObjects(obstacles)) throw std::runtime_error("collision_scene_update_failed");
    auto held_id = "observed_" + object.at("id").get<std::string>();
    grip(width_, false);
    move(pose(p[0], p[1], lift));
    moveit_msgs::msg::CollisionObject contact;
    contact.header.frame_id = base_; contact.id = held_id;
    contact.operation = moveit_msgs::msg::CollisionObject::REMOVE;
    if (!planning_scene_.applyCollisionObject(contact)) throw std::runtime_error("contact_scene_update_failed");
    move(pose(p[0], p[1], p[2]), true);
    grip(grasp_width, true);
    auto held = *std::find_if(obstacles.begin(), obstacles.end(), [&](const auto& item) { return item.id == held_id; });
    if (!planning_scene_.applyCollisionObject(held)) throw std::runtime_error("held_geometry_update_failed");
    std::vector<std::string> touch_links;
    node_->get_parameter_or("touch_links", touch_links, std::vector<std::string>{});
    if (!group_.attachObject(held_id, group_.getEndEffectorLink(), touch_links))
      throw std::runtime_error("attachment_failed");
    move(pose(p[0], p[1], lift), true);
    move(pose(d[0], d[1], lift));
    move(pose(d[0], d[1], d[2] + size[2] / 2 + 0.005), true);
    grip(width_, false);
    if (!group_.detachObject(held_id)) throw std::runtime_error("detachment_failed");
    move(pose(d[0], d[1], lift), true);
    // Motor completion alone does not prove successful placement.
    const double completed_at = now_seconds();
    for (int attempt = 0; attempt < 30; ++attempt) {
      running();
      std::this_thread::sleep_for(100ms);
      std::lock_guard lock(mutex_);
      if (scene_.is_null() || rokid::number(scene_.at("observed_at")) <= completed_at) continue;
      bool destination = false, source_clear = true;
      for (const auto& item : scene_.at("objects")) {
        auto v = rokid::xyz(item.at("center"));
        if (std::hypot(v[0] - p[0], v[1] - p[1]) < 0.025) source_clear = false;
        auto other_size = rokid::xyz(item.at("size"));
        if (std::hypot(v[0] - d[0], v[1] - d[1]) < rokid::number(zone.at("radius")) &&
            std::abs(other_size[0] - size[0]) < 0.015 &&
            std::abs(other_size[1] - size[1]) < 0.015) destination = true;
      }
      if (destination && source_clear) return;
    }
    throw std::runtime_error("placement_not_observed");
  }
public:
  explicit Gateway(rclcpp::Node::SharedPtr node)
    : node_(node), group_(node, node->get_parameter("move_group").as_string()) {
    robot_ = node_->get_parameter("robot").as_string();
    if (robot_ != "fr3" && robot_ != "xarm6") throw std::runtime_error("unsupported_robot");
    base_ = node_->get_parameter("base_frame").as_string();
    gripper_ = node_->get_parameter("gripper_namespace").as_string();
    lo_ = node_->get_parameter("workspace_min").as_double_array();
    hi_ = node_->get_parameter("workspace_max").as_double_array();
    width_ = node_->get_parameter("max_grasp_width").as_double();
    force_ = node_->get_parameter("gripper_force").as_double();
    qualified_ = node_->get_parameter("hardware_qualified").as_bool();
    if (lo_.size() != 3 || hi_.size() != 3) throw std::runtime_error("invalid_workspace");
    agent_token_ = env("ROBOT_GATEWAY_TOKEN"); perception_token_ = env("ROBOT_PERCEPTION_TOKEN");
    if (agent_token_.size() < 32 || perception_token_.size() < 32 || agent_token_ == perception_token_)
      throw std::runtime_error("distinct_strong_credentials_required");
    journal_path_ = env("ROBOT_JOURNAL");
    if (std::filesystem::exists(journal_path_)) {
      std::ifstream in(journal_path_); in >> journal_;
      for (auto& item : journal_.items()) if (item.value().at("state") == "executing")
        item.value()["state"] = "uncertain";
      save();
    }
    group_.setPoseReferenceFrame(base_);
    group_.setMaxVelocityScalingFactor(node_->get_parameter("velocity_scale").as_double());
    group_.setMaxAccelerationScalingFactor(node_->get_parameter("acceleration_scale").as_double());
    group_.setPlanningTime(5.0);
    arm_service_ = node_->create_service<std_srvs::srv::Trigger>("~/arm",
      [this](const std_srvs::srv::Trigger::Request::SharedPtr,
             std_srvs::srv::Trigger::Response::SharedPtr response) {
        std::lock_guard lock(mutex_);
        bool unresolved = false;
        for (const auto& record : journal_) unresolved |= record.at("state") == "uncertain";
        response->success = qualified_ && !busy_ && !unresolved && !scene_.is_null() &&
          scene_.value("calibrated", false) && steady_seconds() - heartbeat_ < 2 &&
          now_seconds() - scene_.value("observed_at", 0.0) < 2;
        if (response->success) { stopped_ = false; armed_ = true; }
        response->message = response->success ? "armed" : "qualification_or_reconciliation_required";
      });
    reconcile_service_ = node_->create_service<std_srvs::srv::Trigger>("~/reconcile",
      [this](const std_srvs::srv::Trigger::Request::SharedPtr,
             std_srvs::srv::Trigger::Response::SharedPtr response) {
        std::lock_guard lock(mutex_);
        if (busy_ || armed_) { response->success = false; response->message = "stop_first"; return; }
        // Explicit local operator attestation after inspecting the arm and any held object.
        for (auto& record : journal_) if (record.at("state") == "uncertain") {
          record["state"] = "failed";
          record["reason"] = "operator_reconciled_after_physical_inspection";
        }
        save(); response->success = true; response->message = "reconciled_still_disarmed";
      });
    watchdog_ = std::jthread([this](std::stop_token stop_token) {
      while (!stop_token.stop_requested()) {
        bool scene_lost = false;
        { std::lock_guard lock(mutex_);
          scene_lost = scene_.is_null() || !scene_.value("calibrated", false) ||
            now_seconds() - scene_.value("observed_at", 0.0) > 2;
        }
        if (armed_ && (steady_seconds() - heartbeat_ > 2 || scene_lost)) stop();
        std::this_thread::sleep_for(50ms);
      }
    });
  }
  void stop() { armed_ = false; stopped_ = true; group_.stop(); }
  ~Gateway() { watchdog_.request_stop(); stop(); if (worker_.joinable()) worker_.join(); }

  void serve() {
    auto cert = env("ROBOT_TLS_CERT"), key = env("ROBOT_TLS_KEY");
    httplib::SSLServer server(cert.c_str(), key.c_str());
    if (!server.is_valid()) throw std::runtime_error("invalid_TLS_identity");
    server.set_payload_max_length(256000);
    server.set_exception_handler([](const auto&, auto& response, std::exception_ptr ep) {
      response.status = 409;
      try { std::rethrow_exception(ep); }
      catch (const std::exception&) {
        response.set_content("{\"error\":\"request_rejected\"}", "application/json");
      }
    });
    server.set_pre_routing_handler([this](const auto& request, auto& response) {
      bool perception = request.path == "/v1/scene" && request.method == "POST";
      if (!authorized(request, perception)) {
        response.status = 401;
        return httplib::Server::HandlerResponse::Handled;
      }
      return httplib::Server::HandlerResponse::Unhandled;
    });
    server.Get("/v1/capabilities", [this](const auto&, auto& response) {
      json result = {{"robot", robot_}, {"actions", {"pick_place"}}, {"frame_id", "robot_base"},
        {"min_corner", {{"x",lo_[0]}, {"y",lo_[1]}, {"z",lo_[2]}}},
        {"max_corner", {{"x",hi_[0]}, {"y",hi_[1]}, {"z",hi_[2]}}},
        {"max_grasp_width",width_}, {"hardware_qualified",qualified_}};
      response.set_content(result.dump(), "application/json");
    });
    server.Post("/v1/heartbeat", [this](const auto&, auto& response) {
      heartbeat_ = steady_seconds(); response.set_content("{}", "application/json");
    });
    server.Post("/v1/stop", [this](const auto&, auto& response) {
      stop(); response.set_content("{}", "application/json");
    });
    server.Post("/v1/scene", [this](const auto& request, auto& response) {
      auto incoming = json::parse(request.body);
      rokid::check_scene(incoming);
      auto age = now_seconds() - rokid::number(incoming.at("observed_at"));
      if (age < -0.1 || age > 1) throw std::runtime_error("scene_clock_not_synchronized");
      std::lock_guard lock(mutex_);
      scene_ = std::move(incoming); response.set_content("{}", "application/json");
    });
    server.Get("/v1/scene", [this](const auto&, auto& response) {
      std::lock_guard lock(mutex_);
      if (scene_.is_null()) throw std::runtime_error("scene_not_available");
      response.set_content(scene_.dump(), "application/json");
    });
    server.Get(R"(/v1/operations/([a-f0-9]{32}))", [this](const auto& request, auto& response) {
      std::lock_guard lock(mutex_);
      auto id = request.matches[1].str();
      if (!journal_.contains(id)) { response.status = 404; return; }
      json result = journal_.at(id); result.erase("request");
      response.set_content(result.dump(), "application/json");
    });
    server.Post("/v1/operations", [this](const auto& request, auto& response) {
      auto operation = json::parse(request.body);
      std::string id = operation.at("operation_id");
      if (!std::regex_match(id, std::regex("[a-f0-9]{32}"))) throw std::runtime_error("invalid_id");
      std::unique_lock lock(mutex_);
      if (journal_.contains(id)) {
        if (journal_.at(id).at("request") != operation) throw std::runtime_error("idempotency_conflict");
        auto result = journal_.at(id); result.erase("request");
        response.set_content(result.dump(), "application/json"); return;
      }
      running();
      if (busy_) throw std::runtime_error("robot_busy");
      if (!planning_scene_.getObjects({"work_table"}).contains("work_table"))
        throw std::runtime_error("calibrated_work_table_collision_required");
      rokid::check_request(operation, scene_, now_seconds(), lo_, hi_, width_);
      busy_ = true;
      journal_[id] = {{"operation_id",id}, {"state","executing"}, {"reason",nullptr}, {"request",operation}};
      save();
      // Execute only geometry received from the independently authenticated camera producer.
      auto execution = operation;
      execution["scene"] = scene_;
      lock.unlock();
      if (worker_.joinable()) worker_.join();
      worker_ = std::jthread([this, execution, id] {
        std::string state = "succeeded", reason;
        try { perform(execution); }
        catch (const std::exception& error) {
          state = "uncertain"; reason = error.what(); stop();
        }
        std::lock_guard guard(mutex_);
        journal_[id]["state"] = state;
        journal_[id]["reason"] = reason.empty() ? json(nullptr) : json(reason);
        try { save(); }
        catch (const std::exception&) {
          stop(); RCLCPP_ERROR(node_->get_logger(), "journal_write_failed_operator_reconciliation_required");
        }
        busy_ = false;
      });
      response.set_content(json({{"operation_id",id}, {"state","executing"}, {"reason",nullptr}}).dump(), "application/json");
    });
    const char* address = std::getenv("ROBOT_BIND");
    if (!server.listen(address ? address : "127.0.0.1", 8770)) throw std::runtime_error("listen_failed");
  }
};

int main(int argc, char** argv) {
  rclcpp::init(argc, argv);
  auto node = std::make_shared<rclcpp::Node>("robot_gateway",
    rclcpp::NodeOptions().automatically_declare_parameters_from_overrides(true));
  rclcpp::executors::MultiThreadedExecutor executor;
  executor.add_node(node);
  std::jthread spin([&] { executor.spin(); });
  int result = 0;
  try { Gateway gateway(node); gateway.serve(); }
  catch (const std::exception& error) { RCLCPP_ERROR(node->get_logger(), "%s", error.what()); result = 1; }
  executor.cancel(); rclcpp::shutdown();
  return result;
}
