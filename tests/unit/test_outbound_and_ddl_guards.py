"""Two controls that scanners found, and that no test held before.

Both sit on paths where the dangerous value is a literal today and could stop
being one tomorrow. A control like that decays quietly: nothing fails when it
is removed, because nothing currently exercises the branch it protects. These
tests exercise the branch directly, so removing either control turns them red.
"""

from __future__ import annotations

import pytest


class TestTheCatalogFetcherSpeaksHttpsOnly:
    """GCAT download: CWE-918, reported by GitLab SAST as urllib-urlopen.

    The finding was real in substance. ``urlopen`` serves ``file://`` and
    ``ftp://`` as readily as ``https://``, so a URL that reached it from
    configuration rather than from the module's own table could read the
    container's filesystem. It is now httpx, which has no handler for either
    scheme, with an https-only check in front of it.
    """

    @staticmethod
    def _fetch_recording_transport_use(url: str) -> tuple[object, bool]:
        """Run the fetcher against *url*, reporting whether httpx was reached.

        A sentinel that raises would prove nothing here: the fetcher catches
        ``Exception`` so that one unreachable dataset cannot take the other
        eighteen down with it, and it would swallow the sentinel and return
        ``(key, None)`` exactly as a refusal does. The two outcomes have to be
        told apart by something the except clause cannot absorb, so the stub
        records the call in a list instead of raising.
        """
        import httpx

        from spectre.web.routes import gcat

        reached: list[str] = []

        def _record(*args: object, **kwargs: object) -> object:
            reached.append(url)
            raise RuntimeError("stubbed transport")

        original = httpx.Client
        httpx.Client = _record  # type: ignore[misc, assignment]
        try:
            _, df = gcat._fetch_one("probe", {"url": url, "label": "PROBE"})
        finally:
            httpx.Client = original  # type: ignore[misc]
        return df, bool(reached)

    def test_a_file_url_never_reaches_the_transport(self) -> None:
        """The scheme check must stop it, not the transport's own limitations."""
        df, reached = self._fetch_recording_transport_use("file:///etc/passwd")
        assert not reached, "a file: URL was handed to the HTTP client"
        assert df is None, "a file: URL produced a dataframe"

    @pytest.mark.parametrize("url", [
        "ftp://planet4589.org/space/gcat/tsv/derived/currentcat.tsv",
        "http://planet4589.org/space/gcat/tsv/derived/currentcat.tsv",
        "gopher://example.invalid/x",
        "/etc/passwd",
    ])
    def test_every_other_scheme_is_refused_too(self, url: str) -> None:
        """Plain http is refused as well: the allowlist is https, not 'not file'."""
        df, reached = self._fetch_recording_transport_use(url)
        assert not reached, f"{url} was handed to the HTTP client"
        assert df is None

    def test_an_https_url_does_reach_the_transport(self) -> None:
        """Otherwise every test above would pass on a fetcher that fetches nothing."""
        df, reached = self._fetch_recording_transport_use(
            "https://planet4589.org/space/gcat/tsv/derived/currentcat.tsv",
        )
        assert reached, "the allowlisted scheme was refused as well"
        assert df is None, "the stubbed transport somehow produced a dataframe"

    def test_the_real_dataset_table_is_entirely_https(self) -> None:
        """If the table ever drifts, the check starts refusing live datasets."""
        import urllib.parse

        from spectre.web.routes import gcat

        offenders = [
            (key, meta["url"])
            for key, meta in gcat.DATASETS.items()
            if urllib.parse.urlsplit(meta["url"]).scheme not in gcat._ALLOWED_URL_SCHEMES
        ]
        assert not offenders, f"these datasets would now be refused: {offenders}"

    def test_the_fetcher_no_longer_imports_urlopen(self) -> None:
        """The swap is the fix; a re-import would bring the finding back."""
        import pathlib

        from spectre.web.routes import gcat

        source = pathlib.Path(gcat.__file__).read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )
        assert "urllib.request" not in code, "urllib.request is back in gcat.py"
        assert "urlopen" not in code, "urlopen is back in gcat.py"


class TestTheMigrationDdlGuard:
    """ALTER TABLE is the one statement in this codebase built by interpolation.

    It has to be: DDL takes no bind parameters. The guard is therefore the only
    thing between a migration entry and the database, and it is currently
    unreachable from outside because every entry is a literal. These tests call
    it directly so that it is covered anyway.
    """

    def test_the_real_migration_list_passes(self) -> None:
        """The guard must not reject what the application actually ships."""
        from spectre.web.database import _assert_safe_ddl

        _assert_safe_ddl("training_challenge_results", "scored", "BOOLEAN NOT NULL DEFAULT TRUE")

    @pytest.mark.parametrize(("table", "column", "definition"), [
        ("users; DROP TABLE users", "scored", "BOOLEAN"),
        ("users", "x; DROP TABLE users", "BOOLEAN"),
        ("users", "scored", "BOOLEAN; DROP TABLE users"),
        ("users", "scored", "BOOLEAN -- "),
        ("users", "scored", 'BOOLEAN DEFAULT "x"'),
        ("", "scored", "BOOLEAN"),
        ("1users", "scored", "BOOLEAN"),
        ("users", "scored", ""),
    ])
    def test_an_injected_fragment_raises(
        self, table: str, column: str, definition: str,
    ) -> None:
        from spectre.web.database import _assert_safe_ddl

        with pytest.raises(ValueError, match="unsafe migration"):
            _assert_safe_ddl(table, column, definition)

    def test_the_guard_runs_before_the_statement_is_built(self) -> None:
        """Order matters: validating after interpolation would prove nothing."""
        import ast
        import pathlib

        from spectre.web import database

        source = pathlib.Path(database.__file__).read_text(encoding="utf-8")
        function = next(
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_apply_migrations"
        )
        loop = next(node for node in ast.walk(function) if isinstance(node, ast.For))
        body = ast.unparse(loop)
        # Asserted before the index is taken. Reaching straight for .index()
        # meant that removing the guard raised ValueError: substring not found
        # from inside the test, so whoever read the failure saw a crash rather
        # than the sentence explaining what had been removed.
        assert "_assert_safe_ddl" in body, "the guard is no longer called in the migration loop"
        assert "ALTER TABLE" in body, "the migration loop no longer assembles the statement"
        guard_at = body.index("_assert_safe_ddl")
        execute_at = body.index("ALTER TABLE")
        assert guard_at < execute_at, "the guard runs after the statement is assembled"
