"""The Code Quality rule checker raises what the gate raised, and nothing it passed (SPC-233).

Every case below is a line the App Store gate actually reported, or one it
actually passed, so the checker is calibrated against the gate rather than
against a reading of the rule's documentation. The release replay (0.6.1 to
0.6.5, each against its predecessor) is recorded in docs/SONAR-RULES.md; these
are the unit-level fence around it.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.unit.test_deployment_contract import _repo_only

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "sonar_rules.py"
_LEDGER = _ROOT / "docs" / "SONAR-RULES.md"

# The suite also runs inside the App Store package, where scripts/ and docs/
# are stripped on purpose. The checker is a repository tool, so it is tested
# where it exists.
if not _SCRIPT.is_file():
    pytest.skip("scripts/ is excluded from the submission package", allow_module_level=True)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sonar_rules", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["sonar_rules"] = module
    spec.loader.exec_module(module)
    return module


rules = _load()

_ALL = set(range(1, 400))


def _py(source: str, base: str | None = None, changed: set[int] = _ALL) -> list[str]:
    return [f.rule for f in rules.check_python("x.py", source, base, changed) if f.blocking]


def _html(text: str, changed: set[int] = _ALL) -> list[str]:
    return [f.rule for f in rules.check_template("x.html", text, changed) if f.blocking]


def _js(text: str, changed: set[int] = _ALL) -> list[str]:
    return [f.rule for f in rules.check_template("spectre/web/static/js/x.js", text, changed) if f.blocking]


class TestDuplicatedLiterals:
    def test_a_third_use_of_a_path_is_new(self) -> None:
        """0.6.5 before release: the UDL timestamp format went from two uses to three."""
        base = 'A = "%Y-%m-%dT%H:%M:%S.%f"\nB = "%Y-%m-%dT%H:%M:%S.%f"\n'
        assert _py(base + 'C = "%Y-%m-%dT%H:%M:%S.%f"\n', base, {3}) == ["python:S1192"]

    def test_identifier_like_literals_are_not_counted(self) -> None:
        """0.6.4 passed with "fields_side" used three times, new in that release."""
        assert _py('a = {"fields_side": 1}\nb = {"fields_side": 2}\nc = a["fields_side"]\n') == []

    def test_short_literals_are_not_counted(self) -> None:
        assert _py('a = "R/L"\nb = "R/L"\nc = "R/L"\n') == []

    def test_a_literal_already_over_the_threshold_is_not_new(self) -> None:
        base = "\n".join(f'v{i} = "Hop Type"' for i in range(3)) + "\n"
        source = base + 'v9 = "Hop Type"\n'
        findings = rules.check_python("x.py", source, base, {4})
        assert [f.blocking for f in findings if f.rule == "python:S1192"] == [False]

    def test_docstrings_are_not_literals(self) -> None:
        body = '    """Hop Type and more."""\n'
        assert _py("".join(f"def f{i}():\n{body}" for i in range(3))) == []

    def test_untouched_uses_are_out_of_scope(self) -> None:
        source = 'a = "a b c d"\nb = "a b c d"\nc = "a b c d"\nd = 1\n'
        assert _py(source, None, {4}) == []

    def test_an_f_string_fragment_warns_and_does_not_block(self) -> None:
        source = "".join(f'v{i} = f"{{x}} km away"\n' for i in range(3))
        findings = rules.check_python("x.py", source, None, _ALL)
        assert [(f.rule, f.blocking) for f in findings] == [("python:S1192", False)]


class TestPythonRules:
    def test_exact_float_equality(self) -> None:
        assert _py("ok = ecc == 0.0\n") == ["python:S1244"]
        assert _py("ok = ecc != -0.0\n") == ["python:S1244"]
        assert _py("ok = n == 0\n") == []
        assert _py("ok = not ecc\n") == []

    def test_nested_conditional(self) -> None:
        assert _py('band = "a" if x else "b" if y else "c"\n') == ["python:S3358"]
        assert _py('band = "a" if x else "b"\n') == []

    def test_too_many_parameters(self) -> None:
        many = ", ".join(f"p{i}" for i in range(14))
        assert _py(f"def f({many}):\n    pass\n") == ["python:S107"]
        assert _py(f"def f(self, {', '.join(f'p{i}' for i in range(13))}):\n    pass\n") == []

    def test_fastapi_default_dependency(self) -> None:
        route = '@router.get("/x")\nasync def r(user: User = Depends(require_login)):\n    pass\n'
        annotated = '@router.get("/x")\nasync def r(user: Annotated[User, Depends(require_login)]):\n    pass\n'
        assert _py(route) == ["python:S8410"]
        assert _py(annotated) == []

    def test_a_plain_function_default_is_not_a_route(self) -> None:
        assert _py("def helper(user = Depends(require_login)):\n    pass\n") == []

    def test_an_exception_and_its_subclass(self) -> None:
        """0.6.0: SignatureExpired is a BadSignature."""
        pytest.importorskip("itsdangerous")
        source = (
            "from itsdangerous import BadSignature, SignatureExpired\n"
            "try:\n    pass\nexcept (SignatureExpired, BadSignature):\n    pass\n"
        )
        assert _py(source) == ["python:S5713"]
        assert _py("try:\n    pass\nexcept (KeyError, LookupError):\n    pass\n") == ["python:S5713"]
        assert _py("try:\n    pass\nexcept (KeyError, ValueError):\n    pass\n") == []

    def test_list_around_an_iterable(self) -> None:
        assert _py("for t in list(tasks):\n    t.cancel()\n") == ["python:S7504"]
        assert _py("for t in tasks.copy():\n    t.cancel()\n") == []

    def test_regex_character_class(self) -> None:
        assert _py('import re\nre.compile(r"^[a-zA-Z0-9_]+$")\n') == ["python:S6353"]
        assert _py('import re\nre.compile(r" *([0-9]{2}) *")\n') == ["python:S6353"]
        assert _py('import re\nre.compile(r"^\\w+$", re.ASCII)\n') == []

    @pytest.mark.parametrize(("comment", "flagged"), [
        ("x = 1  # noqa: BLE001 - any unreadable body has no token", True),
        ("x = 1  # noqa: BLE001", False),
        ("x = 1  # noqa: S603, S607", False),
        ("x = 1  # noqa", False),
    ])
    def test_noqa_with_text(self, comment: str, flagged: bool) -> None:
        """0.6.0 raised the first; the second is the 0.6.1 fix that passed."""
        assert (_py(comment + "\n") == ["python:S7632"]) is flagged

    def test_only_changed_lines_are_scored(self) -> None:
        source = "a = x == 0.0\nb = y == 0.0\n"
        findings = rules.check_python("x.py", source, None, {2})
        assert [(f.rule, f.line) for f in findings] == [("python:S1244", 2)]


class TestJavaScript:
    def test_global_number_functions(self) -> None:
        """0.6.1: the intercept sort's parseFloat and isNaN, now in spectre/web/static/js/."""
        line = "var n = parseFloat(v); if (isNaN(n)) { n = 0; }"
        assert _js(line) == ["javascript:S7773", "javascript:S7773"]
        assert _js("var n = Number.parseFloat(v); Number.isNaN(n);") == []
        assert _js("var w = Number.parseInt(s) || 500;") == []

    def test_data_attributes(self) -> None:
        assert _js("item.setAttribute('data-idx', String(i));") == ["javascript:S7761"]
        assert _js("if (!el.hasAttribute('data-activate')) { return; }") == ["javascript:S7761"]
        assert _js("item.dataset.idx = String(i);") == []
        assert _js("row.getAttribute('data-sort-' + col);") == [], "0.6.1 passed this"

    def test_script_in_a_template_is_read_too(self) -> None:
        assert _html("<script>var n = parseFloat(v);</script>") == ["javascript:S7773"]


