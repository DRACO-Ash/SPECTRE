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


class TestTheCatalogFetcherRechecksEveryRedirectHop:
    """The scheme check above was made once, against the table's own URL.

    The transport was then built with ``follow_redirects=True``, which carries
    no policy of its own, so a 30x from planet4589.org walked the fetch
    wherever it liked: plain http, or an address inside the cluster, with the
    allowlist never consulted again. Narrow, because it needs control of
    planet4589.org, but the check was advertised as covering the transport and
    it did not.
    """

    @staticmethod
    def _fetch_with_scripted_hops(
        start: str, script: dict[str, tuple[int, str]],
    ) -> tuple[object, list[str], list[bool]]:
        """Run the fetcher against a client replaying *script*, recording the hops.

        The trap the stub above describes applies here word for word: a
        sentinel that raises proves nothing, because ``_fetch_one`` catches
        ``Exception`` so one unreachable dataset cannot take the other
        eighteen down with it, and it would swallow the sentinel and return
        ``(key, None)`` exactly as a refusal does. What is asserted here is
        therefore the list of URLs the transport was actually asked for.
        Following a refused redirect records the second hop; refusing it does
        not, and no except clause can absorb the difference.
        """
        import httpx

        from spectre.web.routes import gcat

        requested: list[str] = []
        follow_flags: list[bool] = []

        class _ScriptedClient:
            def __init__(self, **kwargs: object) -> None:
                follow_flags.append(bool(kwargs.get("follow_redirects")))

            def __enter__(self) -> _ScriptedClient:
                return self

            def __exit__(self, *exc: object) -> bool:
                return False

            def get(self, url: str, headers: dict[str, str] | None = None) -> httpx.Response:
                requested.append(url)
                status, location = script.get(url, (200, ""))
                return httpx.Response(
                    status,
                    headers={"location": location} if location else {},
                    content=b"#name\tvalue\nALPHA\t1\n",
                    request=httpx.Request("GET", url),
                )

        original = httpx.Client
        httpx.Client = _ScriptedClient  # type: ignore[misc, assignment]
        try:
            _, df = gcat._fetch_one("probe", {"url": start, "label": "PROBE"})
        finally:
            httpx.Client = original  # type: ignore[misc]
        return df, requested, follow_flags

    _START = "https://planet4589.org/space/gcat/tsv/derived/currentcat.tsv"

    @pytest.mark.parametrize("destination", [
        "http://planet4589.org/space/gcat/tsv/derived/currentcat.tsv",
        "http://169.254.169.254/latest/meta-data/",
        "ftp://planet4589.org/space/gcat/tsv/derived/currentcat.tsv",
    ])
    def test_a_redirect_off_https_is_refused(self, destination: str) -> None:
        """The hop the first check never saw: downgrade, and the metadata service."""
        df, requested, _ = self._fetch_with_scripted_hops(
            self._START, {self._START: (302, destination)},
        )
        assert destination not in requested, f"the fetcher followed a 302 to {destination}"
        assert requested == [self._START], f"unexpected hops: {requested}"
        assert df is None, "a refused redirect still produced a dataframe"

    def test_a_redirect_within_https_is_still_followed(self) -> None:
        """Otherwise a fetcher that refuses everything would pass the test above."""
        onward = "https://planet4589.org/space/gcat/tsv/derived/moved.tsv"
        df, requested, _ = self._fetch_with_scripted_hops(
            self._START, {self._START: (302, onward)},
        )
        assert requested == [self._START, onward], f"unexpected hops: {requested}"
        assert df is not None, "an allowed redirect was refused as well"

    def test_a_relative_location_is_resolved_against_the_hop_that_served_it(self) -> None:
        """A relative Location is legal, and has no scheme of its own to read."""
        df, requested, _ = self._fetch_with_scripted_hops(
            self._START, {self._START: (302, "/space/gcat/tsv/derived/moved.tsv")},
        )
        assert requested[-1] == "https://planet4589.org/space/gcat/tsv/derived/moved.tsv"
        assert df is not None, "a relative redirect inside the allowlist was refused"

    def test_a_redirect_loop_stops_at_the_cap(self) -> None:
        """Unbounded hops are a hang, which on a probe reads as a dead pod."""
        from spectre.web.routes import gcat

        other = "https://planet4589.org/space/gcat/tsv/derived/other.tsv"
        df, requested, _ = self._fetch_with_scripted_hops(
            self._START, {self._START: (302, other), other: (302, self._START)},
        )
        assert len(requested) == gcat._MAX_REDIRECT_HOPS + 1, (
            f"the chain ran to {len(requested)} hops against a cap of "
            f"{gcat._MAX_REDIRECT_HOPS}"
        )
        assert df is None, "a redirect loop produced a dataframe"

    def test_the_transport_is_not_left_to_follow_redirects_by_itself(self) -> None:
        """With follow_redirects on, httpx consumes the 30x and the loop never runs."""
        _, _, follow_flags = self._fetch_with_scripted_hops(self._START, {})
        assert follow_flags == [False], (
            "httpx.Client was built with follow_redirects enabled, which hides every "
            "hop from the scheme check above"
        )


class TestTheMigrationDdlGuard:
    """ALTER TABLE is the one statement in this codebase built by interpolation.

    It has to be: DDL takes no bind parameters. The guard is therefore the only
    thing between a migration entry and the database, and it is currently
    unreachable from outside because every entry is a literal. These tests call
    it directly so that it is covered anyway.
    """

    def test_every_real_migration_passes(self) -> None:
        """The guard must not reject what the application actually ships.

        Read from _apply_migrations rather than restated here. The previous
        form hardcoded one entry, so the session_generation migration added
        later was never checked against the guard it has to satisfy: the test
        would have stayed green while a new migration crashed at boot.
        """
        import ast
        import pathlib as _pathlib

        from spectre.web import database
        from spectre.web.database import _assert_safe_ddl

        source = _pathlib.Path(database.__file__).read_text(encoding="utf-8")
        function = next(
            node for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_apply_migrations"
        )
        literals = [
            ast.literal_eval(node) for node in ast.walk(function)
            if isinstance(node, ast.List)
        ]
        migrations = next((lit for lit in literals if lit and isinstance(lit[0], tuple)), [])
        assert migrations, "no migration list found, so this test checks nothing"
        assert len(migrations) >= 2, (
            f"expected the shipped migrations, found only {migrations}"
        )
        for table, column, definition in migrations:
            _assert_safe_ddl(table, column, definition)

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
