"""Scripted model that still executes the real LangChain agent graph."""

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from pydantic import Field

SECTIONS = {
    "architecture_summary": ["Scanner and analyzer with file-backed evidence."],
    "risks": ["Evidence-bound risk."],
    "project_highlights": ["Deterministic analysis."],
    "next_steps": ["Add runtime tests."],
}


class ScriptedModel(FakeMessagesListChatModel):
    seen_messages: list = Field(default_factory=list)

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self

    def _generate(self, messages, **kwargs):
        self.seen_messages.append(list(messages))
        return super()._generate(messages, **kwargs)


def call(name, args=None, call_id="call-1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": call_id}])


def final(sections=None):
    return call("ReviewSections", SECTIONS if sections is None else sections, "final")
