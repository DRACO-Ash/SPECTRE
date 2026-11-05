# Analyst session: agenda and questions (SPC-080)

**Purpose:** one afternoon with a practising orbital warfare analyst, so SPECTRE builds the Phase 3 capability they would use first and cites the weights its ranking rests on.
**Owner:** Ash Higgins arranges the session (owner ruling, 2026-11-05). Claude prepared this agenda.
**Time:** about 4 hours, with a break.
**What the session must produce:** three things, written down before anyone leaves.
1. The 5 Phase 3 capabilities in the analyst's order, each with one sentence on why.
2. A figure and a source, or a stated rationale, for each of the 5 composite weights and the 2 normalisations.
3. Answers to the 6 calibration questions in part 4, or a named person who can answer them.

## Before the session

● Send the analyst the operator question from `.board/README.md`: "Something moved. Can it reach one of mine, how long have I got, does it mean anything, and what do I need to decide, by when?"
● Run SPECTRE on the analyst's laptop or a shared screen with the bundled demonstration data. Every bundled element set is SYNTHETIC, so every Understanding reads LOW. Say so at the start, so it is not mistaken for a defect.
● Agree the classification of the conversation in advance. The seed list and grade table are ruled never classified (2026-11-05); the analyst's own examples may be, and those stay out of the repository.

## Part 1. Orientation (20 minutes)

Show, do not explain:
● The threat sweep for one red object: range, Understanding, decide-by and the cues.
● The Decision Engine opened from that sweep: the matrix, the three selector rules and a 2-turn tree.

Ask:
● Which of these would you look at first on shift, and which would you ignore?
● Where did the screen make you stop and work something out?

## Part 2. Rank the Phase 3 capabilities (75 minutes)

Take each in turn for about 10 minutes, then rank. Two of the original 7 (custody risk and the decision clock) are already built as decide-by and the Decision Engine; show them, do not rank them.

| Item | Capability | The question to ask |
|:-|:-|:-|
| SPC-081 | Reachability as a field: every red object's reachable set across the catalogue, kept warm | Would "who is inside whose envelope right now" change what you watch? How often must it refresh to be worth having? |
| SPC-082 | Behavioural fingerprinting across the GEO belt | Do you already compare an object with its bus class or neighbours? Which signature changes would you want flagged? |
| SPC-083 | Intent from an approach sequence (drift halt, plane match, phasing, closing) | Which sequences do you treat as a warning today, and how many steps in before you call it? |
| SPC-084 | Counterfactual planning against a detected threat | The engine does most of this now. What is missing from what you saw in part 1? |
| SPC-085 | Propellant-bounded horizons: can it ever reach my asset again | Would you trust a "never" from a propellant estimate? What would it need to show before you did? |

Then ask the analyst to order all 5, and for the top one: what would you need to see working to use it on shift?

## Part 3. Cite the composite weights (SPC-151, 60 minutes)

The Decision Engine ranks responses by a weighted sum. The defaults are rules of thumb (audit F-S05-02), so the score is never stronger than a lookup.

| Term | Default weight | The question to ask |
|:-|:-|:-|
| Custody lost | 0.35 | How much worse is losing custody than a close approach? |
| Closest approach | 0.25 | At what distance does a close approach stop mattering? (normalised to 50,000 km today) |
| Our delta-V | 0.20 | What delta-V spend is significant for a blue asset? (normalised to 100 m/s today) |
| Time to execute | 0.10 | How much does a slow response cost against a fast one? |
| Reversibility | 0.10 | Does a reversible response earn credit in practice? |

For each: a figure, and either a source (doctrine, a published study, an exercise report) or the analyst's stated rationale. Record which. A rationale is acceptable; it is recorded as the analyst's judgement, not a citation.

Also ask about the owner's 2026-11-05 ruling that degraded custody (orbit current, no history to judge burns) carries one quarter of the custody penalty: does that match how the analyst treats a track with no history?

## Part 4. Calibration questions (40 minutes)

Each is a figure SPECTRE currently tunes or leaves out because nothing sourced exists.
1. **Collection costs** (concept decision 12): what does a sensor retask or an analyst look actually cost, in time and in what it displaces? Without this, collections stay listed beside the ranking, not scored.
2. **Detection rates** (game tree D10): how often does a burn go unseen for a turn, by regime? The tree uses the custody rule today, not invented rates.
3. **Persistence** (game tree D11): does a red object that manoeuvred once become more likely to manoeuvre again within days? The owner ruled to keep P as entered; this informs a later revisit.
4. **The 8 km conjunction margin** (concept decision 14): is "closer than before the burn by more than 8 km" a fair test of a meaningful approach?
5. **A hostile floor that never lapses** (concept decision 7): would you ever clear suspicion without a fresh hostile burn?
6. **Response time for decide-by**: the default is 12 hours, Claude's choice. What is a realistic time from decision to a blue burn?

## Part 5. Close (15 minutes)

Read back the 3 outputs from the top of this page and get the analyst's agreement on each. Then:
● Record the ranking and the weights in `.board/README.md` as owner rulings, citing the session.
● Close SPC-080 and SPC-151; promote the top-ranked Phase 3 item to the release track.
● Name anything the analyst asked for that is not on this page as a new backlog item.
