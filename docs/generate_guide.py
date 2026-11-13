#!/usr/bin/env python3
"""Generate the SPECTRE Operator Guide as a formatted .docx document.

Follows the Bluestaq Ltd Document Style Guide — A4, Segoe UI, navy/gold
colour scheme, accent bar, metric cards, data tables, and callout boxes.

Usage::

    python docs/generate_guide.py

Outputs ``docs/SPECTRE_Operator_Guide.docx``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn, nsdecls
from docx.shared import Cm, Emu, Inches, Mm, Pt, RGBColor

# ── Bluestaq colour palette ─────────────────────────────────────────────────
COMMAND_NAVY = RGBColor(0x00, 0x22, 0x44)
ALLIANCE_BLUE = RGBColor(0x00, 0x49, 0x90)
OPS_BLUE = RGBColor(0x00, 0x65, 0x9E)
COMMAND_GOLD = RGBColor(0xC8, 0xA4, 0x15)
BODY_TEXT = RGBColor(0x2C, 0x3E, 0x50)
TABLE_ALT_BG = "F5F7FA"
CALLOUT_BG = "FFF9E6"
GREEN = RGBColor(0x27, 0xAE, 0x60)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

# ── SPECTRE theme colours ────────────────────────────────────────────────────
THREAT_RED    = RGBColor(0xE2, 0x4B, 0x4A)
NOMINAL_GREEN = RGBColor(0x1D, 0x9E, 0x75)
INTEL_BLUE    = RGBColor(0x37, 0x8A, 0xDD)
SENSOR_GREY   = RGBColor(0x7A, 0x8B, 0xA6)

OUTPUT_PATH = Path(__file__).parent / "SPECTRE_Operator_Guide.docx"


# ═══════════════════════════════════════════════════════════════════════════
#  Style helpers
# ═══════════════════════════════════════════════════════════════════════════


def _setup_document() -> Document:
    """Create a new A4 document with Bluestaq defaults."""
    doc = Document()
    section = doc.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.top_margin = Inches(0.75)
    section.bottom_margin = Inches(0.75)
    section.left_margin = Inches(0.79)
    section.right_margin = Inches(0.79)

    # Default font.
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Segoe UI"
    font.size = Pt(10)
    font.color.rgb = BODY_TEXT
    style.paragraph_format.space_after = Pt(4)
    return doc


def _add_accent_bar(doc: Document) -> None:
    """Insert a four-segment colour bar in the header."""
    header = doc.sections[0].header
    table = header.add_table(rows=1, cols=4, width=Emu(doc.sections[0].page_width - doc.sections[0].left_margin - doc.sections[0].right_margin))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    colours = ["002244", "004990", "00659E", "C8A415"]
    for idx, cell in enumerate(table.rows[0].cells):
        shading = OxmlElement("w:shd")
        shading.set(qn("w:fill"), colours[idx])
        shading.set(qn("w:val"), "clear")
        cell._element.get_or_add_tcPr().append(shading)
        cell.paragraphs[0].text = ""
        # Row height via trHeight.
        cell.width = Emu(int((doc.sections[0].page_width - doc.sections[0].left_margin - doc.sections[0].right_margin) / 4))

    # Set row height to thin bar.
    tr = table.rows[0]._tr
    trPr = tr.get_or_add_trPr()
    trHeight = OxmlElement("w:trHeight")
    trHeight.set(qn("w:val"), "120")
    trHeight.set(qn("w:hRule"), "exact")
    trPr.append(trHeight)

    # Remove cell borders for clean appearance.
    for cell in table.rows[0].cells:
        tc = cell._element
        tcPr = tc.get_or_add_tcPr()
        borders = OxmlElement("w:tcBorders")
        for edge in ("top", "left", "bottom", "right"):
            el = OxmlElement(f"w:{edge}")
            el.set(qn("w:val"), "none")
            el.set(qn("w:sz"), "0")
            el.set(qn("w:space"), "0")
            el.set(qn("w:color"), "auto")
            borders.append(el)
        tcPr.append(borders)


def _add_heading_h1(doc: Document, text: str) -> None:
    """Add a top-level heading — 20pt bold, Command Navy."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(18)
    p.paragraph_format.space_after = Pt(8)
    run = p.add_run(text)
    run.font.name = "Segoe UI"
    run.font.size = Pt(20)
    run.font.bold = True
    run.font.color.rgb = COMMAND_NAVY


def _add_eyebrow(doc: Document, text: str) -> None:
    """Add an eyebrow label — 9pt ALL CAPS, Command Gold."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text.upper())
    run.font.name = "Segoe UI"
    run.font.size = Pt(9)
    run.font.bold = True
    run.font.color.rgb = COMMAND_GOLD


def _add_heading_h2(doc: Document, text: str) -> None:
    """Add a section heading — 16pt bold Navy + 3pt gold rule below."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(6)
    run = p.add_run(text)
    run.font.name = "Segoe UI"
    run.font.size = Pt(16)
    run.font.bold = True
    run.font.color.rgb = COMMAND_NAVY

    # Gold rule below via paragraph border.
    pPr = p._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")  # half-points → 3pt
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "C8A415")
    borders.append(bottom)
    pPr.append(borders)


def _add_heading_h3(doc: Document, text: str) -> None:
    """Add a sub-section heading — 13pt bold Alliance Blue."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(text)
    run.font.name = "Segoe UI"
    run.font.size = Pt(13)
    run.font.bold = True
    run.font.color.rgb = ALLIANCE_BLUE


def _add_body(doc: Document, text: str) -> None:
    """Add a body paragraph — 10pt Segoe UI #2C3E50."""
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = "Segoe UI"
    run.font.size = Pt(10)
    run.font.color.rgb = BODY_TEXT


def _add_bullet(doc: Document, text: str, level: int = 0) -> None:
    """Add a bullet point with alternating blue/gold markers."""
    colour = OPS_BLUE if level % 2 == 0 else COMMAND_GOLD
    marker = "\u25CF " if level == 0 else "  \u25A0 "
    indent = "    " * level
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.left_indent = Cm(1.2 * (level + 1))
    marker_run = p.add_run(marker)
    marker_run.font.color.rgb = colour
    marker_run.font.size = Pt(10)
    marker_run.font.bold = True
    text_run = p.add_run(text)
    text_run.font.name = "Segoe UI"
    text_run.font.size = Pt(10)
    text_run.font.color.rgb = BODY_TEXT


def _add_data_table(doc: Document, headers: list[str], rows: list[list[str]]) -> None:
    """Add a data table with navy header row and alternating row shading."""
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Header row.
    for idx, hdr in enumerate(headers):
        cell = table.rows[0].cells[idx]
        cell.text = ""
        p = cell.paragraphs[0]
        run = p.add_run(hdr)
        run.font.name = "Segoe UI"
        run.font.size = Pt(9)
        run.font.bold = True
        run.font.color.rgb = WHITE
        shading = OxmlElement("w:shd")
        shading.set(qn("w:fill"), "002244")
        shading.set(qn("w:val"), "clear")
        cell._element.get_or_add_tcPr().append(shading)

    # Data rows.
    for r_idx, row_data in enumerate(rows):
        for c_idx, val in enumerate(row_data):
            cell = table.rows[r_idx + 1].cells[c_idx]
            cell.text = ""
            p = cell.paragraphs[0]
            run = p.add_run(val)
            run.font.name = "Segoe UI"
            run.font.size = Pt(9)
            run.font.color.rgb = BODY_TEXT
            if r_idx % 2 == 1:
                shading = OxmlElement("w:shd")
                shading.set(qn("w:fill"), TABLE_ALT_BG)
                shading.set(qn("w:val"), "clear")
                cell._element.get_or_add_tcPr().append(shading)


def _add_callout(doc: Document, text: str) -> None:
    """Add a callout box with left gold border and warm background."""
    # Implemented as a single-cell table for reliable background.
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = table.rows[0].cells[0]
    cell.text = ""
    p = cell.paragraphs[0]
    run = p.add_run(text)
    run.font.name = "Segoe UI"
    run.font.size = Pt(9.5)
    run.font.color.rgb = BODY_TEXT
    run.font.italic = True

    # Background shading.
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), CALLOUT_BG)
    shading.set(qn("w:val"), "clear")
    cell._element.get_or_add_tcPr().append(shading)

    # Left gold border only.
    tcPr = cell._element.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), "18")
    left.set(qn("w:color"), "C8A415")
    left.set(qn("w:space"), "0")
    borders.append(left)
    for edge in ("top", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "none")
        el.set(qn("w:sz"), "0")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "auto")
        borders.append(el)
    tcPr.append(borders)


def _add_metric_card(doc: Document, metric: str, label: str) -> None:
    """Add a metric card — navy top border, bold value, grey label."""
    table = doc.add_table(rows=2, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    # Top border on first cell.
    cell_val = table.rows[0].cells[0]
    cell_val.text = ""
    p = cell_val.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(metric)
    run.font.name = "Segoe UI"
    run.font.size = Pt(18)
    run.font.bold = True
    run.font.color.rgb = COMMAND_NAVY

    tcPr = cell_val._element.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    top = OxmlElement("w:top")
    top.set(qn("w:val"), "single")
    top.set(qn("w:sz"), "12")
    top.set(qn("w:color"), "002244")
    top.set(qn("w:space"), "0")
    borders.append(top)
    tcPr.append(borders)

    cell_lbl = table.rows[1].cells[0]
    cell_lbl.text = ""
    p2 = cell_lbl.paragraphs[0]
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run2 = p2.add_run(label.upper())
    run2.font.name = "Segoe UI"
    run2.font.size = Pt(8)
    run2.font.bold = True
    run2.font.color.rgb = RGBColor(0x5A, 0x7A, 0x9A)


def _add_footer(doc: Document, title: str = "SPECTRE Operator Guide") -> None:
    """Add footer with title left and page numbers right."""
    footer = doc.sections[0].footer
    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    p.clear()

    # Left-aligned title.
    run = p.add_run(f"Bluestaq Ltd \u2014 {title}")
    run.font.name = "Segoe UI"
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(0x5A, 0x7A, 0x9A)

    # Tab to right.
    run_tab = p.add_run("\t\t")

    # Page X of Y field codes.
    run_page = p.add_run("Page ")
    run_page.font.name = "Segoe UI"
    run_page.font.size = Pt(8)
    run_page.font.color.rgb = RGBColor(0x5A, 0x7A, 0x9A)

    fld_page = OxmlElement("w:fldSimple")
    fld_page.set(qn("w:instr"), " PAGE ")
    run_p = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    run_p.append(rPr)
    t = OxmlElement("w:t")
    t.text = "1"
    run_p.append(t)
    fld_page.append(run_p)
    p._p.append(fld_page)

    run_of = p.add_run(" of ")
    run_of.font.name = "Segoe UI"
    run_of.font.size = Pt(8)
    run_of.font.color.rgb = RGBColor(0x5A, 0x7A, 0x9A)

    fld_total = OxmlElement("w:fldSimple")
    fld_total.set(qn("w:instr"), " NUMPAGES ")
    run_n = OxmlElement("w:r")
    rPr2 = OxmlElement("w:rPr")
    run_n.append(rPr2)
    t2 = OxmlElement("w:t")
    t2.text = "1"
    run_n.append(t2)
    fld_total.append(run_n)
    p._p.append(fld_total)


def _add_page_break(doc: Document) -> None:
    """Insert a page break."""
    doc.add_page_break()


# ═══════════════════════════════════════════════════════════════════════════
#  Content sections
# ═══════════════════════════════════════════════════════════════════════════


def _section_01_introduction(doc: Document) -> None:
    """Section 1: Introduction to SPECTRE."""
    _add_eyebrow(doc, "Section 1")
    _add_heading_h1(doc, "Introduction to SPECTRE")

    _add_body(doc,
        "SPECTRE — the Space Planning, Evaluation & Counter-Threat Response Engine — is a "
        "real-time orbital manoeuvre planning and space intelligence tool designed for space "
        "defence operators. It enables rapid assessment of intercept trajectories, conjunction "
        "analysis, adversary intent evaluation, and defensive repositioning of space assets, "
        "all from a single browser-based interface."
    )
    _add_body(doc,
        "SPECTRE is built on a fully self-contained, pure-Python orbital mechanics engine "
        "with no dependency on external astrodynamics software. Operators can compute 23 "
        "distinct intercept and manoeuvre methods spanning classical transfers (Lambert, "
        "Hohmann, bi-elliptic), tactical manoeuvres (phasing, CW relative motion, plane "
        "changes, J2 drift, collision avoidance, evasion), advanced analysis (GEO drift, "
        "NMC safety ellipse, manoeuvre classification, detectability), and decision-support "
        "tools (intent prediction, intercept envelopes, stability assessment, fingerprinting, "
        "formation defence, orbital terrain mapping, min-time intercept)."
    )
    _add_body(doc,
        "Beyond manoeuvre planning, SPECTRE provides a suite of space intelligence "
        "capabilities: Historical Pattern of Life (PoL) analysis detects past manoeuvres "
        "and characterises operator behaviour from TLE history; NOTSO Correlation cross-"
        "references Notice to Space Operators messages against detected manoeuvres to build "
        "operator behavioural profiles; Photometry Analysis detects brightness anomalies "
        "from light-curve data that may indicate attitude changes or physical alterations. "
        "The Decision Engine applies decision analysis over operator-entered rows to "
        "support commander-level response selection, with a worst-case floor (minimax), a "
        "best case (minimin) and expected value. Randomised (mixed) responses are not "
        "considered, so minimax is a guaranteed floor over pure responses, not a game "
        "solution. The Training Environment provides a sandboxed gamified environment for "
        "operator skill development across five progressive levels."
    )
    _add_body(doc,
        "Integration with the Unified Data Library (UDL) provides authoritative live TLE "
        "data from authorised source providers. The GCAT Browser gives instant access to "
        "28 of Jonathan McDowell's General Catalogue datasets spanning the full history "
        "of orbital activity."
    )
    _add_callout(doc,
        "Key design principle: SPECTRE is designed for speed-of-relevance decision-making. "
        "All computations run in-browser with sub-second response times, enabling "
        "operators to evaluate multiple intercept options before a conjunction window closes. "
        "No external astrodynamics libraries are required — SPECTRE runs on any system "
        "with a modern browser and network access to the SPECTRE server."
    )


def _section_02_system_overview(doc: Document) -> None:
    """Section 2: System Overview."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 2")
    _add_heading_h1(doc, "System Overview")

    _add_heading_h2(doc, "Architecture")
    _add_body(doc,
        "SPECTRE follows a server-side rendering architecture with HTMX for dynamic "
        "partial updates. The backend is built on FastAPI (Python 3.14+) with Jinja2 "
        "templates. All orbital mechanics computations are performed by the spectre.astro "
        "package — a pure-Python library providing classical transfer solvers (Lambert, "
        "Hohmann, bi-elliptic), tactical manoeuvre solvers (phasing, CW relative motion, "
        "plane change, J2 drift, collision avoidance, evasion), advanced analysis "
        "(GEO drift, NMC safety ellipse, manoeuvre classification, detectability), "
        "decision-support solvers (intent prediction, intercept envelope, stability "
        "analysis, fingerprinting, formation defence, orbital terrain, min-time intercept), "
        "and SGP4-based orbit propagation."
    )

    _add_heading_h2(doc, "Technology Stack")
    _add_data_table(doc,
        ["Component", "Technology", "Purpose"],
        [
            ["Web Framework", "FastAPI + Uvicorn", "Async HTTP server with ASGI"],
            ["Templates", "Jinja2 + HTMX", "Server-side rendering with partial swaps"],
            ["Orbit Propagation", "SGP4 (via sgp4 library)", "TLE-based satellite position/velocity"],
            ["Classical Solvers", "spectre.astro.maneuvers", "Lambert, Hohmann, bi-elliptic transfers"],
            ["Tactical Solvers", "spectre.astro.tactical", "Phasing, CW, plane change, J2 drift, COLA"],
            ["Event Detection", "spectre.astro.events", "Apogee, perigee, node crossings"],
            ["Authentication", "SQLAlchemy + bcrypt", "Operator credential management"],
            ["TLE Source", "UDL (Unified Data Library)", "Authoritative TLE retrieval via HTTPS"],
            ["Charting", "Chart.js 4.x", "Trade-space scatter plots in the browser"],
            ["Browser Scripts", "First-party files in /static/js",
             "Every control's behaviour; the Content Security Policy allows no inline script and no eval"],
            ["Design System", "Bluestaq Dark Ops", "Navy/gold operational colour scheme"],
        ],
    )


def _section_03_getting_started(doc: Document) -> None:
    """Section 3: Getting Started."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 3")
    _add_heading_h1(doc, "Getting Started")

    _add_heading_h2(doc, "Login")
    _add_body(doc,
        "Navigate to the SPECTRE URL in your browser. Enter your operator username and "
        "password on the login screen. Credentials are managed by the system administrator "
        "and stored as bcrypt hashes — plaintext passwords are never retained."
    )

    _add_heading_h2(doc, "UDL Credentials")
    _add_body(doc,
        "To fetch authoritative TLE data from the Unified Data Library, connect your "
        "UDL account via the connection chip in the navigation bar. Click the UDL chip, "
        "enter your UDL username and password, and press Connect. A green status dot "
        "confirms a successful connection."
    )
    _add_callout(doc,
        "UDL credentials are held in session memory only and are never persisted to disc. "
        "You will need to re-enter them after each login."
    )

    _add_heading_h2(doc, "UDL Data Mode")
    _add_body(doc,
        "UDL tags every elset record with a data classification mode. The session-wide "
        "data mode can be set from the UDL panel after connecting:"
    )
    _add_data_table(doc,
        ["Mode", "Meaning"],
        [
            ["REAL", "Operational live data (default)"],
            ["SIMULATED", "Synthetic scenario data"],
            ["EXERCISE", "Training exercise data"],
            ["TEST", "Development/test data"],
        ],
    )
    _add_body(doc,
        "Two per-panel data mode overrides are also available:"
    )
    _add_bullet(doc, "Threat Sweep — a filter dropdown in the results panel hides rows whose cached TLE was fetched under a different data mode. This is a display-time filter; no re-fetch occurs.")
    _add_bullet(doc, "Intercept Engine — an 'Intercept Data Mode' dropdown on the intercept form re-fetches the red and blue TLEs from UDL under the selected mode immediately before computing.")

    _add_heading_h2(doc, "TLE Source Provider")
    _add_body(doc,
        "UDL holds element sets from several providers (for example 18th SPCS, ExoAnalytic, KBR, KRTL, LeoLabs "
        "and NorthStar). A latest fetch, whether from the TLE panel, a quick-add, a sweep or the refresh at "
        "connect, asks UDL's element set archive over the last 72 hours first and takes the newest set any "
        "provider filed; only when the archive holds none in that window does it ask UDL's current catalogue. "
        "If that newest set is refused, for example because it is an SGP4-XP set, nothing is stored and you are "
        "told; an older set is never taken in its place."
    )
    _add_body(doc,
        "When you connect, SPECTRE lists the providers that filed for the ISS over the last day, and adds every "
        "provider the refresh at connect finds on the sets you hold. The list is cleared when you disconnect. A "
        "'TLE Source' selector appears in the UDL panel: leave it blank to take the newest set from every "
        "provider, or choose one to narrow every latest fetch to that provider."
    )
    _add_body(doc,
        "A set fetched from UDL keeps the provider that filed it. The red card shows it beside the data mode "
        "(Provider: LeoLabs \u00b7 REAL, for example), or says the set was entered by hand, and the sweep names "
        "the interceptor's provider beside its element set age. Editing a fetched set's text makes it your own, "
        "so its data mode and provider are dropped."
    )

    _add_heading_h2(doc, "Setting Scenario Time")
    _add_body(doc,
        "Use the Scenario Time panel to define the analysis window. Enter start and stop "
        "times in ISO 8601 format (e.g., 2026-03-15T00:00:00Z). If no scenario time is "
        "set, SPECTRE defaults to the current UTC time plus 24 hours."
    )


