# policies/infrastructure.rego
# Domain: Host infrastructure safety
# Question: Is this host safe to deploy onto?
# Data it owns: disk_free_gb, cpu_load, mem_free_percent

package swiftdeploy.infrastructure

import future.keywords.if
import future.keywords.contains

# ── thresholds come from policy data, never hardcoded ─────────
min_disk_gb       := data.thresholds.infrastructure.min_disk_free_gb
max_cpu_load      := data.thresholds.infrastructure.max_cpu_load
min_mem_percent   := data.thresholds.infrastructure.min_mem_free_percent

# ── default deny ───────────────────────────────────────────────
default allow := false

allow if {
    count(violations) == 0
}

# ── individual violation rules ─────────────────────────────────
violations contains msg if {
    input.disk_free_gb < min_disk_gb
    msg := sprintf(
        "Disk free %.1fGB is below minimum %.1fGB",
        [input.disk_free_gb, min_disk_gb]
    )
}

violations contains msg if {
    input.cpu_load > max_cpu_load
    msg := sprintf(
        "CPU load %.2f exceeds maximum %.2f",
        [input.cpu_load, max_cpu_load]
    )
}

violations contains msg if {
    input.mem_free_percent < min_mem_percent
    msg := sprintf(
        "Memory free %.1f%% is below minimum %.1f%%",
        [input.mem_free_percent, min_mem_percent]
    )
}

# ── decision output — never a bare boolean ─────────────────────
decision := {
    "allow":      allow,
    "domain":     "infrastructure",
    "violations": violations,
    "reason":     reason,
} if {
    allow
    reason := "All infrastructure checks passed"
} else := {
    "allow":      false,
    "domain":     "infrastructure",
    "violations": violations,
    "reason":     sprintf("Blocked by %d infrastructure violation(s)", [count(violations)]),
}
