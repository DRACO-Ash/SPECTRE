# Threat Understanding: a threat range that narrows as SPECTRE learns the satellite

Concept for owner decision. Bluestaq Limited, 3 November 2026. Baseline: SPECTRE 0.15.0, commit f8c40c7.

Where to find things:
● Code that changes first: `spectre/domain/threat_assessment.py`
● New modules: `spectre/domain/threat_understanding.py` and `spectre/domain/interaction_graph.py`
● Backlog IDs: SPC-160 to SPC-177 are proposed. The highest ID in the repository today is SPC-152.

## 1. The idea

### In the owner's words

> "The more we understand a satellite and its capabilities and its manoeuvres and its interactions, the more we understand its threat score when SPECTRE returns a result."

### For an operator, in one paragraph

When something moves, SPECTRE now gives you two answers and keeps them apart.

**Threat** is a range. Its floor is what the evidence proves at least. Its ceiling is what the evidence cannot yet rule out. The assessed band sits between them.

**Understanding** reads HIGH, MODERATE or LOW. It says how well founded that range is, what is missing, and the quickest observation that would firm it up.

Each part of the satellite we come to know narrows the range: who it is, what it can still do, how it manoeuvres and what it has approached. A part counts only when its evidence is independent, fresh and reliable enough. More understanding narrows the range. It never raises the threat on its own account.

When SPECTRE does not know, it says "cannot assess threat beyond access" and shows you the geometry. If there is time before your decide-by, it tells you which collection would settle the question.

### What changes

● Confidence stops being a count of inputs. Today 4 or more inputs reads HIGH (`_EVIDENCE_FOR_HIGH_CONFIDENCE = 4`, `threat_assessment.py:146`, applied at `:424`). Orbital geometry counts as one of the 4.

● Several figures from one element-set history count once:
  ■ propellant used
  ■ discretionary reserve
  ■ anomaly index
  ■ burn count

● A manufacturable string can no longer zero the threat. Today a recorded "Degraded" status sets capability to MINIMAL (`_incapacity`, `threat_assessment.py:257`) and withholds decide-by (`web/routes/threat.py:2184`).

● The weaker-governs rule stays. ACCESS (geometry) stays deterministic and remains the ceiling no evidence can raise. The verdict is still `min(ACCESS, CAPABILITY)` in its legacy form, now bounded by earned evidence.

### Why now: four cases measured in the venv at f8c40c7

| Case | Today | Under this concept |
|:-|:-|:-|
| No intel record, history with 0 burns | Capability HIGH, confidence HIGH. Its "inputs" are geometry, a regime-assumed full tank counted twice, and "manoeuvres = 0" | Understanding LOW. The verdict is access, and the screen shows what to collect |
| Intel record only | Confidence MEDIUM | Understanding LOW |
| Intel label with a typo | Listed as "used" but adds nothing | Listed as missing, with the reason |
| Geometry only | CRITICAL at LOW confidence | Understanding LOW, range MINIMAL to access, "cannot assess threat beyond access" |

A fifth case, from the design work: an object recorded "Degraded", with anomaly index 90 and 12 observed burns, reads MINIMAL at confidence HIGH, and its decide-by is withheld. Under this concept the status is voided by the burns and named as possible deception, and decide-by stays.

## 2. What we learned from Google, and where the analogy breaks

**Access constraint.** WebFetch could not reach research.google, vldb.org, arxiv.org or infolab.stanford.edu from this session. The claims below come from search result extracts, not full-text reads.

**Labels** used in this section and the next:
● **[Fact]**: confirmed by the cited extract.
● **[Fact, recalled, unverified]**: from memory of the paper. Check it against the primary text before any external use.
● **[Inference]**: our reasoning.
● **[Speculation]**: a plausible risk or idea we have not tested.
● **[Tuned, not sourced]**: a SPECTRE constant chosen by judgement.

### 2.1 Many signals, combined explicitly

● [Fact] Google's ranking systems weigh "many factors and signals". Systems for specific needs are kept apart from the core systems. https://developers.google.com/search/docs/appearance/ranking-systems-guide

● [Fact] Learning to rank fits the combination to labelled relevance judgements. RankNet uses a pairwise loss, LambdaRank scales gradients by the change in a list-quality metric, and LambdaMART boosts trees. A LambdaMART ensemble won the 2010 Yahoo! learning-to-rank challenge, Track 1. https://www.microsoft.com/en-us/research/?p=159784 and https://course.ccs.neu.edu/cs6200s14/ssl/paper/to-lambdamart.pdf

● What we take: four evidence dimensions, each read by its own rules and combined explicitly. Identity, Capability, Behaviour and Interactions replace the bare `max()` in `CapabilityEvidence._signals` (`threat_assessment.py:277`). [Inference]

● Where it breaks: we have no labelled training set. A handful of publicly attested hostile manoeuvres sit against thousands of benign ones, so a learned combiner would overfit and could not be audited. Weights are set by hand and labelled. [Inference]

### 2.2 Knowledge Vault: a prior fused with noisy extractions

● [Fact] Knowledge Vault fuses web extractions with priors from existing knowledge bases and outputs calibrated probabilities that a fact is correct. Dong et al., KDD 2014, pp. 601 to 610. https://research.google/pubs/knowledge-vault-a-web-scale-approach-to-probabilistic-knowledge-fusion/ and https://lunadong.com/publication/kv_kdd.pdf

● [Fact] Only about 20 per cent of raw extracted triples were correct, which is why the priors and fusion were needed. Source: Dong's 2015 Stanford talk, https://web.stanford.edu/class/ee380/Abstracts/150429.html.bak

● [Fact, recalled, unverified] The priors came from a path ranking algorithm and a neural model. Fusion used boosted decision stumps.

● What we take: the analyst's assessed label is the prior. It sets the assessed point while evidence is thin. Earned observations bound it from below and above, and as they accumulate they take over. [Inference]

● Where it breaks: calibration needs ground truth, and we have very little. So we show bands and ranges, never probabilities. A declared mission is a prior the adversary can manufacture, so it is capped. [Inference]

### 2.3 Knowledge-Based Trust: source error is not extraction error

● [Fact] Knowledge-Based Trust (KBT) estimates a source's trustworthiness from the correctness of the facts it states. It separates errors made by the extractor from errors made by the source. Dong et al., PVLDB 8(9), 2015, pp. 938 to 949. https://arxiv.org/abs/1502.03519

● What we take: each evidence item carries two reliabilities.
  ■ Source: the provider, graded on the Admiralty letter scale (section 3).
  ■ Extraction: our processing chain. That means the SGP4 fit, burn detection and normality judgement.
  A poor fit across a stale element set is an extraction error. It does not count against the object, and it does not count against the provider. [Inference]

● Where it breaks: KBT needed millions of facts per source. Our provider grades start as hand-set values with their basis stated. They change only through adjudicated contradictions. [Inference]

### 2.4 Source dependence: copies are not corroboration

● [Fact] Bayesian models detect copying between sources, so agreement among copiers is not counted as independent support. Dong, Berti-Equille and Srivastava, PVLDB 2(1), 2009, pp. 550 to 561. https://lunadong.com/publication/dependence_vldb.pdf

● What we take: items that share a source chain form one independence group, and the group counts once. This fixes today's largest flaw: the four figures derived from one element-set history count four times. [Inference]

● Where it breaks: here dependence is usually visible in metadata (provider, data source, derived-from), so we group on metadata rather than infer it. Where the metadata is missing, items are grouped together, which under-claims. [Inference]

### 2.5 Query Deserves Freshness

● [Fact] Query Deserves Freshness (QDF) detects a "hot" topic and boosts recent documents for it. Amit Singhal described it to the New York Times in June 2007. Secondary sources: https://searchengineland.com/guide/query-deserves-freshness-qdf and https://www.searchenginejournal.com/google-algorithm-history/freshness-algorithm/

● [Fact] Google still lists "freshness systems" among its ranking systems. https://developers.google.com/search/docs/appearance/ranking-systems-guide

● What we take: evidence decays with age at a rate set for each dimension. An unusual burn makes the object a hot topic, and Capability and Behaviour evidence from before that burn loses half its weight. [Inference]

● Where it breaks: here the hot topic is the adversary's own act, so the adversary partly controls when the picture refreshes. [Speculation] An actor could burn just after a known observation gap. So freshness is judged against our own observation cadence (custody and element-set age), not only against the object's last burn. [Inference]

### 2.6 PageRank and TrustRank: authority and suspicion through links

