"""Idle detector for the hourly board sync (owner instruction, 2026-10-02: if nothing has changed in 3 hourly
checks, pause automatically until activity restarts).

WHAT COUNTS AS A CHANGE. A fingerprint of everything the sync reads, taken from the dump the run has just made:
delivery's head commit, and the content of every document in gates, items, plan, releases, accuracy, threads, links
and intake, plus board/meta with the sync's own bookkeeping removed. The fingerprint is compared with the one stored
in board/meta at the end of the previous run. It is computed the same way every time, so the decision is mechanical.

FAILS CLOSED. A missing collection, an empty one that should not be, or an unreadable file means the run cannot say
that nothing changed, so it reports a change and never pauses. A pause that rested on a partial read would hide
activity, which is the failure this exists to avoid.

USAGE
  brain.py idle --dump DIR --sha SHA --meta FILE [--threshold 3] [--now ISO]
    prints JSON: fingerprint, changed, idleChecks, pause, metaUpdate (what to write to board/meta).
    Run it at the start of a run to decide, and again after any write the run made with --store, so a run that
    wrote something is stored as the new baseline and does not make the next run look like a change.
  brain.py idle --selftest
"""
import argparse, datetime, hashlib, json, os

COLLECTIONS = ('gates', 'items', 'plan', 'releases', 'accuracy', 'threads', 'links', 'intake')
OWN_META_KEYS = ('pipelineSyncedAt', 'pipelineSyncedFrom', 'pipelineNote', 'updatedAt', 'idleChecks', 'syncFingerprint',
                 'syncPaused', 'pausedAt', 'lastChangeAt', 'pauseEnabled')


def _load_collection(dump, name):
    d = os.path.join(dump, name)
    if not os.path.isdir(d):
        raise ValueError(f'collection {name} was not dumped')
    out = {}
    for f in sorted(os.listdir(d)):
        if f.endswith('.json'):
            x = json.load(open(os.path.join(d, f)))
            out[f[:-5]] = x.get('data', x)
    return out


def fingerprint(dump, sha, meta):
    """Hash of delivery's head and every document the sync reads. Raises ValueError when the read is incomplete."""
    if not sha or not str(sha).strip():
        raise ValueError('no delivery head SHA')
    h = hashlib.sha256()
    h.update(('sha:' + str(sha).strip() + '\n').encode())
    for name in COLLECTIONS:
        docs = _load_collection(dump, name)
        if name in ('items', 'plan') and not docs:
            raise ValueError(f'collection {name} is empty, which is not a real board')
        for k in sorted(docs):
            h.update((name + '/' + k + '=' + json.dumps(docs[k], sort_keys=True, ensure_ascii=False) + '\n').encode())
    m = {k: v for k, v in (meta or {}).items() if k not in OWN_META_KEYS}
    h.update(('meta=' + json.dumps(m, sort_keys=True, ensure_ascii=False) + '\n').encode())
    return h.hexdigest()


