# Working papers

The raw inputs behind the phase 4 to 8 artefacts, kept so that every number in `audit/FINDINGS.md`, `audit/REFUTATION.md` and `audit/MANIFEST.json` can be traced and every check rerun.

| Path | What it is |
|---|---|
| `slices/S00.md` to `S10.md` | Slice reviews (phases 4 and 5) under `audit/LENS-BRIEF.md`. S00 holds the orchestrator's own findings |
| `slices/*.files` | The exact ledger rows assigned to each slice (332 in total, each assigned once) |
| `refute/BRIEF.md` | The refutation brief given to the independent refuters |
| `refute/R*.candidates.md` | The candidate blocks each refuter received |
| `refute/R*.verdicts.md` | Each refuter's verdict table. R4 was run twice: `R4` is the second opinion; `R4a` and `R4b` were adopted |
| `refute-scripts/` | Scripts the refuters executed against a scratch clone of `a34e273` |
| `tools/` | Orchestrator scripts: ledger, suppression classifier, route extractor, slice assignment, merge and quote check, mutation harness, test audit, combine and build, and the probes |

Paths inside the scripts point at the session scratch directory (`/tmp/claude-0/...`). To rerun a script, point it at a fresh clone of commit `a34e273` and a Python 3.12 virtualenv built from the lockfiles, as described in `audit/TOOLS.md` section 0.

No content from `spectre/data/notso_cache.json` is reproduced here beyond field names and the marking label, which `audit/FINDINGS.md` also quotes as evidence.
