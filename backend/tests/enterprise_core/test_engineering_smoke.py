from __future__ import annotations

import json

from enterprise_agent import __version__
from enterprise_agent.cli import main


def test_package_has_version() -> None:
    assert __version__ == "0.1.0"


def test_cli_version(capsys) -> None:
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_cli_doctor_is_machine_readable_and_secret_free(capsys) -> None:
    assert main(["doctor"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["supported_python"] is True
    assert payload["default_model"] == "fake"
    assert all("key" not in key.lower() for key in payload)
