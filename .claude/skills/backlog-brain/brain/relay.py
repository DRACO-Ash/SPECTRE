"""Relay helper: send a message to the threads a thread has a relationship to (VH-366-F).

Relays used to depend on session ids held in memory. This reads the threads and links the board holds and works out
who to poke from a relationship ("feeds work to", "is the prime development thread for", and so on), so the target is
never typed by hand. It builds the poke request; the session tool sends it (a Routine with no schedule, bound to the
target session, fired once, then deleted).

It enforces the same bound as the owner's standing approval: a poke from a registered thread to a different registered
thread with a valid session id. Anything else is returned as needing the owner and is not sent. The message is stamped
with the clock at the moment of building, never a time the caller supplies, so a relay cannot carry a time ahead of
the clock. Standard library only.
"""
import datetime
import re

SESSION = re.compile(r"^session_[A-Za-z0-9]{10,40}$")
ALLOWED_KINDS = ("poke",)


def session_of(thread):
    sid = thread.get("sessionId") or ""
    if not sid:
        url = thread.get("url") or ""
        sid = url.rstrip("/").rsplit("/", 1)[-1] if "/session_" in url else ""
    return sid if SESSION.match(sid) else ""


def check(threads, src, dst, kind="poke"):
    """The target session id, or ValueError saying why the relay needs the owner."""
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"'{kind}' is not covered by the standing approval (only: {', '.join(ALLOWED_KINDS)})")
    for label, key in (("from", src), ("to", dst)):
        if key not in threads:
            raise ValueError(f"{label} '{key}' is not a registered thread")
    if src == dst:
        raise ValueError("a thread does not poke itself")
    if not session_of(threads[src]):
        raise ValueError(f"thread '{src}' has no valid session id on the board")
    sid = session_of(threads[dst])
    if not sid:
        raise ValueError(f"thread '{dst}' has no valid session id on the board")
    return sid


def targets(threads, links, src, relation):
    """Thread keys src has the given relationship to, in the board's own order. A link to a key that is not a thread is ignored here."""
    seen, out = set(), []
    for l in links.values():
        if l.get("from") == src and l.get("kind") == relation and l.get("to") in threads and l["to"] not in seen:
            seen.add(l["to"])
            out.append(l["to"])
    return sorted(out, key=lambda k: (threads[k].get("order", 99), k))


def stamp(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%H:%M UTC %Y-%m-%d")


def poke_requests(threads, links, src, relation, message, now=None):
    """Returns (requests, needs_owner). One request per reachable target; a target that fails the bound is listed in
    needs_owner with the reason and nothing is built for it."""
    if not isinstance(message, str) or not message.strip():
        raise ValueError("a relay needs a message")
    if src not in threads:
        raise ValueError(f"from '{src}' is not a registered thread")
    reqs, owner = [], []
    who = threads[src].get("name", src)
    for dst in targets(threads, links, src, relation):
        try:
            sid = check(threads, src, dst)
        except ValueError as e:
            owner.append({"to": dst, "why": str(e)})
            continue
        to_name = threads[dst].get("name", dst)
        reqs.append({"to": dst, "session_id": sid,
                     "arguments": {"name": f"{relation} relay to {to_name}"[:80],
                                   "prompt": f"From the {who} thread, {stamp(now)}. {message.strip()}",
                                   "persistent_session_id": sid, "initiation": "human_request"}})
    if not reqs and not owner:
        owner.append({"to": None, "why": f"'{src}' has no '{relation}' link to a registered thread"})
    return reqs, owner
