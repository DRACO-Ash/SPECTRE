import sys; sys.path.insert(0, sys.argv[1])
from spectre.web.log_safety import log_safe
for n in range(0,5): r = log_safe("abcdefghij", limit=n); print(n, repr(r), len(r))