def decide(prev_meta, fp, threshold=3, now=None, store=False):
    """The next idle count and what to write. store=True records fp as the new baseline without counting a check."""
    prev_meta = prev_meta or {}
    same = prev_meta.get('syncFingerprint') == fp
    n = int(prev_meta.get('idleChecks') or 0)
    stamp = (now or datetime.datetime.now(datetime.timezone.utc)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    if store:
        return {'changed': not same, 'idleChecks': n if same else 0, 'pause': False,
                'metaUpdate': {'syncFingerprint': fp, 'idleChecks': n if same else 0}}
    if not same:
        return {'changed': True, 'idleChecks': 0, 'pause': False,
                'metaUpdate': {'syncFingerprint': fp, 'idleChecks': 0, 'lastChangeAt': stamp, 'syncPaused': False}}
    n += 1
    pause = n >= threshold
    upd = {'idleChecks': n}
    if pause:
        upd.update({'syncPaused': True, 'pausedAt': stamp})
    return {'changed': False, 'idleChecks': n, 'pause': pause, 'metaUpdate': upd}


def selftest():
    import tempfile, shutil
    root = tempfile.mkdtemp()
    try:
        def build(items=None, intake=None, drop=None, empty_items=False):
            d = tempfile.mkdtemp(dir=root)
            for c in COLLECTIONS:
                if c == drop:
                    continue
                os.makedirs(os.path.join(d, c))
            docs = {'items': items if items is not None else {'VH-1': {'minutes': 5}}, 'plan': {'r': {'name': 'V2.7'}},
                    'intake': intake or {}}
            if empty_items:
                docs['items'] = {}
            for c, kv in docs.items():
                if c == drop:
                    continue
                for k, v in kv.items():
                    json.dump(v, open(os.path.join(d, c, k + '.json'), 'w'))
            return d
        meta = {'currentRelease': 'V2.7', 'updatedAt': 'x'}
        a = fingerprint(build(), 'abc', meta)
        assert a == fingerprint(build(), 'abc', dict(meta, updatedAt='y', pipelineSyncedAt='z', idleChecks=2)), 'own bookkeeping changed the fingerprint'
        assert a != fingerprint(build(), 'abd', meta), 'a new delivery head was not seen'
        assert a != fingerprint(build(items={'VH-1': {'minutes': 6}}), 'abc', meta), 'an item edit was not seen'
        assert a != fingerprint(build(intake={'i': {'status': 'submitted'}}), 'abc', meta), 'a new intake entry was not seen'
        assert a != fingerprint(build(), 'abc', dict(meta, currentRelease='V2.8')), 'an owner meta change was not seen'
        for bad in (dict(drop='links'), dict(drop='gates'), dict(empty_items=True)):
            try:
                fingerprint(build(**bad), 'abc', meta)
            except ValueError:
                continue
            raise AssertionError(f'an incomplete read was accepted: {bad}')
        try:
            fingerprint(build(), '', meta)
        except ValueError:
            pass
        else:
            raise AssertionError('a missing head SHA was accepted')
        t = datetime.datetime(2026, 10, 2, 3, 0, tzinfo=datetime.timezone.utc)
        base = {'syncFingerprint': a, 'idleChecks': 0}
        r1 = decide(base, a, 3, t); assert r1['idleChecks'] == 1 and not r1['pause'], r1
        r2 = decide({'syncFingerprint': a, 'idleChecks': 1}, a, 3, t); assert r2['idleChecks'] == 2 and not r2['pause'], r2
        r3 = decide({'syncFingerprint': a, 'idleChecks': 2}, a, 3, t)
        assert r3['pause'] and r3['metaUpdate']['syncPaused'] is True and r3['metaUpdate']['pausedAt'] == '2026-10-02T03:00:00.000Z', r3
        ch = decide({'syncFingerprint': a, 'idleChecks': 2}, 'other', 3, t)
        assert not ch['pause'] and ch['idleChecks'] == 0 and ch['metaUpdate']['syncPaused'] is False, ch   # a change resets and clears a pause
        first = decide({}, a, 3, t); assert first['changed'] and first['idleChecks'] == 0, first           # no baseline yet is a change
        st = decide({'syncFingerprint': 'old', 'idleChecks': 2}, a, 3, t, store=True)
        assert st['metaUpdate']['syncFingerprint'] == a and st['idleChecks'] == 0 and not st['pause'], st   # storing after a write is not a check
        print('selftest ok: bookkeeping ignored, 4 kinds of change seen, 4 incomplete reads refused, pause at the third unchanged check, a change resets')
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="brain.py idle")
    ap.add_argument('--dump'); ap.add_argument('--sha'); ap.add_argument('--meta')
    ap.add_argument('--threshold', type=int, default=3); ap.add_argument('--now')
    ap.add_argument('--store', action='store_true'); ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        selftest()
        return 0
    meta = json.load(open(a.meta)) if a.meta else {}
    meta = meta.get('data', meta)
    now = datetime.datetime.fromisoformat(a.now.replace('Z', '+00:00')) if a.now else None
    try:
        fp = fingerprint(a.dump, a.sha, meta)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        print(json.dumps({'error': str(e), 'changed': True, 'pause': False, 'idleChecks': 0, 'metaUpdate': {}}))
        return 2
    r = decide(meta, fp, a.threshold, now, a.store)
    r['fingerprint'] = fp
    print(json.dumps(r, indent=1))
    return 0