class TestTemplates:
    def test_an_unlabelled_field(self) -> None:
        assert _html('<input id="red-satno" name="satno" />') == ["Web:InputWithoutLabelCheck"]

    @pytest.mark.parametrize("markup", [
        '<label for="red-satno">SATNO</label><input id="red-satno" name="satno" />',
        '<label>Max dV <input type="number" name="max_dv" /></label>',
        '<input type="hidden" name="elset_mode" value="REAL" />',
        '<label for="{{ side }}-tle">TLE</label><textarea id="{{ side }}-tle"></textarea>',
        '<input type="text" name="fr_name" aria-label="Friendly response name">',
        '<span id="h">Name</span><input type="text" name="fr_name" aria-labelledby="h">',
    ])
    def test_labelled_or_exempt_fields(self, markup: str) -> None:
        assert _html(markup) == []

    def test_an_empty_aria_label_is_no_label(self) -> None:
        assert _html('<input type="text" name="fr_name" aria-label=" ">') == ["Web:InputWithoutLabelCheck"]

    def test_markup_in_a_script_string_is_not_html(self) -> None:
        """0.6.3 passed decision_panel's rows built in a template literal."""
        assert _html('<script>div.innerHTML = `<input type="text" name="fr_name">`;</script>') == []

    @pytest.mark.parametrize("end", ["</script >", "</SCRIPT>", "</script\n>", '</script foo="bar">'])
    def test_every_end_tag_html_reads_ends_the_script(self, end: str) -> None:
        """HTML ends a script at each of these (CodeQL py/bad-tag-filter on PR 35)."""
        assert _html(f'<script>div.innerHTML = `<input type="text" name="fr_name">`;{end}') == []

    def test_an_edit_anywhere_in_the_element_brings_it_into_scope(self) -> None:
        """0.6.3: a rewritten title, two lines below the tag's first line, counted."""
        markup = '<input id="red-satno"\n       name="satno"\n       title="new text" />\n'
        findings = rules.check_template("x.html", markup, {3})
        assert [(f.rule, f.line) for f in findings] == [("Web:InputWithoutLabelCheck", 1)]

    def test_an_untouched_element_is_out_of_scope(self) -> None:
        markup = '<input id="red-satno" name="satno" />\n<p>new</p>\n'
        assert _html(markup, {2}) == []

    def test_a_role_with_a_native_element(self) -> None:
        """0.6.3: the training banner's role="status"."""
        assert _html('<div id="b" role="status" aria-label="x"></div>') == ["Web:S6819"]
        assert _html('<div id="b" role="note" aria-label="x"></div>') == []
        assert _html('<div id="b" aria-live="polite" aria-atomic="true"></div>') == []
        assert _html('<svg role="img" aria-label="3 profiles"></svg>') == []

    def test_a_jinja_comment_read_as_attributes(self) -> None:
        """0.6.0: the parser read role="button" inside a {# #} as an attribute."""
        tag = '<tr class="row" {# was role="button" #} tabindex="0"></tr>'
        assert set(_html(tag)) == {"Web:JinjaCommentInTag", "Web:S6819"}

    def test_a_plain_jinja_comment_in_a_tag_only_warns(self) -> None:
        tag = '<button type="button" {# the first burn epoch goes in #} data-x="1"></button>'
        findings = rules.check_template("x.html", tag, _ALL)
        assert [(f.rule, f.blocking) for f in findings] == [("Web:JinjaCommentInTag", False)]