def _section_04_dashboard(doc: Document) -> None:
    """Section 4: Operator Dashboard Walkthrough."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 4")
    _add_heading_h1(doc, "Operator Dashboard Walkthrough")

    _add_body(doc,
        "The main dashboard uses a three-column force grid layout, designed for "
        "rapid situational awareness."
    )

    _add_heading_h2(doc, "Blue Forces (Left Column)")
    _add_bullet(doc, "Lists all friendly blue assets added to the session.")
    _add_bullet(doc, "Each asset displays its object name, NORAD catalogue number, and TLE epoch.")
    _add_bullet(doc, "Add assets by NORAD ID or by pasting a raw TLE.")
    _add_bullet(doc, "Remove assets with the \u00D7 button.")

    _add_heading_h2(doc, "Red Tracks (Centre Column)")
    _add_bullet(doc, "Lists threat objects being tracked.")
    _add_bullet(doc, "Same add/remove workflow as blue assets.")
    _add_bullet(doc, "Red tracks are colour-coded with a red accent border.")

    _add_heading_h2(doc, "Intelligence & Planning (Right Column)")
    _add_bullet(doc, "Manoeuvre search configuration and intercept engine controls.")
    _add_bullet(doc, "Orbital event detection (apogee, perigee, node crossings).")
    _add_bullet(doc, "Intercept results with per-burn ΔV breakdown.")
    _add_bullet(doc, "Trade-space scatter plot (when multiple solutions exist).")
    _add_bullet(doc, "Session activity log with real-time streaming.")


def _section_05_assets(doc: Document) -> None:
    """Section 5: Managing Blue Assets & Red Tracks."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 5")
    _add_heading_h1(doc, "Managing Blue Assets & Red Tracks")

    _add_heading_h2(doc, "Adding a Satellite")
    _add_body(doc,
        "There are three modes for adding a satellite to your session:"
    )
    _add_bullet(doc, "UDL Fetch — Enter the NORAD catalogue number and SPECTRE fetches the latest TLE from UDL automatically. Requires an active UDL connection.")
    _add_bullet(doc, "Catalogue Search — Search the on-orbit catalogue by name or NORAD ID. Select from results to add with a single click.")
    _add_bullet(doc, "Manual TLE — Paste a two-line or three-line TLE directly into the text area. Useful for objects not yet in the public catalogue.")

    _add_heading_h2(doc, "Removing a Satellite")
    _add_body(doc,
        "Click the red \u00D7 button next to any asset or track to remove it from "
        "the session. This action is immediate and does not require confirmation. "
        "Removing a satellite does not affect previously computed intercept results."
    )

    _add_heading_h2(doc, "HRR Watchlist")
    _add_body(doc,
        "The HRR (High Rate Revisit) Watchlist sub-tab in the Assets panel provides "
        "instant access to the Joint Capability Office (JCO) HRR satellite list from "
        "UDL. Click 'Fetch HRR' to load the latest notification (up to 3 days lookback). "
        "The panel shows two tables — Blue HRR and Red HRR — each with:"
    )
    _add_data_table(doc,
        ["Column", "Description"],
        [
            ["Actions", "One-click \u2192 Blue and \u2192 Red ingestion buttons (first column)"],
            ["Name", "Common name from HRR notification"],
            ["SATNO", "NORAD catalogue number"],
            ["Country", "Owner country code"],
            ["Orbit", "Orbit regime (LEO / MEO / GEO / HEO)"],
            ["Rank", "JCO threat rank (0\u20135, lower = higher priority)"],
        ],
    )
    _add_body(doc,
        "Clicking \u2192 Blue fetches the TLE from UDL and adds the satellite as a "
        "blue asset in one action. Clicking \u2192 Red does the same as a red track. "
        "A confirmation badge replaces the button immediately on success. The table "
        "supports column sorting by clicking any header."
    )
    _add_callout(doc,
        "HRR objects are also automatically available as target groups in the "
        "Threat Sweep panel, grouped by side (Blue/Red) and rank."
    )


def _section_06_scenario_time(doc: Document) -> None:
    """Section 6: Setting Scenario Time Window."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 6")
    _add_heading_h1(doc, "Setting Scenario Time Window")

    _add_body(doc,
        "The scenario time window defines the temporal bounds for all orbital event "
        "detection and manoeuvre planning. It is set in the Scenario Time panel at "
        "the top of the Blue Forces column."
    )

    _add_data_table(doc,
        ["Field", "Format", "Default"],
        [
            ["Start Time", "ISO 8601 (e.g. 2026-03-15T00:00Z)", "Current UTC time"],
            ["Stop Time", "ISO 8601 (e.g. 2026-03-16T00:00Z)", "Start + 24 hours"],
        ],
    )

    _add_callout(doc,
        "Tip: For conjunction analysis, set the scenario window to span at least "
        "two orbital periods of the target object to capture all relevant geometry."
    )


def _section_07_manoeuvre_theory(doc: Document) -> None:
    """Section 7: Orbital Manoeuvre Theory."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 7")
    _add_heading_h1(doc, "Classical Orbital Transfers")

    _add_body(doc,
        "SPECTRE implements three fundamental orbital transfer methods as its classical "
        "solver set. Each has distinct trade-offs between ΔV cost, transfer time, "
        "and geometric constraints. Understanding these trade-offs is essential for "
        "selecting the optimal intercept strategy."
    )

    # Lambert.
    _add_heading_h2(doc, "Lambert Transfer")
    _add_body(doc,
        "The Lambert problem is the boundary-value problem of two-body orbital "
        "mechanics: given two position vectors and a time of flight, determine the "
        "orbit connecting them. SPECTRE uses the Izzo algorithm (2015) — a robust, "
        "Householder-iteration solver with guaranteed convergence."
    )
    _add_bullet(doc, "Inputs: departure position, arrival position, time of flight.")
    _add_bullet(doc, "Output: required velocity vectors at departure and arrival.")
    _add_bullet(doc, "The ΔV is the difference between the required velocity and the satellite's current velocity at the departure point.")
    _add_bullet(doc, "Supports both short-way and long-way (multi-revolution) transfers.")
    _add_callout(doc,
        "Lambert transfers are the most flexible method — they work for arbitrary "
        "geometries and arbitrary transfer times. However, they may require higher "
        "ΔV than specialised two-burn transfers when the orbits are nearly coplanar."
    )

    # Hohmann.
    _add_heading_h2(doc, "Hohmann Transfer")
    _add_body(doc,
        "The Hohmann transfer is the minimum-energy two-impulse manoeuvre between "
        "two coplanar circular orbits. It uses an elliptical transfer orbit that is "
        "tangent to both the initial and final orbits."
    )
    _add_bullet(doc, "Burn 1 (departure): Raise/lower apogee to touch the target orbit.")
    _add_bullet(doc, "Burn 2 (arrival): Circularise at the target altitude.")
    _add_bullet(doc, "Transfer time is exactly half the period of the transfer ellipse.")
    _add_body(doc,
        "The vis-viva equation governs the velocity at any point on a Keplerian orbit:"
    )
    _add_body(doc,
        "    v\u00B2 = \u03BC (2/r \u2212 1/a)"
    )
    _add_body(doc,
        "where \u03BC is the gravitational parameter, r is the radial distance, and a "
        "is the semi-major axis."
    )

    # Bi-elliptic.
    _add_heading_h2(doc, "Bi-elliptic Transfer")
    _add_body(doc,
        "The bi-elliptic transfer uses three impulses and two intermediate ellipses. "
        "It is more fuel-efficient than Hohmann when the ratio of the final to initial "
        "orbit radius exceeds approximately 11.94."
    )
    _add_bullet(doc, "Burn 1: Boost to a high intermediate apogee (above both orbits).")
    _add_bullet(doc, "Burn 2: At the intermediate apogee, adjust the perigee to match the target orbit.")
    _add_bullet(doc, "Burn 3: At the new perigee, circularise into the target orbit.")
    _add_callout(doc,
        "The bi-elliptic transfer trades increased transfer time for reduced ΔV. "
        "For orbit ratio r\u2082/r\u2081 > 11.94, it is always cheaper than Hohmann. "
        "Between 11.94 and ~15.58, the savings depend on the intermediate apogee altitude."
    )

    # Comparison table.
    _add_heading_h2(doc, "Method Comparison")
    _add_data_table(doc,
        ["Property", "Lambert", "Hohmann", "Bi-elliptic"],
        [
            ["Number of burns", "1 (single impulse)", "2", "3"],
            ["ΔV efficiency", "Variable", "Optimal for r\u2082/r\u2081 < 11.94", "Optimal for r\u2082/r\u2081 > 11.94"],
            ["Transfer time", "User-specified", "Fixed (half period)", "Longer than Hohmann"],
            ["Geometry constraint", "None (arbitrary)", "Coplanar circular", "Coplanar circular"],
            ["Best use case", "General intercept", "Altitude change", "Large altitude ratio"],
            ["Plane change", "Included in ΔV", "Not included", "Not included"],
        ],
    )


