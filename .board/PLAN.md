pace 1.00 from settings (nothing measured yet)

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
