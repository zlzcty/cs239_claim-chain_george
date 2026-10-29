import httpx
import pytest
from openai import OpenAI

from claim_chain.check_connection import check_connection, display_environment


def test_environment_masks_keys(capsys: pytest.CaptureFixture[str]) -> None:
    display_environment(
        {"API_KEY": "secret-value", "CUSTOM_KEY": "other-secret", "OPENAI_MODEL": "demo"},
        "CUSTOM_KEY",
    )
    output = capsys.readouterr().out
    assert "secret" not in output
    assert "API_KEY=(set, masked)" in output
    assert "CUSTOM_KEY=(set, masked)" in output
    assert "OPENAI_MODEL=demo" in output


@pytest.mark.parametrize("status", [200, 401, 429])
def test_connection_reports_success_or_failure(
    status: int, capsys: pytest.CaptureFixture[str]
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        body = (
            {
                "id": "test",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}}],
                "created": 0,
                "model": "demo",
                "object": "chat.completion",
            }
            if status == 200
            else {"error": {"message": "sensitive provider response", "type": "test"}}
        )
        return httpx.Response(status, json=body)

    with OpenAI(
        api_key="test-key",
        base_url="https://example.org/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    ) as client:
        assert check_connection(client, "demo") is (status == 200)
    output = capsys.readouterr().out
    assert ("SUCCESS" if status == 200 else f"HTTP {status}") in output
    assert "sensitive" not in output
    assert "test-key" not in output