def _section_08_tactical_theory(doc: Document) -> None:
    """Section 8: Tactical Manoeuvre Theory."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 8")
    _add_heading_h1(doc, "Tactical Manoeuvres")

    _add_body(doc,
        "Beyond classical orbital transfers, SPECTRE provides tactical manoeuvres "
        "designed for space control operations. These are computationally lightweight, "
        "operationally focused, and optimised for rapid threat response rather than "
        "textbook optimal transfers."
    )

    # Phasing.
    _add_heading_h2(doc, "Phasing Orbit")
    _add_body(doc,
        "The phasing manoeuvre adjusts the satellite's orbital period so that it "
        "arrives at the target's angular position after a specified number of "
        "revolutions. It is the primary tool for along-track rendezvous when both "
        "objects share a similar orbit."
    )
    _add_bullet(doc, "Burn 1: Lower/raise the orbit to change the period (enter phasing orbit).")
    _add_bullet(doc, "Coast: Complete N revolutions in the phasing orbit, closing the angular gap.")
    _add_bullet(doc, "Burn 2: Return to the original orbit (symmetric with Burn 1).")
    _add_bullet(doc, "More revolutions = lower ΔV but longer wait time.")
    _add_callout(doc,
        "Operational use: stealth rendezvous, delayed intercept, constellation spacing, "
        "passive intercept geometry. The phasing orbit is invisible to observers who "
        "only track the manoeuvre burns — the coast phase appears ballistic."
    )

    # CW Relative Motion.
    _add_heading_h2(doc, "Relative Motion (Hill / Clohessy-Wiltshire)")
    _add_body(doc,
        "The CW equations describe linearised relative motion near a circular "
        "reference orbit. SPECTRE uses them to compute precise impulses for "
        "controlled proximity operations."
    )
    _add_heading_h3(doc, "Radial Separation")
    _add_bullet(doc, "A single radial impulse produces oscillating radial displacement.")
    _add_bullet(doc, "x(t) = (Δvx / n) sin(nt) — radial position at time t.")
    _add_bullet(doc, "Also creates along-track drift: y(t) = -(2Δvx / n)(1 - cos(nt)).")
    _add_bullet(doc, "Use case: rapid defensive spacing, inspection distance changes, collision avoidance.")
    _add_heading_h3(doc, "Along-Track Drift")
    _add_bullet(doc, "A single along-track impulse produces secular (growing) along-track displacement.")
    _add_bullet(doc, "y(t) = Δvy (4sin(nt) - 3nt) / n — secular term dominates over time.")
    _add_bullet(doc, "Use case: satellite shadowing, constellation phasing, passive intercept.")
    _add_heading_h3(doc, "Combined Manoeuvre")
    _add_bullet(doc, "Solves the full 2×2 CW system for simultaneous radial + along-track targets.")
    _add_bullet(doc, "Operator specifies: 'Create X km radial separation and Y km along-track offset in T minutes.'")
    _add_callout(doc,
        "CW manoeuvres are most accurate when the relative separation is small "
        "compared to the orbital radius (< 100 km). For larger separations, use "
        "Lambert or Hohmann transfers instead."
    )

    # Plane Change.
    _add_heading_h2(doc, "Plane Change")
    _add_body(doc,
        "Many tactical intercepts require orbital plane alignment before a transfer "
        "can be executed. SPECTRE evaluates two strategies:"
    )
    _add_bullet(doc, "Pure plane change: ΔV = 2v sin(Δi/2). Evaluated at both the equatorial node and apogee — apogee is cheaper for eccentric orbits.")
    _add_bullet(doc, "Combined altitude + plane change: Uses the cosine rule to fold the inclination change into a Hohmann-like transfer. Always cheaper than performing them separately.")
    _add_callout(doc,
        "Key question for operators: 'Is it cheaper to change plane first, or during "
        "the transfer?' SPECTRE answers this automatically by comparing pure and combined costs."
    )

    # J2 Drift.
    _add_heading_h2(doc, "J2 Drift Planner")
    _add_body(doc,
        "Earth's oblateness (J2) causes the right ascension of the ascending node "
        "(RAAN) to precess secularly. SPECTRE exploits this for fuel-free orbital "
        "plane alignment."
    )
    _add_body(doc,
        "    dΩ/dt = -3/2 · n · J2 · (R_E / p)² · cos(i)"
    )
    _add_bullet(doc, "Prograde orbits (i < 90°): RAAN drifts westward (negative rate).")
    _add_bullet(doc, "Retrograde orbits (i > 90°): RAAN drifts eastward (positive rate).")
    _add_bullet(doc, "Polar orbits (i = 90°): No RAAN drift — J2 cannot help.")
    _add_bullet(doc, "Different altitudes produce different drift rates → natural convergence.")
    _add_body(doc,
        "SPECTRE computes the natural convergence time between two satellites and the "
        "small altitude change that would accelerate convergence — trading a tiny ΔV "
        "for days or weeks of waiting time."
    )
    _add_callout(doc,
        "J2 drift is extremely powerful for strategic orbit planning. A 50 km altitude "
        "change can shift the differential RAAN rate by several tenths of a degree per "
        "day — potentially saving weeks of waiting for natural alignment."
    )

    # COLA.
    _add_heading_h2(doc, "Collision Avoidance (COLA)")
    _add_body(doc,
        "When a conjunction is predicted, SPECTRE computes the minimum ΔV to move the "
        "satellite outside the collision probability envelope. Three strategies are "
        "evaluated simultaneously:"
    )
    _add_bullet(doc, "Radial kick — displace the satellite perpendicular to its orbit plane.")
    _add_bullet(doc, "In-track drift — along-track impulse creates growing separation via differential period.")
    _add_bullet(doc, "Out-of-plane burn — normal impulse shifts the orbit plane slightly.")
    _add_body(doc,
        "SPECTRE selects the cheapest strategy automatically. The operator sees all three "
        "options and their ΔV costs in the result notes."
    )
    _add_callout(doc,
        "For typical LEO conjunctions with 1+ hour warning, along-track burns are "
        "usually cheapest. For short-notice events (< 30 minutes), radial or "
        "out-of-plane burns may be the only viable option."
    )

    # Evasion.
    _add_heading_h2(doc, "Optimal Defensive Evasion")
    _add_body(doc,
        "The evasion planner extends COLA into a full defensive manoeuvre "
        "generator. Given an incoming threat, a fuel budget, and available "
        "warning time, SPECTRE evaluates multiple burn strategies across multiple "
        "timing offsets to find the optimal evasion burn."
    )
    _add_bullet(doc, "Respects fuel budget constraints — will not exceed available ΔV.")
    _add_bullet(doc, "Evaluates prograde, normal, and radial burns at 25%, 50%, 75%, and 100% of available warning time.")
    _add_bullet(doc, "Reports remaining fuel after the manoeuvre.")
    _add_bullet(doc, "Selects the strategy that achieves the required miss distance with minimum ΔV.")
    _add_callout(doc,
        "The key difference from COLA: evasion respects operational constraints. "
        "A COLA computation may suggest a burn that exceeds your fuel budget. The "
        "evasion planner will find the best achievable miss distance within your constraints."
    )

    # GEO Drift.
    _add_heading_h2(doc, "GEO Drift Orbit")
    _add_body(doc,
        "For geostationary satellites, SPECTRE computes east-west longitude "
        "relocation via drift orbits. A small SMA change induces a secular "
        "longitude drift, and a symmetric burn at the target longitude "
        "re-circularises the orbit."
    )
    _add_body(doc,
        "    dλ/dt = -3/2 · n_geo · Δa / a_geo"
    )
    _add_bullet(doc, "Raising SMA by ~1 km → westward drift of ~0.01°/day.")
    _add_bullet(doc, "Two symmetric burns: enter drift orbit + stop at target longitude.")
    _add_bullet(doc, "Also supports graveyard orbit transfers (GEO + 300 km, standard end-of-life disposal).")
    _add_callout(doc,
        "GEO drift is extremely fuel-efficient — relocating 30° in longitude "
        "over 30 days costs only a few m/s of ΔV. This makes it ideal for "
        "strategic repositioning of GEO defence assets."
    )

    # NMC / Safety Ellipse.
    _add_heading_h2(doc, "Natural Motion Circumnavigation (NMC)")
    _add_body(doc,
        "The NMC solver computes relative orbits for proximity operations. "
        "In CW dynamics, bounded (non-drifting) relative motion follows a "
        "2:1 ellipse: the along-track amplitude is always twice the radial "
        "amplitude."
    )
    _add_bullet(doc, "Passive safety: if propulsion fails, the inspector naturally drifts away from the target.")
    _add_bullet(doc, "Safety margin = radial amplitude (minimum distance from target).")
    _add_bullet(doc, "Single impulse to establish the relative orbit (radial + optional cross-track).")
    _add_bullet(doc, "Used by NASA, ESA, and DoD for formation flying and satellite inspection.")
    _add_callout(doc,
        "The passive safety guarantee is critical for high-value assets. If the "
        "inspector's propulsion fails during proximity operations, a properly "
        "designed NMC trajectory ensures it drifts harmlessly away rather than "
        "colliding with the target."
    )

    # Manoeuvre Classification.
    _add_heading_h2(doc, "Manoeuvre Classification Engine")
    _add_body(doc,
        "Given two TLEs of the same satellite at different epochs, SPECTRE "
        "estimates what manoeuvre occurred between them. This transforms SPECTRE "
        "from a planning tool into a space intelligence tool."
    )
    _add_bullet(doc, "Compares Keplerian elements (Δa, Δe, Δi, ΔRAAN) between epochs.")
    _add_bullet(doc, "Subtracts expected J2 RAAN drift to isolate manoeuvre-induced changes.")
    _add_bullet(doc, "Classifies: altitude change, plane change, phasing, station-keeping, combined, or unknown.")
    _add_bullet(doc, "Estimates ΔV magnitude and burn direction (prograde, normal, radial, combined).")
    _add_bullet(doc, "Reports confidence level (0–100%) for the classification.")

    # Detectability.
    _add_heading_h2(doc, "Intercept Detectability Metric")
    _add_body(doc,
        "For any computed intercept, SPECTRE assesses how detectable the "
        "manoeuvre would be by ground-based space surveillance networks. "
        "This enables counter-space analysis and operational security planning."
    )
    _add_bullet(doc, "ΔV categorisation: micro (< 1 m/s), small (1–10 m/s), medium (10–100 m/s), large (> 100 m/s).")
    _add_bullet(doc, "Detection probability based on altitude regime (LEO/MEO/GEO) and ΔV magnitude.")
    _add_bullet(doc, "Estimated time to detection (hours) — how quickly ground tracking would notice.")
    _add_bullet(doc, "Overall observability score (0–100) combining all factors.")
    _add_callout(doc,
        "Micro-manoeuvres (< 1 m/s) in GEO are extremely difficult to detect — "
        "detection probability below 10% and potentially days before orbital "
        "changes become apparent. This is why GEO drift manoeuvres are so "
        "strategically significant."
    )

    # Intent Predict.
    _add_heading_h2(doc, "Intent Predict")
    _add_body(doc,
        "The intent predictor scores adversary intercept intent by correlating "
        "observed orbital behaviour against known attack profiles. It combines "
        "manoeuvre classification output with geometric opportunity analysis "
        "to produce a composite threat score."
    )
    _add_bullet(doc, "Analyses recent manoeuvre history (Δa, Δi, ΔRAAN sequence) for convergent behaviour towards a blue asset.")
    _add_bullet(doc, "Geometric opportunity score: evaluates phase angle closure rate, coplanarity trend, and relative altitude convergence.")
    _add_bullet(doc, "Intent score (0–100): weighted combination of behavioural correlation and geometric opportunity.")
    _add_bullet(doc, "Thresholds: 0–25 nominal, 25–50 ambiguous, 50–75 suspicious, 75–100 hostile.")
    _add_callout(doc,
        "Intent prediction is inherently probabilistic — it identifies patterns "
        "consistent with intercept preparation, not certainty. Always combine with "
        "intelligence context and orbital geometry before escalating."
    )

    # Intercept Envelope.
    _add_heading_h2(doc, "Intercept Envelope")
    _add_body(doc,
        "The intercept envelope solver computes the probabilistic reachability "
        "volume for a satellite within a given time horizon. It sweeps time of "
        "flight values across the vis-viva equation to determine the set of "
        "orbits achievable within a ΔV budget."
    )
    _add_bullet(doc, "Vis-viva TOF sweep: evaluates reachable semi-major axes for ΔV budgets from 10 to 5,000 m/s.")
    _add_bullet(doc, "Produces altitude-vs-time contour showing the reachability envelope.")
    _add_bullet(doc, "Identifies which blue assets fall within the adversary's reachable set at each time step.")
    _add_bullet(doc, "Supports both prograde-only and arbitrary-direction burn assumptions.")
    _add_callout(doc,
        "The intercept envelope answers the key operational question: 'Which of "
        "our assets can this threat reach, and how quickly?' Use it for force "
        "protection prioritisation and early warning."
    )

    # Stability Analysis.
    _add_heading_h2(doc, "Stability Analysis")
    _add_body(doc,
        "The stability analyser evaluates the boundedness of relative motion "
        "between two co-orbital objects using the CW drift condition. Bounded "
        "(non-drifting) relative motion requires the initial along-track velocity "
        "offset to satisfy:"
    )
    _add_body(doc,
        "    Δvy₀ = −2n · Δx₀"
    )
    _add_bullet(doc, "Computes the stability score: ratio of actual Δvy₀ to the bounded-motion requirement.")
    _add_bullet(doc, "Score near 1.0 = bounded (formation-stable); score ≫ 1.0 or ≪ 1.0 = drifting apart or converging.")
    _add_bullet(doc, "Reports the secular drift rate in km/orbit if the condition is not satisfied.")
    _add_bullet(doc, "Use case: assess whether an adversary is passively co-orbiting or actively maintaining proximity.")
    _add_callout(doc,
        "A stability score near 1.0 for an adversary satellite is a strong indicator "
        "of deliberate station-keeping relative to your asset — this is a key input "
        "to the intent predictor."
    )

    # Fingerprint.
    _add_heading_h2(doc, "Manoeuvre Fingerprinting")
    _add_body(doc,
        "The fingerprint engine extends manoeuvre classification by matching "
        "observed behaviour against six canonical manoeuvre profiles. Each "
        "profile captures a distinct operational pattern with characteristic "
        "orbital element signatures."
    )
    _add_bullet(doc, "Profile 1 — Station-keeping: periodic small Δa corrections, stable inclination and RAAN.")
    _add_bullet(doc, "Profile 2 — Phasing: periodic Δa oscillations with monotonic phase-angle closure.")
    _add_bullet(doc, "Profile 3 — Plane alignment: progressive Δi or ΔRAAN changes toward a target plane.")
    _add_bullet(doc, "Profile 4 — Intercept approach: combined altitude and plane convergence toward a specific target.")
    _add_bullet(doc, "Profile 5 — Evasion: abrupt manoeuvre followed by divergent trajectory relative to a threat.")
    _add_bullet(doc, "Profile 6 — Disposal: monotonic altitude decrease or GEO graveyard insertion.")
    _add_bullet(doc, "Returns the best-matching profile, correlation score (0–1), and confidence level.")
    _add_callout(doc,
        "Fingerprinting is most effective when multiple TLE epochs are available "
        "(3+ manoeuvre observations). Single-epoch classification reverts to the "
        "standard manoeuvre classification engine."
    )

    # Formation Defence.
    _add_heading_h2(doc, "Formation Defence")
    _add_body(doc,
        "The formation defence solver extends COLA by adding a formation spacing "
        "constraint. When defending a formation of blue assets, collision avoidance "
        "manoeuvres must not only avoid the threat but also maintain the minimum "
        "required spacing between formation members."
    )
    _add_bullet(doc, "Input: formation member positions, minimum inter-satellite spacing, and the conjunction threat.")
    _add_bullet(doc, "Evaluates COLA manoeuvres that maintain formation geometry within tolerance.")
    _add_bullet(doc, "If no single-burn solution preserves formation spacing, recommends coordinated multi-satellite burns.")
    _add_bullet(doc, "Reports post-manoeuvre formation integrity score and any spacing violations.")
    _add_callout(doc,
        "Formation defence is critical for distributed space architectures where "
        "losing formation geometry may be as costly as the conjunction itself. "
        "Always verify formation integrity after any COLA manoeuvre."
    )

    # Orbital Terrain.
    _add_heading_h2(doc, "Orbital Terrain Mapping")
    _add_body(doc,
        "The orbital terrain mapper produces an altitude-vs-inclination risk map "
        "characterising the operational environment. It combines three risk layers "
        "to produce a composite terrain score for any orbital regime."
    )
    _add_bullet(doc, "Debris density: spatial density of tracked debris objects per altitude/inclination bin.")
    _add_bullet(doc, "Congestion: number of active satellites and manoeuvring objects in each bin.")
    _add_bullet(doc, "Radiation: trapped proton and electron flux from the AP-8/AE-8 radiation belt models.")
    _add_bullet(doc, "Composite terrain score (0–100): weighted sum of debris, congestion, and radiation risk.")
    _add_bullet(doc, "Use case: route planning for orbital transfers, identifying safe parking orbits, risk-aware manoeuvre selection.")
    _add_callout(doc,
        "The 800–1000 km altitude band at high inclination (sun-synchronous) "
        "typically scores highest for debris risk due to historical fragmentation "
        "events. GEO scores highest for congestion. MEO radiation belts peak "
        "near 20,000 km altitude."
    )

    # Min-Time Intercept.
    _add_heading_h2(doc, "Min-Time Intercept")
    _add_body(doc,
        "The min-time intercept solver finds the shortest time of flight that "
        "achieves intercept within a given ΔV budget. It uses a binary search "
        "on TOF, evaluating Lambert solutions at each step to find the minimum "
        "transfer time that satisfies the fuel constraint."
    )
    _add_bullet(doc, "Input: blue asset, red track, maximum ΔV budget (m/s).")
    _add_bullet(doc, "Binary search converges on TOF to within 1-second precision.")
    _add_bullet(doc, "Reports the minimum achievable TOF, required ΔV, and the corresponding Lambert solution.")
    _add_bullet(doc, "If no solution exists within the ΔV budget, reports the minimum ΔV required and the corresponding TOF.")
    _add_callout(doc,
        "Min-time intercept answers the urgent operational question: 'How fast can "
        "we get there with the fuel we have?' Use it for time-critical threat "
        "response where speed matters more than fuel efficiency."
    )

    # Extended comparison table.
    _add_heading_h2(doc, "Complete Method Comparison")
    _add_data_table(doc,
        ["Method", "Burns", "Best Use Case", "ΔV Character"],
        [
            ["Lambert", "1–2", "General intercept, arbitrary geometry", "Variable"],
            ["Hohmann", "2", "Altitude change, coplanar circular", "Minimum energy"],
            ["Bi-elliptic", "3", "Large altitude ratio (r₂/r₁ > 11.94)", "Lower than Hohmann for large ratios"],
            ["Phasing", "2", "Along-track rendezvous, delayed intercept", "Very low (period adjustment)"],
            ["CW Radial", "1", "Defensive spacing, inspection geometry", "Very low (metres/s)"],
            ["CW Drift", "1", "Shadowing, constellation spacing", "Very low (metres/s)"],
            ["Plane Change", "1–2", "Inclination alignment", "High (proportional to Δi)"],
            ["J2 Drift", "0–1", "RAAN alignment, strategic planning", "Near-zero (natural precession)"],
            ["COLA", "1", "Conjunction avoidance", "Minimum for required miss distance"],
            ["Evasion", "1", "Defensive manoeuvre under fuel constraints", "Budget-constrained minimum"],
            ["GEO Drift", "2", "GEO longitude relocation", "Very low (mm/s to m/s)"],
            ["NMC", "1", "Proximity ops, formation flying", "Very low (relative orbit establishment)"],
            ["Manoeuvre Detect", "0", "Space intelligence, behaviour analysis", "N/A (analytical)"],
            ["Detectability", "1–2", "Counter-space analysis, OPSEC", "Same as underlying intercept"],
            ["Intent Predict", "0", "Adversary intent scoring, threat assessment", "N/A (analytical)"],
            ["Intercept Envelope", "0", "Reachability analysis, force protection", "Budget-swept (vis-viva)"],
            ["Stability Analysis", "0", "Relative motion boundedness assessment", "N/A (analytical)"],
            ["Fingerprint", "0", "Behavioural classification against 6 profiles", "N/A (analytical)"],
            ["Formation Defence", "1–N", "COLA with formation spacing constraint", "Minimum for miss + spacing"],
            ["Orbital Terrain", "0", "Risk mapping: debris, congestion, radiation", "N/A (analytical)"],
            ["Min-Time Intercept", "1–2", "Fastest intercept within ΔV budget", "Budget-constrained minimum TOF"],
        ],
    )


def _section_09_threat_sweep(doc: Document) -> None:
    """Section 9: Threat Sweep."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 9")
    _add_heading_h1(doc, "Threat Sweep")

    _add_body(doc,
        "The Threat Sweep performs a rapid batch intercept assessment of all HRR "
        "objects in a chosen target group against your primary blue asset. It runs "
        "a Hohmann screening pass across five orbital epochs for each target, then "
        "refines the top-five results with Lambert solvers."
    )

    _add_heading_h2(doc, "Operator Workflow")
    _add_bullet(doc, "1. Connect to UDL and fetch the HRR watchlist (Assets \u2192 HRR tab).")
    _add_bullet(doc, "2. Open the Threat Sweep hero tab.")
    _add_bullet(doc, "3. Select a Target Group from the dropdown (e.g. 'Red HRR \u2013 Rank 1').")
    _add_bullet(doc, "4. Click Fetch TLEs \u2014 SPECTRE retrieves TLEs for all objects in the group and displays a readiness badge (N/M TLEs ready).")
    _add_bullet(doc, "5. Click Sweep Targets \u2014 the batch assessment runs and the ranked results table appears.")
    _add_bullet(doc, "6. Optionally click Refine on any row for a full Lambert refinement of that target.")

    _add_heading_h2(doc, "Sweep Algorithm")
    _add_body(doc,
        "For each target in the selected group, SPECTRE computes Hohmann \u0394V at five "
        "canonical epochs: T+0 (now), apogee passage, perigee passage, ascending node, "
        "and descending node. All N\u00D75 entries are ranked by \u0394V; the five unique "
        "lowest-cost targets are then refined with Lambert solvers for precision \u0394V "
        "and miss distance."
    )
    _add_data_table(doc,
        ["Result Column", "Description"],
        [
            ["Target", "Satellite name and NORAD ID"],
            ["Orbit", "Orbit regime compatibility badge"],
            ["\u0394V (m/s)", "Minimum Lambert transfer cost (refined)"],
            ["Miss Distance (km)", "Closest approach distance at intercept epoch"],
            ["Epoch", "Optimal manoeuvre start epoch"],
            ["Method", "Screening method (Hohmann/Lambert)"],
        ],
    )

    _add_heading_h2(doc, "Data Mode Filter")
    _add_body(doc,
        "A 'Data Mode' dropdown above the results table filters displayed rows by the "
        "UDL data mode tag of the cached TLE (REAL / SIMULATED / EXERCISE / TEST). "
        "Select 'All' to show every target regardless of data mode. This is a "
        "display-time filter — no re-fetch occurs."
    )

    _add_callout(doc,
        "Orbit regime compatibility is enforced: a LEO blue asset will only sweep "
        "LEO targets; a GEO blue asset will only sweep GEO targets. Incompatible "
        "targets are excluded with an explanatory note."
    )