● [Fact] PageRank defines PR(A) = (1 − d) + d·Σ PR(Ti)/C(Ti), with d usually 0.85. Brin and Page, 1998. https://research.google/pubs/the-anatomy-of-a-large-scale-hypertextual-web-search-engine/ (formula extract: https://www.site.uottawa.ca/%7Ediana/csi4107/Google_SearchEngine.pdf)

● [Fact] TrustRank propagates trust from a small human-labelled seed set and dampens it at each hop. It relies on "approximate isolation": good pages seldom link to bad ones. Gyöngyi, Garcia-Molina and Pedersen, VLDB 2004. https://vldb.org/conf/2004/RS15P3.PDF

● What we take: manoeuvre-attributable approaches become graph edges. Suspicion flows at most two hops from analyst-adjudicated hostile seeds and halves at each hop. Trust never flows from benign seeds. [Inference]

● Where it breaks:
  ■ The population of active manoeuvring objects is in the low thousands and hostile edges are rare, so a stationary distribution would be unstable and one edge could dominate. We cap propagation instead of solving for one. [Inference]
  ■ A web link is deliberate, but a close pass in a crowded GEO slot often is not. So an edge counts only when a burn by the object caused the approach. [Inference]
  ■ An adversary can build a clean "sleeper" record before acting. [Speculation] So trust earned by quiet behaviour decays.

### 2.7 The content advisory

● [Fact] When Google's systems lack high confidence in result quality, they show a content advisory. Secondary: https://developers.google.com/search/blog/2022/11/introducing-guide-to-ranking-systems

● What we take: this is SPECTRE's house rule. When understanding is LOW, SPECTRE says so, shows only what geometry supports and names what would fix it. [Inference]

### 2.8 Feedback signals

● [Fact] At the 2023 US Department of Justice (DOJ) antitrust trial, Pandu Nayak described NavBoost, a click-based system dating to about 2005, as one of Google's strongest ranking signals. It does nothing for documents without click history. Secondary: https://www.hobo-web.co.uk/navboost-how-google-uses-large-scale-user-interaction-data-to-rank-websites/ and https://seranking.com/blog/navboost/

● What we take: analyst adjudication is our only feedback. It is logged with provenance and used to check whether outcomes fall inside the range and to review provider grades. [Inference]

● Where it breaks: feedback is sparse, slow, possibly classified and biased towards objects analysts already watch. If overrides trained the score, they would teach it the analysts' assumptions. [Speculation] So feedback never moves a band.

### 2.9 Where the web analogy fails overall

● **The adversary manufactures signals in both directions.** It can feign benignity (declared missions, routine-looking station keeping, burns sized inside the budget) and deny signals (burns in coverage gaps). So absence of evidence lowers understanding and never lowers the threat. [Inference]

● **The stakes are asymmetric.** Search optimises average relevance. A defender pays far more for a missed threat than for a false alarm. So the ceiling, not the centre, governs whether decide-by is withheld. [Inference]

● **There is no scale.** Every weight states its basis. [Tuned, not sourced]

## 3. The defence standard it aligns with, and why

**Verification.** gov.uk, dni.gov and irp.fas.org were outside this session's allowed network domains, so these citations come from search result summaries.

**Primary frame: UK Professional Head of Intelligence Assessment (PHIA) practice.**

● [Fact] UK assessment keeps likelihood and confidence apart: "analytical confidence reflects the soundness and stability of the foundations on which the assessment of likelihood has been made". https://www.gov.uk/government/publications/explaining-uncertainty-in-uk-intelligence-assessment/explaining-uncertainty-in-uk-intelligence-assessment (published 24 March 2025)

● [Fact] The Analytical Confidence Rating (AnCR) has three levels: High, Moderate and Low. It is informed by three categories:
  ■ Information Base
  ■ Analytical Rigour
  ■ Complexity and Volatility
  An AnCR statement sets out where the remaining uncertainty lies, what effect it has and how confidence could be raised. Same source, and https://www.gov.uk/government/publications/phia-common-analytical-standards/phia-common-analytical-standards

● [Inference] This is the owner's idea expressed in doctrine. Threat is the likelihood; Understanding is the AnCR. The three categories map directly onto the model in section 6.

**Evidence tagging: the North Atlantic Treaty Organization (NATO) Admiralty code.** It is set out in Allied Joint Publication 2 (AJP-2) and Standardization Agreement (STANAG) 2511.

● [Fact] Source reliability is graded A (completely reliable) to E (unreliable), with F meaning it cannot be judged. Information credibility is graded 1 (confirmed by other sources) to 5 (improbable), with 6 meaning it cannot be judged. The two grades are judged independently. https://en.wikipedia.org/wiki/Admiralty_code and https://pangearesearch.substack.com/p/the-admiralty-code-nato-6x6-system

● [Fact] Current AJP-2.1 text does not appear to be public. The labels come from reproductions.

● [Inference] The code grades items, not judgements, so it goes on each ledger row. NATO and Five Eyes readers can then read the basis of an assessment without translation.

**Allied translation only: US Intelligence Community Directive 203 (ICD 203).**

● [Fact] ICD 203 requires products to state likelihood, confidence and the uncertainty behind both. It says likelihood and confidence should not be combined in one sentence. https://www.dni.gov/files/documents/ICD/ICD-203.pdf

● [Fact] An Office of the Director of National Intelligence (ODNI) research note found that confidence levels were never clearly defined and that analysts default to "moderate". https://www.dni.gov/files/documents/FOIA/DF-2024-00001-NIU_Research_Short.pdf

● [Inference] Lesson for SPECTRE: every Understanding level needs explicit criteria. Today's rule has explicit criteria, but they measure quantity, not quality.

**Why independence grouping and not a naive sum.**

● [Fact] Weight of evidence adds across observations only when they are independent given the hypothesis. Turing, as written up by Good. https://jhanley.biostat.mcgill.ca/bios601/CandH-ch0102/GoodOnTuring.pdf

● [Fact] Analysts using Analysis of Competing Hypotheses (ACH) treated perfectly correlated cues as independent. Karvetski, Mandel and Irwin, 2020. https://doaj.org/article/3d19a7e3b1bf4b28b07aa346da34f0db

**Why not Dempster-Shafer.**

● [Fact] Under high conflict, Dempster's rule normalises the conflict away and can put all belief on a minority hypothesis (Zadeh's paradox). https://arxiv.org/pdf/math/0404371

● [Inference] Conflicting sensor reports are exactly the case a threat tool must handle. We keep only the idea that "unknown" differs from "evenly balanced", and express it through Understanding and the range.

**Space Domain Awareness (SDA) practice this joins up.**

● [Fact] Rendezvous and Proximity Operations (RPO) can be detected from relative kinematics, and Pattern of Life (PoL) analysis improves threat characterisation. https://amostech.com/TechnicalPapers/2024/Poster/Serrano.pdf

● [Fact] Observed RPO capability is not proof of counterspace intent. https://swfound.org/media/208089/swf_global_counterspace_capabilities_2025.pdf

● [Fact] Normal behaviour can be defined from each satellite's own PoL. https://dspace.mit.edu/handle/1721.1/151249

● [Fact] Knowledge-graph approaches compare an object with related classes to find PoL anomalies. https://stottlerhenke.com/wp-content/uploads/2025/10/2025_AMOS_Jensen_et-al_SHERLOC.pdf

● [Inference] We found no published source that combines RPO kinematics, PoL baselines, interaction history and an earned confidence rating from start to finish. That combination, in a UK sovereign tool, is a differentiator.

**Gated wording.** The PHIA probability yardstick terms (for example "highly likely") and the ICD 203 percentage table do not appear on screen. Three things must be checked first:
● The yardstick bands below 55 per cent are recalled, not verified.
● The ICD 203 table is recalled, not verified.
● The AJP-2.1 wording for grades F and 6 needs MOD channels.

A yardstick word also carries a calibrated percentage band to a trained reader, and we have not earned calibration. See SPC-177.

## 4. The model

A new pure module, `spectre/domain/threat_understanding.py`. It does no I/O. `assess_threat` consumes it. Every constant in this section is a named module constant marked "tuned, not sourced", following the convention in `normality.py` and `pol_assessment.py`.

### 4.1 Terms

● **Band**: the existing `Band` IntEnum (`threat_assessment.py:71`), ordered MINIMAL < LOW < MEDIUM < HIGH < CRITICAL.

● **Dimension**: what the item tells us about the satellite.
  ■ IDENTITY: who it is
  ■ CAPABILITY: what it can still do
  ■ BEHAVIOUR: how it manoeuvres
  ■ INTERACTIONS: what it has approached
  ACCESS is not a dimension. It is computed every sweep and is the question being asked, not evidence of understanding.

