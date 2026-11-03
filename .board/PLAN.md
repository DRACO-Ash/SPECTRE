pace 1.00 from settings (nothing measured yet)

V0.16: 3 items, 780 priced min, gates browser, container, lint, quality, sast, tests
  forecast 13h00 to 13h00 (middle 13h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-160       300m  priority high; anchors the release
    SPC-161       180m  priority high
    SPC-162       300m  priority high
  lane 1 (480m): SPC-160, SPC-161
  lane 2 (300m): SPC-162

V0.17: 3 items, 780 priced min, gates none
  forecast 13h00 to 13h00 (middle 13h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-163       300m  priority high; anchors the release
    SPC-164       240m  priority high
    SPC-170       240m  priority high
  lane 1 (780m): SPC-163, SPC-164, SPC-170

V0.18: 3 items, 780 priced min, gates browser, container, lint, quality, sast, tests
  forecast 13h00 to 13h00 (middle 13h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-165       300m  priority high; anchors the release
    SPC-167       180m  priority high
    SPC-166       300m  priority high
  lane 1 (780m): SPC-165, SPC-167, SPC-166

V0.19: 3 items, 780 priced min, gates browser, container, lint, quality, sast, tests
  forecast 13h00 to 13h00 (middle 13h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-169       240m  priority high, adds gate browser, container, lint, quality, sast, tests
    SPC-168       300m  priority high; anchors the release
    SPC-175       240m  rider: priority med, adds no gate
  lane 1 (480m): SPC-169, SPC-175
  lane 2 (300m): SPC-168

V0.20: 4 items, 765 priced min, gates browser, container, lint, quality, sast, tests
  forecast 12h45 to 12h45 (middle 12h45), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-119        45m  rider: priority low, adds no gate
    SPC-118       120m  rider: priority med, adds no gate
    SPC-172       300m  rider: priority med, adds no gate
    SPC-171       300m  priority high; anchors the release
  lane 1 (465m): SPC-119, SPC-118, SPC-171
  lane 2 (300m): SPC-172

V0.21: 3 items, 780 priced min, gates browser, container, lint, quality, sast, tests
  forecast 13h00 to 13h00 (middle 13h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-150       180m  priority high
    SPC-173       300m  priority med; anchors the release
    SPC-174       300m  priority med
  lane 1 (600m): SPC-173, SPC-174
  lane 2 (180m): SPC-150

V0.22: 3 items, 780 priced min, gates browser, container, lint, quality, sast, tests
  forecast 13h00 to 13h00 (middle 13h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-121       360m  priority high
    SPC-125       120m  rider: priority med, adds no gate
    SPC-176       300m  priority med; anchors the release
  lane 1 (480m): SPC-121, SPC-125
  lane 2 (300m): SPC-176

V0.23: 3 items, 780 priced min, gates browser, container, lint, quality, sast, tests
  forecast 13h00 to 13h00 (middle 13h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-124       300m  priority med; anchors the release
    SPC-130       240m  priority med
    SPC-131       240m  priority med
  lane 1 (540m): SPC-124, SPC-131
  lane 2 (240m): SPC-130

V0.24: 2 items, 660 priced min, gates browser, container, lint, quality, sast, tests
  forecast 11h00 to 11h00 (middle 11h00), people's time 0 min, evidence: settings (nothing measured yet)
    SPC-132       180m  priority med; anchors the release
    SPC-140       480m  priority med
  lane 1 (660m): SPC-132, SPC-140

V0.25: 2 items, 660 priced min, gates browser, container, lint, quality, sast, tests
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

waiting: SPC-177 - needs an owner answer

off path: SPC-072 - research: no release gate

off path: SPC-081 - research: no release gate

off path: SPC-082 - research: no release gate

off path: SPC-083 - research: no release gate

off path: SPC-084 - research: no release gate

off path: SPC-085 - research: no release gate

off path: SPC-151 - research: no release gate
WARNING SPC-032: cannot be placed, its dependencies never become ready