def _section_10_intercept_calculations(doc: Document) -> None:
    """Section 10: Running Intercept Calculations."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 10")
    _add_heading_h1(doc, "Running Intercept Calculations")

    _add_heading_h2(doc, "Method Selection")
    _add_body(doc,
        "Select the intercept method from the dropdown in the Intercept Engine panel. "
        "Methods are grouped into two categories:"
    )
    _add_bullet(doc, "Classical Transfers: Lambert, Hohmann, Bi-elliptic, Proximity, Rendezvous.")
    _add_bullet(doc, "Tactical Manoeuvres: Phasing, CW Radial, CW Drift, Plane Change, J2 Drift, COLA, Evasion.")
    _add_bullet(doc, "Advanced Analysis: GEO Drift, NMC (safety ellipse), Manoeuvre Detect, Detectability.")
    _add_bullet(doc, "Decision Support: Intent Predict, Intercept Envelope, Stability Analysis, Fingerprint, Formation Defence, Orbital Terrain, Min-Time Intercept.")
    _add_body(doc,
        "The form adapts to show relevant fields for each method — time of flight "
        "is shown for Lambert and CW methods; target distance is shown for CW, "
        "COLA, and Proximity methods."
    )

    _add_heading_h2(doc, "Parameters")
    _add_data_table(doc,
        ["Parameter", "Description", "Default"],
        [
            ["Red Satellite", "Target threat track to intercept", "(select from red tracks)"],
            ["Blue Satellite", "Friendly asset performing the manoeuvre", "(select from blue assets)"],
            ["Manoeuvre Start", "UTC epoch for the first burn", "Current UTC time"],
            ["Coast Hours", "Coast duration before first burn (hours)", "1.0"],
            ["Intercept Hours", "Time of flight for Lambert solver (hours)", "6.0"],
            ["Targeting", "Search: try burning now and at the red satellite's next apogee, perigee and nodes, with a range of times of flight, revolutions and hops, and keep each red approach's cheapest plan that arrives. Typed: solve each method once with the values below.", "Search for the cheapest approach"],
            ["Approach within", "How close, in metres, a red approach must come to the target to count; 0 means 50 km.", "0 (50 km)"],
            ["Max ΔV", "ΔV budget (m/s) for evasion, the envelope and typed minimum-time, and the reference for each row's budget share. The default is the most any satellite in JCO's NOTSO record spent on station in 14 days (owner ruling, 12 November 2026).", "171.8"],
            ["Intercept Data Mode", "Re-fetch red/blue TLEs from UDL under this data mode before computing. Leave blank to use session TLEs.", "Session default (REAL)"],
        ],
    )

    _add_heading_h2(doc, "Red Approaches, Realism and the Most Likely Course of Action")
    _add_body(doc,
        "Calculate All Intercepts ranks the 23 methods in three groups: red approaches first, then avoidance and "
        "defence (COLA, Evasion and Formation Defence, blue's options, never ranked as red threats), then the "
        "assessments, J2 drift among them."
    )
    _add_bullet(doc, "Flown closest approach: each red approach's burns are flown (two-body for red between burns, "
                     "SGP4 for the target) and the closest it comes to the target is reported, with the 1-sigma "
                     "element-set error band beside it. The V-bar and H-bar hops list every burn of the sequence, "
                     "and are flown too. "
                     "A figure that could not be computed reads \"not computed\" and never counts as arriving. The "
                     "V-bar hop burns toward the target's side: inward for a target ahead, outward for one behind.")
    _add_bullet(doc, "Realism: Seen before (within what this satellite has spent on station in its busiest 14 days), "
                     "Possible (within 171.8 m/s, the most any satellite in the NOTSO record spent) or Unrealistic. "
                     "The record is a floor on what satellites have done, not a ceiling on what they could do.")
    _add_bullet(doc, "No approach: the plan never comes within the approach distance. Such rows, and Unrealistic ones, "
                     "stay listed, dimmed, with their reason; they cannot set the worst case.")
    _add_bullet(doc, "Most likely course of action: the cheapest red approach that arrives and is Seen before or "
                     "Possible, with its burn point, ΔV and closest approach.")
    _add_body(doc,
        "Expand a row to see the burn point, coast, time of flight, revolutions or hops the search kept, how many "
        "options it compared, the closest approach and the realism reason. When searching, minimum-time is given "
        "36.8 m/s, what nine in ten satellites stay within over 14 days, or the red satellite's own busiest 14 days "
        "if that is more."
    )

    _add_heading_h2(doc, "Interpreting the Burn Table")
    _add_body(doc,
        "The result displays a per-burn breakdown table with the following columns:"
    )
    _add_bullet(doc, "Burn # — sequential burn index (1-based).")
    _add_bullet(doc, "Segment — descriptive name of the manoeuvre segment.")
    _add_bullet(doc, "Burn Epoch — UTC time of the impulsive burn.")
    _add_bullet(doc, "ΔV m/s — total delta-V magnitude for this burn.")
    _add_bullet(doc, "Prograde — velocity-direction component (VNB frame).")
    _add_bullet(doc, "Normal — orbit-normal component (VNB frame).")
    _add_bullet(doc, "Radial — co-normal/radial component (VNB frame).")

    _add_heading_h2(doc, "VNB Reference Frame")
    _add_body(doc,
        "SPECTRE decomposes all ΔV vectors into the VNB (Velocity-Normal-Binormal) frame, "
        "also known as the local orbital frame. This is the standard frame used by "
        "spacecraft operators for manoeuvre planning:"
    )
    _add_bullet(doc, "V (Prograde): Along the velocity vector. Positive prograde raises the orbit on the opposite side.")
    _add_bullet(doc, "N (Normal): Perpendicular to the orbital plane (angular momentum direction). Used for plane changes.")
    _add_bullet(doc, "B (Radial/Binormal): Completes the right-hand triad. Points generally away from the central body.")


def _section_11_trade_space(doc: Document) -> None:
    """Section 11: Trade-Space Analysis."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 11")
    _add_heading_h1(doc, "Trade-Space Analysis")

    _add_body(doc,
        "The trade-space scatter plot visualises all intercept solutions computed "
        "during the current session. It plots ΔV (m/s) against transfer time (minutes), "
        "with points colour-coded by method:"
    )
    _add_bullet(doc, "Lambert / Proximity — Ops Blue (#00659E)")
    _add_bullet(doc, "Hohmann / Rendezvous — Command Gold (#C8A415)")
    _add_bullet(doc, "Bi-elliptic — Green (#27AE60)")
    _add_bullet(doc, "Tactical manoeuvres (Phasing, CW, Plane Change, J2 Drift, COLA) — distinct colours per method")

    _add_heading_h2(doc, "Using the Trade-Space Plot")
    _add_body(doc,
        "Run intercept calculations with different methods and parameters. After "
        "the second solution, the trade-space chart appears automatically below the "
        "burn table. Hover over any point to see the method, ΔV, transfer time, and "
        "miss distance, or \"not computed\" where it could not be."
    )
    _add_body(doc,
        "Look for the Pareto front — solutions in the lower-left region of the chart "
        "offer the best combination of low ΔV and short transfer time. Solutions "
        "closer to the axes represent trade-offs: low ΔV with longer transfers, or "
        "fast transfers with higher ΔV."
    )

    _add_heading_h2(doc, "Clearing History")
    _add_body(doc,
        "Click the 'Clear History' button on the chart to reset all accumulated "
        "solutions and start a fresh trade-space analysis. This also clears the "
        "current intercept result display."
    )


