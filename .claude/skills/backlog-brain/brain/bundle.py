"""The whole board as one file, and back (VH-366-E): export, import, and the degrade path when the store is unavailable.

A bundle is {schema, exported_at, collections: {name: {doc id: fields}}, counts, sha256}. Importing refuses the whole
bundle on any problem (wrong schema, a count that does not match, a hash that does not match), and never half applies one.
Standard library only.
"""
import hashlib
import json
import os
import tempfile

SCHEMA = 1
NAMES = ("items", "plan", "gates", "releases", "accuracy", "threads", "links", "intake", "board")
# Of the board collection only the header and the page's settings travel (VH-584). board/standing holds one project's
# standing approvals and rules, which must never reach another project's board through an export.
BOARD_DOCS = ("meta", "settings")


def _digest(collections):
    return hashlib.sha256(json.dumps(collections, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_dump(folder, names=NAMES):
    """Collections from a folder of per-collection folders of JSON documents. A missing collection is left out, not invented."""
    out = {}
    for name in names:
        d = os.path.join(folder, name)
        if not os.path.isdir(d):
            continue
        docs = {}
        for f in sorted(os.listdir(d)):
            if name == "board" and f[:-5] not in BOARD_DOCS:
                continue
            if f.endswith(".json"):
                x = json.load(open(os.path.join(d, f)))
                docs[f[:-5]] = x.get("data", x) if isinstance(x, dict) else x
        out[name] = docs
    return out


def export_board(collections, now):
    c = {k: collections[k] for k in sorted(collections)}
    return {"schema": SCHEMA, "exported_at": now, "collections": c, "counts": {k: len(v) for k, v in c.items()}, "sha256": _digest(c)}


def import_board(bundle):
    """Returns (collections, problems). Any problem and the collections come back empty."""
    problems = []
    if not isinstance(bundle, dict):
        return {}, ["the file is not a bundle"]
    if bundle.get("schema") != SCHEMA:
        problems.append(f"schema is {bundle.get('schema')!r}, this pack reads {SCHEMA}")
    c = bundle.get("collections")
    if not isinstance(c, dict) or not c:
        problems.append("it holds no collections")
        return {}, problems
    for k, v in c.items():
        if not isinstance(v, dict):
            problems.append(f"collection {k} is not a set of documents")
    counts = bundle.get("counts") or {}
    for k, v in c.items():
        if isinstance(v, dict) and counts.get(k) != len(v):
            problems.append(f"collection {k} holds {len(v)} documents but the count says {counts.get(k)}")
    if bundle.get("sha256") != _digest(c):
        problems.append("the checksum does not match: the file was changed or cut short")
    return ({}, problems) if problems else (c, [])


def write_dump(folder, collections):
    """Writes a bundle's collections as a dump. Refuses a folder that already holds any collection, so nothing is overwritten."""
    for name in collections:
        if os.path.exists(os.path.join(folder, name)):
            raise FileExistsError(f"{os.path.join(folder, name)} already exists; import into an empty folder")
    for name, docs in collections.items():
        d = os.path.join(folder, name)
        os.makedirs(d)
        for ref, doc in docs.items():
            json.dump({"data": doc}, open(os.path.join(d, ref + ".json"), "w"), indent=1, sort_keys=True)


def save(path, obj):
    """Writes beside the target and renames over, so a failed write leaves the old file whole."""
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".bundle-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
