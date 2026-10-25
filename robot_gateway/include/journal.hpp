#pragma once

#include <string>
#include <nlohmann/json.hpp>

namespace rokid {
// The caller holds the journal lock and latches motion if persistence throws.
// An in-memory result must not look successful when its durable write failed.
template<class Persist>
void persist_operation_state(nlohmann::json& record, const std::string& state,
                             const nlohmann::json& reason, Persist persist) {
  record["state"] = state;
  record["reason"] = reason;
  try { persist(); }
  catch (...) {
    record["state"] = "uncertain";
    record["reason"] = "journal_write_failed_operator_reconciliation_required";
    throw;
  }
}
} // namespace rokid
