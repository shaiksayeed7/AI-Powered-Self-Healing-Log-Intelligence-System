"""Remediation fix suggester based on RCA results."""
from typing import List


_FIX_MAP = {
    "DB overload": {
        "actions": [
            {"priority": 1, "action": "Restart payment-api service", "command": "systemctl restart payment-api"},
            {"priority": 2, "action": "Increase DB connection pool size", "command": ""},
            {"priority": 3, "action": "Scale replicas from 3 → 6", "command": "kubectl scale deployment payment-api --replicas=6"},
            {"priority": 4, "action": "Enable DB query caching", "command": ""},
        ],
        "auto_executable": False,
    },
    "Memory saturation": {
        "actions": [
            {"priority": 1, "action": "Trigger garbage collection / heap dump", "command": "kill -s SIGUSR1 $(pgrep -f payment-api)"},
            {"priority": 2, "action": "Increase memory limits in pod spec", "command": "kubectl patch deployment payment-api -p '{\"spec\":{\"template\":{\"spec\":{\"containers\":[{\"name\":\"payment-api\",\"resources\":{\"limits\":{\"memory\":\"2Gi\"}}}]}}}}'"},
            {"priority": 3, "action": "Rolling restart to clear memory leaks", "command": "kubectl rollout restart deployment payment-api"},
        ],
        "auto_executable": False,
    },
    "Auth service failure": {
        "actions": [
            {"priority": 1, "action": "Restart auth-service", "command": "systemctl restart auth-service"},
            {"priority": 2, "action": "Check token expiry configuration", "command": ""},
            {"priority": 3, "action": "Switch to backup auth provider", "command": ""},
        ],
        "auto_executable": False,
    },
    "Network connectivity issue": {
        "actions": [
            {"priority": 1, "action": "Check DNS resolution", "command": "nslookup internal-service"},
            {"priority": 2, "action": "Verify firewall / security group rules", "command": ""},
            {"priority": 3, "action": "Restart network interfaces on affected nodes", "command": ""},
        ],
        "auto_executable": False,
    },
    "Resource exhaustion": {
        "actions": [
            {"priority": 1, "action": "Kill runaway processes", "command": "top -b -n1 | head -20"},
            {"priority": 2, "action": "Scale up cluster nodes", "command": "kubectl scale nodepool default --node-count 5"},
            {"priority": 3, "action": "Free disk space (remove old logs)", "command": "find /var/log -name '*.log' -mtime +7 -delete"},
        ],
        "auto_executable": False,
    },
}

_DEFAULT_ACTIONS = [
    {"priority": 1, "action": "Investigate recent deployments for regressions", "command": ""},
    {"priority": 2, "action": "Review recent log spikes in monitoring dashboard", "command": ""},
    {"priority": 3, "action": "Alert on-call engineer", "command": ""},
]


class FixSuggester:
    """Generates remediation suggestions from RCA results."""

    def suggest_fixes(self, rca_result: dict, anomalies: List[dict]) -> dict:
        cause = rca_result.get("cause", "")
        severity = rca_result.get("severity", "MEDIUM")

        fix_template = _FIX_MAP.get(cause)
        if fix_template:
            actions = list(fix_template["actions"])
            auto_executable = fix_template["auto_executable"]
        else:
            actions = list(_DEFAULT_ACTIONS)
            auto_executable = False

        # Append service-specific restart if we know the affected service
        affected = rca_result.get("affected_services", [])
        for svc in affected:
            actions.append({
                "priority": len(actions) + 1,
                "action": f"Monitor {svc} error rate after applying fixes",
                "command": f"kubectl logs -f deployment/{svc} --tail=100",
            })

        return {
            "cause": cause,
            "severity": severity,
            "actions": actions,
            "auto_executable": auto_executable,
        }