● **Group**: the independence key, made of the dimension and a `derived_from` root, for example `("BEHAVIOUR", "elset-history:UDL:18SDS")`.

### 4.2 The evidence item

```
EvidenceItem(
    dimension, label, group,
    floor_to: Band | None,        # the floor this item would raise to
    ceiling_to: Band | None,      # the ceiling this item would lower to
    source_grade: "A".."F",       # Admiralty reliability
    credibility: 1..6,            # Admiralty credibility
    extraction: float,            # our processing chain, 0 to 1
    basis: provenance.Basis,      # LOOKUP < SAMPLED < COMPUTED
    observed_at: datetime | None,
    manufacturable: bool,         # the adversary controls it
    controlled: bool,             # own, allied or 18th Space Defense Squadron (18 SDS)
    note: str,
)
```

### 4.3 The reliability of one item

```
q_i = min(cap_i, r_src × r_cred × r_ext × f_i)
```

| Factor | Values [tuned, not sourced] |
|:-|:-|
| r_src (Admiralty letter) | A 0.9 own or allied sensor, analyst-adjudicated. B 0.8 18 SDS catalogue through the Unified Data Library (UDL), and the GCAT catalogue. C 0.6 commercial provider, and an open-source intel record. D 0.3 declared by the object's operator (status, mission, NOTSO manoeuvre notification). E 0.1. F 0.3 |
| r_cred (Admiralty digit) | 1 1.0 confirmed by an independent source. 2 0.85. 3 0.6. 4 0.4. 5 0.2. 6 0.3 |
| r_ext | Burn detection grade from `astro/dv_estimation.py` `_grade_confidence`: HIGH 0.9, MODERATE 0.6, LOW 0.3, REJECT 0. A figure resting on a regime Isp or mass-fraction assumption: 0.5. An assessed label: 0.5. A catalogue field read directly: 1.0. Halved for a burn across a `long_gap`. Halved when `TLERecord.rms_residual` exceeds the regime threshold; no change when it is missing, but the row says so |
| Manual element set | r_ext from `_CONFIDENCES` (`threat.py:284`): CONFIRMED 1.0, HIGH 0.9, MEDIUM 0.6, LOW 0.3, UNCONFIRMED 0.1 |
| cap_i | 0.3 for manufacturable items (declared status, declared mission, NOTSO filings). 0.5 for a ROUTINE normality verdict, because the baseline is self-referential. Otherwise 1 |

### 4.4 Freshness

```
f_i = 0.5^(age_i / h_d) × reset_i
```

● h_d is the half-life for the dimension and regime:
  ■ Identity: 365 days
  ■ Capability: 90 days
  ■ Behaviour: 60 days at GEO, 14 days in LEO, 30 days in MEO and HEO
  ■ Interactions: 30 days
  [Tuned, not sourced]

● The age clock depends on the item:
  ■ Items derived from an element-set history take `observed_at` from the newest element set held. Freshness therefore follows our observation cadence, not the object's last act.
  ■ A burn item takes the burn epoch.
  ■ An undated item, such as all 44 bundled intel records, is taken as one half-life old.

● QDF reset: `reset_i = 0.5` for Capability and Behaviour items observed before the latest confirmed burn judged UNUSUAL or UNPRECEDENTED. Otherwise it is 1.

● Persistence asymmetry: a floor reading that was earned when it was judged stays applied until a later confirmed burn has been judged. Its coverage still decays, so Understanding falls and a "re-observe" cue appears. Ceiling-lowering readings decay normally. In short, trust decays and suspicion persists until it is re-observed.

### 4.5 Independence and coverage

● Within a group, only the strongest item counts:

```
q_g = max_{i in g} q_i
```

● Coverage of a dimension is a noisy-OR across its groups:

```
u_d = 1 − Π_g (1 − q_g)
```

● A dimension is **earned** at u_d ≥ 0.5 and **partial** at u_d ≥ 0.25. [Tuned, not sourced]

● u_d can never fall when a group is added, so understanding grows with each independent item.

● One capped manufacturable item (at most 0.3) can never earn a dimension alone.

● Each provider named in `Manoeuvre.corroborated_by` opens its own group with credibility 1.

### 4.6 Readings and the threat range

A reading applies only when both hold:
● its dimension is earned
● its own q_i ≥ 0.25

Unapplied items are listed in the ledger with the reason. Then:

```
F = applicable floor readings,   C = applicable ceiling readings
floor_cap   = max(F, default MINIMAL)
ceiling_cap = min(C, default CRITICAL)
floor   = min(ACCESS, floor_cap)
ceiling = min(ACCESS, ceiling_cap)
```

| Reading | Effect |
|:-|:-|
| Latest burn UNPRECEDENTED | Floor HIGH |
| Latest burn UNUSUAL | Floor MEDIUM |
| Anomaly index rung (`pol_assessment._RISK_LADDER`) | Floor raised to the rung, capped at MEDIUM, because the index is uncalibrated |
| Posture AGGRESSIVE or BEYOND_PLATFORM (`manoeuvre_calibration.classify_posture`) | Floor MEDIUM |
| Assessed role HIGH or CRITICAL from a dated, sourced record | Floor MEDIUM. A prior never raises the floor higher |
| Attributable warning change NEWLY_IN_REACH or CUT against our asset | Floor HIGH |
| Attributable closest approach under 50 km | Floor MEDIUM |
| Propagation from a hostile seed | Floor MEDIUM at most |
| Discretionary reserve ≤ 0 m/s, or propellant used ≥ 95 per cent, with no later burn | Ceiling MINIMAL (COMPUTED incapacity) |
| Reserve share below 0.5 | Ceiling MEDIUM |
| Impaired status, corroborated (no confirmed burn held, custody HELD, `DetectionLimits.sees_routine_station_keeping`) | Ceiling MEDIUM, never lower (I5) |
| ROUTINE normality, ample reserve, "no burns", NOTSO filing, declared mission | No reading. Coverage only |

### 4.7 Conflicts and possible deception

● **Void first.** An impaired status is voided when the held history contains a confirmed burn newer than the record. An undated record is treated as older than any held burn. The row reads "voided: possible deception", and Understanding is capped at MODERATE.

● **Then conflicts.** A floor reading f and a ceiling reading c conflict when f > c. Every reading in a conflicting pair is removed, and the range is recomputed from the rest. Removing readings can only lower the floor and raise the ceiling, so **conflict never narrows the range**. Both items are named, and Understanding is capped at MODERATE.

### 4.8 The verdict

```
legacy   = min(ACCESS, capability.band())   or ACCESS when capability is None   (today's rule)
assessed = clamp(legacy, floor, ceiling)
verdict  = ceiling     if Understanding is LOW or the range spans 4 or more bands
           assessed    otherwise
```

● The legacy reading is the Knowledge Vault prior. It sets the point only inside what evidence has earned.

● When Understanding is LOW, the verdict is the ceiling. That is access, unless earned COMPUTED incapacity has lowered it.

● In the shadow phase (SPC-166 to SPC-174) the displayed verdict stays legacy, and the range and Understanding render beside it. The switch is SPC-175.

### 4.9 Interactions and propagation

● An edge v → x exists only when it is **manoeuvre-attributable**: a confirmed burn by v preceded the approach within 7 days, and the approach is closer than the pre-burn closest approach. [Tuned, not sourced]

● First source: `domain/warning_change.py` `classify()` (`:127`), which is already computed per sweep. Second source: UDL conjunctions held per object.

● Seeds are analyst-adjudicated hostile objects, plus the cited counterspace events in `manoeuvre_calibration` (Luch/Olymp-K, SJ-21).

● A propagation item for object v takes `q = q_edge × 0.5^hops`, for at most 2 hops, and its reading is floor MEDIUM at most.

● A third hop adds nothing. Benign seeds propagate nothing. One edge cannot lift the floor past MEDIUM through propagation.

### 4.10 Value of information and collect-first

For each dimension d that is not earned, SPECTRE asks what one more piece of evidence could change:

● It re-runs the range twice with one hypothetical group of the cue's typical grade. One run carries the most benign reading d admits; the other carries the most hostile.

```
VOI_d = (ceiling_now − ceiling_benign) + (floor_hostile − floor_now)     in band steps
```

● Cues are ranked by VOI_d divided by hours to collect, and each cue states the steps it would remove.

