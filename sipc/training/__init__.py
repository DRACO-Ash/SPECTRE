"""SIPC Gamified Training Environment.

Completely isolated from operational data.  Training routes only access:
  - sipc/training/config/*.yaml  (read-only scenario + gamification config)
  - training_* database tables   (per-operator progress, scores, sessions)

They never touch SessionState, operational TLEs, or UDL credentials.
"""
