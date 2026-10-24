import sys
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
from spectre.astro.dv_estimation import _j2_argp_rate_deg_day, _j2_raan_rate_deg_day
print("argp 550km 53deg:", _j2_argp_rate_deg_day(6928.137, 0.0, 53.0))
print("raan ISS a=6778 i=51.6:", _j2_raan_rate_deg_day(6778.0, 0.0, 51.6))
