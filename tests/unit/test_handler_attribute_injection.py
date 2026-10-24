"""Object names never reach JavaScript source inside an event attribute.

Audit F-038. Names were quoted by hand into ``onclick="loadInEngine('…')"``.
Autoescape turns ``'`` into ``&#39;``, but the browser decodes the attribute
before it compiles the handler, so a name containing ``');…//`` ran as code in
the operator's session. The content security policy allows inline script, so
nothing else stood in the way. Names come from UDL notifications, the HRR
list and free text, and are treated as untrusted.

The values now travel in ``data-*`` attributes, which the browser hands to the
handler as strings and never compiles.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

_TEMPLATES = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"
_PAYLOAD = "x');alert(1);//"
_QUOTED_IN_HANDLER = re.compile(r"""\son[a-z]+="[^"]*['"]\{\{""")


class _Buttons(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.found: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "button":
            self.found.append(dict(attrs))


def test_no_template_quotes_a_value_into_an_event_handler() -> None:
    offenders = [
        f"{path.relative_to(_TEMPLATES)}:{n}"
        for path in _TEMPLATES.rglob("*.html")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if _QUOTED_IN_HANDLER.search(line)
    ]
    assert not offenders, f"quote values through data-* attributes instead: {offenders}"


def test_a_hostile_name_reaches_the_load_button_only_as_data() -> None:
    from spectre.web.app import templates

    entry = SimpleNamespace(
        target=SimpleNamespace(target_name=_PAYLOAD),
        burn_epoch=datetime(2026, 4, 10, 12, 0, tzinfo=UTC),
        method="lambert",
        burn_location="apogee",
        delta_v_m_s=12.0, dv_prograde=0.012, dv_normal=0.0, dv_radial=0.0,
        tof_hours=6.0, posture_label="",
    )
    html = templates.env.get_template("partials/threat_sweep_row.html").render(
        entry=entry, red_name=_PAYLOAD, index=0, group_idx=0,
    )
    parser = _Buttons()
    parser.feed(html)
    load = next(b for b in parser.found if "loadInEngine" in (b.get("onclick") or ""))
    assert _PAYLOAD not in (load["onclick"] or ""), "the name reached the handler source"
    assert load["data-red"] == _PAYLOAD
    assert load["data-blue"] == _PAYLOAD