def _section_12_scenario_planning(doc: Document) -> None:
    """Section 12: Scenario Planning."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 12")
    _add_heading_h1(doc, "Scenario Planning")

    _add_heading_h2(doc, "Access Windows")
    _add_body(doc,
        "SPECTRE detects orbital events — apogee, perigee, ascending node, and "
        "descending node — for both red and blue satellites within the scenario "
        "time window. These events define natural manoeuvre opportunities."
    )
    _add_bullet(doc, "Apogee burns are efficient for lowering the perigee.")
    _add_bullet(doc, "Perigee burns are efficient for raising the apogee.")
    _add_bullet(doc, "Node crossings indicate plane-change opportunities.")

    _add_heading_h2(doc, "Conjunction Detection")
    _add_body(doc,
        "When both a red track and a blue asset are loaded, SPECTRE can identify "
        "close-approach windows by propagating both TLEs through the scenario "
        "period. Events are displayed as clickable badges that auto-populate "
        "the manoeuvre start time field."
    )
    _add_callout(doc,
        "Operator tip: Use orbital events to identify the optimal manoeuvre epoch, "
        "then run Lambert solvers at those epochs to minimise ΔV."
    )


def _section_13_decision_engine(doc: Document) -> None:
    """Section 13: Decision Engine & Scenario Evaluation, as built at 0.24.0 (SPC-152), with SPC-191's score scales."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 13")
    _add_heading_h1(doc, "Decision Engine & Scenario Evaluation")

    _add_body(doc,
        "Something moved. The sweep tells you whether it can reach one of yours, how long you have and whether "
        "it means anything. The Decision Engine answers the last part of the question: what you need to decide, "
        "and by when. You set out what red might do next and what you could do in reply; the engine scores every "
        "pairing, ranks your responses, shows the pick of each of its three rules side by side, and recommends "
        "the pick of your deployment's primary rule, whichever rule you choose."
    )
    _add_body(doc,
        "The recommendation is a modelled estimate, not a computed solution, and the page says so. Every figure "
        "behind it states what it rests on, so you can see how much of the answer is physics and how much is rule "
        "of thumb."
    )

    _add_heading_h2(doc, "What Each Figure Rests On")
    _add_body(doc,
        "Each figure in the results is marked with its basis in words, with the rule behind it beside it:"
    )
    _add_data_table(doc,
        ["Basis", "What it means"],
        [
            ["Computed", "Propagated from the real element sets of the bound red track and blue asset, both on one "
             "propagator, with no randomness."],
            ["Sampled", "The P5 of many propagated runs of a hypothesised red burn, the miss only 1 run in 20 came "
             "closer than, with its spread and how well it is known."],
            ["Lookup", "A fixed rule of thumb or table value. It moves the ranking but rests on no orbit. Each one "
             "is listed in docs/lookup-register.md with its source, owner and the date it was set."],
            ["Judgement", "A value on the panel when you evaluated, set by you or kept where the panel started it. "
             "It is not evidence, and it never lends a figure more standing than a lookup."],
        ],
    )
    _add_body(doc,
        "The composite score is always a lookup. Its weights are not yet cited (SPC-151), so read a cell's figures, "
        "not only its rank. No score is coloured by its value: no sourced threshold says where a score turns good "
        "or bad, so each is shown as its number, to three places, lower being better, with its basis (SPC-208, "
        "finding F-18 of the independent evaluation). A response marked not permitted is still greyed."
    )
    _add_body(doc,
        "The score adds custody lost and closest approach as separate terms, with nothing joining them (SPC-219, "
        "finding F-20 of the independent evaluation): a close approach while custody is lost scores what the two "
        "score apart, no more, though an approach you cannot see may be worse than the two added together. No "
        "source for a term joining them was found, so none is added, and a note beside the matrix and the game tree "
        "says so."
    )
    _add_body(doc,
        "Training only (SPC-207, finding F-17 of the independent evaluation). Where nothing is computed or sampled, "
        "a figure is set by one of seven relations of the lookup model: the custody rule, a sensor retask's custody "
        "gap of half its time to execute, a closest approach by red's action type (200 km against a manoeuvre, "
        "5,000 km against no action, 10,000 km against a sensor retask, 3,000 km against any other), our "
        "manoeuvre's and our posture change's multipliers on that miss, our delta-V of cost times 50 m/s with no "
        "burn sized, and a closest approach at 0.4 of the horizon. None has a source; each is listed in "
        "docs/lookup-register.md as an unsourced judgement. A result whose figures, in the matrix or in any branch "
        "of a game tree, rest on any of them says so at the top of the results, starting 'Training only.', and names "
        "each relation in words: use it to train, not to decide. The label comes first in the results, before the "
        "collect-first advice and every pick. A fully bound scenario with every figure computed "
        "or sampled carries no label. Your decision record keeps the label as shown, and the Decision records page "
        "shows it; a record written before the label was recorded reads 'Training-only label: not recorded'."
    )
    _add_body(doc,
        "Element-set error is in every closest approach the engine propagates (SPC-202, evaluation finding F-11). "
        "Its model is the threat sweep's rule of thumb, tuned, not sourced: 1 km at epoch plus 2 km a day by the "
        "LEO figure, which MEO and HEO/Molniya sets take too, and 2 km plus 1 km a day by the GEO figure, for GEO and "
        "sets beyond the GEO band, at each element set's age. In a sampled cell every sample "
        "also draws each object's element-set error along track, red and blue each their own, so the band, P5 and "
        "the score read the moved objects; no radial or cross-track part is drawn. A computed cell keeps its miss "
        "as the figure and shows a band beside it, the miss less and plus both sets' error at the closest approach "
        "in quadrature, 1 sigma, and its score reads the band's lower edge, the closer case: Claude's choice. A "
        "sampled cell scores on P5, so the two are read at different confidence levels. Where our burn is sized, "
        "the burn is sized on the miss, and its cell scores its own band's lower edge, so the rule can change which "
        "response is picked. A sampled time of closest approach carries only the growth of the error after the "
        "scenario epoch, since every sample draws the error at the epoch. A record written by 0.28.0 to 0.31.0 is "
        "replayed under the rule it was evaluated by, with no element-set error, and the replay says so first. A "
        "wider band needs more samples to converge: a GEO pair 15 km apart with both sets a day old needs 1,000, "
        "where the default is 500."
    )
    _add_body(doc,
        "Under the basis lines, 'Judgement inputs' lists every input on the panel that enters a score or a pick, "
        "each marked '(judgement)': the weights, the keep-out distance, the horizon and the turns; each response's "
        "type, cost, reversibility and time to execute, and its burn's target separation, budget and axis; each "
        "row's type, P and Conf, and its custody gap share where the rule of thumb reads it; each manoeuvre "
        "hypothesis and its samples; and the turn-1 observation you state for a tree. A value you kept where the "
        "panel started it is your judgement too, and its note says where a new panel starts it; a budget left blank "
        "is the 50 m/s default you kept. Each line says what reads it. A P you never edited is marked '(lookup)', the "
        "panel's default, and so are a P and Conf from a NOTSO suggestion you applied. A hypothesis is marked by where "
        "it came from: entered, or an archetype you chose, is your judgement, with an archetype's delta-V a lookup; "
        "a burn detected in the element-set history is what red did, '(computed)'. Its line says its row was sampled "
        "from it only when it was. A figure's own mark names the evidence and rules it rests on, taking your inputs as "
        "given. The recommended response's type, cost, reversibility and time to execute, and each row's type, P and "
        "Conf in the matrix, carry the same mark. The last basis line names the code version that computed the "
        "result. Every lookup, and every value a new panel starts at, is listed in docs/lookup-register.md."
    )
    _add_body(doc,
        "The score values closest approach and your delta-V in orders of magnitude. Set the keep-out distance on "
        "the panel, 'Keep-out distance (km)', from 0.1 to 10,000 km: a miss at or inside it scores the full "
        "closest-approach penalty, and each tenfold beyond it scores less, down to none at 50,000 km. Its default, "
        "10 km, is Claude's choice and unsourced, and the results state the distance used. Your delta-V scores in "
        "orders of magnitude up to 1,000 m/s, the engine's per-burn limit, so a 100 m/s burn and a 500 m/s burn "
        "score apart. At the default weights and keep-out distance, a burn of up to about 9 m/s that opens a miss "
        "from 1 km to 100 km scores better than doing nothing. The break-even moves with the keep-out distance: "
        "about 38 m/s at 1 km, and none at 100 km, where both misses score the full penalty. A cleared field is "
        "refused, not scored at the default. Neither scale has yet been signed off by the technical authority."
    )

    _add_heading_h2(doc, "Bind the Scenario to Real Objects")
    _add_body(doc,
        "Under 'Bind to real objects', choose a held red track and a held blue asset. The results then name them, "
        "show each element set's epoch and its age against its limit (72 hours for GEO or a perigee beyond GEO, 24 "
        "hours otherwise, Molniya-class and other HEO orbits included), and record both in the result's provenance. Unbound, every figure is a lookup. Bound, the "
        "engine computes or samples what it can, and never falls back on a lookup constant where a computed or "
        "sampled figure exists."
    )
    _add_body(doc,
        "Beside each bound set the results state its regime, read from its period and eccentricity: LEO, MEO, "
        "HEO/Molniya, GEO or other deep-space. They say whose staleness limit and element-set error rate it takes. "
        "No figure has been sourced for any regime, so where the set takes another regime's figure the results say "
        "so, for example \"LEO figure applied to HEO/Molniya, unsourced for this regime\". The red card, the "
        "sweep's element-set ages and delta-V band, and the Intercept Engine's error band say the same."
    )
    _add_body(doc,
        "Every element set passes one acceptance check before SPECTRE holds it, whichever way it arrives: from UDL, "
        "pasted by you, in a Pattern of Life history, from the bundled watchlist or from a training scenario. Both "
        "lines must carry their line numbers and good checksums in plain ASCII and one catalogue number, "
        "which must be for the number asked when a set is fetched for one; a readable epoch; every field "
        "written as the format writes it, B* and the drag terms included, so a 0 changed to a letter is caught "
        "though the checksum cannot see it; every orbital element inside its range; an ephemeris type of 0, SGP4, "
        "since SGP4 would propagate an SGP4-XP set (type 4) to a wrong orbit without an error; not an uncorrelated "
        "track (UCT) from UDL; and an orbit SGP4 can start from. When the newest set UDL answers with is refused for "
        "its type, no older set is taken in its place, and you are told. A set that "
        "fails is not stored and never replaces a set already held; you are told which object and what failed, "
        "on the page or, where the path has no page of its own, in the run log, and the log records the same "
        "without the set's text. A scenario checks its sets again when you bind it."
    )
    _add_body(doc,
        "The conditions the engine is fit for, and where each is enforced, are in "
        "docs/decision-engine-envelope.md. Under 'Outside the operating envelope', the results flag a bound object "
        "on SDP4, SGP4's deep-space branch, which SGP4 uses from a period of about 225 minutes. Its figures stand. "
        "For a GEO set, its staleness limit and element-set error model are the "
        "GEO rules of thumb, tuned rather than sourced; for HEO, Molniya-class and other orbits on SDP4 they are rules of thumb set for LEO and GEO, "
        "not validated for it. The flag says that the error model also sets every sample's draw, every computed "
        "band, and the closest approach and score that read them. An object below the 100 km re-entry floor at any moment searched, or that SGP4 "
        "reports decayed, has decayed: no closest approach is computed from it, and the results say so. With all 5 weights at 0, Evaluate is refused, since every score would be 0."
    )
    _add_body(doc,
        "In the threat sweep, each entry that arrives has a Decide control. It opens the panel already bound to the "
        "red track, with the blue asset when the target is held as one of yours, a hypothesis from that entry's own "
        "departure burn, and a second row from the latest confirmed burn in the red track's held element-set "
        "history when there is one. Nothing is evaluated for you, and P and Conf are never filled."
    )
    _add_body(doc,
        "A transfer of several burns is carried whole on its row, as one action with one P. The departure burn "
        "fills the row's fields, and the panel lists every burn of the transfer before you press Evaluate, each "
        "with its own UTC time and its prograde, normal and radial parts in m/s. Each later burn's parts are "
        "split in red's own in-track, cross-track and radial frame at its state on the transfer, where the engine "
        "applies it. The engine applies them in time order wherever the row is sampled or our burn is sized "
        "against it. A burn at or before the bound red element set's epoch is never applied, since that set may "
        "already include it: the panel and the results name each such burn, and a row whose every burn is dropped "
        "is not sampled. A later burn over 1,000 m/s is named on the panel, and Evaluate refuses the row."
    )

    _add_heading_h2(doc, "Adversary Actions")
    _add_body(doc,
        "Enter up to five adversary actions. Each row has:"
    )
    _add_data_table(doc,
        ["Field", "Description"],
        [
            ["Name and type", "A label, and Manoeuvre, Sensor Retask, Posture Change or No Action"],
            ["P", "Your assessed chance [0 to 1] that red takes this action; the rows must be mutually "
             "exclusive, so their P sum to at most 1, and expected value weighs each row by its P"],
            ["Conf", "How sure the intelligence behind P is [0 to 1]; it is recorded and moves no figure"],
            ["Custody gap share", "Wherever custody is not read: the share of the horizon [0 to 1] custody is "
             "lost after an unanswered manoeuvre (default 0.7), a rule of thumb. A bound red track's custody "
             "replaces it once read"],
            ["Manoeuvre hypothesis", "Optional: an archetype, delta-V in m/s, direction, spread, samples (100 to "
             "2,000) and burn time in hours from the moment you press Evaluate"],
        ],
    )
    _add_body(doc,
        "P and Conf are yours. As the panel opens, each row shows a NOTSO suggestion: a suggested P and Conf from "
        "the red track's NOTSO history with its basis and an interval on P. It writes nothing: tick it to apply it "
        "at Evaluate, "
        "and it is applied only while it is still the one shown. Gaps in the NOTSO cache are never read as quiet, "
        "and nothing is offered below 3 events."
    )
    _add_body(doc,
        "P is a probability over mutually exclusive actions (SPC-203, evaluation finding F-12). Before, expected "
        "value divided each P by the sum of the rows' P, so one row at P 0.1 was weighed exactly as at P 1, as "
        "certain, and the chance that none of your actions happens was never weighed. Now:"
    )
    _add_bullet(doc, "Your rows' P must sum to at most 1. Evaluate refuses a sum above 1 with a sentence naming the "
                "sum, before anything runs. A new row starts at P 0.5, marked as the panel's default until you edit "
                "it, so three new rows sum to 1.5 and are refused until you set their P.")
    _add_bullet(doc, "A NOTSO suggestion you tick replaces its row's P, so the sum is read with the suggestions "
                "applied; a sum above 1 they make is refused, naming the rows that carry them.")
    _add_bullet(doc, "When your rows' P sum below 1, the engine adds a row of its own, last: No adversary action "
                "(remainder of P), at 1 less the sum of your rows' P. It is evaluated as any no-action row, a lookup "
                "or computed where bound, and minimax, minimin, expected value, the rules side by side, the game "
                "tree and the decision record all read it. It is labelled as the engine's remainder, not your row, "
                "and it has no Conf. A no-action row of your own is one of your actions at the P you gave it, so the "
                "remainder still stands as a row of its own beside it. At a sum of exactly 1 nothing is added.")
    _add_bullet(doc, "Each row shows, beside its P, the share of expected value it takes, which is its P, written "
                "as the P beside it is.")
    _add_bullet(doc, "A NOTSO interval on P is checked only up to where your rows' P reach 1, the remainder taking "
                "up each move. With your rows' P at exactly 1 no remainder row is evaluated, so the interval is not "
                "checked: a lower P would leave a remainder this evaluation holds no cells for. The results say so; "
                "set your rows' P to sum below 1 and the interval is checked.")
    _add_bullet(doc, "On a game tree the remainder is one of red's moves in every turn, so it adds to the tree's "
                "branches and cost: three rows summing below 1 make four red moves. A depth refused for size or "
                "cost says so, and rows whose P sum to 1 make one red move fewer.")
    _add_bullet(doc, "A decision record written by 0.28.0 or 0.29.0 is replayed under the rule it was evaluated by, "
                "each row's P over the rows' sum and no remainder, even where its P sum above 1, and the replay "
                "command says so before it compares anything.")

    _add_heading_h2(doc, "Friendly Responses and Our Burns")
    _add_body(doc,
        "Enter up to five friendly responses, each with a type, a cost and reversibility [0 to 1] and a time to "
        "execute in hours. A manoeuvre response may carry a target separation in km, a delta-V budget in m/s "
        "(50 m/s unless given) and an axis. With both sides bound, the engine sizes our burn to reach the target "
        "within the budget, applies it to the blue asset and shows what the burn buys. A burn that cannot reach "
        "the target within the budget flies the whole budget, and the cell says how far short it falls. A burn "
        "that would come after the closest approach or the span searched, or whose arc fails, is refused in its cell "
        "and its delta-V stays a lookup."
    )

    _add_heading_h2(doc, "Marking a Response Not Permitted")
    _add_body(doc,
        "A response that breaks a legal, rules-of-engagement or safety constraint must never be recommended, however "
        "well it scores (finding F-04, gate G4, SPC-195; the gate's Red rating stands until the evaluation is "
        "repeated). Tick Not permitted on its row and give the reason in the field beside it: the reason is required "
        "when the box is ticked, at most 500 characters on one line. A reason typed without the tick is refused "
        "rather than dropped."
    )
    _add_bullet(doc, "No rule ever picks a response marked not permitted: not the headline, not a pick beside it, "
                "not a turn of the game tree, and not a pick in your decision record. A tie is broken among the "
                "permitted responses alone, so a tie never brings it back.")
    _add_bullet(doc, "It is still evaluated, so you see what was excluded and why. It is greyed, with Not permitted: "
                "and your reason in words, in the matrix heading, in the rankings, where it is listed last with no "
                "rank and is never ranked first, and beside each of its branches in the tree. Every later branch below "
                "it in the tree is greyed too, saying it follows that response.")
    _add_bullet(doc, "If every response is marked not permitted, nothing is recommended: the headline reads No "
                "recommendation and the results say why, on the matrix and on the game tree alike.")
    _add_bullet(doc, "Your record keeps which responses were marked not permitted and why. You may still record one "
                "as your decision, but only with a rationale, and the record says it was marked not permitted. "
                "The stored inputs are version 2 of their document, holding each veto; a record written by "
                "0.28.0, version 1, still reads and replays, with nothing vetoed.")
    _add_bullet(doc, "Each veto is yours, response by response. Constraint libraries drawn from doctrine or rules "
                "of engagement are the owner's to supply later; these choices are Claude's design, awaiting the "
                "owner's ruling.")

    _add_heading_h2(doc, "What Is Refused Rather Than Guessed")
    _add_bullet(doc, "Every row must post each of its fields, and every scoring weight must be given. A missing P, "
                "Conf, Gap, cost, reversibility, time to execute, name or action type is refused, naming the row and "
                "the field, and a blank or missing weight is refused, naming it: none is given a default (SPC-222). "
                "The panel posts every field of every row, so this is met by evaluating from the panel.")
    _add_bullet(doc, "A composite score that is not a finite number is refused before any rule picks on it: the "
                "page says nothing is recommended and that it is a fault in the engine or a figure it was given, "
                "not in your entries; the server log names the cell (SPC-221).")
    _add_bullet(doc, "An element set whose epoch is more than 5 minutes after the time it is checked is refused "
                "wherever a set enters and when it is bound, naming its epoch and how far ahead it is: a set dated "
                "in the future would otherwise read as current. The red card and the sweep say FUTURE EPOCH for any "
                "such set already held (SPC-226). The 5 minutes, for clock skew, is Claude's choice, unsourced.")

    _add_heading_h2(doc, "How the Figures Are Worked Out")
    _add_bullet(doc, "Closest approach, computed: for a red action that does not move red, both orbits are "
                "propagated from their element sets with no burn, searched every 60 s and refined to 0.01 s. "
                "Beside the miss is a band, the miss less and plus both sets' element-set error at the closest "
                "approach in quadrature, 1 sigma, and the score reads its lower edge.")
    _add_bullet(doc, "Closest approach, sampled: for a row with a hypothesis, each sample's burn is drawn and "
                "propagated beside the blue asset, and each sample also draws both objects' element-set error "
                "along track at each set's age at the scenario epoch. The row scores on P5. It is refused, and says why, for fewer "
                "than 50 samples, an out-of-date orbit, a red element set newer than the burn, or a cost over the "
                "cap. The row counts as converged when P5, P50 and P95 are each known to within 1 km, or 5 per "
                "cent of P5 where larger. The basis note gives how closely P5 itself is known, its own half-width, "
                "and names apart the widest of the three, the figure convergence is judged on. It also states the "
                "integrator's own error against a tight reference: by 72 h up to 0.89 km per object in LEO, 0.015 "
                "km at GEO and 0.38 km in a pair's separation, less at shorter horizons. It states the handover "
                "from SGP4, which works on the WGS-72 constants, to RK45, which flies its states with WGS-84's: by "
                "72 h each object moves up to 3.52 km in LEO and 1.43 km at GEO against the same flight on WGS-72, "
                "but a pair's separation at most 0.18 km, since both drift alike (SPC-225).")
    _add_bullet(doc, "Seeds: every sample of a row is drawn on its hypothesis's seed, 42 unless stated, and the "
                "figures you see are that draw's. The row is drawn again on a second seed, 43, and counts as "
                "converged only when both draws are; if they disagree the row is not converged, is not sampled, and "
                "its cells name both seeds (SPC-224). The basis note and a line under the matrix name the seeds. The "
                "second draw doubles a row's sampling time, so each sampled row counts twice against the cap: at "
                "500 samples about 11.8 h fits with no burn to size. A record from 0.41.0 or earlier replays on its "
                "one seed, as it was evaluated. On a game tree this holds for turn 1 alone: turns 2 and 3 draw each "
                "branch's samples on a seed derived from the row's seed, the turn and the branch, and each sequence's "
                "closest approach is judged converged on that one draw, which the tree says beside it.")
    _add_bullet(doc, "A row of several burns is sampled from the first burn it applies, and costed from that "
                "burn. Every later burn is drawn at its own time with the row's pointing, timing and drag spreads, "
                "and a delta-V spread in proportion to its size. A burn due after the span searched ends is flown "
                "by no sample. Each figure's basis names how many of the row's burns it applies.")
    _add_bullet(doc, "A manoeuvre with no hypothesis is refused a closest approach: where red goes if it does not "
                "move is not the outcome of a manoeuvre. Add a hypothesis.")
    _add_bullet(doc, "Time of closest approach carries an uncertainty from both element sets' errors, and is "
                "printed no finer than that uncertainty. A sampled one carries only the errors' growth after the "
                "scenario epoch, since every sample draws the errors at the epoch.")
    _add_bullet(doc, "Custody is read from the bound red track as the sweep reads it and carried over the horizon, "
                "assuming no newer element set arrives. Degraded custody can judge your warning time but not "
                "whether a burn is normal, so the hours it is degraded are shown as degraded, never as held or "
                "lost, and a span under 0.1 h says so rather than 0.0 h. By the owner's ruling of 5 November 2026, "
                "each hour degraded carries 0.25 of the custody penalty an hour lost carries, and the custody gap "
                "counts lost hours only. Like held custody, it is lost once its element set passes its limit or a "
                "burn is newer than it, and a manoeuvre with no burn time takes the worst case. Your response is "
                "not applied to custody. A row of several burns is read at the earliest burn it applies.")
    _add_bullet(doc, "Show trajectory opens the Hill-frame view of a cell's pair, which shows the shape of the "
                "approach, not the cell's figures. A sampled cell also has a histogram of its sampled times.")
    _add_body(doc,
        "A scenario that samples or sizes a burn runs as a job inside a 300 s budget, capped at "
        "12,000 sample-hours, the owner's ruling of 5 November 2026. A game tree has a cap of its own, 21,000 "
        "sample-hours, set from trees timed under load in the build container (SPC-188); it should be measured again "
        "on the machine SPECTRE runs on. The page shows progress and a Cancel button; a stopped evaluation scores "
        "nothing."
    )

    _add_heading_h2(doc, "Collect First and the Sweep's Threat Picture")
    _add_body(doc,
        "When the last sweep in this session was of the bound red track, the results show its Threat range, its "
        "Understanding and decide-by at any age, each in its own sentence, and beside each the picture's age at "
        "evaluation in words, for example \"from the sweep's picture assessed 3 h 10 min before this evaluation\". "
        "The collect-first advice and rows and the expected-value guidance it feeds carry the same age. The session "
        "holds one picture, so a later sweep of another red track replaces it, as does a sweep whose model failed: "
        "sweep the bound red track again to read one. A decide-by that has passed by the evaluation is said again "
        "against the evaluation: when it was, and when the intercept could arrive, counted from the evaluation, not "
        "the sweep. An old picture may no longer hold: weigh its age, or sweep again. The sweep's advice is judged "
        "against the action line, the Threat band at which the owner may set that a response changes, HIGH by "
        "default, tuned, not sourced, and the results say so in a sentence of their own. If the Threat range "
        "straddles the action line and a collection that could narrow it, whose result SPECTRE can read, lands "
        "before decide-by, the sweep would collect first; otherwise it says act on the ceiling. Collections are listed beside the ranking "
        "and never scored, so the recommendation is always one of your own responses."
    )
    _add_body(doc,
        "Decide-by rests on your response time: the hours you need to plan, approve and carry out a response, set on "
        "the sweep form for every target or for one. With none set for a target in reach, the sweep says decide-by "
        "needs one, names the target and shows no time, and no collection can be shown to land before it, so the "
        "advice acts on the ceiling (SPC-211, finding F-23 of the independent evaluation). Until 0.38.0 a 12-hour "
        "default, tuned, not sourced, stood in. A decision record keeps the decide-by the sweep set, so a record "
        "from before replays as it was shown."
    )
    _add_body(doc,
        "The Decision Engine collects first only for a collection whose outcomes give different recommended "
        "responses, and that lands before decide-by (SPC-204, finding F-14 of the independent evaluation). It builds "
        "the matrix again under each of the collection's outcomes, the benign and the hostile, through "
        "the same cell step the evaluation ran, from plans made with no picture in them, and compares the "
        "recommendation under each. Today the outcome matrix reads no Threat band, so the two are always the same, "
        "and in place of collect first the results say, for example: 'Collecting \"pull its element-set history\" "
        "would narrow the Threat range but cannot change the recommended response: the outcome matrix reads no "
        "Threat band.' Do not delay your decision for it. Where the sweep says act on the ceiling, or that the range "
        "is below the action line, and the picture holds a collection, the results add: "
        "'No collection the picture holds can change the recommended response: the outcome matrix reads no Threat "
        "band.' Should a later release let a band move a figure, the advice follows, naming the recommendation under "
        "each outcome."
    )

    _add_heading_h2(doc, "Selector Rules")
    _add_data_table(doc,
        ["Rule", "How it picks", "When to use it"],
        [
            ["Minimax", "The response whose worst case scores least", "The default primary rule and the cautious "
             "rule: use it when P is not well founded"],
            ["Expected value", "The response whose probability-weighted score is least", "When P rests on "
             "evidence; the results say whether the pick holds across a NOTSO interval"],
            ["Minimin", "The response whose best case scores least", "The optimistic rule, not a robust one"],
        ],
    )
    _add_body(doc,
        "This is decision analysis over operator-entered rows, with a worst-case floor (minimax), a best case "
        "(minimin) and expected value, each picking one of your responses. Scores are lower-is-better, so the "
        "floor is a floor on the outcome: its score can be no worse than that. Randomised (mixed) responses are not "
        "considered, so minimax is a guaranteed floor over pure responses, not a game solution: a mix chosen at "
        "random can guarantee only a better expected score, against a red that cannot see the draw, than any one "
        "response, and the engine does not look for one."
    )
    _add_body(doc,
        "Every result shows all three rules' picks side by side, each with its rule's meaning in one line, worked "
        "out on the same scores, and a line saying whether they agree or, where they do not, which picks differ. "
        "For a game tree it also shows each rule's pick for turn 1 over the tree already built. The headline "
        "recommendation is the deployment's primary rule's pick, set by the administrator with "
        "SPECTRE_PRIMARY_RULE before use (minimax unless set; a value naming no rule is logged and read as "
        "minimax). The panel's Selector Strategy starts on the primary rule; if you choose another, the results "
        "name the primary rule and its pick beside your rule's, so no rule chosen after seeing a result can hide "
        "the primary rule's answer. Your decision record keeps the primary rule and whether your rule differed. "
        "This answers finding F-03 of the independent evaluation, gate G3 (all rules' results available, "
        "disagreement flagged); the gate's Red rating stands until the evaluation is repeated."
    )
    _add_bullet(doc, "The evaluation still runs under the rule you chose: the matrix's star and the ranking's blue "
                "highlights mark that rule's pick, and a line above the matrix says so, naming the primary rule's "
                "pick beside it when the two rules differ.")
    _add_bullet(doc, "A tie is shown as a tie (SPC-206, finding F-13 of the independent evaluation). Responses whose "
                "values under a rule lie within 0.0000005 of each other, half the last place every composite score "
                "is kept to, tie: the headline reads Tie: and names each, a line says the rule does not choose "
                "between them and the choice is yours, the star marks each, and every rule's pick names the tie. "
                "Your record still keeps the response with the lowest score, as 0.37.0 did, which need not be "
                "the first entered, so its replay is unchanged.")
    _add_bullet(doc, "With every row at P 0, the remainder of P carries the whole weight, so expected value picks "
                "the best response against no adversary action. Only replaying a record 0.28.0 or 0.29.0 wrote can "
                "find expected value with no weight to pick on: the replay then says it has no pick, never counts it as "
                "agreeing with another rule, and nothing is starred under it.")
    _add_bullet(doc, "When the time budget stopped a game tree before its last turn, the line on each rule's turn-1 "
                "pick names the turns you asked for and the turns built in full.")
    _add_body(doc,
        "Beside the recommendation the results give its weight stability (SPC-205, finding F-16 of the independent "
        "evaluation): the smallest change of one weight, the other four scaled in proportion to keep the sum 1 as "
        "the panel scales them, that changes the pick, and what it makes it, for example 'The recommendation holds "
        "unless a weight moves by at least 0.165: our delta-V's weight from 0.200 to 0.034 makes it manoeuvre "
        "(F0).' Open 'Every weight' (a details element) for each weight lowered and raised, or that no value from 0 "
        "to 1 changes it. It is exact, not sampled: each score is linear in the moved weight, so every point where "
        "the pick can change is found. Each score is rounded to 6 decimal places, as the engine rounds it, and a tie "
        "goes to the response listed first, as the engine breaks it. The change is rounded down, so 'at least' is "
        "never more than it, and the weight's value is rounded away from the panel's, so the pick named is the "
        "engine's there. A response marked not permitted is never the pick it names. If you chose a rule other than "
        "the primary rule, its pick's stability is shown beside it. The game tree's picks are not covered: a line "
        "says so when you asked for more than one turn, and on the record. Your decision record keeps the "
        "recommendation's line in its own column, weight_stability; a record from before reads 'Weight stability: "
        "not recorded'. A small change here means "
        "the recommendation rests on a judgement of the weights as much as on the figures: the weights are not yet "
        "cited (SPC-151)."
    )
    _add_body(doc,
        "Under expected value, a bound row whose Understanding is LOW, or any row whose P you never edited, "
        "carries a line saying expected value rests on a probability the evidence has not earned, and names "
        "minimax's pick. The rule is never switched for you. The form records a P once you change it from the panel's "
        "0.5, and keeps the record if you set it back, so to choose 0.5 deliberately, change P and then set it "
        "to 0.5; leaving 0.5 in place, or typing 0.5 over it, is not recorded. A P from a NOTSO suggestion you "
        "applied counts as edited. Each row says whose P and Conf it holds: a P never edited is the panel's "
        "default."
    )

    _add_heading_h2(doc, "Looking Further Ahead: the Game Tree")
    _add_body(doc,
        "Turn depth, on the panel, sets how many turns the engine looks ahead: 1 is the outcome matrix alone; 2 "
        "or 3 let red move again after each of your responses. A tree needs a red track and a blue asset bound "
        "and current, and an orbit from every row, so give each manoeuvre row a hypothesis."
    )
    _add_bullet(doc, "Once the tree has what it needs, a depth the evaluation cannot fit, by branches (1,000 at "
                "most) or by cost (21,000 sample-hours, the tree's own cap since SPC-188; a record from before is "
                "replayed against the 12,000 it shared with the matrix then), is refused as soon as you press "
                "Evaluate, naming the largest depth that would "
                "fit. The remainder of P counts as one of red's moves, and the refusal says so. A tree missing what it needs still evaluates as one turn, and the results say why.")
    _add_bullet(doc, "The engine sets each turn's length from the rows' burn times, so every burn falls inside "
                "its own turn; you never set a length. Turns are equal where every burn fits; otherwise a turn ends "
                "midway between the last burn it holds and the first burn of the next turn, or, "
                "with no burn after it, midway between that burn and the end of the span searched. "
                "A row carrying several burns of one transfer gives each burn a turn of its own, so it needs at "
                "least as many turns as burns, and the results say so if it has fewer.")
    _add_bullet(doc, "A transfer taken in turn 1 makes its later burns in the turns they fall in, whatever red "
                "does next; taken again in a later turn, it makes each burn the same time after its own turn "
                "starts, and a burn that would fall after the last turn is not made.")
    _add_bullet(doc, "Each later turn starts where the last one left both orbits, after red's burn and yours. "
                "Every figure in a tree is propagated by RK45 for both orbits.")
    _add_bullet(doc, "The results show the recommendation per turn for the rule in use: turn 1's pick, then the "
                "pick for turn 2 after each thing turn 1 may show, and in a 3-turn tree the pick for turn 3 after "
                "what turns 1 and 2 showed.")
    _add_bullet(doc, "The tree itself is a set of collapsible branches. Each names its turn, red's move and your "
                "response, and the path of moves it rests on; opened, it shows its figures in m/s and km, each "
                "with its basis. A branch on the recommended plan says so in words. Under a response the rule "
                "does not pick, its best continuation says so in words of its own, in italic and with no star, "
                "for example 'Best continuation under minimax after Avoid in turn 1, which minimax does not pick "
                "there; not on the plan' (SPC-189). Responses that tie in a turn are each named, and the plan "
                "follows each.")
    _add_bullet(doc, "Above the branches the tree is drawn (SPC-190): a box for each branch, from turn 1 on the left "
                "to the last turn on the right, naming red's move and your response with the branch's sequence "
                "score and closest approach along it, each with its basis, the same figures the branch below shows. "
                "A box on the plan, a best continuation and a branch not permitted each say so in words. Each box "
                "with branches after it has a button that collapses or opens them, and Zoom in, Zoom out and Reset "
                "buttons sit beside the drawing; each works from the keyboard with Tab, Enter and Space. Without "
                "script the drawing shows in full and its buttons are hidden. The branches below stay the text "
                "version of the drawing.")
    _add_bullet(doc, "Beside the tree two notes say what its figures assume: each branch of the last turn shown, the "
                "deepest built in full, is valued as if no one moves after it (SPC-220), and the score's terms are "
                "added with nothing joining them (SPC-219).")
    _add_bullet(doc, "A tree that runs out of budget shows the deepest turn built in full and says so.")
    _add_body(doc,
        "What turn 1 shows of red is read through the red track's custody: lost at a burn shows a burn, held "
        "shows no burn, anything else, degraded included, shows nothing. You may state what turn 1 showed. Under expected value the "
        "results then show the update after turn 1 for that observation, with its likelihood model; with none "
        "stated they say nothing was updated. The update moves no figure and writes no P. One turn has no later "
        "pick to update, so an observation stated with a depth of 1 is refused beside the form. Minimax and "
        "minimin do not use probability: in place of the update the results show 'What each turn lets us see', "
        "the same custody rule that sets what each later pick may depend on, and say nothing was updated."
    )
    _add_body(doc,
        "The update's likelihood is uncalibrated (SPC-210, finding F-22 of the independent evaluation). It treats "
        "what custody shows as certain, and no held history of what red did has been scored against it, so there "
        "is no calibration data yet. Wherever the update's share of the weight is shown, the likelihood model's line "
        "and the update's basis both say so. A calibration harness exists for when held histories are supplied: "
        "scripts/calibrate_likelihood.py reads a UTF-8 comma-separated file with the header "
        "history,predicted,observed (an identifier, the probability from 0 to 1 the update gave the outcome, and 1 "
        "or 0 for whether it came about) and reports the Brier score, a reliability table by bin and the sample "
        "count. It names the file by the SHA-256 of its bytes, and the code by SPECTRE's version and the SHA-256 "
        "of the scoring module and of the command, each covering that one file only. The score measures the "
        "probabilities in the file: it says something about the update's likelihood only if the update produced "
        "them for real held outcomes, which the harness cannot check. Until it has been run on such histories, read "
        "the update's shares as the custody rule's arithmetic, not as a calibrated probability."
    )

    _add_heading_h2(doc, "Recording Your Decision")
    _add_body(doc,
        "SPECTRE keeps one record for each finished evaluation, whether it was answered at once or ran as a job. "
        "This is the record half of gate G1 in the independent evaluation (finding F-01); the advisory half and "
        "the gate's Red rating were not reassessed. The record holds when it finished, in UTC, your username, the "
        "scenario's name, the rule you used and the one-turn matrix's pick under it, the picks of all "
        "three rules (minimax, minimin and expected value) on the same figures, the code version and a hash of "
        "every input, the turn depth and the keep-out distance, the deployment's primary rule and whether your "
        "rule differed. Since 0.28.0 it also holds the evaluation's inputs in full (finding F-02, gate G2, SPC-193; "
        "the gate's Red rating stands until the evaluation is repeated): the whole "
        "scenario, each bound element set's text with its epoch, age, limit, data mode and custody, every "
        "hypothesis with its seed, any NOTSO suggestion applied and the Threat picture, with the rule and every "
        "composite score, as one document with its SHA-256. An administrator can replay a record with "
        "scripts/replay_decision.py and the record's number: it evaluates the stored scenario again under the "
        "stored rule and reports whether the recommendation, every rule's pick and every score match exactly. "
        "It also sets the record's own rule, code version and input hashes against the stored inputs, so an "
        "edit to them shows even when their SHA-256 was worked out again. Before replaying it says which code "
        "version wrote the inputs, when that is another code version than the one running, and when the "
        "evaluation ran out of "
        "its time budget, since the replay runs in full and what the budget left out may differ. It opens the "
        "database to read only and writes nothing. A record written before 0.28.0 "
        "holds no element-set text and no raw input, so it cannot be replayed. An evaluation that is refused, "
        "cancelled, replaced, ended by sign-out or that fails before its sampling finished writes no record."
    )
    _add_bullet(doc, "The results end with Your decision: choose one of the scenario's own responses, None of "
                "these, or Decision deferred, and give a rationale of at most 2,000 characters. The rationale is "
                "required for None of these and for a response marked not permitted, and may not hold a control "
                "character other than a tab or a line break. Record decision stores it with its own UTC time.")
    _add_bullet(doc, "A record takes one decision, once: a second is refused with a sentence. Only the operator who "
                "ran the evaluation may decide it; an admin reads every record but decides only their own.")
    _add_bullet(doc, "Once a job has finished sampling it writes its record before the results show, and Cancel no "
                "longer stops it. A record can still describe results never shown: you reloaded or closed the "
                "console while the job ran, or a newer evaluation or a sign-out came while the record was written. "
                "Decide it on the Decision records page. If the record cannot be written the results say so, and "
                "no decision can be recorded against them.")
    _add_bullet(doc, "Decision records, linked from the top of the panel, opens in a new tab and lists your own "
                "records newest first: when, the scenario, the rule you used and its pick, the primary rule and its "
                "pick, which was the recommendation shown, all three rules' picks, "
                "and your decision, rationale and its time, or No decision recorded with the form to record it. "
                "An admin sees every record and whose it is. Records are kept by account, so they are there after "
                "you sign out and in again.")
    _add_bullet(doc, "For a game tree the record names the one-turn matrix pick and the tree's own pick for turn 1, "
                "which can differ, with the tree's recommendation lines. The page names the primary rule and its "
                "pick, "
                "says whether the rule you used differed, and repeats the warning when expected value rests on a "
                "probability not earned. A record written before 0.28.0 says the results showed only the rule used.")
    _add_bullet(doc, "A name holding the NUL control character, which PostgreSQL cannot store, is recorded with the "
                "replacement character in its place.")
    _add_bullet(doc, "No retention is applied: records stay until the owner decides otherwise. A record holds a "
                "username, free text and the evaluation's stored inputs, element sets included, so "
                "retention and access are the owner's decision, as data protection lead; the open ruling "
                "(SPC-228) covers the stored inputs too.")
    _add_bullet(doc, "Claude's design choice, awaiting the owner's ruling: a deleted account's records are kept, "
                "and the page has no pagination.")

    _add_heading_h2(doc, "What It Does Not Do")
    _add_bullet(doc, "It does not cite its scoring weights yet (SPC-151); the score is a weighted heuristic.")
    _add_bullet(doc, "It holds no constraint library: a response is marked not permitted only when you tick it.")
    _add_bullet(doc, "It draws element-set error along track only, from a rule of thumb, tuned, not sourced; "
                "error across track is not in any band.")
    _add_bullet(doc, "It does not model J3 and J4, the Moon, the Sun or solar radiation pressure: they move each "
                "object up to 24 km at GEO by 72 h. Two objects of the same area-to-mass ratio move largely alike, "
                "but when they differ the separation moves too, by up to 2.4 km at GEO (SPC-209, finding F-19 of "
                "the independent evaluation). Set against the spread a row samples, they exceed the sampled spread "
                "with no burn, and can with a burn of 0.1 m/s in LEO and at GEO; they are under a tenth of it from "
                "1 m/s outside LEO and from 10 m/s in LEO. Each sampled closest approach's basis note says so for "
                "red's regime.")
    _add_bullet(doc, "It does not model a sensor's line of sight to red.")
    _add_bullet(doc, "It does not model how red's first move bears on its next: red's later moves are weighed by "
                "P as entered.")
    _add_bullet(doc, "It adds custody lost and closest approach to the score as separate terms, with nothing joining "
                "them, so losing custody does not make a close approach count for more (SPC-219, finding F-20 of "
                "the independent evaluation). No source for a term joining them was found; the matrix and the game "
                "tree say so.")
    _add_bullet(doc, "Its game tree looks at most 3 turns ahead, and each branch of the last turn is valued as if no "
                "one moves after it, to the end of the span searched: a move red or you would make later is in no "
                "figure (SPC-220, finding F-21 of the independent evaluation). The tree says so beside it.")
    _add_bullet(doc, "Its game tree models one impulsive burn per adversary row per turn, so a row carrying several "
                "burns of one transfer is evaluated as one turn.")
    _add_bullet(doc, "It does not guess burns a sweep solution does not list: a V-bar or H-bar hop solution lists only "
                "its entry and final burns, so its row carries the entry burn alone, and the panel says so.")
    _add_callout(doc,
        "The Decision Engine output is a recommendation, not an order. Operators retain full authority over "
        "response selection. It shows its working so you can challenge it; context, rules of engagement and "
        "commander intent always take precedence."
    )


