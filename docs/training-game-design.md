# SPECTRE Training: the game, on real data

Design for the training redesign the owner asked for on 16 November 2026: every instruction achievable, training
driven by real data, and a fully gamified experience, "75% more fun" than the training it replaces. It follows the
training audit of the same day (`docs/training-audit-2026-11-16.md`), which found 84 problems in the old material.

Decisions marked **Claude's call** are design choices made without a ruling; the owner can overturn any of them.

## 1. What was wrong, in one paragraph

The old training was a reading exercise. Every scenario opened with paragraphs of small print, gave away its own
answers in that print, and then asked the operator to tick boxes saying they had done things, which scored whether or
not they had. The synthetic objects were 13 to 17 months old, so the console's tools propagated them to dates where
the geometry no longer matched the briefings, and several briefings were wrong even at their own epoch. Tools named
in the instructions did not exist under those names, or needed a UDL session the training could not provide. Nothing
on the page moved when the operator did something right.

## 2. The game in one paragraph

SPECTRE Training becomes **SPECTRE: Orbital Watch**, a campaign of short missions flown in the real console against
real satellites. Each mission opens with an alert, not a page of text: one line of situation, the real object's intel
card, and a first action. The operator then works in the live console while a mission HUD sits over it: objectives
tick themselves the moment the operator does the thing, points fly in, a spotlight shows the next control on request,
and a mission clock runs. The debrief awards up to three stars, ranks, medals and intel cards, and shows what the best
answer was and why. **Claude's call:** the name.

## 3. Fun, made measurable

"75% more fun" is not measurable directly, so the redesign is held to four proxies, each measured on the old training
by the audit and on the new by the mission test harness (section 9). **Claude's call:** the proxies and targets.

| Proxy | Old | Target |
|---|---|---|
| Words the operator must read before the first action | 180 to 420 per scenario | 75% fewer: at most 60 |
| Reward moments per mission (points, ticks, unlocks shown as they happen) | 1 (the debrief) | at least 4, live |
| Time from a correct action to visible feedback | never, until submit | under 1 second |
| Objectives that score without the operator doing the thing | most | none |

## 4. Real data

