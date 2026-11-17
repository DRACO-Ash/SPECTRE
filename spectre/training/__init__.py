"""SPECTRE Gamified Training Environment.

Training routes access:
  - spectre/training/config/*.yaml  (read-only scenario + gamification config)
  - training_* database tables   (per-operator progress, scores, sessions)
  - the operator's SessionState, to which a scenario adds its synthetic
    objects, tagged ``training=True`` and removed when the scenario ends
    (Submit, Reset, Abandon or the next start) and when the operator leaves
    training by any route; and whose scenario time a scenario sets to its
    epoch until the operator leaves.

They never touch operational TLE sources or UDL credentials. An earlier
version of this note said they never touch SessionState (audit F-051).
"""
