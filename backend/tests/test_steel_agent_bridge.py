"""P3 Bridge event translation and Feature Flag regression tests."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import AgentChatRequest
from routers import agent_chat
from steel_agent import bridge
from steel_agent.tools import registry as adapters


def test_fake_bridge_reaches_done_with_sse_compatible_events(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STEEL_AGENT_TEST_MODEL", "fake")
    monkeypatch.setenv("STEEL_AGENT_STATE_DIR", str(tmp_path / "agent-state"))
    monkeypatch.delenv("STEEL_AGENT_SKILL_ID", raising=False)
    monkeypatch.setattr(adapters, "query_receipt", lambda **_kwargs: [])

    events = list(bridge.run_new_agent("查询测试单据", [], session_id="p3-session"))

    assert [event["type"] for event in events] == [
        "stage",
        "stage",
        "tool_call",
        "tool_result",
        "stage",
        "delta",
        "done",
    ]
    assert events[2]["name"] == "db_lookup_receipt"
    assert events[3]["ok"] is True
    assert events[-1]["reply"] == events[-2]["content"]
    assert set(events[-1]["audit"]) == {"run_id", "tool_calls", "risks", "succeeded", "denied", "failed", "elapsed_ms"}
    assert "filepath" not in json.dumps(events[-1], ensure_ascii=False)


def test_bridge_returns_safe_error_event_for_invalid_explicit_skill(monkeypatch) -> None:
    monkeypatch.setenv("STEEL_AGENT_SKILL_ID", "not-declared")

    events = list(bridge.run_new_agent("测试", []))

    assert events == [{"type": "error", "message": "新 Agent 暂时无法启动，请检查模型配置后重试。"}]


def test_feature_flag_defaults_to_legacy_and_selects_new_bridge(monkeypatch) -> None:
    monkeypatch.delenv("STEEL_USE_NEW_AGENT", raising=False)
    assert agent_chat._use_new_agent() is False
    monkeypatch.setenv("STEEL_USE_NEW_AGENT", "1")
    assert agent_chat._use_new_agent() is True


def test_stream_route_uses_the_new_bridge_when_flag_is_enabled(monkeypatch) -> None:
    monkeypatch.setenv("STEEL_USE_NEW_AGENT", "1")
    monkeypatch.setattr(agent_chat, "run_new_agent", lambda *_args, **_kwargs: iter([{"type": "done", "reply": "new", "history": []}]))
    request = AgentChatRequest(message="测试")

    response = asyncio.run(agent_chat.agent_chat_stream(request))

    async def body() -> str:
        return "".join([chunk async for chunk in response.body_iterator])

    payload = asyncio.run(body())
    assert json.loads(payload.removeprefix("data: ").strip())["reply"] == "new"


def test_stream_route_keeps_legacy_loop_when_flag_is_unset(monkeypatch) -> None:
    monkeypatch.delenv("STEEL_USE_NEW_AGENT", raising=False)
    monkeypatch.setattr(agent_chat, "agent_loop_stream", lambda *_args, **_kwargs: iter([{"type": "done", "reply": "legacy", "history": []}]))
    request = AgentChatRequest(message="测试")

    response = asyncio.run(agent_chat.agent_chat_stream(request))

    async def body() -> str:
        return "".join([chunk async for chunk in response.body_iterator])

    payload = asyncio.run(body())
    assert json.loads(payload.removeprefix("data: ").strip())["reply"] == "legacy"