def _section_14_training(doc: Document) -> None:
    """Section 14: Training Environment."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 14")
    _add_heading_h1(doc, "Training Environment")

    _add_body(doc,
        "SPECTRE includes a fully sandboxed Training Environment that allows operators "
        "to develop and maintain proficiency without touching operational data. The "
        "training mode uses synthetic TLEs and scenario parameters entirely; no "
        "real satellite tracking data is used or accessible within a training session."
    )
    _add_body(doc,
        "Access the Training Environment by clicking the Training button (shown as "
        "a lightning bolt icon) in the navigation bar. Training sessions are isolated "
        "from the main operational workspace — any assets, results, or UDL data from "
        "the operational session remain unaffected."
    )

    _add_heading_h2(doc, "Level-Based Progression")
    _add_body(doc,
        "Operators progress through five levels, each unlocking more complex scenarios "
        "and analysis tools. Advancement requires accumulating points on the relevant "
        "skill axes and meeting specific unlock conditions:"
    )
    _add_data_table(doc,
        ["Level", "Title", "Unlock Condition", "Focus Area"],
        [
            ["1", "Observer", "Default — available on first login", "Basic TLE handling, orbital events, Lambert transfers"],
            ["2", "Analyst", "Complete the introductory tutorial", "Threat assessment, manoeuvre classification, PoL basics"],
            ["3", "Planner", "100+ points in manoeuvre_planning axis", "Tactical manoeuvres, COLA, evasion, trade-space analysis"],
            ["4", "Commander", "5 scenarios completed and at least 50 decision_quality points", "Decision Engine, multi-threat scenarios, formation defence"],
            ["5", "Strategist", "3 challenge scenarios completed", "Full capability — all methods, gauntlet challenges, adversary modelling"],
        ],
    )

    _add_heading_h2(doc, "Skill Axes")
    _add_body(doc,
        "Points earned in training are distributed across skill axes, providing a "
        "multi-dimensional view of operator proficiency:"
    )
    _add_data_table(doc,
        ["Skill Axis", "Description"],
        [
            ["manoeuvre_planning", "Accuracy and efficiency of orbital transfer and manoeuvre solutions"],
            ["threat_assessment", "Quality of threat identification, classification, and prioritisation"],
            ["decision_quality", "Soundness of response selection in decision-engine scenarios"],
            ["situational_awareness", "Speed and accuracy of orbital event detection and conjunction analysis"],
            ["system_proficiency", "Breadth of SPECTRE features used correctly across a session"],
        ],
    )

    _add_heading_h2(doc, "Scenario Types")
    _add_body(doc,
        "Three scenario types are available, each testing a different operational "
        "skill set:"
    )
    _add_bullet(doc,
        "Analyst scenarios — present a threat object and a TLE history; the operator "
        "must correctly classify the manoeuvre type, estimate the ΔV, and assess "
        "intent. These scenarios develop threat_assessment and situational_awareness."
    )
    _add_bullet(doc,
        "Planner scenarios — provide a blue asset and a threat object; the operator "
        "must select the optimal manoeuvre method and parameterise it correctly to "
        "meet mission objectives within a fuel budget. These develop manoeuvre_planning."
    )
    _add_bullet(doc,
        "Challenge scenarios (Gauntlet) — multi-stage scenarios that combine threat "
        "assessment, manoeuvre planning, and decision support. All tools are available; "
        "points are awarded for optimal solutions across each stage. Gauntlets are only "
        "accessible at Level 5."
    )

    _add_heading_h2(doc, "Points System")
    _add_body(doc,
        "Points are awarded per completed objective within a scenario. Objectives "
        "have a base point value and may include a speed multiplier — completing the "
        "objective in under half the allotted time doubles the point award. Axis "
        "weights determine how base points are distributed across skill axes:"
    )
    _add_bullet(doc, "Correct manoeuvre method selection — base 50 pts, 80% manoeuvre_planning, 20% system_proficiency.")
    _add_bullet(doc, "ΔV within 5% of optimal — base 100 pts with speed multiplier, 100% manoeuvre_planning.")
    _add_bullet(doc, "Correct threat classification — base 75 pts, 80% threat_assessment, 20% situational_awareness.")
    _add_bullet(doc, "Decision Engine response selection matching recommended COA: base 100 pts, 100% decision_quality.")
    _add_callout(doc,
        "Tutorial completion is a prerequisite for Level 2 unlock. The introductory "
        "tutorial walks through adding assets, fetching TLEs from the synthetic UDL "
        "endpoint, running a Lambert intercept, and reading the burn table. It takes "
        "approximately 10 minutes and can be re-run at any time from the Training menu."
    )


def _section_15_notso_correlation(doc: Document) -> None:
    """Section 15: NOTSO Correlation."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 15")
    _add_heading_h1(doc, "NOTSO Correlation")

    _add_body(doc,
        "NOTSO (Notice to Space Operators) messages are formal notifications issued "
        "by spacecraft operators to USSPACECOM prior to planned manoeuvres, proximity "
        "operations, launches, or deorbits. SPECTRE's NOTSO Correlation engine parses "
        "these free-text messages, temporally correlates them with manoeuvres detected "
        "by the Pattern of Life engine, and builds operator behavioural profiles that "
        "inform intent assessment."
    )
    _add_body(doc,
        "The correlation analysis answers a fundamental intelligence question: does "
        "this operator file NOTSOs before manoeuvring? If so, how reliably and how "
        "far in advance? Operators who consistently file precise NOTSOs exhibit "
        "predictable, transparent behaviour; those who never file NOTSOs for detected "
        "manoeuvres are classified as stealth operators — a significant intelligence indicator."
    )

    _add_heading_h2(doc, "Parsing NOTSO Messages")
    _add_body(doc,
        "NOTSO data may be sourced from the UDL notification endpoint (if available "
        "for the operator's account) or pasted directly into the NOTSO panel as free "
        "text. Both paths produce structured NOTSO records. The parser handles the "
        "standard USSPACECOM template format (field: value line structure) and "
        "reasonable variants, extracting:"
    )
    _add_bullet(doc, "Message ID and issuing entity.")
    _add_bullet(doc, "NORAD catalogue number (from SATNO, NORAD ID, or COSPAR fields).")
    _add_bullet(doc, "Effective window: start and end UTC datetime (defaulting to a 24-hour window if end is not specified).")
    _add_bullet(doc, "NOTSO type: MANOEUVRE, DEORBIT, LAUNCH, PROXIMITY_OPS, TEST, or OTHER (inferred from free text).")
    _add_bullet(doc, "Predicted ΔV magnitude (m/s) if stated in the message.")
    _add_bullet(doc, "Predicted burn direction if stated.")

    _add_heading_h2(doc, "Correlation Logic")
    _add_body(doc,
        "Each NOTSO is matched against PoL-detected manoeuvres for the same NORAD ID "
        "using a configurable tolerance window (default 24 hours):"
    )
    _add_bullet(doc,
        "Matched — the manoeuvre epoch falls within [NOTSO effective_start − tolerance, "
        "NOTSO effective_end + tolerance]. If multiple manoeuvres qualify, the one "
        "closest to the NOTSO window midpoint is selected."
    )
    _add_bullet(doc,
        "NOTSO-only (phantom) — a NOTSO was filed but no corresponding manoeuvre was "
        "detected in the TLE analysis. May indicate a cancelled manoeuvre, a manoeuvre "
        "below the ΔV detection threshold, or a false notification."
    )
    _add_bullet(doc,
        "Manoeuvre-only (silent) — a manoeuvre was detected but no NOTSO was filed. "
        "This is the most intelligence-significant outcome: the operator executed a "
        "manoeuvre without notification."
    )
    _add_data_table(doc,
        ["Metric", "Description"],
        [
            ["Time offset (h)", "NOTSO effective_start minus manoeuvre epoch — positive = NOTSO led the manoeuvre"],
            ["Magnitude ratio", "Predicted ΔV from NOTSO divided by detected ΔV — close to 1.0 indicates accurate prediction"],
            ["Window accuracy", "Fraction of matched manoeuvres that fell inside the NOTSO window (not just the tolerance band)"],
        ],
    )

    _add_heading_h2(doc, "Operator Behaviour Profiles")
    _add_body(doc,
        "The correlation results are aggregated into an OperatorBehaviourProfile for "
        "each analysed NORAD ID. The profile captures notification reliability, timing "
        "patterns, and predictability:"
    )
    _add_data_table(doc,
        ["Profile Field", "Description"],
        [
            ["Notification rate", "Fraction of detected manoeuvres with a corresponding NOTSO [0–1]"],
            ["Mean lead time (h)", "Average hours between NOTSO effective_start and detected manoeuvre epoch"],
            ["Lead time std (h)", "Standard deviation of lead time — measures timing consistency"],
            ["Phantom NOTSO count", "NOTSOs filed with no detected manoeuvre — may indicate deception"],
            ["consistent_notifier", "Flag: notification rate > 90%"],
            ["stealth_operator", "Flag: notification rate < 30% — significant intelligence indicator"],
            ["predictable_timing", "Flag: lead time standard deviation < 6 hours — highly regular behaviour"],
        ],
    )
    _add_callout(doc,
        "A stealth_operator classification (rate < 30%) combined with an increasing "
        "intent score from the Intent Predictor is a high-confidence composite indicator "
        "of adversarial activity. Escalate immediately to command for all-source "
        "intelligence corroboration. Never rely on NOTSO behaviour alone as a basis "
        "for operational response."
    )