● The **action line** A is the band at which the operator's response changes. The default is HIGH, set by the operator. [Tuned, not sourced]

```
collection_advice:
  COLLECT_FIRST       if floor < A ≤ ceiling, some cue has VOI > 0, and now + hours ≤ decide_by
  ACT_ON_CEILING      if floor ≥ A, or the range straddles A and no cue lands before decide_by
  BELOW_ACTION_LINE   if ceiling < A
```

`decide_by` already subtracts the response time (`domain/decide_by.py`), so it is not subtracted again.

### 4.11 Invariants (each becomes a test)

● I1: Adding a non-conflicting item never widens [floor, ceiling] and never lowers any u_d. Understanding can fall only if the item is a new UNUSUAL or UNPRECEDENTED burn, because the picture has become volatile.

● I2: Adding an item to an existing group, no stronger than its best member, changes nothing.

● I3: Adding a conflicting item never narrows the range, caps Understanding at MODERATE and names both items.

● I4: Ageing never raises Understanding, and never lowers the floor before a later burn is judged.

● I5: Manufacturable benign items alone never pull the ceiling below MEDIUM.

● I6: The ceiling never exceeds ACCESS. With Understanding LOW, the verdict equals the ceiling.

● I7: An impaired status never lowers the ceiling while a newer confirmed burn is held.

● I8: "No burns" adds coverage only under the absence rule (section 5) and never moves a band.

● I9: ROUTINE moves no band.

● I10: The same inputs give the same ledger and the same provenance hash.

● I11: Every ledger row carries a basis and a grade, and every unearned dimension carries a cue.

● I12: The four measured cases in section 1 hold as fixed regression cases.

● I13: Threat and Understanding never share a sentence. No percentage is rendered. No bare HIGH or LOW appears without "Threat" or "Understanding" before it.

### 4.12 Worked example

