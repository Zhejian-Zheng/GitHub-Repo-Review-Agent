import os
import unittest
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage
from test_llm import sample_ai_review_json, sample_report

from repo_review_agent import llm


class ProviderTests(unittest.TestCase):
    def test_factory_is_shared_by_synthesis(self):
        self.assertTrue(
            hasattr(llm, "create_chat_model"), "Synthesis must use LangChain model factory"
        )

    def test_provider_configuration(self):
        from repo_review_agent.provider import create_chat_model

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test",
                "OPENROUTER_API_KEY": "router",
                "ANTHROPIC_API_KEY": "anthropic",
            },
            clear=True,
        ):
            for provider in ("openai", "openrouter", "anthropic", "ollama"):
                with self.subTest(provider=provider):
                    model = create_chat_model(
                        provider=provider,
                        model="test-model",
                        timeout=7,
                        max_output_tokens=123,
                        ollama_url="http://localhost:9999",
                    )
                    self.assertEqual(
                        model.model
                        if provider == "ollama"
                        else model.model_name
                        if provider in ("openai", "openrouter")
                        else model.model,
                        "test-model",
                    )
                    if provider == "ollama":
                        self.assertEqual(model.num_predict, 123)
                        self.assertEqual(model.base_url, "http://localhost:9999")
                        self.assertEqual(model.client_kwargs["timeout"], 7)
                    else:
                        self.assertEqual(model.max_tokens, 123)
                        self.assertEqual(model.max_retries, 0)
                    if provider == "openrouter":
                        self.assertEqual(model.openai_api_base, "https://openrouter.ai/api/v1")

    def test_missing_keys_and_unknown_provider(self):
        from repo_review_agent.provider import create_chat_model

        with patch.dict(os.environ, {}, clear=True):
            for provider in ("openai", "openrouter", "anthropic", "unknown"):
                with self.subTest(provider=provider), self.assertRaises(llm.AIProviderError):
                    create_chat_model(provider=provider)

    def test_missing_extra_explains_installation(self):
        from repo_review_agent.provider import create_chat_model

        with (
            patch("repo_review_agent.provider.import_module", side_effect=ImportError),
            self.assertRaisesRegex(llm.AIProviderError, r"\[ollama\]"),
        ):
            create_chat_model(provider="ollama")

    def test_new_synthesis_requires_all_sections_and_repairs_once(self):
        with patch(
            "repo_review_agent.llm.create_chat_model",
            return_value=FakeListChatModel(
                responses=['{"architecture_summary": ["incomplete"]}', sample_ai_review_json()]
            ),
        ):
            result = llm.add_ai_review(sample_report(), provider="ollama")
        self.assertEqual(result.ai_review.status, "generated")
        self.assertTrue(all(result.ai_review.sections.values()))

    def test_invalid_synthesis_is_not_reported_as_success(self):
        with (
            patch(
                "repo_review_agent.llm.create_chat_model",
                return_value=FakeListChatModel(responses=["not json"]),
            ),
            self.assertRaises(llm.AIProviderError),
        ):
            llm.add_ai_review(sample_report(), provider="ollama")

    def test_error_does_not_echo_provider_secrets(self):
        from repo_review_agent.provider import provider_error

        secret = "sk-sensitive-key"
        with patch.dict(os.environ, {"OPENAI_API_KEY": secret}):
            error = provider_error(RuntimeError(f"Authorization Bearer {secret}"))
        self.assertNotIn(secret, str(error))
        self.assertNotIn("Authorization", str(error))

    def test_message_text_accepts_blocks(self):
        from repo_review_agent.provider import message_text

        self.assertEqual(
            message_text(AIMessage(content=[{"type": "text", "text": "hello"}])), "hello"
        )

    def test_openrouter_preserves_existing_header_environment(self):
        from repo_review_agent.provider import create_chat_model

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test",
                "OPENROUTER_HTTP_REFERER": "https://example.test",
                "OPENROUTER_APP_TITLE": "Repo Review",
            },
            clear=True,
        ):
            model = create_chat_model(provider="openrouter")
        self.assertEqual(
            model.default_headers,
            {"HTTP-Referer": "https://example.test", "X-Title": "Repo Review"},
        )

    def test_openrouter_legacy_header_aliases_and_precedence(self):
        from repo_review_agent.provider import create_chat_model

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test",
                "OPENROUTER_SITE_URL": "https://legacy.test",
                "OPENROUTER_SITE_NAME": "Legacy",
            },
            clear=True,
        ):
            model = create_chat_model(provider="openrouter")
            self.assertEqual(
                model.default_headers, {"HTTP-Referer": "https://legacy.test", "X-Title": "Legacy"}
            )
            with patch.dict(
                os.environ,
                {
                    "OPENROUTER_HTTP_REFERER": "https://current.test",
                    "OPENROUTER_APP_TITLE": "Current",
                },
            ):
                model = create_chat_model(provider="openrouter")
            self.assertEqual(
                model.default_headers,
                {"HTTP-Referer": "https://current.test", "X-Title": "Current"},
            )

    def test_nonpositive_limits_and_sdk_construction_error(self):
        from unittest.mock import Mock

        from repo_review_agent.provider import AIProviderError, create_chat_model

        for args in ({'timeout': 0}, {'max_output_tokens': -1}):
            with self.assertRaises(AIProviderError):
                create_chat_model(provider='ollama', **args)
        integration = Mock()
        integration.ChatOllama.side_effect = ValueError('secret configuration content')
        with patch('repo_review_agent.provider.import_module', return_value=integration), self.assertRaises(AIProviderError) as error:
            create_chat_model(provider='ollama')
        self.assertNotIn('secret configuration content', str(error.exception))

    def test_direct_synthesis_rejects_unverified_code_findings(self):
        import json
        body = json.loads(sample_ai_review_json())
        body['findings'] = [dict(title='Invented', severity='high', path='missing.py',
            start_line=1, end_line=1, evidence='fake', confidence=1, recommendation='Fix')]
        with patch('repo_review_agent.llm.create_chat_model', return_value=FakeListChatModel(
            responses=[json.dumps(body)]
        )), self.assertRaisesRegex(llm.AIProviderError, 'cannot verify'):
            llm.add_ai_review(sample_report(), provider='ollama')