def _section_16_photometry(doc: Document) -> None:
    """Section 16: Photometry Analysis."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 16")
    _add_heading_h1(doc, "Photometry Analysis")

    _add_body(doc,
        "SPECTRE's Photometry Analysis module detects anomalous brightness changes "
        "in space objects from ground-based optical observations. Brightness "
        "anomalies may indicate attitude changes, panel deployments, physical damage, "
        "or reflectivity alterations — all of which can be correlated with manoeuvres "
        "detected by the Pattern of Life engine to provide a richer characterisation "
        "of object behaviour."
    )
    _add_body(doc,
        "The pipeline accepts CSV-format light-curve data, applies geometric and "
        "atmospheric corrections, fits a solar-phase-angle baseline using iterative "
        "sigma-clipping, and compares a recent observation window against the baseline "
        "using a two-sample Welch's t-test. All computations are performed in pure "
        "Python with no external scientific library dependency."
    )

    _add_heading_h2(doc, "Data Ingestion")
    _add_body(doc,
        "Photometric observations are provided as a CSV file with the following "
        "column structure:"
    )
    _add_data_table(doc,
        ["Column", "Required?", "Description"],
        [
            ["epoch_utc", "Yes", "ISO 8601 observation timestamp (UTC)"],
            ["apparent_magnitude", "Yes", "Observed brightness in magnitudes"],
            ["uncertainty", "No (default 0.05)", "1-sigma magnitude measurement uncertainty"],
            ["filter_band", "No (default 'unfiltered')", "Photometric filter (V, R, unfiltered, etc.)"],
            ["range_km", "No (default 1000)", "Observer–object distance for range normalisation"],
            ["solar_phase_angle_deg", "No (default 45°)", "Sun–object–observer angle for phase correction"],
            ["elevation_deg", "No (default 45°)", "Object elevation above horizon for airmass correction"],
            ["lunar_phase_fraction", "No (default 0.0)", "Lunar illumination [0=new, 1=full] for quality flagging"],
            ["lunar_separation_deg", "No (default 90°)", "Angular separation from Moon for quality flagging"],
        ],
    )

    _add_heading_h2(doc, "Geometric Corrections")
    _add_body(doc,
        "Before baseline fitting, each observation is corrected for two geometric "
        "effects that would otherwise mask intrinsic brightness changes:"
    )
    _add_bullet(doc,
        "Range normalisation — apparent magnitude is reduced to a standard range "
        "(default 1,000 km) using: reduced_mag = apparent_mag − 5·log10(range/ref_range)."
    )
    _add_bullet(doc,
        "Atmospheric extinction — Rozenberg (1966) airmass is used below 10° elevation "
        "for accuracy; the correction is relative to zenith: Δmag = k·(airmass − 1)."
    )
    _add_bullet(doc,
        "Quality flagging — observations near the lunar limb (separation < 20° or "
        "phase > 0.8) are flagged 'lunar'; low-elevation observations (< 15°) are "
        "flagged 'low_elevation'; both together produce 'reject' flags."
    )

    _add_heading_h2(doc, "Baseline Fitting & Change Detection")
    _add_body(doc,
        "The analysis fits a quadratic solar-phase-angle model "
        "(mag = a₀ + a₁·phase + a₂·phase²) to the corrected observations using "
        "iterative 3σ sigma-clipping. This establishes the object's nominal brightness "
        "as a function of viewing geometry. The baseline is then used to compute "
        "per-epoch residuals."
    )
    _add_body(doc,
        "Change detection compares residuals from the recent window (default last 30 days) "
        "against residuals from the historical baseline window (default 30–120 days ago). "
        "A Welch two-sample t-test determines statistical significance:"
    )
    _add_data_table(doc,
        ["Output Field", "Description"],
        [
            ["baseline_mean / baseline_std", "Mean and std of residuals in the historical baseline window"],
            ["recent_mean / recent_std", "Mean and std of residuals in the recent window"],
            ["magnitude_change (Δmag)", "recent_mean − baseline_mean; positive = object is fainter"],
            ["change_direction", "'brightening' (Δmag < 0), 'fading' (Δmag > 0), or 'none'"],
            ["significant_at_95 / significant_at_99", "Whether the change is statistically significant at 95% / 99% confidence"],
            ["p_value", "Two-tailed p-value from the Welch t-test"],
            ["estimated_change_epoch", "First epoch where the residual exceeded 2σ of the baseline scatter"],
            ["confidence", "Composite confidence score [0–1] based on p-value and sample sizes"],
        ],
    )

    _add_heading_h2(doc, "Manoeuvre Correlation & Interpretation")
    _add_body(doc,
        "If a statistically significant brightness change is detected, SPECTRE "
        "automatically searches for PoL-detected manoeuvres within ±48 hours of the "
        "estimated change epoch. Any correlated manoeuvre epochs are reported in the "
        "assessment output."
    )
    _add_bullet(doc,
        "Brightening correlated with a manoeuvre may indicate panel deployment, "
        "attitude reorientation to a more reflective aspect, or removal of a "
        "protective cover."
    )
    _add_bullet(doc,
        "Fading correlated with a manoeuvre may indicate panel loss or damage, "
        "attitude change to a less reflective aspect, or insertion into shadow."
    )
    _add_bullet(doc,
        "Brightness change without a correlated manoeuvre may indicate a passive "
        "attitude evolution, tumbling onset, or environmental damage not yet "
        "large enough to produce a detectable TLE change."
    )
    _add_callout(doc,
        "Photometry is a complementary intelligence layer. A confident brightening "
        "detection (p < 0.01) that correlates with a NOTSO-silent manoeuvre (stealth "
        "operator profile) and an elevated Intent Predict score represents a high-"
        "confidence composite indicator of adversarial activity. Treat each layer as "
        "corroborating evidence, not proof in isolation."
    )


def _section_17_scenarios(doc: Document) -> None:
    """Section 17: Operator Scenarios."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 17")
    _add_heading_h1(doc, "Operator Scenarios")

    # Scenario 1.
    _add_heading_h2(doc, "Scenario 1: Quick-Look Conjunction Assessment")
    _add_body(doc, "Objective: Rapidly assess whether a conjunction event requires a manoeuvre.")
    _add_bullet(doc, "Add the blue asset by NORAD ID (e.g., 25544 for ISS).")
    _add_bullet(doc, "Add the red track by NORAD ID.")
    _add_bullet(doc, "Set the scenario window to cover the predicted conjunction epoch \u00B1 12 hours.")
    _add_bullet(doc, "Run Orbital Events to identify the closest approach geometry.")
    _add_bullet(doc, "Run a Lambert intercept at the conjunction epoch to determine the ΔV required for a collision avoidance manoeuvre.")
    _add_bullet(doc, "If ΔV is below about 10 m/s the adjustment is within routine station-keeping. Above about 100 m/s it is an aggressive profile: consider alternative timing.")

    # Scenario 2.
    _add_heading_h2(doc, "Scenario 2: Defensive Repositioning of Blue Asset")
    _add_body(doc, "Objective: Move a blue asset to a safer orbit to avoid a persistent threat.")
    _add_bullet(doc, "Add the blue asset and identify its current orbital elements from the TLE.")
    _add_bullet(doc, "Determine the desired target altitude (e.g., raise by 50 km).")
    _add_bullet(doc, "Run a Hohmann transfer to compute the two-burn sequence for the altitude change.")
    _add_bullet(doc, "Review the burn table: verify the total ΔV is within the satellite's remaining fuel budget.")
    _add_bullet(doc, "Note the transfer time — if too long, consider a Lambert solution with a shorter time of flight.")

    # Scenario 3.
    _add_heading_h2(doc, "Scenario 3: Multi-Method Intercept Comparison")
    _add_body(doc, "Objective: Compare Lambert, Hohmann, and bi-elliptic solutions for the same target pair.")
    _add_bullet(doc, "Add one blue asset and one red track.")
    _add_bullet(doc, "Run Lambert with 6-hour time of flight.")
    _add_bullet(doc, "Run Hohmann for the same satellite pair.")
    _add_bullet(doc, "Run Bi-elliptic for the same pair.")
    _add_bullet(doc, "The trade-space chart appears after the second run. Compare all three points.")
    _add_bullet(doc, "Select the solution on the Pareto front that best balances ΔV and transfer time for your operational constraints.")

    # Scenario 4.
    _add_heading_h2(doc, "Scenario 4: Historical TLE Epoch Analysis")
    _add_body(doc, "Objective: Analyse how intercept costs change with different TLE epochs.")
    _add_bullet(doc, "Add the red track using the most recent TLE from UDL.")
    _add_bullet(doc, "Run a Lambert intercept and note the ΔV and miss distance.")
    _add_bullet(doc, "Remove the red track and re-add with an older TLE (e.g., from a previous day).")
    _add_bullet(doc, "Run the same Lambert intercept and compare results.")
    _add_bullet(doc, "Larger miss distances with older TLEs indicate orbital prediction degradation. Use this to assess TLE freshness requirements for your mission.")

    # Scenario 5.
    _add_heading_h2(doc, "Scenario 5: Full Mission Planning Workflow")
    _add_body(doc, "Objective: Plan a complete intercept mission from initial assessment through solution selection.")
    _add_bullet(doc, "Log in and connect to UDL.")
    _add_bullet(doc, "Set the scenario window to the mission planning period.")
    _add_bullet(doc, "Add all relevant blue assets and red tracks.")
    _add_bullet(doc, "Run Orbital Events for each red/blue pair to identify manoeuvre windows.")
    _add_bullet(doc, "For each promising window, run Lambert, Hohmann, and Bi-elliptic solutions.")
    _add_bullet(doc, "Use the trade-space plot to identify the optimal solution.")
    _add_bullet(doc, "Record the selected burn table (epoch, ΔV components) for uplink to the spacecraft.")
    _add_bullet(doc, "Clear history and repeat for the next target pair if required.")

    # Scenario 6.
    _add_heading_h2(doc, "Scenario 6: CW Defensive Spacing")
    _add_body(doc, "Objective: Create a safe standoff distance from a threat using CW proximity manoeuvres.")
    _add_bullet(doc, "Add the blue asset and the red track (both in similar orbits).")
    _add_bullet(doc, "Select CW Radial Separation with a target distance of 5 km and a time of 30 minutes.")
    _add_bullet(doc, "Review the single-impulse ΔV — typically metres per second for short-range proximity operations.")
    _add_bullet(doc, "If along-track displacement is also needed, switch to CW Along-Track Drift and specify the desired drift distance.")
    _add_bullet(doc, "Compare both CW solutions in the trade-space plot — radial manoeuvres are faster but oscillatory; along-track drift is secular (growing).")

    # Scenario 7.
    _add_heading_h2(doc, "Scenario 7: COLA Conjunction Response")
    _add_body(doc, "Objective: Respond to a predicted conjunction by computing the cheapest avoidance manoeuvre.")
    _add_bullet(doc, "Add the blue asset and the red threat object.")
    _add_bullet(doc, "Run Orbital Events to confirm the conjunction geometry and timing.")
    _add_bullet(doc, "Select COLA and set the required miss distance (e.g., 5 km).")
    _add_bullet(doc, "SPECTRE evaluates all three strategies (radial, in-track, out-of-plane) and recommends the cheapest.")
    _add_bullet(doc, "Review the result notes to see all three strategy costs and the selected option.")
    _add_bullet(doc, "If time permits (> 1 hour to conjunction), the in-track burn is usually cheapest. For urgent conjunctions, radial or cross-track may be the only option.")

    # Scenario 8.
    _add_heading_h2(doc, "Scenario 8: GEO Longitude Relocation")
    _add_body(doc, "Objective: Relocate a GEO satellite 15° eastward over 15 days.")
    _add_bullet(doc, "Add the GEO satellite as a blue asset.")
    _add_bullet(doc, "Add a reference satellite at the target longitude as a red track (or use a GEO satellite already at the desired slot).")
    _add_bullet(doc, "Select GEO Drift and set coast hours to represent the desired drift duration in days.")
    _add_bullet(doc, "Review the two-burn solution: enter drift orbit (small prograde burn) and stop at target longitude (symmetric retrograde burn).")
    _add_bullet(doc, "Verify total ΔV is within the satellite's remaining fuel budget — typical GEO relocations cost only a few m/s.")

    # Scenario 9.
    _add_heading_h2(doc, "Scenario 9: Threat Behaviour Analysis")
    _add_body(doc, "Objective: Classify an observed manoeuvre by an adversary satellite.")
    _add_bullet(doc, "Obtain two TLEs for the same satellite at different epochs (before and after suspected manoeuvre).")
    _add_bullet(doc, "Add the earlier TLE as a red track and the later TLE as a blue asset.")
    _add_bullet(doc, "Select Manoeuvre Detect — SPECTRE compares the orbital elements and classifies the manoeuvre.")
    _add_bullet(doc, "Review: manoeuvre type (altitude change, plane change, phasing, etc.), estimated ΔV, burn direction, and confidence level.")
    _add_bullet(doc, "Use the classification to assess intent — altitude changes suggest repositioning, plane changes suggest target tracking.")

    # Scenario 10.
    _add_heading_h2(doc, "Scenario 10: Adversary Intent Assessment with Formation Defence")
    _add_body(doc, "Objective: Assess adversary intent toward a blue formation and compute a coordinated defensive response.")
    _add_bullet(doc, "Add all formation members as blue assets and the suspected adversary as a red track.")
    _add_bullet(doc, "Run Intent Predict to score the adversary's intercept intent against each formation member.")
    _add_bullet(doc, "Run Intercept Envelope to determine which formation members fall within the adversary's reachable set.")
    _add_bullet(doc, "Run Stability Analysis on the adversary-to-nearest-blue pair to assess whether the adversary is actively station-keeping relative to the formation.")
    _add_bullet(doc, "Run Fingerprint on the adversary's recent TLE history to classify its behavioural profile.")
    _add_bullet(doc, "If intent score exceeds 50, run Formation Defence to compute a coordinated COLA manoeuvre that preserves formation spacing.")
    _add_bullet(doc, "Review the Orbital Terrain map to identify safe retreat orbits with low debris and congestion risk.")
    _add_bullet(doc, "If immediate response is required, run Min-Time Intercept to find the fastest achievable defensive repositioning within the fuel budget.")