**The object.** RED-GEO-1 is a fictional GEO inspector. Its behaviour is modelled on public reporting of Luch/Olymp-K (https://swfound.org/media/208089/swf_global_counterspace_capabilities_2025.pdf). The figures are illustrative.

**The situation at 3 November 2026, 12:00Z.**
● The sweep finds a deliverable approach to BLUE-COMSAT at 9 m/s, arriving in 31 hours. ACCESS is CRITICAL.
● Decide-by is 19 hours away: 31 hours of flight time less the 12-hour default response time.
● Custody is HELD. The data mode is REAL.

**Today, SPECTRE 0.15.0, reads** capability CRITICAL from the intel label, verdict CRITICAL and confidence HIGH (5 inputs).

| # | Evidence added | q | Coverage I, C, B, X | Threat range | Understanding (governing category) |
|:-|:-|:-|:-|:-|:-|
| 0 | None (geometry only) | | 0, 0, 0, 0 | MINIMAL to CRITICAL | LOW (information base) |
| 1 | Intel record, role CRITICAL, undated, single open source [C3] | 0.6 × 0.6 × 0.5 × 0.5 = 0.09 | 0.09, 0, 0, 0 | unchanged: q below 0.25, listed only | LOW |
| 2 | GCAT entry: bus, launch, operator [B2], refreshed 30 days ago | 0.8 × 0.85 × 1.0 × 0.945 = 0.64 | 0.67, 0, 0, 0 | unchanged | LOW (one dimension earned) |
| 3 | UDL history [B2], 400 days, 23 confirmed burns, newest set 6 hours old. Reserve 72 of 120 m/s on the regime Isp assumption | 0.8 × 0.85 × 0.5 × 0.998 = 0.34 | 0.67, 0.34, 0, 0 | unchanged (share 0.6, no reading) | LOW |
| 4 | Latest burn 2 Nov 03:10Z, 11 m/s, detection HIGH, UNPRECEDENTED. Same history, Behaviour dimension | 0.8 × 0.85 × 0.9 × 0.984 = 0.60 | 0.67, 0.34, 0.60, 0 | **HIGH to CRITICAL** | MODERATE (information base; volatility) |
| 5 | Allied optical track confirms the burn [A1], 24 hours old | 0.9 × 1.0 × 0.9 × 0.989 = 0.80 | 0.67, 0.34, 0.92, 0 | unchanged | MODERATE |
| 6 | Commercial provider's history [C2], reserve share 0.55 | 0.6 × 0.85 × 0.5 × 1.0 = 0.26 | 0.67, 0.51, 0.92, 0 | unchanged | MODERATE (volatility only) |
| 7 | Warning change NEWLY_IN_REACH against BLUE-COMSAT, caused by the 2 Nov burn [B2] | 0.8 × 0.85 × 0.9 × 0.969 = 0.59 | 0.67, 0.51, 0.92, 0.59 | unchanged (floor HIGH already) | MODERATE |
| 8 | 12 November: custody held for 9 days after the burn, no new anomaly. Items have decayed | Behaviour 0.54 and 0.72, Interactions 0.48, Identity 0.63 | 0.67, 0.51, 0.87, 0.48 | HIGH to CRITICAL (floor persists) | **HIGH** |

How each Understanding reading is reached:

● **Row 4 reads MODERATE.**
  ■ Information base is MODERATE: Identity and Behaviour are earned, and Capability is partial.
  ■ Rigour is HIGH: the floor rests on a COMPUTED Behaviour reading from a controlled source, and the ceiling is COMPUTED access.
  ■ Volatility is MODERATE: an UNPRECEDENTED burn 33 hours ago, and the post-burn orbit has not yet been held for 3 element-set limits (9 days at GEO).

● **Row 6 reads MODERATE** because volatility is the only category short of HIGH.

● **Row 8 reads HIGH.**
  ■ All three categories are HIGH.
  ■ There are three independent source chains.
  ■ A and B grades are present in Behaviour.

Two things to note:
● The assessed point stays CRITICAL throughout. More understanding narrowed the range from 5 bands to 2. It did not inflate the threat.
● Today's HIGH confidence on row 3's evidence was not earned. This model reads LOW at that point.

**Contrast A: a feigned status.** Take row 4, plus intel status "Degraded" [D, capped at 0.3].
● The 2 Nov burn is newer than the undated record, so the status is voided and named "possible deception".
● The range stays HIGH to CRITICAL, and decide-by is shown.
● Today the same object reads MINIMAL at confidence HIGH, with decide-by withheld.

**Contrast B: a routine burn.** Take row 4, but the latest burn is ROUTINE.
● Behaviour q is capped at 0.50, so the dimension is earned but no reading applies.
● The range is MINIMAL to CRITICAL, 5 bands, so the verdict line reads "Threat: cannot assess beyond access (CRITICAL)". Understanding is MODERATE.
● With action line HIGH, the range straddles it, so SPECTRE runs the value-of-information cues:

| Cue | Effect it could have | Steps removed | Time | Steps per hour |
|:-|:-|:-|:-|:-|
| Hold UDL conjunctions | Could raise the floor to HIGH | 3 | 0.25 h | 12 |
| Pull a second provider's history | Could lower the ceiling to MINIMAL | 4 | 0.5 h | 8 |
| Analyst to date and source the intel record | Could raise the floor to MEDIUM | 2 | 4 h | 0.5 |

All three land within the 19 hours to decide-by, so the advice is COLLECT_FIRST.

**Contrast C: the measured false HIGH.**
● The object has no intel record and 400 days of history with 0 burns.
● Custody is HELD. `floor_m_s` is 0.4, below the 9 m/s the intercept needs, and there is no long gap, so the absence rule holds.
● "No burns" adds Behaviour coverage of 0.34 and moves nothing. Capability is 0.34.
● Understanding is LOW, and the verdict is the access ceiling. Today the same object reads capability HIGH at confidence HIGH.

## 5. The signals

The tables below use these abbreviations:
● Grades use the Admiralty letter and digit.
● "Group" is the independence key.
● Half-lives are given in section 4.4.

Every weight and threshold is tuned, not sourced, unless a citation is given.

### 5.1 Identity

| Signal | Source in SPECTRE | Reading | Reliability basis | Freshness | Group | Adversary resistance |
|:-|:-|:-|:-|:-|:-|:-|
| Intel record: threat_level, role, status, source | `spectre/data/intel.py` `get_intel()`, read at `web/routes/threat.py` `_red_capability` (`:819`) | Floor MEDIUM when the role is HIGH or CRITICAL and the record is dated and sourced | C; credibility 3 if undated and single-source, else 2; extraction 0.5 | 365 days; undated counts as one half-life old | `intel-record:{satno}` | A prior only. Cannot narrow the range alone and never lowers the ceiling |
| GCAT entry: bus, launch, operator | `web/routes/gcat.py` cache. Not wired to threat today | Coverage only | B2, extraction 1.0 | 365 days from refresh | `gcat:{satno}` | Declared fields are recorded as declared and never move a band |
| HRR membership, side, regime | `state.hrr_objects`; High Rate Revisit (HRR) list | None. Sets the regime for half-lives | not applicable | not applicable | not applicable | not applicable |
| NOTSO operator profile | `astro/notso.py` `OperatorBehaviourProfile` | Coverage only | D, capped at 0.3 | 365 days | `notso:{operator}` | Adversary-controlled: whether to file, and what to say |

### 5.2 Capability

| Signal | Source in SPECTRE | Reading | Reliability basis | Freshness | Group | Adversary resistance |
|:-|:-|:-|:-|:-|:-|:-|
| Discretionary reserve, propellant used | `domain/pol_assessment.py` `PropellantAssessment` (`:423`) via `_red_capability` | Ceiling MINIMAL when exhausted with no later burn; ceiling MEDIUM when the share is below 0.5 | Provider grade; extraction 0.5 (Isp and mass fraction assumed per regime, `manoeuvre_calibration`) | 90 days from the newest set; QDF reset applies | `elset-history:{provider}` | Burns below the floor, or a refuelling, keep the tank reading full. Capability only ever lowers the ceiling and never raises the floor. `reserve_reset_for()` is honoured |
| Impaired status | Intel record; `CapabilityEvidence.is_impaired()` (`:239`) | Ceiling MEDIUM, only when corroborated | D, capped at 0.3 | 90 days | `status:{satno}` | Voided by a newer confirmed burn and named possible deception (I5, I7) |

### 5.3 Behaviour

| Signal | Source in SPECTRE | Reading | Reliability basis | Freshness | Group | Adversary resistance |
|:-|:-|:-|:-|:-|:-|:-|
| Normality of the latest burn | `domain/normality.py` `judge_burn()` via `routes/pol.py` `history_evidence()` | UNPRECEDENTED: floor HIGH. UNUSUAL: floor MEDIUM. ROUTINE: none. NOT_ENOUGH_HISTORY: listed as missing | Provider grade × burn detection grade; ROUTINE capped at 0.5 | 60 days at GEO, 14 in LEO, 30 otherwise | `elset-history:{provider}` | The baseline is self-referential, so ROUTINE never lowers anything. A hostile reading persists until a later burn is judged |
| Anomaly index | `pol_assessment._assess_anomaly` | Floor at the rung, capped at MEDIUM | Same group, folded unless it is the strongest | as above | as above | Uncalibrated, so capped |
| Burn detection grade | `astro/dv_estimation.py` `_grade_confidence` | Sets extraction | not applicable | not applicable | not applicable | Burning near the noise lowers extraction. That lowers Understanding, not the threat |
| Corroboration | `astro/pattern_of_life.py` `Manoeuvre.corroborated_by` (`:211`) | As the burn | Credibility 1 | as above | One group per provider | Copies of one catalogue count once |
| Own or allied optical or RF confirmation | Not held today. Operator entry, then a feed | As the burn | A1 | as above | `allied:{sensor}` | A controlled source is needed for HIGH rigour |
| Absence of burns | `PolAnalysis.manoeuvres` empty; `DetectionLimits.floor_m_s` (`pol_assessment.py:721`); custody | Coverage only | Provider grade × 0.5, capped at 0.5 | as above | `elset-history:{provider}` | Counts only if custody was HELD across the window, the span is at least 30 days, `floor_m_s` < `AccessEvidence.best_delta_v_m_s`, and no `long_gap` is open |
| Posture of the latest burn | `manoeuvre_calibration.classify_posture()` | AGGRESSIVE or BEYOND_PLATFORM: floor MEDIUM | Provider grade × burn grade | as above | as above | Computed against cited bands |
| Photometry change correlated with a burn | `astro/photometry.py` `assess_photometry()`, upload only | Coverage, as a new phenomenology | Grade of the uploader's source | 60 days | `photometry:{source}` | Attitude changes alter brightness. Coverage only |
| NOTSO filing matching a burn | `astro/notso.py` correlation; `threat.py` `_notso_cue` (`:1962`) | Coverage only | D, capped at 0.3 | 60 days | `notso:{operator}` | Adversary-controlled |
| Manual element set confidence | `threat.py` `_CONFIDENCES` (`:284`). Shown today but not wired | Sets extraction; caps Understanding | not applicable | not applicable | not applicable | not applicable |

### 5.4 Interactions

| Signal | Source in SPECTRE | Reading | Reliability basis | Freshness | Group | Adversary resistance |
|:-|:-|:-|:-|:-|:-|:-|
| Warning change caused by a burn | `domain/warning_change.py` `classify()`; `threat.py` `_warning_change()` (`:1922`) | NEWLY_IN_REACH or CUT: floor HIGH | Provider grade × burn grade | 30 days | `approach:{red}:{blue}` | Only attributable changes count |
| Closest approach after a burn | `astro/elset_approach.py` | Under 50 km within 7 days of a burn, and closer than before it: floor MEDIUM | as above | 30 days | as above | Refused on out-of-date sets, as `decision.py` `_earned_s` |
| UDL conjunctions | `web/udl_conjunction.py` `read_conjunctions()`; miss distance arrives as a string | Same rule | Provider grade | 30 days | `conjunction:{pair}` | Accidental passes add nothing |
| Hostile seed propagation | New `domain/interaction_graph.py` | Floor MEDIUM at most | q_edge × 0.5^hops, at most 2 hops | 30 days | `seed:{seed}` | Nothing propagates from benign seeds |

### 5.5 Modifiers: inputs to Understanding, not evidence

● Custody: `domain/custody.py` `assess_custody()` via `routes/pol.py` `custody_from_history()`. This is the same shared rule as the Decision Engine.
● Element-set age: `web/elsets.py` `elset_age()`.
● Data mode: `threat.py` `_red_track_mode`.
● Truncation: `PolAnalysis.history_truncated_at`.
● Basis: `domain/provenance.py` `weakest()`.

**Held but deliberately not used.** The `astro/tactical.py` intent, fingerprint and detectability scores have uncited weights (audit findings F-018 to F-020).

## 6. How Understanding is computed and shown

### 6.1 Three categories, the weakest governs

This follows the PHIA AnCR and SPECTRE's own weaker-governs rule (`provenance.weakest()`). Each level has explicit criteria, which is the ODNI lesson.

**Information Base**
● HIGH requires all three of:
  ■ Identity, Capability and Behaviour earned (Interactions may stand in for Identity)
  ■ at least 2 independent source chains across the ledger
  ■ at least 1 group graded A or B in Capability or Behaviour
● MODERATE: 2 dimensions earned, one of them Behaviour or a COMPUTED Capability reading.
● LOW: anything less.

**Analytical Rigour**
● HIGH requires both:
  ■ the weakest basis among the readings that set the floor and ceiling is COMPUTED
  ■ a controlled source group is among them
● MODERATE: the weakest basis is SAMPLED, or COMPUTED from uncontrolled sources only.
● LOW: any governing reading is a LOOKUP.

**Complexity and Volatility**
● HIGH requires all three of:
  ■ custody HELD
  ■ no conflict
  ■ a latest burn that is ROUTINE, or that has been held for 3 element-set limits since it occurred
● MODERATE: custody DEGRADED, a conflict or possible deception, a recent UNUSUAL or UNPRECEDENTED burn, or a truncated history.
● LOW: custody LOST.

### 6.2 Caps

● A data mode of SYNTHETIC, TEST, EXERCISE or SIMULATED caps Understanding at **LOW**. The statement reads: "computed from SYNTHETIC element sets: describes the exercise, not the satellite".
● An unrecorded data mode reads UNKNOWN, not REAL as `threat.py` assumes today (`:520`, `:1438`, `:1454`, `:2648`, `:2723`, `:2725`). It caps Understanding at MODERATE.
● A manual element set caps Understanding at the operator's stated confidence:
  ■ CONFIRMED or HIGH: HIGH
  ■ MEDIUM: MODERATE
  ■ LOW or UNCONFIRMED: LOW
● Orbital geometry never counts towards Understanding.

### 6.3 The statement

The statement follows the AnCR form:
● one sentence naming the governing category and what is missing
● then up to 3 cues, each with the steps it would remove

Example:

"Understanding MODERATE. Governing: volatility, an unprecedented burn 33 h ago whose new orbit is not yet settled. Raise it by: 9 days of held custody after the burn; a second provider's element sets (closes Capability)."

### 6.4 On screen

● **Every figure is labelled "Threat" or "Understanding".** Neither scale ever shows a bare HIGH or LOW.
● **The Threat line comes first, in its own sentence:** "Threat: assessed CRITICAL. Could be as low as HIGH." When the floor rule applies, it reads "Threat: cannot assess beyond access (CRITICAL). The verdict below is geometry alone."
● **The Understanding line follows, in a separate sentence,** with the statement.
● **The verdict badge is outlined, not filled, when Understanding is LOW.** This is the content-advisory cue.
● **The understanding strip has four cells:** Identity, Capability, Manoeuvres and Interactions. Each is filled, half-filled or empty from u_d. The tooltip lists each item with its grade (for example "B2"), age and basis.
● **"What it rests on" is a ledger, collapsed by default.** It has one row per item, showing:
  ■ dimension
  ■ claim
  ■ grade
  ■ age
  ■ basis
  ■ q
  ■ status: counted, folded ("same history as reserve; not counted again"), voided ("possible deception"), below threshold, or decayed
● **"Missing" lists dimensions and signals not held,** for example "photometry not uploaded", "no second provider" or "NOTSO cache 7 months old".
● **No percentage and no PHIA yardstick word is rendered** until SPC-177 and calibration allow it.

## 7. How SPECTRE uses it

### 7.1 The sweep

`templates/partials/threat_sweep.html` changes at lines 147 to 167. The ranked order of the operator's four outputs is kept:
1. Is this normal
2. The warning-time change
3. Decide-by
4. The recommended response

Threat Understanding adds to output 1, changes when output 3 is withheld, and feeds output 4.

Wiring in `web/routes/threat.py`:
● `_red_custody` moves before `_worst_coa_in_context` (around `:2363`).
● Custody, the latest normality, data mode, element-set age and the held history are passed into the evidence adapters.
● Provenance carries the ledger hash.

### 7.2 The screen

● The ranked table in `templates/partials/threat_screen.html` (`:127` to `:129`) gains RANGE and UNDERSTANDING columns. It has no confidence column today.

● `_screen_one_actor` (`threat.py:1134`) reads only histories already cached by `routes/pol.py` `held_history()`. It makes no new fetch. An actor without a cached history reads "Understanding LOW: no history held", and the cue is to pull it.

● The disagreement sentence in `rank_actors` (`threat_assessment.py:564`) gains a case: "X is assessed MEDIUM at Understanding LOW, but its ceiling is CRITICAL and it arrives in 3.1 h."

### 7.3 The intel and Pattern of Life panels

● **The target intel card** (`templates/partials/pair_card.html`, included from the sweep, the red orbit view, the intercept result and Pattern of Life):
  ■ It keeps "Analyst judgement, not a computed score" on `threat_level`.
  ■ It gains the record's grade and status in the ledger, for example "undated, single open source [C3]: listed, does not move the range".
  ■ It adds the cue "date and source this record".

● **The Pattern of Life panel** (`templates/partials/pol_results.html`) shows the same understanding strip, so one object reads the same on every panel. Custody and normality there are the same values that set volatility.

### 7.4 Decide-by

● `_sweep_decide_by` (`threat.py:2172`) withholds decide-by only in two cases:
  ■ custody is LOST (as today)
  ■ the **ceiling** is MINIMAL on earned COMPUTED incapacity, and Understanding is not LOW
● A status string alone no longer silences the clock. The withheld or shown sentence names the evidence.
● The arrival times are unchanged.

### 7.5 The Decision Engine

**1. Collect first.**
● `collection_advice()` returns COLLECT_FIRST, ACT_ON_CEILING or BELOW_ACTION_LINE (section 4.10).
● Cues that need a sensor or an analyst become prefilled `FriendlyResponse` rows with `ActionType.SENSOR_RETASK` (`decision.py:150`). Each row's name is the cue, `time_to_execute_hours` is the cue's lookup duration, and its `FigureBasis` is LOOKUP with the note "collection to narrow the threat range".
● The existing lookup already treats SENSOR_RETASK as halving the custody gap (`decision.py:1427` to `:1430`).
● Cues inside SPECTRE, such as pulling a history or holding conjunctions, are one-click actions on the card.

**2. AdversaryAction.confidence is not touched.**
● In `_lookup_figures`, `custody_gap_hours = scenario.horizon_hours × adversary.confidence` (`decision.py:1426`). Higher intelligence confidence therefore lengthens our own custody gap, so the field's meaning is inverted.
● SPC-161 separated the two meanings in 0.17.0: the custody gap has its own per-row share, and confidence moves no figure. Understanding may now be offered for this field, as a suggestion the operator accepts, never prefilled.

**3. AdversaryAction.probability is never prefilled.**
● Both fields default to 0.5 (`routes/decision.py:194` to `:195`).
● The Threat range and Understanding are shown beside the fields as context only.

**4. Objective guidance.**
● When `SelectorStrategy.EXPECTED_VALUE` is selected and any bound adversary row has Understanding LOW, or an untouched default probability, the result says: "Expected value rests on a probability the evidence has not earned." It recommends MINIMAX.
● Each adversary row carries its Understanding level into the result.

**5. One deadline.** The engine's deadline is the sweep's decide-by, through the same wrapper, so the two cannot disagree. This is the single-rule pattern used for custody (SPC-123).

### 7.6 Feedback

● Accept, override and annotate actions are logged with the result's provenance hashes, as are after-action outcomes.
● They feed two things:
  ■ a coverage report: how often adjudicated outcomes fell inside [floor, ceiling]
  ■ a proposed change to provider grades, which an analyst must approve
● They never move a band.

## 8. What is deliberately not done

● **No learned combiner.** There are no labels, and it could not be audited. It becomes possible only once adjudications accumulate.

● **No probabilities or percentages on screen,** and no PHIA or ICD 203 words, until the citations are verified (SPC-177) and calibration exists.

● **No Dempster's rule.** It turns conflict into false certainty.

● **No full PageRank.** The graph is too sparse, so propagation is capped instead.

● **No trust propagation from benign seeds.** Proximity to a friendly-looking object clears nothing.

● **No feedback that moves a band.**

● **No silent fill of `AdversaryAction.confidence`.** SPC-161 has separated its meaning, so Understanding may be offered as a suggestion, never written into the field unasked.

● **No change to how ACCESS is computed.** Geometry stays the ceiling.

● **No downgrade from ROUTINE, "no burns", declared status or declared mission alone.**

● **No use of the `astro/tactical.py` heuristic intent scores.**

● **No new dependencies.** Hypothesis is not installed, so the invariants are tested by exhaustive `itertools` subsets and parametrised orderings.

## 9. Owner decisions needed

1. **The HIGH rule.** HIGH needs Identity, Capability and Behaviour earned, with Interactions able to stand in for Identity. The alternative is to require Interactions once SPC-172 ships. Recommendation: decide at SPC-172.

2. **Visible drops.** Objects now shown at confidence HIGH will drop. All 38 bundled HRR element sets are SYNTHETIC, so every demonstration will read Understanding LOW. That is the honest answer, and it should be briefed before 0.16.

3. **Verdict at the ceiling under LOW Understanding** (SPC-175). Some verdicts will rise to access, for example HIGH to CRITICAL in contrast C. The switch needs sign-off against the reference table.

4. **Decide-by after a declared "Degraded"** (SPC-167). Operators will see more deadlines. Recommendation: ship it live, because it removes the cheapest manufacturable override.

5. **Who owns the seed list and the provider grade table.** Either may become classified. Keep them as data under UK sovereign handling, not in bundled files.
6. **When a stronger copy arrives with no reading (found building SPC-163).** I1 (adding an item never widens the range) and I2 (a copy never narrows it) meet here. A stronger item from the same source chain, arriving at the same epoch with no reading of its own, folds a weaker member's reading, so the range can widen. As built, I2 wins: only the strongest member of a group applies a reading, and a test pins it. Claude's choice, not a ruling.

7. **What ends a hostile floor (found building SPC-163).** Section 4.4 says any later judged burn. As built, only a later UNUSUAL or UNPRECEDENTED burn ends it, following section 5.3, section 8 ("no downgrade from ROUTINE alone") and I9. The floor's coverage and Understanding still decay, so a stale floor reads as poorly understood. Claude's choice, not a ruling.

8. **A spent tank read from one provider (found building SPC-167).** Section 7.4 withholds decide-by only on an earned COMPUTED MINIMAL ceiling. Section 4.6 applies a reading only in an earned dimension, and one provider's reserve figure is q 0.34 (B2, extraction 0.5), so it cannot earn Capability alone. Contrast B already names a second provider's history as what would lower the ceiling to MINIMAL. The sweep holds one merged history, so on the live sweep today a computed spent tank never withholds decide-by: only custody LOST does, and the decide-by sentence says why the tank did not ("Capability not earned"). Before SPC-167 that one history withheld it. The options are to accept this (more deadlines, the cautious side), to grade a provider A, or to let the sweep read a second provider's cached history (SPC-169). Built as the concept reads and pinned by a test (`TestTheLiveSweepOnOneProvider`). Accepted for 0.17.0 as Claude's choice, not a ruling: showing a deadline that may prove unnecessary is the cautious side, and withholding one asserts an incapacity the evidence has not earned. SPC-169 is how a second provider earns it. The owner may overrule.

9. **Where the Decision Engine reads the Threat range and decide-by (found building SPC-171).** Section 7.5 assumes the engine can read decide-by and the range. It cannot: the engine has no intercept in view, so no ACCESS and no deadline of its own, and the sweep keeps neither once it has rendered. As built, the sweep's half is `hold_threat_picture` in `web/decision_threat.py`, one call after the sweep's decide-by, and the engine reads the picture only when it is bound to the same red track and the picture is under 30 min old, the age at which the sweep would fetch the history again. The sweep's decide-by is for its soonest target, so with another blue asset bound the engine reads the picture with no deadline, and a straddle acts on the ceiling. With no current picture, its rows read "Understanding not assessed: the engine holds no current picture from the sweep", which is true whether or not a sweep was run. The one call belongs in `web/routes/threat.py`, which the SPC-171 build was not allowed to change, so until it is made the engine page shows no collect-first advice. Claude's choice, not a ruling.

10. **Collect first with no decide-by (found building SPC-171).** Section 4.10 tests `now + hours ≤ decide_by`, which has no answer when decide-by is withheld or no target is in reach. As built, no cue can then be shown to land in time, so a straddle acts on the ceiling, the cautious side, and the sentence says no decide-by is set. Only a cue that could move a band and whose result SPECTRE can read counts: holding conjunctions and a second provider's history cannot be read yet, so they never make the advice collect first. Section 4.10 asks only for VOI above 0; as built, a cue counts only when one of its outcomes takes the range off the action line (its benign ceiling under it, or its hostile floor at or above it), since a cue that leaves the range across the line either way cannot change the decision and spends time before decide-by for nothing. Claude's choice, not a ruling.

11. **What counts as an untouched probability (found building SPC-171).** Section 7.5 item 4 names "an untouched default probability". The form cannot tell 0.5 left alone from 0.5 typed again, so a row at the engine's default of 0.5 is read as untouched, and the guidance shows. A bound red track with no picture held counts as Understanding not earned. Both err towards showing the guidance, which recommends and never switches the selector. With no current picture held, the guidance says only that: "Expected value rests on a probability no current Threat picture for the red track supports". Claude's choice, not a ruling.

12. **Collect-first rows are listed, not scored (found reviewing SPC-171).** Section 7.5 item 1 makes each analyst or sensor cue a `FriendlyResponse` of type SENSOR_RETASK. Built that way, the row won the ranking under minimax and expected value: the custody lookup credits a sensor retask with a short custody gap, and its cost of 0 and reversibility of 1 were made up for it. No collection in the code tasks a sensor, and collecting moves no figure until what it finds is in the sweep. As built, each such cue is a collection row listed beside the ranking, named by the cue, timed by its lookup duration and labelled "collection to narrow the threat range", and it never enters the outcome matrix, the robust choice or the minimax guidance. The recommended response is always one of the operator's own rows. Claude's choice, not a ruling.

13. **What a scenario opened from the sweep can carry (found building SPC-150).** The sweep's entry sums every burn of a transfer into its prograde, normal and radial figures, which is no one burn, and the engine models one impulsive burn per adversary row. As built, the sweep keeps each entry's first burn (`ThreatSweepEntry.departure_m_s`) and the scenario's first row is that departure burn, at its own UTC time, so it does not move along the orbit while the panel is open. A detected burn is built from the element set before it through `hypothesis_from_tle_record`, as asked, but the engine refuses to sample any burn older than the bound red element set, which may already include it (`decision._after_burn`); a detection is found from the element set after it, so on a current red track its row is nearly always carried for its burn time, which sets when custody is lost, with its closest approach a lookup, and the panel says so before Evaluate. The target binds as the blue asset only by catalogue number, never by name, and a red track binds only while the set the sweep flew is the one held. Claude's choice, not a ruling.

14. **Which UDL conjunctions count as Interactions (found building SPC-173).** Only REAL-mode rows count, whatever data mode the red track came from, and a conjunction counts as closer only by more than 8 km, the smallest element-set error the SPC-118 model allows at epoch, since a UDL record carries no element-set age we read. An exercise sweep therefore refuses exercise conjunctions, and says so. Claude's choice, not a ruling; tuned, not sourced.

15. **What the screen says about a hostile seed (found reviewing SPC-174).** A propagated path reads "1 hop from a hostile seed, through X": the seed itself is named only when it is the object the operator already sees approached, and the ledger never lists the seed count. Whether operators may see seed identities at all belongs with decision 5. Claude's choice, not a ruling.

16. **What Load from NOTSO loads (found building SPC-131).** Section 7.5 items 2 and 3 forbid filling P or Conf. As built, the panel lists each adversary row with a labelled "Load from NOTSO" control, and no row's NOTSO history is read until the operator presses it. Loading shows the suggestion, its basis, its interval and the control that applies it, unticked; it writes nothing into the P or Conf fields, and applying is still the tick, honoured at Evaluate only while the suggestion is the one shown. A loaded row stays loaded through later changes to the form by a hidden field the region carries, and a ticked row counts as loaded. Before SPC-131 every row's suggestion was worked out on every change. The results show a NOTSO timeline for each applied suggestion: its covered periods, the gaps between them, any time before the launch year, the time from the cache's last covered moment to the moment evaluated (named as not covered, so a cache not synced since reads as uncovered, not quiet), and each notice it counted, dated to the minute and marked when it copies an event already counted, as a list named in words and a bar on which a gap is hatched and outlined and a notice is a full-height tick, so it reads without colour. Notices outside the covered periods are not listed, since none of them was counted. Claude's choice, not a ruling.

17. **The interval on a NOTSO-derived P (found building SPC-132).** The interval is the exact (Garwood) 95 in 100 Poisson interval on the events counted, carried over the horizon as P is: half the chi-square quantiles at 0.025 on 2k and at 0.975 on 2k + 2 degrees of freedom. The events are a count over an exposure time, which is what a Poisson interval describes, and a suggestion rests on as few as 3 of them, where a normal interval runs below 0 and under-covers; the exact interval keeps at least its stated coverage at any count and errs wide, the side a floor should err on. Its edges are rounded outward, a lower edge under the hundredth reads "under 0.01", never 0, and the pick is then checked from the exact edge. It is an interval on the reported rate: like P, it says nothing of burns no notice was filed for. The line beside the suggestion gives its reason for an exact interval in terms true at any count: a suggestion can rest on as few as 3 events, where an approximate interval runs below 0. Claude's choice, not a ruling.

18. **How the interval reaches the pick (found building SPC-132).** Under expected value, each row holding an applied suggestion has its P moved across its interval with the other rows held at their own P, and the result says whether the recommended response holds at every P in it or names, on each side of the row's P, the P at which it changes and what it changes to. Every response's expected score shares one total, so each is ordered by a weighted sum that is a line in the row's P, and the pick can change only where two lines cross; the pick is read between crossings, never by sampling. With two or more rows holding applied suggestions, they are also moved together: every corner of the box their intervals make is checked, and the result says the pick holds throughout or names a corner, each row's P at it, where it changes and what to. Each response's region of the box is an intersection of half-spaces, so convex, and holds the whole box when it holds every corner; the corners therefore answer exactly, and at most 5 rows make 32 of them. Moving rows one at a time alone could read as stable when the pick changes once they move together. Minimax and minimin read no probability, so under either the result says so in one line naming the rows and shows no interval. Claude's choice, not a ruling.

## 10. Build plan

Each item is test-first: write the failing case or invariant, write the code, then run the full unit suite. The first item ships alone in 0.16.

**Releases**
● The backlog plans the releases (`.board/PLAN.md`), in the dependency order of the table below.
● SPC-160 ships first. The verdict itself changes only at SPC-175, behind a setting that stays off until the owner signs off against the reference table.

**Estimate:** about 77 hours.

| ID | Title | Hours | Files | Depends on | The test that proves it |
|:-|:-|:-|:-|:-|:-|
| SPC-160 | Confidence stops counting copies and geometry | 5 | `domain/threat_assessment.py`, `web/routes/threat.py`, `threat_sweep.html`, `tests/unit/test_threat_assessment.py`, `test_threat_sweep_template.py` | none | I12 four measured cases. Across all 64 subsets of the 6 inputs, adding one never lowers the level unless it adds a conflict. SYNTHETIC gives LOW. Custody LOST gives LOW. History figures count once |
| SPC-161 | Separate the custody-gap meaning from `AdversaryAction.confidence` | 3 | `domain/decision.py`, `web/routes/decision.py`, `tests/unit/test_decision_reference_cases.py` | none | Raising intelligence confidence no longer lengthens our custody gap. Existing reference cases are unchanged at the default |
| SPC-162 | Evidence items, reliability and coverage | 5 | new `domain/threat_understanding.py`, new `tests/unit/test_threat_understanding.py` | none | q in [0, 1]. Freshness monotone in age. QDF reset halves pre-burn items. Undated counts as one half-life. Manufacturable cap. I2 duplicate no-op. A single capped item never earns |
| SPC-163 | Threat range, readings, voiding and conflicts | 5 | `threat_understanding.py`, tests | SPC-162 | I1, I3, I5, I6, I7, I9. floor ≤ assessed ≤ ceiling across parametrised grids. Contrast A voids the status |
| SPC-164 | Understanding categories, caps and statement | 4 | `threat_understanding.py`, tests | SPC-162, SPC-163 | One case per criterion row. SYNTHETIC LOW. UNKNOWN mode MODERATE. Manual set cap. I4 |
| SPC-165 | Adapters from held signals | 5 | `threat_understanding.py`, `web/routes/threat.py`, `web/routes/gcat.py`, tests | SPC-162 | The absence rule with the Δv test. `corroborated_by` opens a group. The `long_gap` halving. The worked example rows 1 to 6 reproduce |
| SPC-166 | Sweep wiring in shadow, with ledger hash | 5 | `web/routes/threat.py`, `domain/provenance.py`, `tests/unit/test_threat_sweep.py` | SPC-163, SPC-164, SPC-165 | The legacy verdict is unchanged on all 20 bundled red objects. I10: same inputs give the same hash |
| SPC-167 | Status becomes evidence; decide-by withheld only on an earned MINIMAL ceiling | 3 | `domain/threat_assessment.py`, `web/routes/threat.py`, tests | SPC-163 | Degraded with a newer burn keeps decide-by. A COMPUTED spent tank with no later burn still withholds |
| SPC-168 | Operator display: Threat and Understanding lines, outlined badge, strip, ledger, panels | 5 | `threat_sweep.html`, `pair_card.html`, `pol_results.html`, template tests | SPC-166 | I13 regex: no shared sentence, no percentage, no bare band. The badge is outlined under LOW. The strip matches on every panel |
| SPC-169 | Screening with cached history; RANGE and UNDERSTANDING columns | 4 | `web/routes/threat.py`, `threat_screen.html`, `domain/threat_assessment.py`, `test_threat_screen_template.py` | SPC-166 | A cached history raises Understanding. An uncached one reads "no history held". The new disagreement case renders |
| SPC-170 | Cues and value of information | 4 | `threat_understanding.py`, tests | SPC-163, SPC-164 | Order follows steps per hour. VOI is 0 when both hypotheticals give the same range. No cue for an earned dimension. Contrast B ranks as in 4.12 |
| SPC-171 | Decision Engine: collect-first rows and the MINIMAX guidance | 5 | `domain/decision.py`, `web/routes/decision.py`, `test_decision_figure_basis.py`, new `test_decision_understanding.py` | SPC-170, SPC-161 | A straddle with time gives COLLECT_FIRST. The same range with decide-by PASSED gives ACT_ON_CEILING. Bases stay LOOKUP. Probability is never prefilled |
| SPC-172 | Interactions v1 from warning changes | 5 | new `domain/interaction_graph.py`, `web/routes/threat.py`, tests | SPC-165 | A pass with no prior burn adds nothing. NEWLY_IN_REACH after a burn raises the floor to HIGH. Worked example row 7 |
| SPC-173 | Interactions v2: UDL conjunctions and closest approaches held per object | 5 | `web/udl_conjunction.py`, `astro/elset_approach.py`, `interaction_graph.py`, tests | SPC-172 | Malformed miss-distance strings are refused and stated. Stale sets are refused. The "closer than before the burn" rule holds |
| SPC-174 | Hostile seeds and propagation | 5 | `interaction_graph.py`, seed data file, tests | SPC-172 | 1-hop and 2-hop values. A third hop adds nothing. A benign seed has no effect. One edge never lifts the floor past MEDIUM through propagation |
| SPC-175 | Verdict switch behind a setting, with a reference table | 4 | `domain/threat_assessment.py`, `config/constants.py`, reference test | SPC-166 to SPC-169 | The old and new verdicts for all 20 bundled red objects match a committed table. The setting stays off until the owner signs off |
| SPC-176 | Adjudication log and coverage report | 5 | new `domain/adjudication.py`, `web/routes/threat.py`, tests | SPC-166 | An override never changes a band. The coverage rate is computed once 30 or more adjudications exist |
| SPC-177 | Citation check gate for doctrine wording | 2 | `docs/threat_confidence_concept.md`, `domain/threat_understanding.py` | Network access to gov.uk and dni.gov, and MOD channels for AJP-2.1 | A test fails if any yardstick or ICD 203 term renders while the `VERIFIED` flag is false |

## 11. Sources

**Search and data integration**
● Brin and Page 1998: https://research.google/pubs/the-anatomy-of-a-large-scale-hypertextual-web-search-engine/ and https://www.site.uottawa.ca/%7Ediana/csi4107/Google_SearchEngine.pdf
● TrustRank, Gyöngyi et al. 2004: https://vldb.org/conf/2004/RS15P3.PDF
● Google ranking systems guide: https://developers.google.com/search/docs/appearance/ranking-systems-guide and https://developers.google.com/search/blog/2022/11/introducing-guide-to-ranking-systems
● Burges 2010, RankNet to LambdaMART: https://www.microsoft.com/en-us/research/?p=159784
● QDF, secondary: https://searchengineland.com/guide/query-deserves-freshness-qdf
● Knowledge Vault 2014: https://research.google/pubs/knowledge-vault-a-web-scale-approach-to-probabilistic-knowledge-fusion/
● Knowledge-Based Trust 2015: https://arxiv.org/abs/1502.03519
● Source dependence 2009: https://lunadong.com/publication/dependence_vldb.pdf
● NavBoost, secondary: https://www.hobo-web.co.uk/navboost-how-google-uses-large-scale-user-interaction-data-to-rank-websites/

**Intelligence assessment**
● PHIA: https://www.gov.uk/government/publications/explaining-uncertainty-in-uk-intelligence-assessment/explaining-uncertainty-in-uk-intelligence-assessment and https://www.gov.uk/government/publications/phia-common-analytical-standards/phia-common-analytical-standards
● Admiralty code: https://en.wikipedia.org/wiki/Admiralty_code and https://pangearesearch.substack.com/p/the-admiralty-code-nato-6x6-system
● ICD 203: https://www.dni.gov/files/documents/ICD/ICD-203.pdf
● ODNI research note: https://www.dni.gov/files/documents/FOIA/DF-2024-00001-NIU_Research_Short.pdf

**Evidence combination**
● Good on Turing: https://jhanley.biostat.mcgill.ca/bios601/CandH-ch0102/GoodOnTuring.pdf
● Karvetski, Mandel and Irwin 2020: https://doaj.org/article/3d19a7e3b1bf4b28b07aa346da34f0db
● Zadeh's paradox: https://arxiv.org/pdf/math/0404371

**Space Domain Awareness**
● RPO and PoL: https://amostech.com/TechnicalPapers/2024/Poster/Serrano.pdf
● Secure World Foundation 2025: https://swfound.org/media/208089/swf_global_counterspace_capabilities_2025.pdf
● PoL baselines: https://dspace.mit.edu/handle/1721.1/151249
● SHERLOC: https://stottlerhenke.com/wp-content/uploads/2025/10/2025_AMOS_Jensen_et-al_SHERLOC.pdf