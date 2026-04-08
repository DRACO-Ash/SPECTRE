# Claude Prompt: Gamified Training Environment for the Space Planning, Evaluation & Counter-Threat Response Engine

> **Purpose:** Paste this prompt into Claude when you're ready to have it build the gamified training environment.  
> **Pre-requisite:** Claude should already have the SPECTRE codebase in context (uploaded or in-session).  
> **Usage:** Adapt the [PLACEHOLDER] sections to match your current codebase state before submitting.

---

## The Prompt

---

I'm building a gamified training environment for the **Space Planning, Evaluation & Counter-Threat Response Engine (SPECTRE)** — a modelling and simulation application that provides fast manoeuvre calculations for Protect & Defend operators. The training environment must be a **sandboxed area** that lets operators learn, practise, and build confidence without touching real operational data.

### Who the learners are

- Military space domain analysts and Protect & Defend operators.
- Mixed experience levels: some are experienced orbital analysts, others are new to the tool.
- They work under time pressure and need to build muscle memory for the SPECTRE workflow.
- They are motivated by competence and mission readiness, not by trivial rewards.

### What a training session looks like today

There is currently no training session, this is a new application.

### What I need you to build — the full scope

#### 1. Sandbox Architecture (Data Isolation)

Design and implement a sandboxed training environment that:

- **Completely isolates training data from operational data.** Training actions must never write to, modify, or read from production data stores. Define the isolation boundary explicitly — I want to understand exactly where the wall is.
- **Uses realistic but synthetic scenario data.** Generate or define a library of training scenarios that feel operationally authentic (realistic orbits, plausible threat geometries, credible timing) but are clearly marked as training data.
- **Mirrors the production UI exactly.** The sandbox should look and behave identically to the operational tool — same controls, same workflow, same outputs — so skills transfer directly. The only visual difference should be a clear, persistent **"TRAINING MODE"** indicator so operators never confuse training with operations.
- **Resets cleanly.** Operators should be able to reset any scenario to its starting state without side effects.

#### 2. UI Integration

- Add a **"Training"** link/button in the application banner, positioned near the logout button, visually consistent with the existing nav design.
- When an operator enters training mode, the environment should transition smoothly — no jarring page reloads or context loss.
- The training area needs its own internal navigation: tutorials, sandbox free-play, challenge scenarios, and the operator's progress dashboard.
- Provide a clear, one-click **"Return to Operations"** path that exits training mode unambiguously.

#### 3. Walkthrough Tutorials (Guided Learning)

Build an interactive tutorial system with the following properties:

- **Step-by-step guided walkthroughs** that overlay the actual SPECTRE interface (not a separate documentation page). The operator learns by doing, with contextual guidance appearing as they interact with real controls.
- **Progressive disclosure** — start with the simplest workflow (e.g., "Load a scenario and view the orbit") and build toward complex tasks (e.g., "Plan an evasive manoeuvre under time constraint").
- **Tutorials should cover these operator workflows** (adapt to match your actual SPECTRE features):
  1. **Orientation** — Navigate the interface, understand what each panel shows.
  2. **Scenario Loading** — Load a pre-built threat scenario, interpret the initial conditions.
  3. **Threat Assessment** — Read the threat geometry, identify the aggressor's approach, understand the timeline.
  4. **Manoeuvre Planning** — Use the planning tools to compute a response manoeuvre.
  5. **Decision Evaluation** — Compare manoeuvre options, assess delta-v cost vs effectiveness.
  6. **Full Engagement Cycle** — End-to-end: detect → assess → plan → decide → act, under simulated time pressure.
- Each tutorial step should have: a **highlight/focus** on the relevant UI element, a **brief instruction** (1-2 sentences), an **action the operator must take**, and **validation that they did it correctly** before advancing.
- Allow operators to **skip ahead** or **restart** any tutorial.

#### 4. Sandbox Free-Play Area

- Provide a library of **pre-built scenarios** ranging from simple (single threat, cooperative geometry) to complex (multiple threats, constrained delta-v budget, degraded sensor coverage).
- Let operators **modify scenario parameters** — change orbits, add/remove threats, adjust timing — and immediately see the effect.
- Include a **"What-if" mode** where operators can fork a scenario, try different manoeuvre options, and compare outcomes side-by-side.
- Every sandbox session should be **disposable** — no persistent state unless the operator explicitly saves a scenario for later.

