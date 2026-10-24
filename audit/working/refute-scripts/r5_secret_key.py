"""R5: run validate_secret_key on the README placeholder (F-S10-04) and the .env.example variant."""
import sys, os
sys.path.insert(0, sys.argv[1])
os.environ["SECRET_KEY"] = "ci-only-ephemeral-signing-key-not-a-secret"
from spectre.config.settings import validate_secret_key
for k in ["change-me-to-a-long-random-string", "change-me-to-a-random-string", "change-me"]:
    try:
        r = validate_secret_key(k)
        print(repr(k), "ACCEPTED ->", repr(r)[:60])
    except Exception as e:
        print(repr(k), "REFUSED", type(e).__name__, e)