class TestScope:
    @pytest.mark.parametrize(("path", "scored"), [
        ("spectre/web/routes/threat.py", True),
        ("spectre/web/templates/partials/threat_sweep.html", True),
        ("spectre/web/static/js/operator.js", True),
        ("tle_clustering/cluster.py", True),
        ("spectre/web/static/htmx.min.js", False),
        ("scripts/sonar_rules.py", False),
        ("tests/unit/test_sonar_rules.py", False),
        ("spectre/web/static/style.css", False),
    ])
    def test_what_the_gate_analyses(self, path: str, scored: bool) -> None:
        """sonar.sources is spectre and tle_clustering; vendored minified libraries are never edited here."""
        assert rules.in_scope(path) is scored


class TestTheLedgerAndTheCheckerAgree:
    def test_every_encoded_rule_has_a_row_and_every_row_a_check(self) -> None:
        if not _LEDGER.is_file():
            pytest.skip("docs/ is excluded from the submission package")
        table = _LEDGER.read_text(encoding="utf-8")
        documented = set(re.findall(r"^\| `([\w:]+)` \|", table, re.M))
        assert documented == set(rules.RULES)
        assert len(documented) == 14


class TestTheGatesRunIt:
    def test_check_quality_runs_it_before_the_python_only_exit(self) -> None:
        """Templates and JavaScript are its own ground: a change touching no Python must still be checked."""
        text = _repo_only("scripts/check-quality.sh").read_text(encoding="utf-8")
        assert 'scripts/sonar_rules.py "$BASE"' in text
        assert text.index("scripts/sonar_rules.py") < text.index("Nothing to check")

    def test_the_packager_refuses_to_build_on_a_finding(self) -> None:
        text = _repo_only("scripts/package-appstore.sh").read_text(encoding="utf-8")
        run = text.index("scripts/sonar_rules.py")
        assert run < text.index("# ── Build")
        assert "exit 1" in text[run:text.index("# ── Build")]


class TestTheCommandLine:
    def test_a_clean_tree_exits_zero_and_a_new_issue_exits_one(self, tmp_path: Path) -> None:
        git_exe = shutil.which("git")
        if git_exe is None:
            pytest.skip("git is not available here")

        def git(*args: str) -> None:
            subprocess.run([git_exe, *args], cwd=tmp_path, check=True, capture_output=True)  # noqa: S603

        git("init", "-q", "-b", "master")
        git("config", "user.email", "t@example.invalid")
        git("config", "user.name", "t")
        git("config", "commit.gpgsign", "false")
        page = tmp_path / "spectre" / "web" / "templates" / "p.html"
        page.parent.mkdir(parents=True)
        page.write_text('<label for="a">A</label><input id="a" />\n', encoding="utf-8")
        git("add", ".")
        git("commit", "-qm", "base")
        git("checkout", "-qb", "work")
        script = str(_SCRIPT)

        def run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(  # noqa: S603
                [sys.executable, script, "master"], cwd=tmp_path, capture_output=True, text=True, check=False,
            )

        assert run().returncode == 0
        page.write_text('<label for="a">A</label><input id="a" />\n<input name="b" />\n', encoding="utf-8")
        script_js = tmp_path / "spectre" / "web" / "static" / "js" / "new.js"
        script_js.parent.mkdir(parents=True)
        script_js.write_text("var n = parseFloat(v);\n", encoding="utf-8")
        result = run()
        assert result.returncode == 1
        assert "Web:InputWithoutLabelCheck  spectre/web/templates/p.html:2" in result.stdout
        assert "javascript:S7773  spectre/web/static/js/new.js:1" in result.stdout, "an untracked file is new whole"
        assert "Web:InputWithoutLabelCheck  spectre/web/templates/p.html:1" not in result.stdout

    def test_every_line_mode_reads_a_path_given(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        page = tmp_path / "p.html"
        page.write_text('<div role="status"></div>\n', encoding="utf-8")
        assert rules.main(["--all", str(page)]) == 1
        assert "Web:S6819" in capsys.readouterr().out
