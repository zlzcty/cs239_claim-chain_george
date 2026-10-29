import sys

import pytest

from claim_chain.cli import main
from claim_chain.workflow import MIN_CALLS


@pytest.mark.parametrize("max_calls", [12, 13])
def test_cli_rejects_budgets_without_research_allowance(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], max_calls: int
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["claim-audit", "--model", "test", "--max-calls", str(max_calls)]
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert f"max-calls >= {MIN_CALLS}" in capsys.readouterr().err
