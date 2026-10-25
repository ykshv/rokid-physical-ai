#pragma once

#include <array>
#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <string>
#include <set>
#include <regex>
#include <nlohmann/json.hpp>

namespace rokid {
using json = nlohmann::json;

inline double number(const json& value) {
  if (!value.is_number()) throw std::runtime_error("number_required");
  double n = value.get<double>();
  if (!std::isfinite(n)) throw std::runtime_error("finite_number_required");
  return n;
}
inline std::array<double, 3> xyz(const json& p) {
  if (!p.is_object() || p.size() != 3) throw std::runtime_error("invalid_vector");
  return {number(p.at("x")), number(p.at("y")), number(p.at("z"))};
}
inline void fields(const json& value, std::initializer_list<std::string> allowed) {
  if (!value.is_object()) throw std::runtime_error("object_required");
  for (const auto& item : value.items())
    if (std::find(allowed.begin(), allowed.end(), item.key()) == allowed.end())
      throw std::runtime_error("unknown_contract_field");
}
inline void identifier(const json& value) {
  static const std::regex pattern("[a-zA-Z0-9_-]{1,80}");
  if (!value.is_string() || !std::regex_match(value.get<std::string>(), pattern))
    throw std::runtime_error("invalid_identifier");
}
inline void label(const json& value) {
  if (!value.is_string()) throw std::runtime_error("invalid_label");
  const auto& text = value.get_ref<const std::string&>();
  // JSON parsing validates UTF-8; count code points, not bytes, for Russian labels.
  auto length = std::count_if(text.begin(), text.end(), [](unsigned char c) { return (c & 0xC0) != 0x80; });
  if (length < 1 || length > 80) throw std::runtime_error("invalid_label");
}
inline bool inside(const json& p, const std::vector<double>& lo, const std::vector<double>& hi) {
  auto v = xyz(p);
  for (int i = 0; i < 3; ++i) if (v[i] < lo.at(i) || v[i] > hi.at(i)) return false;
  return true;
}
inline json find_id(const json& collection, const std::string& id) {
  for (const auto& object : collection) if (object.at("id") == id) return object;
  throw std::runtime_error("unknown_scene_id");
}
inline void check_scene(const json& scene) {
  fields(scene, {"version", "frame_id", "calibrated", "revision", "calibration_id",
                 "observed_at", "objects", "zones"});
  if (scene.at("version") != 1 || scene.at("frame_id") != "robot_base" ||
      !scene.at("calibrated").is_boolean() || !scene.at("revision").is_string() ||
      !scene.at("calibration_id").is_string() || !scene.at("objects").is_array() ||
      !scene.at("zones").is_array() || scene.at("objects").size() > 20 ||
      scene.at("zones").empty() || scene.at("zones").size() > 10)
    throw std::runtime_error("invalid_scene");
  number(scene.at("observed_at"));
  identifier(scene.at("revision"));
  identifier(scene.at("calibration_id"));
  std::set<std::string> ids;
  for (const auto* collection : {&scene.at("objects"), &scene.at("zones")}) {
    for (const auto& entry : *collection) {
      auto id = entry.at("id").get<std::string>();
      identifier(entry.at("id"));
      label(entry.at("label"));
      if (!ids.insert(id).second)
        throw std::runtime_error("invalid_scene_id");
      xyz(entry.at("center"));
      if (collection == &scene.at("objects")) {
        fields(entry, {"id", "label", "center", "size", "yaw", "grasp_width"});
        auto dims = xyz(entry.at("size"));
        double width = number(entry.at("grasp_width"));
        if (*std::min_element(dims.begin(), dims.end()) <= 0 || width <= 0 || width > 0.2)
          throw std::runtime_error("invalid_object_geometry");
        if (entry.contains("yaw")) number(entry.at("yaw"));
      } else {
        fields(entry, {"id", "label", "center", "radius"});
        double radius = number(entry.at("radius"));
        if (radius <= 0 || radius > 0.5) throw std::runtime_error("invalid_zone");
      }
    }
  }
}
inline void check_request(const json& request, const json& scene, double now,
                          const std::vector<double>& lo, const std::vector<double>& hi,
                          double max_width) {
  check_scene(scene);
  if (request.at("version") != 1 || !scene.at("calibrated").get<bool>())
    throw std::runtime_error("uncalibrated_or_unsupported_version");
  auto age = now - number(scene.at("observed_at"));
  if (age < 0 || age > 2 || number(request.at("expires_at")) < now ||
      number(request.at("expires_at")) > now + 3) throw std::runtime_error("expired_scene_or_request");
  if (request.at("scene").at("calibration_id") != scene.at("calibration_id") ||
      request.at("intent").at("scene_revision") != scene.at("revision"))
    throw std::runtime_error("scene_changed");
  const auto& intent = request.at("intent");
  if (intent.at("action") != "pick_place") throw std::runtime_error("unsupported_action");
  auto object = find_id(scene.at("objects"), intent.at("object_id"));
  auto zone = find_id(scene.at("zones"), intent.at("destination_id"));
  double width = number(object.at("grasp_width"));
  if (width <= 0 || width + 0.01 > max_width) throw std::runtime_error("grasp_width_limit");
  if (!inside(object.at("center"), lo, hi) || !inside(zone.at("center"), lo, hi))
    throw std::runtime_error("outside_workspace");
  auto size = xyz(object.at("size"));
  if (*std::min_element(size.begin(), size.end()) <= 0 ||
      *std::max_element(size.begin(), size.end()) > 0.15)
    throw std::runtime_error("unsupported_object_dimensions");
  if (number(zone.at("radius")) < std::hypot(size[0], size[1]) / 2)
    throw std::runtime_error("placement_zone_too_small");
  auto destination = xyz(zone.at("center")), source = xyz(object.at("center"));
  if (std::hypot(destination[0] - source[0], destination[1] - source[1]) < 0.08)
    throw std::runtime_error("source_destination_overlap");
  for (const auto& other : scene.at("objects")) {
    if (other.at("id") == object.at("id")) continue;
    auto p = xyz(other.at("center")), extent = xyz(other.at("size"));
    double clearance = std::hypot(size[0], size[1])/2 + std::hypot(extent[0], extent[1])/2 + 0.05;
    if (std::hypot(p[0]-source[0], p[1]-source[1]) < clearance ||
        std::hypot(p[0]-destination[0], p[1]-destination[1]) < clearance)
      throw std::runtime_error("pick_or_place_not_isolated");
  }
}
} // namespace rokid
