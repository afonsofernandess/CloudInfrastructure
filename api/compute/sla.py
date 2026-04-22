"""
SLA (Service Level Agreement) policy for the elastic compute service.

Rules:
- Always keep at least MIN_VMS running so users get resources immediately.
- Never exceed MAX_VMS regardless of load (cost/resource cap).
- Scale up when average CPU across all active VMs exceeds SCALE_UP_CPU_PCT.
- Scale down when average CPU drops below SCALE_DOWN_CPU_PCT.
- A VM must be idle for SCALE_DOWN_WINDOW_SEC before it is torn down (avoids flapping).
- The autoscaler checks every CHECK_INTERVAL_SEC seconds.
"""

MIN_VMS = 1                  # minimum VMs always kept alive
MAX_VMS = 5                  # hard ceiling
SCALE_UP_CPU_PCT = 70.0     # scale up when avg CPU > 70%
SCALE_DOWN_CPU_PCT = 20.0    # scale down when avg CPU < 20%
SCALE_DOWN_WINDOW_SEC = 120  # VM must be idle for 2 min before teardown
CHECK_INTERVAL_SEC = 30      # autoscaler loop interval
DEFAULT_TEMPLATE_ID = 0      # Alpine Linux 3.20