#### 5. Gamification Layer — This is the core of what I want you to design carefully

I want gamification that **respects the operator's intelligence** and reinforces genuine skill development, not superficial engagement. The game mechanics must map directly to operational competence. Design the following:

##### 5.1 Points System

- **Define point-earning actions** that map to real operational skills. Examples:
  - Completing a tutorial step → small points (learning).
  - Completing a full tutorial → bonus points (persistence).
  - Successfully planning a manoeuvre that meets mission constraints → significant points (competence).
  - Making a correct threat assessment within a time window → points scaled by speed and accuracy (operational tempo).
  - Identifying the optimal manoeuvre from multiple options → points for analytical quality.
  - Completing a scenario with minimal delta-v expenditure → efficiency bonus.
- **Define point categories** that reflect distinct skill axes, not a single number. Suggested axes:
  - **Situational Awareness** — How quickly and accurately does the operator read a threat scenario?
  - **Manoeuvre Planning** — Can the operator compute effective responses?
  - **Decision Quality** — Does the operator choose the best option, not just a valid one?
  - **Operational Tempo** — Can the operator work at the speed the mission demands?
  - **Efficiency** — Does the operator minimise resource expenditure (delta-v, sensor tasking)?
- Points should be **visible but not distracting** — a summary in the progress dashboard, not a constant pop-up.

##### 5.2 Levels / Progression System

Design a level system that represents genuine **proficiency progression**, not just accumulated screen time. Suggested structure:

| Level | Title | What it represents | Unlock condition |
|-------|-------|--------------------|------------------|
| 1 | **Cadet** | Can navigate the interface and load scenarios | Complete orientation tutorial |
| 2 | **Observer** | Can read and interpret threat scenarios | Complete threat assessment tutorial + pass a timed assessment |
| 3 | **Planner** | Can compute valid manoeuvre responses | Complete manoeuvre planning tutorial + solve 3 planning challenges |
| 4 | **Analyst** | Can evaluate multiple options and choose optimally | Score above threshold on decision quality across 5 scenarios |
| 5 | **Operator** | Can execute the full engagement cycle under time pressure | Complete 3 full-cycle timed scenarios with passing scores on all axes |
| 6 | **Instructor** | Mastery — can handle edge cases and degraded conditions | Complete advanced challenge scenarios (constrained delta-v, degraded sensors, multiple simultaneous threats) |

- Levels should **unlock progressively** — an operator can't skip to Level 5 without demonstrating Level 1-4 skills.
- Each level should unlock **new scenario complexity** and **new challenge types** in the sandbox.
- Level progression should be **visible on the progress dashboard** with clear indication of what's needed to advance.

##### 5.3 Challenge Scenarios (Timed/Scored)

- Distinct from free-play: these are **structured assessment scenarios** with defined success criteria.
- Each challenge has:
  - A **scenario briefing** (threat geometry, defended assets, constraints).
  - A **time limit** (reflecting operational tempo requirements).
  - **Scoring criteria** mapped to the point categories above.
  - A **debrief screen** showing what the operator did, what the optimal action was, and where they gained/lost points.
- Challenge difficulty scales with operator level.
- Include **"daily challenge"** or **"scenario of the week"** mechanics to encourage regular practice without mandating it.

##### 5.4 Progress Dashboard

- Show the operator's **current level and progress toward next level**.
- Show **skill axis breakdown** (radar/spider chart or similar) across the point categories.
- Show **recent activity** — scenarios attempted, scores, improvement trends.
- Show **time spent in training** — but frame it as investment, not surveillance.
- Optionally: **anonymised team/cohort comparison** ("You're in the top quartile for Manoeuvre Planning") — but only if this suits your organisational culture. Make this toggleable.
- Include a **"Recommended Next Step"** based on the operator's weakest skill axis.

##### 5.5 Anti-Patterns to Avoid

