#pragma once

#include <array>
#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <string>
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
  return {number(p.at("x")), number(p.at("y")), number(p.at("z"))};
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
inline void check_request(const json& request, const json& scene, double now,
                          const std::vector<double>& lo, const std::vector<double>& hi,
                          double max_width) {
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
