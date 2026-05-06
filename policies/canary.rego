# policies/canary.rego
# Domain: Canary service health
# Question: Is the canary healthy enough to promote?
# Data it owns: error_rate, p99_latency_ms

package swiftdeploy.canary

import future.keywords.if
import future.keywords.contains

# ── thresholds from data, not hardcoded ────────────────────────
max_error_rate    := data.thresholds.canary.max_error_rate_percent
max_p99_latency   := data.thresholds.canary.max_p99_latency_ms
min_sample_count  := data.thresholds.canary.min_sample_count

# ── default deny ───────────────────────────────────────────────
default allow := false

allow if {
    count(violations) == 0
}

# ── individual violation rules ─────────────────────────────────
violations contains msg if {
    input.error_rate_percent > max_error_rate
    msg := sprintf(
        "Error rate %.2f%% exceeds maximum %.2f%%",
        [input.error_rate_percent, max_error_rate]
    )
}

violations contains msg if {
    input.p99_latency_ms > max_p99_latency
    msg := sprintf(
        "P99 latency %.0fms exceeds maximum %.0fms",
        [input.p99_latency_ms, max_p99_latency]
    )
}

violations contains msg if {
    input.sample_count < min_sample_count
    msg := sprintf(
        "Insufficient samples: %d (need at least %d)",
        [input.sample_count, min_sample_count]
    )
}

violations contains msg if {
    input.chaos_active != 0
    msg := sprintf(
        "Chaos is still active (code %d) — recover before promoting",
        [input.chaos_active]
    )
}

# ── decision output ────────────────────────────────────────────
decision := {
    "allow":      allow,
    "domain":     "canary",
    "violations": violations,
    "reason":     reason,
} if {
    allow
    reason := sprintf(
        "Canary healthy: error_rate=%.2f%% p99=%.0fms samples=%d",
        [input.error_rate_percent, input.p99_latency_ms, input.sample_count]
    )
} else := {
    "allow":      false,
    "domain":     "canary",
    "violations": violations,
    "reason":     sprintf("Canary blocked by %d violation(s)", [count(violations)]),
}
