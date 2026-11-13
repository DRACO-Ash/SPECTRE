"""The lookup register holds every constant the Decision Engine reads, at its value (SPC-196, evaluation F-05).

docs/lookup-register.md lists each lookup constant and rule of thumb with its value, where it is, what it does, its
source, its owner and the date it was set. This test holds the register and the code to each other both ways: a
constant named in the register that disappears from the code, or whose value changes without the register changing,
fails; and a module-level numeric constant in one of the Decision Engine's own modules (_ENGINE below) that the
register does not list fails, however it is assigned: a plain name, a tuple of names unpacked, or an annotated name.

The rule for "numeric": a number that is not a truth value, or a non-empty table, tuple, list or set whose every
value is numeric in turn, so a table of tuples of numbers counts. Every such constant in those modules is listed, unit
conversions and display limits too, each in the section it belongs to. The lookup model's own functions hold no bare
number but 0 and 1, so a rule of thumb cannot return there as a literal unseen. The values a new panel starts at are
held to the constants the register lists, so the panel cannot start elsewhere while the register stays green.

The lookup model's relations (SPC-207, evaluation F-17) are a table of their own: each relation the code names is
listed, in its order, with the words the training-only label gives it, the constants it reads and its basis, and a
relation the code labels training only must say "unsourced judgement", each constant it names listed above with the
training-only source.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from spectre.astro.monte_carlo import MANOEUVRE_ARCHETYPES
from spectre.domain.decision import (
    DEFAULT_CONFIDENCE,
    DEFAULT_HORIZON_H,
    DEFAULT_RESPONSE_COST,
    DEFAULT_REVERSIBILITY,
    DEFAULT_TIME_TO_EXECUTE_H,
    LOOKUP_RELATION_WORDS,
    LookupRelation,
    Scenario,
)
from spectre.domain.decision_figures import DEFAULT_BUDGET_KM_S
from spectre.domain.manoeuvre_calibration import from_km_s
from spectre.web.decision_from_sweep import DEFAULT_SAMPLES
from spectre.web.routes import decision as decision_route

_ROOT = Path(__file__).resolve().parents[2]
_REGISTER = _ROOT / "docs" / "lookup-register.md"
_DECISION = "spectre/domain/decision.py"
#: The Decision Engine's own modules: every numeric module constant in each is listed in the register.
_ENGINE = (
    _DECISION, "spectre/domain/decision_tree.py", "spectre/domain/tree_selectors.py", "spectre/domain/turn_update.py",
    "spectre/domain/rule_comparison.py", "spectre/domain/decision_inputs.py", "spectre/domain/decision_replay.py",
    "spectre/domain/decision_figures.py", "spectre/domain/decision_transfer.py", "spectre/domain/decision_judgement.py",
    "spectre/domain/decide_by.py", "spectre/domain/notso_prior.py", "spectre/domain/decision_envelope.py",
    "spectre/domain/weight_stability.py", "spectre/domain/likelihood_calibration.py",
)
#: The lookup model's functions, which hold no bare number but these.
_LOOKUP_MODEL = ("_lookup_figures", "_lookup_cell")
_PLAIN_NUMBERS = frozenset({0, 1})
_DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b")


@dataclass(frozen=True)
class Entry:
    """One row of the register."""

    label: str
    value: Any
    path: str
    name: str
    source: str
    owner: str
    when: str


def _ticked(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def entries(text: str) -> list[Entry]:
    """Every row of every constants table: a row whose first cell is the header's "Constant" or a rule is skipped, and
    so is every row of the lookup model's relations, a table of its own (relations below)."""
    found = []
    in_relations = False
    for line in text.splitlines():
        in_relations = line.startswith("|") and (in_relations or line.startswith("| Relation "))
        if in_relations or not line.startswith("| ") or line.startswith(("| Constant ", "|---")):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) == 7, f"a register row has 7 cells: {line}"
        label, value, where, _what, source, owner, when = cells
        (literal, *_), (path, name) = _ticked(value), _ticked(where)
        found.append(Entry(label, ast.literal_eval(literal), path, name, source, owner, when))
    return found


