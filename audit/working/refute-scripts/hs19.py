import sys; sys.path.insert(0,"/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
from spectre.web.log_safety import log_safe
for lim in range(0,5):
    r=log_safe("abcdefghij", limit=lim)
    print(f"limit={lim} -> {r!r} len={len(r)} (violates if len>limit)")
