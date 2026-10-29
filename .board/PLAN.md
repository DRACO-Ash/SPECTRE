pace 1.00 from settings (nothing measured yet)

V0.9: 3 items, 840 priced min, gates browser, container, lint, quality, sast, tests
  forecast 14h00 to 14h00 (middle 14h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-006       360m  priority high; anchors the release
    SPC-101       180m  fills the release to its floor
    SPC-007       300m  priority high
  lane 1 (660m): SPC-006, SPC-007
  lane 2 (180m): SPC-101

V0.10: 4 items, 840 priced min, gates browser, container, lint, quality, sast, tests
  forecast 14h00 to 14h00 (middle 14h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-030       180m  rider: priority med, adds no gate
    SPC-100       240m  fills the release to its floor
    SPC-005       180m  rider: priority med, adds no gate
    SPC-008       240m  priority high; anchors the release
  lane 1 (420m): SPC-005, SPC-008
  lane 2 (420m): SPC-100, SPC-030

V0.11: 3 items, 780 priced min, gates browser, container, lint, quality, sast, tests
  forecast 13h00 to 13h00 (middle 13h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-060       240m  priority med
    SPC-031       300m  priority low; anchors the release
    SPC-061       240m  rider: priority low, adds no gate
  lane 1 (540m): SPC-060, SPC-031
  lane 2 (240m): SPC-061

V0.12: 3 items, 780 priced min, gates container, lint, quality, sast, tests
  forecast 13h00 to 13h00 (middle 13h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-102       240m  priority high; anchors the release
    SPC-110       360m  priority high, adds gate container, quality, sast
    SPC-111       180m  priority high
  lane 1 (540m): SPC-110, SPC-111
  lane 2 (240m): SPC-102

V0.13: 4 items, 840 priced min, gates browser, container, lint, quality, sast, tests
  forecast 14h00 to 14h00 (middle 14h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-114       240m  priority high
    SPC-150       180m  fills the release to its floor
    SPC-112       240m  priority high; anchors the release
    SPC-113       180m  priority high, adds gate browser
  lane 1 (840m): SPC-114, SPC-150, SPC-112, SPC-113

V0.14: 3 items, 780 priced min, gates browser, container, lint, quality, sast, tests
  forecast 13h00 to 13h00 (middle 13h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-120       300m  priority high
    SPC-130       240m  rider: priority med, adds no gate
    SPC-115       240m  priority high; anchors the release
  lane 1 (540m): SPC-120, SPC-130
  lane 2 (240m): SPC-115

V0.15: 3 items, 780 priced min, gates container, lint, quality, sast, tests
  forecast 13h00 to 13h00 (middle 13h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-121       360m  priority high; anchors the release
    SPC-123       300m  priority high
    SPC-125       120m  rider: priority med, adds no gate
  lane 1 (780m): SPC-121, SPC-123, SPC-125

V0.16: 3 items, 720 priced min, gates browser, container, lint, quality, sast, tests
  forecast 12h00 to 12h00 (middle 12h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-131       240m  priority med
    SPC-132       180m  priority med
    SPC-124       300m  priority med; anchors the release
  lane 1 (720m): SPC-131, SPC-132, SPC-124

V0.17: 2 items, 840 priced min, gates container, lint, quality, sast, tests
  forecast 14h00 to 14h00 (middle 14h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-140       480m  priority med; anchors the release
    SPC-141       360m  fills the release to its floor
  lane 1 (840m): SPC-140, SPC-141

V0.18: 1 items, 300 priced min, gates browser, container, lint, quality, sast, tests
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

off path: SPC-072 - research: no release gate

off path: SPC-081 - research: no release gate

off path: SPC-082 - research: no release gate

off path: SPC-083 - research: no release gate

off path: SPC-084 - research: no release gate

off path: SPC-085 - research: no release gate

off path: SPC-151 - research: no release gate
