"""The proxy-CA build hook actually inserts the CA into the Dockerfile.

Audit F-176. verify-container.sh and simulate-pipeline.sh matched
``COPY requirements.lock ./``, a line no Dockerfile contains (both copy
requirements-runtime.txt), so nothing was inserted, while each printed that
it was building with the proxy CA trusted.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from tests.unit.test_deployment_contract import _repo_only

_AWK = re.compile(r"awk '\n(.*?)\n\s*' ", re.S)


@pytest.mark.parametrize("script", ["scripts/verify-container.sh", "scripts/simulate-pipeline.sh"])
@pytest.mark.parametrize("dockerfile", ["Dockerfile", "Dockerfile.docker-only"])
def test_the_hook_adds_the_ca_to_the_build(script: str, dockerfile: str) -> None:
    awk = shutil.which("awk")
    if awk is None:
        pytest.skip("awk not available")
    program = _AWK.search(_repo_only(script).read_text(encoding="utf-8"))
    assert program, f"{script} has no awk program"
    source = _repo_only(dockerfile).read_text(encoding="utf-8")
    # S603: a resolved binary and a program read from the repository's own script.
    out = subprocess.run(  # noqa: S603
        [awk, program.group(1)], input=source, capture_output=True, text=True, check=True,
    ).stdout
    assert "PIP_CERT" in out
    assert out != source


@pytest.mark.parametrize("script", ["scripts/verify-container.sh", "scripts/simulate-pipeline.sh"])
def test_the_script_refuses_an_unchanged_dockerfile(script: str) -> None:
    text = _repo_only(script).read_text(encoding="utf-8")
    assert "cmp -s" in text, "an unmatched pattern must fail, not report success"
