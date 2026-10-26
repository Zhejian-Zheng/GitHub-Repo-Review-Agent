"""Conservative per-review token reservations, independent of provider billing."""
from __future__ import annotations

import json

from langchain.agents.middleware import AgentMiddleware

from .provider import AIProviderError


class BudgetExceeded(AIProviderError):
    pass


class TokenBudget:
    def __init__(self, limit: int | None, *, output_limit: int):
        if (limit is not None and limit <= 0) or output_limit <= 0:
            raise ValueError('Token limits must be positive.')
        self.limit = limit
        self.output_limit = output_limit
        self.calls = 0
        self.reserved = 0
        self.actual = 0
        self.recorded_calls = 0
        self.usage_complete = True

    def reserve(self, messages, *, tools=None, system_message=None, response_format=None):
        # UTF-8 byte count plus message/schema framing is deliberately conservative.
        # It is a reservation estimate, not a provider tokenizer or money ceiling.
        content = [m.model_dump(exclude_none=True) for m in messages]
        if system_message is not None:
            content.append(system_message.model_dump(exclude_none=True))
        schemas = [t.args_schema.model_json_schema() if hasattr(t, 'args_schema') and t.args_schema else t
                   for t in tools or []]
        if response_format is not None:
            schema = getattr(response_format, 'schema', None)
            schemas.append(schema.model_json_schema() if hasattr(schema, 'model_json_schema') else str(response_format))
        cost = len(json.dumps([content, schemas], ensure_ascii=False, default=str).encode('utf-8')) + 64 * len(messages) + self.output_limit
        if self.limit is not None and self.reserved + cost > self.limit:
            raise BudgetExceeded('AI token budget exhausted before the next model request.')
        self.reserved += cost
        self.calls += 1

    def record(self, messages):
        self.recorded_calls += 1
        for message in messages:
            if message.type != 'ai':
                continue
            usage = getattr(message, 'usage_metadata', None)
            if usage is None:
                self.usage_complete = False
            else:
                self.actual += usage['total_tokens']

    def summary(self):
        return {'model_calls': self.calls, 'reserved_tokens': self.reserved,
                'actual_tokens': self.actual if self.usage_complete and self.recorded_calls == self.calls else None,
                'token_budget': self.limit, 'accounting': 'conservative_reservation'}


class TokenBudgetMiddleware(AgentMiddleware):
    def __init__(self, ledger: TokenBudget):
        self.ledger = ledger

    def wrap_model_call(self, request, handler):
        self.ledger.reserve(request.messages, tools=request.tools,
                            system_message=request.system_message, response_format=request.response_format)
        response = handler(request)
        self.ledger.record(response.result)
        return response