@dataclass(frozen=True)
class RelationRow:
    """One row of the lookup model's relations (SPC-207)."""

    name: str
    words: str
    constants: str
    path: str
    function: str
    basis: str
    owner: str
    when: str


#: The basis of a relation with no source: the code labels every result resting on it training only.
UNSOURCED = "unsourced judgement"
#: The source the constants table gives a constant of an unsourced relation.
TRAINING_SOURCE = "labelled training only (SPC-207)"


def relations(text: str) -> list[RelationRow]:
    """Every row of the lookup model's relations: the table whose header's first cell is "Relation"."""
    found = []
    in_relations = False
    for line in text.splitlines():
        in_relations = line.startswith("|") and (in_relations or line.startswith("| Relation "))
        if not in_relations or line.startswith(("| Relation ", "|---")):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) == 7, f"a relation row has 7 cells: {line}"
        name, words, constants, where, basis, owner, when = cells
        path, function = _ticked(where)
        found.append(RelationRow(name, words, constants, path, function, basis, owner, when))
    return found


def _function_source(source: str, name: str) -> str:
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(source, node) or ""


def relation_problems(rows: list[RelationRow], listed: list[Entry]) -> list[str]:
    """Each way the relations table and the code part: a relation listed or named out of step, its words, its basis,
    or a constant it names that its function does not read or the constants table does not list as training only."""
    problems = []
    if [r.name for r in rows] != [r.value for r in LookupRelation]:
        problems.append(f"the register lists {[r.name for r in rows]}, the code {[r.value for r in LookupRelation]}")
    sources = {e.name: e.source for e in listed}
    for row in rows:
        words = LOOKUP_RELATION_WORDS.get(LookupRelation(row.name)) if row.name in set(LookupRelation) else None
        if row.words != words:
            problems.append(f"{row.name}: the register's words differ from the label's")
        if row.basis != UNSOURCED:
            problems.append(f"{row.name}: labelled training only, so its basis is {UNSOURCED!r}, not {row.basis!r}")
        if not (row.owner and _DATE.search(row.when)):
            problems.append(f"{row.name}: no owner or date")
        if row.constants.startswith("none:"):
            continue
        body = _function_source(_source(row.path), row.function)
        for name in _ticked(row.constants):
            if name not in body:
                problems.append(f"{row.name}: {row.function} does not read {name}")
            if TRAINING_SOURCE not in sources.get(name, ""):
                problems.append(f"{row.name}: {name} is not listed with the training-only source")
    return problems


def _module(path: str) -> ModuleType:
    return importlib.import_module(path.removesuffix(".py").replace("/", "."))


def resolve(module: ModuleType, name: str) -> Any:
    """*name* in *module*: a name, an attribute of one (a class's field default), or a table's entry by its key."""
    node = ast.parse(name, mode="eval").body

    def walk(n: ast.expr) -> Any:
        if isinstance(n, ast.Name):
            return getattr(module, n.id)
        if isinstance(n, ast.Attribute):
            return getattr(walk(n.value), n.attr)
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant):
            return walk(n.value)[n.slice.value]
        raise ValueError(f"the register names {name!r}, which is not a name, an attribute or a table entry")

    return walk(node)


