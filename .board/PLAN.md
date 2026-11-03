pace 1.00 from settings (nothing measured yet)

V0.12: 6 items, 750 priced min, gates browser, container, lint, quality, sast, tests
  forecast 12h30 to 12h30 (middle 12h30), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-028       120m  priority high
    SPC-022       120m  priority low; anchors the release
    SPC-032       240m  rider: priority low, adds no gate
    SPC-026        60m  priority med
    SPC-027        30m  rider: priority low, adds no gate
    SPC-111       180m  priority high
  lane 1 (330m): SPC-028, SPC-022, SPC-026, SPC-027
  lane 2 (420m): SPC-032, SPC-111

V0.13: 3 items, 780 priced min, gates browser, container, lint, quality, sast, tests
  forecast 13h00 to 13h00 (middle 13h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-110       360m  priority high; anchors the release
    SPC-112       240m  priority high
    SPC-113       180m  priority high, adds gate browser
  lane 1 (420m): SPC-112, SPC-113
  lane 2 (360m): SPC-110

V0.14: 3 items, 780 priced min, gates browser, container, lint, quality, sast, tests
  forecast 13h00 to 13h00 (middle 13h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-120       300m  priority high
    SPC-114       240m  priority high; anchors the release
    SPC-115       240m  priority high
  lane 1 (300m): SPC-120
  lane 2 (480m): SPC-114, SPC-115

V0.15: 3 items, 780 priced min, gates container, lint, quality, sast, tests
  forecast 13h00 to 13h00 (middle 13h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-121       360m  priority high; anchors the release
    SPC-123       300m  priority high
    SPC-125       120m  rider: priority med, adds no gate
  lane 1 (780m): SPC-121, SPC-123, SPC-125

V0.16: 3 items, 780 priced min, gates browser, container, lint, quality, sast, tests
  forecast 13h00 to 13h00 (middle 13h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-130       240m  priority med
    SPC-131       240m  priority med
    SPC-124       300m  priority med; anchors the release
  lane 1 (540m): SPC-131, SPC-124
  lane 2 (240m): SPC-130

V0.17: 3 items, 840 priced min, gates browser, container, lint, quality, sast, tests
  forecast 14h00 to 14h00 (middle 14h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-150       180m  fills the release to its floor
    SPC-132       180m  priority med; anchors the release
    SPC-140       480m  priority med
  lane 1 (660m): SPC-132, SPC-140
  lane 2 (180m): SPC-150

V0.18: 2 items, 660 priced min, gates browser, container, lint, quality, sast, tests
  forecast 11h00 to 11h00 (middle 11h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-141       360m  priority med; anchors the release
    SPC-142       300m  priority med, adds gate browser
  lane 1 (360m): SPC-141
  lane 2 (300m): SPC-142

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