- **No pay-to-win or artificial gating.** Every operator should be able to reach every level through demonstrated skill.
- **No punitive mechanics.** Failing a challenge shouldn't cost points — it should offer a debrief and encourage retry.
- **No leaderboards that shame.** If you include comparative elements, make them opt-in and anonymised.
- **No gamification that undermines trust in the tool.** The training environment must feel like professional development, not a mobile game.
- **No achievements for trivial actions.** Every reward must map to a real skill.

#### 6. Implementation Approach

- **Phase 1:** Sandbox isolation architecture + training mode toggle in the banner + basic scenario library. This must work correctly and be data-safe before anything else.
- **Phase 2:** Tutorial overlay system with the first 2-3 guided walkthroughs.
- **Phase 3:** Gamification engine — points, levels, progress dashboard, challenge scoring.
- **Phase 4:** Challenge scenario library, debrief system, recommended next steps.
- **Phase 5:** Polish — animations, transitions, cohort comparison (if desired), daily challenges.

For each phase, provide:
- The code changes with clear file locations.
- How the new code integrates with the existing SPECTRE codebase.
- What tests should be written.
- What the operator sees and experiences.

### Technical constraints

- **Tech stack:** [STATE YOUR CURRENT STACK — e.g., React frontend, Python/FastAPI backend, PostgreSQL database]
- **The training environment must not add latency to the operational tool.** Lazy-load training assets.
- **Training state (progress, points, levels) should persist per-operator** — stored server-side, not in browser storage.
- **The gamification engine should be modular** — easy to add new scenarios, adjust point values, and modify level thresholds without code changes (configuration-driven).
- **Accessibility matters** — the training UI must meet WCAG 2.1 AA minimum. Colour alone should not convey status.

### What I expect in your response

1. **Architecture overview** — how the sandbox, tutorial engine, and gamification engine fit together and integrate with the existing SPECTRE codebase. Include a clear data isolation diagram.
2. **Data model** — schema for training scenarios, operator progress, points, levels, challenge results.
3. **Component breakdown** — every new UI component, its responsibility, and where it lives in the project structure.
4. **Implementation code** — working code for each phase, starting with Phase 1. Not pseudocode — real, integrated, tested code.
5. **Scenario definitions** — at least 3 training scenarios with realistic orbital parameters, threat geometries, and scoring criteria.
6. **Gamification configuration schema** — the config file/structure that defines points, levels, and challenge criteria so these can be tuned without code changes.
7. **Test plan** — how to verify that sandbox isolation works, tutorials advance correctly, points calculate accurately, and levels unlock properly.

---

## Prompt Tuning Notes (for you, not for Claude)

### Before you paste this prompt:

1. **Fill in the [PLACEHOLDER] sections** — your current workflow description and tech stack. Claude will give much better output if it knows what already exists.

2. **Upload your codebase** or at least the key files: your main app component, routing configuration, data access layer, and any existing state management. Claude needs to see where to integrate, not guess.

3. **Decide on these before starting:**
   - Do you want cohort/team comparison features? (Affects data model and privacy considerations.)
   - How many training scenarios do you need at launch? (3-5 is a good minimum viable set.)
   - Do you want training completion to be tracked by supervisors? (Affects permissions model.)
   - Should training progress carry across deployments/updates? (Affects persistence strategy.)

### How to sequence the work with Claude:

- **Session 1:** Paste the full prompt. Let Claude produce the architecture and Phase 1 implementation. Review the sandbox isolation design carefully — this is the safety-critical foundation.
- **Session 2:** Take Phase 1 output, integrate it, test it, then ask Claude to build Phase 2 (tutorials) on top of the working Phase 1.
- **Session 3+:** Continue phase by phase. Each session, upload the current state of the code so Claude can integrate accurately.

### If Claude's output is too generic:

Add this steering instruction at the end of the prompt:

> "Remember: this is a space domain application for military operators. The gamification must feel like professional simulation training (think flight simulator progression), not consumer app engagement. Every game mechanic must map to a measurable operational skill. The aesthetic should be mission-focused — clean, professional, and confidence-inspiring."

### If you want Claude to focus on one phase:

Trim the prompt to just the relevant section and say:

> "I've already implemented [Phase N]. Here's the current code: [upload]. Now build Phase [N+1], integrating with what exists."

---