def plain(value: Any) -> Any:
    """*value* as the register writes it: an enumeration member as "Class.MEMBER", tables and tuples by their parts,
    and a record (a dataclass, such as an archetype) as a table of its numeric fields."""
    if isinstance(value, Enum):
        return f"{type(value).__name__}.{value.name}"
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = {f.name: getattr(value, f.name) for f in dataclasses.fields(value)}
        return {name: field for name, field in fields.items() if _number(field)}
    if isinstance(value, dict):
        return {plain(k): plain(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(plain(v) for v in value)
    return value


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def numeric(value: Any) -> bool:
    """The rule: a number that is not a truth value, or a non-empty table, tuple, list or set whose every value is
    numeric in turn."""
    if isinstance(value, dict):
        return bool(value) and all(numeric(v) for v in value.values())
    if isinstance(value, tuple | list | frozenset | set):
        return bool(value) and all(numeric(v) for v in value)
    return _number(value)


def _target_names(target: ast.expr) -> list[str]:
    """The names an assignment's target binds: a name, or each name of a tuple or list unpacked, at any depth."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Tuple | ast.List):
        return [name for element in target.elts for name in _target_names(element)]
    return []


def module_constants(source: str, module: ModuleType) -> dict[str, Any]:
    """Every module-level name *source* assigns whose value in *module* is numeric."""
    names: list[str] = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            names += [name for t in node.targets for name in _target_names(t)]
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            names += _target_names(node.target)
    return {n: getattr(module, n) for n in names if numeric(getattr(module, n))}


def bare_numbers(source: str, functions: tuple[str, ...]) -> list[str]:
    """Each number written in *functions* of *source* other than 0 and 1, by function and line."""
    found = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in functions:
            found += [f"{node.name}:{c.lineno} {c.value!r}" for c in ast.walk(node)
                      if isinstance(c, ast.Constant) and _number(c.value) and c.value not in _PLAIN_NUMBERS]
    return found


def mismatches(listed: list[Entry]) -> list[str]:
    """Each register row the code no longer bears out: its constant gone, or at another value."""
    problems = []
    for entry in listed:
        try:
            value = resolve(_module(entry.path), entry.name)
        except (AttributeError, KeyError, ModuleNotFoundError) as gone:
            problems.append(f"{entry.path} {entry.name}: not in the code ({gone})")
            continue
        if plain(value) != entry.value or type(plain(value)) is bool:
            problems.append(f"{entry.path} {entry.name}: the code holds {plain(value)!r}, the register {entry.value!r}")
    return problems


def unlisted(source: str, module: ModuleType, listed: list[Entry], path: str = _DECISION) -> list[str]:
    """Each numeric module constant of the module at *path* that the register does not list."""
    named = {e.name for e in listed if e.path == path}
    return sorted(set(module_constants(source, module)) - named)


def _source(path: str) -> str:
    return (_ROOT / path).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def register() -> list[Entry]:
    return entries(_REGISTER.read_text(encoding="utf-8"))


class TestTheRegisterMatchesTheCode:
    def test_every_constant_it_names_is_in_the_code_at_its_value(self, register: list[Entry]) -> None:
        assert mismatches(register) == []

    @pytest.mark.parametrize("path", _ENGINE)
    def test_every_numeric_constant_in_the_engines_modules_is_listed(self, register: list[Entry], path: str) -> None:
        assert unlisted(_source(path), _module(path), register, path) == []

    def test_the_lookup_model_holds_no_bare_number(self) -> None:
        """Its rules of thumb are named constants the register holds, so none can return as a literal unseen."""
        assert bare_numbers(_source(_DECISION), _LOOKUP_MODEL) == []

    def test_every_row_names_its_source_owner_and_date(self, register: list[Entry]) -> None:
        for entry in register:
            assert entry.source and entry.owner, entry.name
            assert _DATE.search(entry.when), f"{entry.name}: no date set"

    @pytest.mark.parametrize("name", [
        "_BASE_CA_KM", "_OTHER_CA_KM", "_MANOEUVRE_CA_PER_COST", "_POSTURE_CA_PER_COST", "_LOOKUP_DV_KM_S_PER_COST",
        "_RETASK_GAP_SHARE", "DEFAULT_CUSTODY_GAP_FRACTION", "DEFAULT_PROBABILITY", "Scenario.w_custody",
        "Scenario.w_closest_approach", "Scenario.w_dv_cost", "Scenario.w_time_to_exec", "Scenario.w_reversibility",
        "DEFAULT_KEEP_OUT_KM", "_CA_NORMALISATION_KM", "DEGRADED_CUSTODY_WEIGHT", "ACTION_LINE",
        "MAX_BURN_M_S", "MAX_RESPONSE_H", "_CONJUNCTION_HOURS", "_GCAT_HOURS", "_HISTORY_HOURS", "_RECORD_HOURS",
        "_WILSON_Z", "_TAIL", "DEFAULT_HORIZON_H", "DEFAULT_CONFIDENCE", "DEFAULT_RESPONSE_COST",
        "DEFAULT_REVERSIBILITY", "DEFAULT_TIME_TO_EXECUTE_H", "_DEFAULT_BUDGET_M_S", "DEFAULT_SAMPLES",
        *(f'MANOEUVRE_ARCHETYPES["{key}"]' for key in MANOEUVRE_ARCHETYPES),
    ])
    def test_it_lists_the_lookups_the_finding_names(self, register: list[Entry], name: str) -> None:
        assert name in {e.name for e in register}

    @pytest.mark.parametrize(("path", "name"), [
        ("spectre/astro/propagator.py", "TLE_LINE_LENGTH"),
        ("spectre/astro/propagator.py", "SGP4_DECAYED"),
        ("spectre/astro/elset_check.py", "_ANGLES[0].low"),
        ("spectre/astro/elset_check.py", "_ANGLES[0].high"),
        ("spectre/astro/elset_check.py", "_ANGLES[1].high"),
        ("spectre/astro/elset_check.py", "_FIRST_YEAR_OF_THE_1900S"),
        ("spectre/web/elsets.py", "_REFUSAL_LOG_LIMIT"),
    ])
    def test_it_lists_the_numbers_that_decide_what_element_set_is_accepted(
        self, register: list[Entry], path: str, name: str,
    ) -> None:
        """SPC-201 added numbers that decide what the engine accepts outside its own modules (review of SPC-201)."""
        assert (path, name) in {(e.path, e.name) for e in register}

    def test_the_owners_rulings_are_named_where_they_exist(self, register: list[Entry]) -> None:
        by_name = {e.name: e for e in register}
        assert "2026-11-05" in by_name["DEGRADED_CUSTODY_WEIGHT"].owner
        assert "SPC-178" in by_name["EVALUATION_BUDGET_S"].owner
        assert by_name["_OTHER_CA_KM"].owner == "unassigned"


class TestTheLookupModelsRelations:
    """SPC-207, evaluation F-17: every relation has a row stating its basis, and the label's words are the
    register's."""

    def test_every_relation_is_listed_with_its_basis_and_the_labels_words(self, register: list[Entry]) -> None:
        rows = relations(_REGISTER.read_text(encoding="utf-8"))
        assert len(rows) == len(LookupRelation) == 7
        assert relation_problems(rows, register) == []

    def test_none_has_a_source(self, register: list[Entry]) -> None:
        assert {r.basis for r in relations(_REGISTER.read_text(encoding="utf-8"))} == {UNSOURCED}

    @pytest.mark.parametrize("name", [
        "_BASE_CA_KM", "_OTHER_CA_KM", "_MANOEUVRE_CA_PER_COST", "_POSTURE_CA_PER_COST", "_LOOKUP_DV_KM_S_PER_COST",
        "_RETASK_GAP_SHARE", "_LOOKUP_TCA_SHARE",
    ])
    def test_each_constant_of_a_relation_says_its_results_are_training_only(
        self, register: list[Entry], name: str,
    ) -> None:
        (entry,) = [e for e in register if e.name == name]
        assert entry.source == (
            "none: unsourced judgement, so a result resting on it is labelled training only (SPC-207)"
        )

    def test_the_relations_table_is_not_read_as_constants(self, register: list[Entry]) -> None:
        assert not {e.name for e in register} & {r.value for r in LookupRelation}

    def test_a_relation_out_of_step_is_caught(self, register: list[Entry]) -> None:
        rows = relations(_REGISTER.read_text(encoding="utf-8"))
        moved = [dataclasses.replace(rows[1], words="half its time", basis="Smith (2020)"), *rows[2:]]
        problems = relation_problems(moved, register)
        assert problems[0].startswith("the register lists ['sensor-retask gap', ")
        assert "sensor-retask gap: the register's words differ from the label's" in problems
        assert "sensor-retask gap: labelled training only, so its basis is 'unsourced judgement', not 'Smith (2020)'" \
            in problems

    def test_a_constant_the_function_does_not_read_or_the_table_does_not_mark_is_caught(
        self, register: list[Entry],
    ) -> None:
        rows = relations(_REGISTER.read_text(encoding="utf-8"))
        wrong = dataclasses.replace(rows[1], constants="`_CA_NORMALISATION_KM`", owner="", when="")
        assert relation_problems([rows[0], wrong, *rows[2:]], register) == [
            "sensor-retask gap: no owner or date",
            "sensor-retask gap: _lookup_figures does not read _CA_NORMALISATION_KM",
            "sensor-retask gap: _CA_NORMALISATION_KM is not listed with the training-only source",
        ]

    def test_an_unknown_relation_has_no_words(self, register: list[Entry]) -> None:
        rows = relations(_REGISTER.read_text(encoding="utf-8"))
        problems = relation_problems([dataclasses.replace(rows[0], name="tide rule"), *rows[1:]], register)
        assert "tide rule: the register's words differ from the label's" in problems


class TestTheCheckBitesBothWays:
    """The checks above, run on a register and a module made to break them, so a pass means something."""

    _ROW = "| Far anchor | `{value}` | `spectre/domain/decision.py` `{name}` | d | none: rule of thumb | unassigned | 2026-04-06 |"

    def test_a_constant_that_left_the_code_is_caught(self) -> None:
        listed = entries(self._ROW.format(value="50_000.0", name="_NO_SUCH_CONSTANT"))
        assert mismatches(listed) == [
            "spectre/domain/decision.py _NO_SUCH_CONSTANT: not in the code "
            "(module 'spectre.domain.decision' has no attribute '_NO_SUCH_CONSTANT')",
        ]

    def test_a_value_changed_without_the_register_is_caught(self) -> None:
        listed = entries(self._ROW.format(value="40_000.0", name="_CA_NORMALISATION_KM"))
        assert mismatches(listed) == [
            "spectre/domain/decision.py _CA_NORMALISATION_KM: the code holds 50000.0, the register 40000.0",
        ]

    def test_a_new_numeric_constant_the_register_does_not_list_is_caught(self) -> None:
        module = ModuleType("fake")
        source = (
            "A = 1.5\nB: int = 3\nC = True\nD = 'text'\nE = {'x': 2.0}\nF = (1, 2)\nG = ()\nH: float\n"
            "I, J = 7.5, 2.5\nK = [7.5, 2.5]\nL = {'a': (1.0, 2.0)}\n(M, (N, O)) = (1, ('s', 2))\nP = {'a': (1, 's')}\n"
        )
        exec(compile(source, "fake", "exec"), module.__dict__)   # noqa: S102 - the test's own literal source
        listed = entries(self._ROW.format(value="1.5", name="A"))
        assert unlisted(source, module, listed) == ["B", "E", "F", "I", "J", "K", "L", "M", "O"]

    def test_a_bare_number_in_the_lookup_model_is_caught(self) -> None:
        source = "def _lookup_figures(c):\n    return c * 6.0 + 1.0 - 0\n\ndef other():\n    return 2.5\n"
        assert bare_numbers(source, _LOOKUP_MODEL) == ["_lookup_figures:2 6.0"]

    def test_a_record_is_read_as_its_numeric_fields(self) -> None:
        listed = entries('| Evasive | `{"typical_delta_v_km_s": 0.002, "delta_v_1sigma_fraction": 0.15, '
                         '"pointing_1sigma_deg": 5.0, "timing_1sigma_seconds": 120.0}` | `spectre/astro/monte_carlo.py`'
                         ' `MANOEUVRE_ARCHETYPES["evasive"]` | d | s | unassigned | 2026-04-06 |')
        assert mismatches(listed) == []
        changed = entries(self._ROW.replace("{value}", '{"typical_delta_v_km_s": 0.003}').replace(
            "`spectre/domain/decision.py` `{name}`", '`spectre/astro/monte_carlo.py` `MANOEUVRE_ARCHETYPES["evasive"]`'))
        assert len(mismatches(changed)) == 1

    def test_a_name_the_resolver_cannot_read_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not a name, an attribute or a table entry"):
            resolve(_module(_DECISION), "f(1)")


class TestThePanelStartsWhereTheRegisterSays:
    """The values a new panel starts at are the registered constants, in the template and in the route's form, so
    the panel cannot start elsewhere while the register stays green."""

    @staticmethod
    def _panel() -> str:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined

        from spectre.web.app import templates as app_templates

        env = Environment(loader=FileSystemLoader(str(_ROOT / "spectre" / "web" / "templates")), autoescape=True,
                          undefined=StrictUndefined)
        env.filters.update(app_templates.env.filters)
        return env.get_template("partials/decision_panel.html").render(pol=None)

    @staticmethod
    def _starts(page: str, name: str) -> list[float]:
        tags = [t for t in re.findall(r"<input[^>]*>", page) if f'name="{name}"' in t]
        return [float(re.search(r'value="([^"]*)"', t).group(1)) for t in tags]  # type: ignore[union-attr]

    @pytest.mark.parametrize(("field", "start"), [
        ("w_custody", Scenario.w_custody), ("w_ca", Scenario.w_closest_approach), ("w_dv", Scenario.w_dv_cost),
        ("w_time", Scenario.w_time_to_exec), ("w_rev", Scenario.w_reversibility), ("horizon_hours", DEFAULT_HORIZON_H),
        ("adv_conf", DEFAULT_CONFIDENCE), ("fr_cost", DEFAULT_RESPONSE_COST), ("fr_rev", DEFAULT_REVERSIBILITY),
        ("fr_time", DEFAULT_TIME_TO_EXECUTE_H),
    ])
    def test_every_field_starts_at_its_registered_value(self, field: str, start: float) -> None:
        values = self._starts(self._panel(), field)
        assert values and all(v == start for v in values), (field, values)

    @pytest.mark.parametrize(("field", "start"), [
        ("w_custody", Scenario.w_custody), ("w_ca", Scenario.w_closest_approach), ("w_dv", Scenario.w_dv_cost),
        ("w_time", Scenario.w_time_to_exec), ("w_rev", Scenario.w_reversibility),
    ])
    def test_the_forms_weights_default_to_the_registered_values(self, field: str, start: float) -> None:
        assert float(decision_route._ScenarioForm.model_fields[field].default) == start

    def test_a_blank_budget_and_the_sample_count_are_the_registered_defaults(self) -> None:
        page = self._panel()
        blank_m_s = from_km_s(DEFAULT_BUDGET_KM_S)
        assert blank_m_s == decision_route._DEFAULT_BUDGET_M_S
        assert f'name="fr_budget" min="0" max="1000" step="any" placeholder="{blank_m_s:g}"' in page
        samples = self._starts(page, "hyp_samples")
        assert samples and all(v == DEFAULT_SAMPLES for v in samples)


def test_the_register_follows_the_house_style() -> None:
    text = _REGISTER.read_text(encoding="utf-8")
    assert not re.search(r"\b(five|six|seven|eight|nine|ten|eleven|twelve)\b", text, re.IGNORECASE), "a number "\
        "of 5 or more in words"
    assert "—" not in text and "–" not in text, "a long dash"
    assert not re.search(r"^(---|\*\*\*|___)\s*$", text, re.MULTILINE), "a horizontal rule"
    assert not re.search(r"^\s*[-*] ", text, re.MULTILINE), "a dash or star bullet"
    assert "--" not in re.sub(r"\|(-{3}\|)+", "", text), "a double dash"