**Objects.** Every mission binds roles (`blue`, `red`, `third party`) to real catalogue objects by NORAD number: the
38 objects on the HRR watchlist, which the app already carries with element sets, and the 45 adversary records in
`spectre/data/adversary_intel.json` (marked UNCLASS // PAIR by the owner's ruling of 24 October 2026). Because the
objects are real, every console tool works on them: Threat Sweep, Asset Screening, Historical PoL, the Intercept and
Decision Engines.

**Element sets.** At mission start each object's element set comes from the operator's session, by the same path and
acceptance check operations use: live UDL when the operator is connected, otherwise the bundled HRR sets, which are
synthetic and are labelled SYNTHETIC on screen exactly as in operations. The mission records which it used.

**Mission clock.** The console's scenario time is set to the mission clock on start and cleared on leave: now, when
every bound set is fresh enough to pass the staleness check; otherwise the newest epoch among the bound sets, and the
HUD says so. **Claude's call.**

**Computed, never typed.** No briefing figure and no answer is written into the mission file. A briefing names
quantities (`range now`, `time of closest approach in the next 72 h`, `sub-satellite longitude`, `cheapest evasion
ΔV`), and the mission engine computes them at start from the bound element sets with the repo's own SGP4 and the
console's own engines. The answers are stored with the attempt, so scoring uses exactly the numbers the operator's
console shows.

**Exercise injects.** Real satellites rarely do something dramatic on cue. Where a mission needs an event (an
inspector closing on a blue asset), the engine applies an *exercise inject* to the real element set: a stated burn,
at a stated time, on the real object. Everything downstream is computed from the injected orbit. The inject is
labelled EXERCISE on every screen that shows it, and never presented as observed behaviour. **Claude's call.**

**Real history.** Intel cards quote the adversary records with their `source` field, word for word, and never add a
claim. Manoeuvre history comes from `spectre/data/manoeuvre_evidence.json` (released by SPC-241). NOTSO records from
`notso_cache.json` are shown only to operators with their own UDL session, as the owner's ruling requires; a mission
that needs them is locked without one and says why.

## 5. The core loop

1. **Alert** (5 s): klaxon card, one line ("SY-12 01 manoeuvring. SKYNET 5A is the nearest blue asset."), the real
   object's card, a big button: *Take the watch*.
2. **Fly** (2 to 6 min): the console with the mission HUD docked on the right. Objectives as a live checklist, each
   ticking itself with a points burst when its condition is met. A mission clock and a par time. *Hint* puts a
   spotlight on the next control and costs points.
3. **Decide** (where the mission has one): a choice card with the options the engines produced, not invented ones.
   The consequence is computed and shown.
4. **Debrief** (20 s): stars, points by skill, the best answer and why, what unlocked, *Next mission*.

## 6. Progression and rewards

● **Stars per mission.** One for completing it, one for finishing within par time, one for no hints and the best
  answer where the mission has a best answer. Stars, not points, open chapters, so a player cannot farm points.
● **Ranks.** The five existing levels keep their titles (Cadet, Observer, Planner, Analyst, Operator) with insignia,
  and each states its full condition in plain words. Points are awarded only for objectives actually met.
● **Medals.** For feats, for example *First Contact* (first mission), *Clean Sheet* (three stars with no hints),
  *Belt Walker* (every GEO mission), *Night Watch* (a Scramble on 7 consecutive days).
● **Intel cards.** One per real red object, unlocked on first encounter, with its cited record. A card turns gold when
  the operator has flown every mission involving it. Collecting is optional and rewarding.
● **Daily Scramble.** A 60-second quiz on a random real object each day ("Regime? Nearest blue asset? Closing or
  opening?"), answers computed from the live data, with a streak counter.
● **Leaderboard.** Off by default. Whether operators see each other's names and scores is a data-protection decision
  for the owner (usernames are personal data); until then only an operator's own history is shown.

## 7. The campaign

Five chapters. The tutorials stop being prose: each becomes a guided mission in Chapter 1 that teaches by spotlight.
Objects named are real; the geometry and every figure come from the data at start.

| Chapter | Missions (each 2 to 6 minutes) | Teaches |
|---|---|---|
| 1. First Watch (Cadet) | Know your asset (SKYNET 5A: load, open its element card, read its slot); Who is near? (Asset Screening on SKYNET 5A); The sweep (Threat Sweep across the HRR list); Read a threat (Intel card, regime, closest approach) | The console, element sets, screening |
| 2. Shadows in the Belt (Observer) | The tug (SJ-21 relative to the nearest blue GEO asset); The inspector (exercise inject: SY-12 01 closes on a blue asset; find time and range of closest approach); The listener (Luch/Olymp-2 history) | Proximity operations, TCA, intel |
| 3. Evade (Planner) | Cheapest way out (Intercept Engine, blue manoeuvres, EVASION within a ΔV budget); Budget bites (same, tight budget, choose the trade); Keep station (station-keeping ΔV for a blue GEO asset) | Manoeuvre planning |
| 4. Choose (Analyst) | Three ways to answer (Decision Engine with bound objects, read the three rules); Pair trouble (TJS-3 and TJS-10, two threats, one asset); Low and fast (Chamran-1 near a blue LEO asset) | Decision quality |
| 5. Theatre Command (Operator) | Three assets, three threats, against the clock; The long way round (Cosmos 2589 and Cosmos 2590 in HEO) | The full cycle under time pressure |

Challenges are timed missions with a hard limit: late means not passed. Chained challenges (the old Gauntlet) run
their missions in order under one clock and pass only when every mission passes.

## 8. Presentation

● Big type, one idea per screen, no paragraph over 25 words in the flow; detail sits behind *More*.
● Motion that rewards: points bursts, a progress ring, star reveals. All motion stops under
  `prefers-reduced-motion`.
● Sound off by default, one toggle, short generated tones (no audio files). **Claude's call.**
● SPECTRE's own dark console palette and amber training accent, so training still reads as the real console.
● No inline script or style handlers: every behaviour lives in first-party static files under the page's Content
  Security Policy (SPC-199).

## 9. How correctness is kept

● **Mission schema.** Missions live in YAML: roles bound by NORAD number, quantities named, objectives typed:
  `condition` (checked against the session state, for example "an Intercept Engine run with SKYNET 5A manoeuvring
  exists"), `answer` (a computed quantity, a tolerance and the precision the console shows it at), `choice` (options
  from an engine run). There is no self-certified objective.
● **The mission test harness.** One test per mission boots the console, plays the mission in Chromium by its own
  instructions, checks that every control an instruction names exists under that name, that every condition can be
  met, that every answer is reachable in the UI at a precision the tolerance accepts, and that every briefing figure
  equals the engine's figure for the data loaded. It runs on the bundled element sets in CI, so it needs no UDL.
● **A schema check at load.** A mission naming an unknown quantity, control, object or condition fails to load, so
  an error is found by the test suite, not by an operator.

## 10. Releases

| Release | Content |
|---|---|
| 0.47.0 | The console faults the audit found (element card, Intercept Engine results and labels, who manoeuvres, Asset Screening of own assets, J2 drift) and the training mechanics (console refresh, mission clock, clean-up, points on a pass only, late challenges fail, live page updates, debrief detail). |
| 0.48.0 | The mission engine on real data (binding, computed quantities, exercise injects, typed objectives, the harness), the HUD over the console, stars and the debrief, Chapter 1 and Chapter 2. |
| 0.49.0 | Chapters 3 to 5, challenges and chained challenges, medals, intel cards, the Daily Scramble, sound. The old scenarios and tutorials are retired. |

## 11. For the owner to decide

● The proxies and targets in section 3.
● Exercise injects on real objects (section 4).
● The leaderboard: whether operators may see each other's names and scores.
● The name *Orbital Watch*.
