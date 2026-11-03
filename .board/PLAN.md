pace 1.00 from settings (nothing measured yet)

V0.18: 3 items, 780 priced min, gates browser, container, lint, quality, sast, tests
  forecast 13h00 to 13h00 (middle 13h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-169       240m  priority high, adds gate browser, container, lint, quality, sast, tests
    SPC-168       300m  priority high; anchors the release
    SPC-170       240m  priority high
  lane 1 (300m): SPC-168
  lane 2 (480m): SPC-169, SPC-170

V0.19: 4 items, 765 priced min, gates browser, container, lint, quality, sast, tests
  forecast 12h45 to 12h45 (middle 12h45), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-172       300m  rider: priority med, adds no gate
    SPC-119        45m  rider: priority low, adds no gate
    SPC-125       120m  rider: priority med, adds no gate
    SPC-171       300m  priority high; anchors the release
  lane 1 (465m): SPC-119, SPC-125, SPC-171
  lane 2 (300m): SPC-172

V0.20: 3 items, 780 priced min, gates browser, container, lint, quality, sast, tests
  forecast 13h00 to 13h00 (middle 13h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-150       180m  priority high
    SPC-173       300m  priority med; anchors the release
    SPC-174       300m  priority med
  lane 1 (600m): SPC-173, SPC-174
  lane 2 (180m): SPC-150

V0.21: 3 items, 780 priced min, gates browser, container, lint, quality, sast, tests
  forecast 13h00 to 13h00 (middle 13h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-176       300m  priority med, adds gate browser
    SPC-130       240m  priority med
    SPC-175       240m  priority med; anchors the release
  lane 1 (300m): SPC-176
  lane 2 (480m): SPC-130, SPC-175

V0.22: 2 items, 420 priced min, gates browser, container, lint, quality, sast, tests
  forecast 7h00 to 7h00 (middle 7h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-131       240m  priority med; anchors the release
    SPC-132       180m  priority med
  lane 1 (420m): SPC-131, SPC-132

V0.23: 2 items, 840 priced min, gates container, lint, quality, sast, tests
  forecast 14h00 to 14h00 (middle 14h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-140       480m  priority med; anchors the release
    SPC-141       360m  fills the release to its floor
  lane 1 (840m): SPC-140, SPC-141

V0.24: 1 items, 300 priced min, gates browser, container, lint, quality, sast, tests
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

waiting: SPC-177 - needs an owner answer

off path: SPC-072 - research: no release gate

off path: SPC-081 - research: no release gate

off path: SPC-082 - research: no release gate

off path: SPC-083 - research: no release gate

off path: SPC-084 - research: no release gate

off path: SPC-085 - research: no release gate

off path: SPC-151 - research: no release gate
WARNING SPC-032: cannot be placed, its dependencies never become ready
