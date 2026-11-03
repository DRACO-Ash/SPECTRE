pace 1.00 from settings (nothing measured yet)

V0.13: 3 items, 690 priced min, gates browser, container, lint, quality, sast, tests
  forecast 11h30 to 11h30 (middle 11h30), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-029        90m  priority low; anchors the release
    SPC-110       360m  priority high
    SPC-112       240m  priority high
  lane 1 (360m): SPC-110
  lane 2 (330m): SPC-112, SPC-029

V0.14: 4 items, 840 priced min, gates browser, container, lint, quality, sast, tests
  forecast 14h00 to 14h00 (middle 14h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-114       240m  priority high
    SPC-150       180m  fills the release to its floor
    SPC-113       180m  priority high; anchors the release
    SPC-115       240m  priority high
  lane 1 (600m): SPC-114, SPC-150, SPC-113
  lane 2 (240m): SPC-115

V0.15: 2 items, 660 priced min, gates container, lint, quality, sast, tests
  forecast 11h00 to 11h00 (middle 11h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-120       300m  priority high; anchors the release
    SPC-121       360m  priority high
  lane 1 (660m): SPC-120, SPC-121

V0.16: 3 items, 720 priced min, gates browser, container, lint, quality, sast, tests
  forecast 12h00 to 12h00 (middle 12h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-123       300m  priority high; anchors the release
    SPC-125       120m  rider: priority med, adds no gate
    SPC-124       300m  priority med, adds gate browser
  lane 1 (420m): SPC-123, SPC-125
  lane 2 (300m): SPC-124

V0.17: 3 items, 660 priced min, gates browser, container, lint, quality, sast, tests
  forecast 11h00 to 11h00 (middle 11h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-130       240m  priority med; anchors the release
    SPC-131       240m  priority med, adds gate browser
    SPC-132       180m  priority med
  lane 1 (660m): SPC-130, SPC-131, SPC-132

V0.18: 2 items, 840 priced min, gates container, lint, quality, sast, tests
  forecast 14h00 to 14h00 (middle 14h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-140       480m  priority med; anchors the release
    SPC-141       360m  fills the release to its floor
  lane 1 (840m): SPC-140, SPC-141

V0.19: 1 items, 300 priced min, gates browser, container, lint, quality, sast, tests
  forecast 5h00 to 5h00 (middle 5h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-142       300m  priority med; anchors the release
  lane 1 (300m): SPC-142

tooling: 10 items, 1830 priced min, 30h30 of build; ships no store artefact, so carries no release overhead
    SPC-014        30m
    SPC-011       240m
    SPC-012       240m
    SPC-013       180m
    SPC-070       180m
    SPC-071       240m
    SPC-152       120m
    SPC-010       240m
    SPC-073       240m
    SPC-074       120m

waiting: SPC-080 - needs an owner answer

waiting: SPC-033 - needs an owner answer

off path: SPC-072 - research: no release gate

off path: SPC-081 - research: no release gate

off path: SPC-082 - research: no release gate

off path: SPC-083 - research: no release gate

off path: SPC-084 - research: no release gate

off path: SPC-085 - research: no release gate

off path: SPC-151 - research: no release gate
WARNING SPC-032: cannot be placed, its dependencies never become ready