def _section_18_glossary(doc: Document) -> None:
    """Section 18: Glossary of Terms."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 18")
    _add_heading_h1(doc, "Glossary of Terms")

    terms = [
        ["Apogee", "The point in an orbit furthest from the central body."],
        ["Bi-elliptic Transfer", "A three-burn orbital transfer using two intermediate ellipses."],
        ["COLA", "Collision Avoidance — minimum-ΔV manoeuvre to avoid a predicted conjunction."],
        ["Conjunction", "A close approach between two space objects."],
        ["Coast", "A ballistic (unpowered) phase between manoeuvres."],
        ["CW Equations", "Clohessy-Wiltshire (Hill) equations for linearised relative motion near a circular orbit."],
        ["ΔV (Delta-V)", "Change in velocity; the fundamental currency of orbital manoeuvres."],
        ["Detectability", "The likelihood that a manoeuvre will be observed by space surveillance networks."],
        ["Drift Orbit", "An orbit with a slightly different SMA than GEO, causing east-west longitude drift."],
        ["Fingerprinting", "Behavioural classification of a satellite's manoeuvre history against canonical operational profiles."],
        ["Formation Defence", "Collision avoidance manoeuvre planning that maintains minimum inter-satellite spacing within a formation."],
        ["Epoch", "A specific point in time, usually UTC."],
        ["Evasion", "A defensive manoeuvre to avoid an incoming threat while respecting fuel constraints."],
        ["GEO", "Geostationary Earth Orbit — circular orbit at 42,164 km radius with 24-hour period."],
        ["Graveyard Orbit", "Disposal orbit 300 km above GEO for end-of-life satellites."],
        ["Hohmann Transfer", "A minimum-energy two-burn transfer between coplanar circular orbits."],
        ["Impulse", "An instantaneous change in velocity (idealised thruster firing)."],
        ["Intent Assessment", "Scoring of adversary intercept intent by correlating observed behaviour with attack profiles and geometric opportunity."],
        ["Intercept Envelope", "The probabilistic reachability volume of a satellite within a given ΔV budget and time horizon."],
        ["J2", "The dominant zonal harmonic of Earth's gravitational field, caused by equatorial bulge."],
        ["J2 Drift", "Exploitation of J2-induced RAAN precession for fuel-free orbital plane alignment."],
        ["Lambert Problem", "The two-point boundary-value problem: find the orbit connecting two positions in a given time."],
        ["Manoeuvre Classification", "Estimating the type and magnitude of a manoeuvre from observed orbital element changes."],
        ["Min-Time Intercept", "The shortest time-of-flight intercept achievable within a given ΔV budget, found by binary search on TOF."],
        ["Miss Distance", "The closest approach distance between two objects at the intercept epoch."],
        ["NMC", "Natural Motion Circumnavigation — passive relative orbit for inspection/proximity operations."],
        ["NORAD ID", "Five-digit catalogue number assigned to each tracked space object."],
        ["Orbital Terrain", "Altitude-vs-inclination risk map combining debris density, congestion, and radiation environment."],
        ["Passive Safety", "Property of a relative orbit where natural motion prevents collision if propulsion fails."],
        ["Perigee", "The point in an orbit closest to the central body."],
        ["Phasing Orbit", "A temporary orbit with a different period, used to close along-track separation over N revolutions."],
        ["Plane Change", "A manoeuvre that alters the orbital inclination or RAAN."],
        ["Prograde", "In the direction of the velocity vector."],
        ["RAAN", "Right Ascension of the Ascending Node — the angle from the vernal equinox to the ascending node."],
        ["Retrograde", "Opposite to the direction of the velocity vector."],
        ["Semi-major Axis", "Half the longest diameter of an elliptical orbit."],
        ["SGP4", "Simplified General Perturbations model 4 — the standard TLE propagator."],
        ["Stability Score", "Ratio of actual Δvy₀ to the CW bounded-motion requirement (Δvy₀ = −2n·Δx₀); 1.0 = bounded relative motion."],
        ["TLE", "Two-Line Element set — the standard format for satellite orbital data."],
        ["Time of Flight", "Duration of the transfer from departure to arrival."],
        ["Trade-Space", "The set of feasible solutions plotted by their key trade-off parameters."],
        ["UDL", "Unified Data Library — authoritative source for TLE data and space object notifications."],
        ["UDL Data Mode", "Classification tag on UDL records: REAL (operational), SIMULATED, EXERCISE, or TEST."],
        ["VNB Frame", "Velocity-Normal-Binormal local orbital reference frame."],
        ["Vis-viva Equation", "Relates orbital velocity to position and semi-major axis."],
        ["GCAT", "General Catalogue — Jonathan McDowell's authoritative space object catalogue at planet4589.org."],
        ["HRR", "High Rate Revisit — JCO satellite watchlist identifying high-priority objects by threat rank."],
        ["Pattern of Life (PoL)", "Analysis of a satellite's full TLE history to characterise manoeuvre behaviour and detect anomalies."],
        ["PoL Status", "Classification of a satellite's historical behaviour: NOMINAL (routine station-keeping), ANOMALOUS (unusual or large manoeuvres), or SUSPICIOUS (evasive or targeting behaviour)."],
        ["TLE Source", "The UDL provider (for example 18th SPCS or LeoLabs) a latest fetch is narrowed to; blank takes the newest set from every provider."],
        ["Drift Phase", "A continuous period of east-west longitude drift at a measurable rate, detected from successive GEO elsets."],
        ["NOTSO", "Notice to Space Operators — formal pre-manoeuvre notification filed with USSPACECOM by spacecraft operators."],
        ["Phantom NOTSO", "A NOTSO filed but for which no corresponding manoeuvre was detected in TLE analysis."],
        ["Consistent Notifier", "Operator behavioural flag: notification rate above 90% — reliable pre-manoeuvre notification behaviour."],
        ["Stealth Operator", "Operator behavioural flag: notification rate below 30% — significant intelligence indicator."],
        ["Predictable Timing", "Operator behavioural flag: lead-time standard deviation below 6 hours — highly regular notification pattern."],
        ["Decision Engine", "SPECTRE's scenario evaluation module: scores every pairing of adversary action and friendly response, recommends a response, and can look up to three turns ahead."],
        ["Minimax", "Decision rule that selects the friendly response whose worst-case composite score is least: the cautious rule and the default."],
        ["Minimin", "Decision rule that selects the friendly response whose best-case composite score is least: the optimistic rule, not a robust one."],
        ["Expected Value", "Decision rule that selects the response minimising the expected composite score weighted by adversary action probabilities."],
        ["Composite Score", "Weighted sum of custody, closest approach, our delta-V, time to execute and reversibility; lower is better for the blue force. A lookup while its weights are uncited."],
        ["Game Tree", "The Decision Engine's look ahead of 2 or 3 turns, in which red may move again after each friendly response."],
        ["Photometry", "Measurement of the brightness of a space object over time; used to detect attitude changes, physical alterations, or reflectivity anomalies."],
        ["Reduced Magnitude", "Apparent magnitude corrected for range and atmospheric extinction; enables like-for-like comparison across different observing geometries."],
        ["Phase Function Baseline", "Quadratic model of brightness vs solar phase angle fitted to historical observations; the reference against which changes are detected."],
        ["Welch t-test", "Two-sample t-test that does not assume equal variance; used by SPECTRE to compare recent vs historical photometric residuals."],
        ["Training Environment", "SPECTRE's sandboxed training mode using synthetic data; supports five progression levels from Observer to Strategist."],
        ["Skill Axis", "One of five proficiency dimensions tracked in the Training Environment: manoeuvre_planning, threat_assessment, decision_quality, situational_awareness, system_proficiency."],
        ["Gauntlet", "Multi-stage challenge scenario in the Training Environment, accessible at Level 5 (Strategist) only."],
    ]
    _add_data_table(doc, ["Term", "Definition"], terms)


def _section_19_pattern_of_life(doc: Document) -> None:
    """Section 19: Historical Pattern of Life Analysis."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 19")
    _add_heading_h1(doc, "Historical Pattern of Life Analysis")

    _add_body(doc,
        "The Historical Pattern of Life (PoL) panel analyses the full TLE history "
        "of a satellite to detect past manoeuvres, characterise station-keeping "
        "behaviour, and identify anomalous activity. It fetches up to 5,000 "
        "historical elsets from UDL and combines them with the latest current elset "
        "to produce a comprehensive orbital element timeline."
    )

    _add_heading_h2(doc, "Operator Workflow")
    _add_bullet(doc, "1. Open the Historical PoL hero tab.")
    _add_bullet(doc, "2. Enter the SATNO to analyse.")
    _add_bullet(doc, "3. Adjust the \u0394V Detection Threshold (default 2.0 m/s) — lower values detect smaller station-keeping manoeuvres; raise it to focus on significant repositioning events.")
    _add_bullet(doc, "4. Choose the data source: UDL session (uses active credentials) or enter UDL credentials directly.")
    _add_bullet(doc, "5. Click Analyse \u2014 SPECTRE fetches TLE history and the current elset, merges and sorts them chronologically, then runs the PoL engine.")
    _add_bullet(doc, "6. Review the results: manoeuvre timeline, orbital element charts, drift phase analysis, and PoL status.")

    _add_heading_h2(doc, "Results Panels")
    _add_data_table(doc,
        ["Panel", "Description"],
        [
            ["Summary", "Total TLE count, manoeuvre count, PoL status (NOMINAL / ANOMALOUS / SUSPICIOUS)"],
            ["Manoeuvre Timeline", "Table of detected manoeuvres with epoch, estimated \u0394V (m/s), manoeuvre type, and longitude at time of manoeuvre"],
            ["Orbital Elements Chart", "Time-series plots of altitude, inclination, eccentricity, RAAN, and period across the full TLE history"],
            ["GEO Longitude Chart", "Longitude and drift rate over time for GEO/near-GEO objects, with drift phase bands"],
            ["Drift Phases", "Table of distinct longitude drift phases: start/end epoch, direction, drift rate (\u00B0/day), start/end longitude"],
            ["Statistics", "Mean \u0394V, 2\u03C3 high-\u0394V threshold, mean manoeuvre interval, and interval bounds"],
        ],
    )

    _add_heading_h2(doc, "Manoeuvre Classification")
    _add_data_table(doc,
        ["Type", "Description"],
        [
            ["station_keeping", "Small periodic manoeuvre to maintain orbital slot or altitude"],
            ["plane_change", "Change in inclination or RAAN"],
            ["repositioning", "Large manoeuvre indicating a change of operational orbit or longitude slot"],
            ["unknown", "Manoeuvre detected but type cannot be classified from TLE data alone"],
        ],
    )

    _add_callout(doc,
        "PoL analysis requires at least 10 valid TLEs for meaningful results. "
        "Objects with sparse TLE histories will produce limited manoeuvre detection. "
        "The dual-fetch strategy (historical + current) ensures the most recent elset "
        "is always included even when the 5,000-record cap is reached."
    )


def _section_20_gcat_browser(doc: Document) -> None:
    """Section 20: GCAT Browser."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 20")
    _add_heading_h1(doc, "GCAT Browser")

    _add_body(doc,
        "The GCAT (General Catalogue) Browser provides instant access to Jonathan "
        "McDowell's authoritative space object catalogue datasets, hosted at "
        "planet4589.org. 28 datasets spanning launch history, payload attributes, "
        "orbital decay records, and deep-space catalogues are available."
    )

    _add_heading_h2(doc, "Accessing the Browser")
    _add_body(doc,
        "Open the GCAT Browser hero tab. The 28 dataset tiles load immediately. "
        "Click any tile to fetch and display that dataset in a searchable, "
        "sortable, paginated table. No UDL connection is required \u2014 data is "
        "fetched directly from planet4589.org on demand."
    )

    _add_heading_h2(doc, "Available Dataset Categories")
    _add_data_table(doc,
        ["Category", "Example Datasets"],
        [
            ["Launch catalogue", "Satcat, Launch log, Launch sites"],
            ["Payload attributes", "Payload catalogue, Owner/operator, Masses"],
            ["Orbital decay", "Decay log, Reentry predictions"],
            ["Deep space", "Deep space catalogue, Lunar missions, Planetary missions"],
            ["Debris & fragmentation", "Fragmentation events, Debris catalogue"],
            ["Auxiliary", "Rocket body catalogue, Infrastructure"],
        ],
    )

    _add_heading_h2(doc, "Search and Navigation")
    _add_body(doc,
        "Each dataset table supports:"
    )
    _add_bullet(doc, "Text search \u2014 filters all visible columns in real time.")
    _add_bullet(doc, "Column sort \u2014 click any header to sort ascending/descending.")
    _add_bullet(doc, "Pagination \u2014 navigate large datasets in pages of 50 rows.")
    _add_callout(doc,
        "GCAT data is fetched on demand and cached for the session. Datasets are "
        "not updated automatically \u2014 click the dataset tile again to refresh."
    )


def _section_21_appendices(doc: Document) -> None:
    """Section 21: Appendices."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 21")
    _add_heading_h1(doc, "Appendices")

    _add_heading_h2(doc, "A. Keyboard Shortcuts & UI Tips")
    _add_data_table(doc,
        ["Action", "How"],
        [
            ["Quick-add satellite", "Enter NORAD ID and press Enter"],
            ["Run intercept", "Click Apply Intercept or press Enter in the form"],
            ["View orbital events", "Click Compute Events with satellites selected"],
            ["Clear trade-space", "Click Clear History on the scatter plot"],
            ["Switch TLE mode", "Use the radio buttons (UDL / Manual / Catalogue)"],
        ],
    )

    _add_heading_h2(doc, "B. Common Error Messages")
    _add_data_table(doc,
        ["Error", "Cause", "Resolution"],
        [
            ["No TLE found", "Satellite not in session", "Add the satellite first"],
            ["Intercept calculation failed", "Solver diverged or invalid geometry", "Try a longer time of flight or different coast duration"],
            ["UDL connection failed", "Invalid credentials or network error", "Re-enter UDL credentials; check network connectivity"],
            ["No orbital events found", "TLE epoch too stale or window too short", "Use a fresher TLE or widen the scenario window"],
        ],
    )

    _add_heading_h2(doc, "C. API Endpoints")
    _add_data_table(doc,
        ["Method", "Endpoint", "Purpose"],
        [
            ["POST", "/plan/maneuver/apply-intercept", "Run an intercept calculation"],
            ["POST", "/plan/maneuver/apply-all-intercepts", "Run all intercepts (bulk)"],
            ["GET", "/plan/maneuver/orbital-events", "Compute orbital events for satellites"],
            ["GET", "/plan/maneuver/trade-space-data", "Retrieve trade-space JSON for charting"],
            ["POST", "/plan/maneuver/clear-history", "Clear intercept history and reset chart"],
            ["GET", "/plan/threat/target-config", "Load threat sweep target group dropdown"],
            ["POST", "/plan/threat/fetch-targets", "Pre-fetch TLEs for a target group"],
            ["POST", "/plan/threat/sweep", "Run batch Hohmann + Lambert threat sweep"],
            ["POST", "/plan/threat/refine", "Lambert-refine a single sweep entry"],
            ["GET", "/pol/panel", "Load the Historical PoL panel"],
            ["POST", "/pol/analyse", "Run PoL analysis for a SATNO"],
            ["GET", "/pol/chart-data/{satno}", "Retrieve PoL chart JSON for a SATNO"],
            ["POST", "/assets/blue/quick-add", "One-click HRR → blue asset ingestion"],
            ["POST", "/assets/red/quick-add", "One-click HRR → red track ingestion"],
            ["POST", "/blue/add", "Add a blue asset to the session"],
            ["POST", "/red/add", "Add a red track to the session"],
            ["POST", "/blue/remove", "Remove a blue asset"],
            ["POST", "/red/remove", "Remove a red track"],
            ["GET", "/admin/users", "List all users (admin only)"],
            ["POST", "/admin/users", "Create a new user (admin only)"],
            ["GET", "/admin/users/{id}/edit", "Open inline edit form for a user (admin only)"],
            ["GET", "/admin/users/{id}/cancel", "Cancel inline edit, return display row (admin only)"],
            ["POST", "/admin/users/{id}", "Save role / password change for a user (admin only)"],
            ["DELETE", "/admin/users/{id}", "Delete a user account (admin only)"],
            ["POST", "/udl/login", "Connect to UDL with credentials"],
            ["POST", "/udl/logout", "Disconnect from UDL"],
            ["POST", "/udl/data-mode", "Set session UDL data mode"],
            ["POST", "/udl/tle-source", "Set preferred TLE source provider"],
            ["GET", "/udl/tle", "Fetch TLE from UDL by NORAD ID (latest or epoch mode)"],
            ["GET", "/udl/statevector", "Fetch latest Cartesian state vector from UDL"],
            ["GET", "/udl/hrr", "Fetch HRR satellite list from UDL"],
            ["GET", "/udl/catalog/search", "Search cached on-orbit catalogue"],
        ],
    )


def _section_22_user_management(doc: Document) -> None:
    """Section 22: User Management."""
    _add_page_break(doc)
    _add_eyebrow(doc, "Section 22")
    _add_heading_h1(doc, "User Management")

    _add_body(doc,
        "SPECTRE provides a web-based user management console at /admin/users. "
        "This interface is restricted to accounts with the admin role. Operators "
        "do not have access to this area."
    )

    _add_heading_h2(doc, "Accessing the Admin Console")
    _add_body(doc,
        "Navigate to /admin/users in your browser while logged in as an admin. "
        "Non-admin accounts receive an HTTP 403 Forbidden response. Unauthenticated "
        "sessions are redirected to the login page."
    )
    _add_callout(doc,
        "The bootstrap admin account is created from the SPECTRE_ADMIN_USER and "
        "SPECTRE_ADMIN_PASS environment variables on first run (only if the users "
        "table is empty). Set these before starting the server for the first time."
    )

    _add_heading_h2(doc, "User Roles")
    _add_data_table(doc,
        ["Role", "Permissions"],
        [
            ["operator", "Full access to all operator console features. Cannot access /admin/*."],
            ["admin", "All operator permissions plus /admin/users account management."],
        ],
    )

    _add_heading_h2(doc, "Creating a User")
    _add_body(doc,
        "At the top of the /admin/users page, complete the Add New User form:"
    )
    _add_bullet(doc, "Username — unique login name, up to 64 characters.")
    _add_bullet(doc, "Password — initial password. The account holder should change this on first login.")
    _add_bullet(doc, "Role — select Operator or Admin.")
    _add_body(doc,
        "Click Create User. The new account appears immediately in the user table below. "
        "A confirmation banner confirms success or describes any validation error "
        "(e.g. duplicate username)."
    )

    _add_heading_h2(doc, "Editing a User")
    _add_body(doc,
        "Click Edit on any user row to open an inline edit form. Two fields are available:"
    )
    _add_bullet(doc, "Role — change between Operator and Admin.")
    _add_bullet(doc, "New Password — enter a new password to reset it. Leave blank to keep the existing password.")
    _add_body(doc,
        "Click Save to apply changes, or Cancel to discard and return to the display row. "
        "Username cannot be changed; create a new account and delete the old one if a "
        "username change is required."
    )

    _add_heading_h2(doc, "Deleting a User")
    _add_body(doc,
        "Click Delete on any user row. A confirmation prompt is shown before the account "
        "is permanently removed. The following constraints apply:"
    )
    _add_bullet(doc, "An admin cannot delete their own account.")
    _add_bullet(doc, "An admin cannot delete or demote the last remaining admin account.")
    _add_bullet(doc, "The account's decision records stay, under its username, for an admin to read; no one can "
                "record a decision on them any more, and a later account of the same name does not see them. "
                "Keeping them is Claude's design choice, awaiting the owner's ruling as data protection lead.")
    _add_callout(doc,
        "Deletion is permanent and immediate. There is no soft-delete or recycle bin. "
        "Ensure the correct account is selected before confirming."
    )

    _add_heading_h2(doc, "Fallback — Direct Database Access")
    _add_body(doc,
        "If all admin accounts are lost (e.g. deleted via direct SQL), access can be "
        "restored by stopping the server and either: (a) deleting spectre.db and restarting "
        "with SPECTRE_ADMIN_PASS set — this re-runs the bootstrap — or (b) for PostgreSQL, "
        "truncating the users table and restarting."
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════


def generate() -> Path:
    """Generate the complete SPECTRE Operator Guide and return the output path."""
    doc = _setup_document()
    _add_accent_bar(doc)
    _add_footer(doc)

    # Title page.
    _add_eyebrow(doc, "Bluestaq Ltd")
    _add_heading_h1(doc, "SPECTRE Operator Guide")
    _add_body(doc, "Space Planning, Evaluation & Counter-Threat Response Engine")
    _add_body(doc, "Comprehensive Operator Reference \u2014 v2.0.0")
    _add_body(doc, "")
    _add_metric_card(doc, "23", "MANOEUVRE METHODS")
    _add_metric_card(doc, "22", "GUIDE SECTIONS")
    _add_metric_card(doc, "28", "GCAT DATASETS")
    _add_metric_card(doc, "5", "TRAINING LEVELS")

    # Content sections.
    _section_01_introduction(doc)
    _section_02_system_overview(doc)
    _section_03_getting_started(doc)
    _section_04_dashboard(doc)
    _section_05_assets(doc)
    _section_06_scenario_time(doc)
    _section_07_manoeuvre_theory(doc)
    _section_08_tactical_theory(doc)
    _section_09_threat_sweep(doc)
    _section_10_intercept_calculations(doc)
    _section_11_trade_space(doc)
    _section_12_scenario_planning(doc)
    _section_13_decision_engine(doc)
    _section_14_training(doc)
    _section_15_notso_correlation(doc)
    _section_16_photometry(doc)
    _section_17_scenarios(doc)
    _section_18_glossary(doc)
    _section_19_pattern_of_life(doc)
    _section_20_gcat_browser(doc)
    _section_21_appendices(doc)
    _section_22_user_management(doc)

    doc.save(str(OUTPUT_PATH))
    return OUTPUT_PATH


if __name__ == "__main__":
    out = generate()
    print(f"Generated: {out}")
