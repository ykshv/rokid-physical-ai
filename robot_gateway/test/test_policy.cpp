#include <gtest/gtest.h>
#include "policy.hpp"

TEST(Policy, RejectsNonfiniteCoordinates) {
  EXPECT_THROW(rokid::number(rokid::json("NaN")), std::runtime_error);
}
TEST(Policy, WorkspaceBoundsAreInclusive) {
  rokid::json point = {{"x", 0.2}, {"y", 0.0}, {"z", 0.1}};
  EXPECT_TRUE(rokid::inside(point, {0.2, -0.1, 0.0}, {0.5, 0.1, 0.2}));
  point["x"] = 0.19;
  EXPECT_FALSE(rokid::inside(point, {0.2, -0.1, 0.0}, {0.5, 0.1, 0.2}));
}
