import importlib.util
import os
import threading
import time
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.runnables import RunnableLambda

from repo_review_agent import telemetry


class TelemetryTests(unittest.TestCase):
    def test_disabled_even_when_credentials_exist(self):
        with (
            patch.dict(
                os.environ, {"LANGFUSE_PUBLIC_KEY": "pk", "LANGFUSE_SECRET_KEY": "sk"}, clear=True
            ),
            patch.object(
                telemetry, "_initialize", side_effect=AssertionError("must not initialize")
            ),
            telemetry.review_tracing() as config,
        ):
            self.assertEqual(config, {})

    def test_missing_credentials_and_sdk_do_not_break_reviews(self):
        with (
            patch.dict(os.environ, {"REPO_REVIEW_LANGFUSE_ENABLED": "true"}, clear=True),
            telemetry.review_tracing() as config,
        ):
            self.assertEqual(config, {})
        with (
            patch.dict(os.environ, self.settings(), clear=True),
            patch.object(telemetry, "_initialize", side_effect=ImportError("unavailable")),
            telemetry.review_tracing() as config,
        ):
            self.assertEqual(config, {})

    def test_review_exception_is_preserved_and_cleanup_failure_ignored(self):
        state = SimpleNamespace(
            client=SimpleNamespace(flush=lambda: None), handler_factory=lambda: None
        )
        with (
            patch.dict(os.environ, self.settings(), clear=True),
            patch.object(telemetry, "_initialize", return_value=state),
            patch.object(telemetry, "_flush_bounded", side_effect=RuntimeError("telemetry")),
            self.assertRaisesRegex(ValueError, "review"),
            telemetry.review_tracing(),
        ):
            raise ValueError("review")

    def test_bounded_flush_returns_and_does_not_spawn_duplicate_flushes(self):
        release = threading.Event()
        started = threading.Event()
        calls = []

        def flush():
            calls.append(1)
            started.set()
            release.wait(2)

        state = telemetry._State(SimpleNamespace(flush=flush), lambda: None)
        try:
            before = time.monotonic()
            telemetry._flush_bounded(state, 0.02)
            self.assertTrue(started.is_set())
            telemetry._flush_bounded(state, 0.02)
            self.assertLess(time.monotonic() - before, 0.5)
            self.assertEqual(calls, [1])
        finally:
            release.set()

    def test_callback_failures_do_not_change_chain_result(self):

        class Broken:
            def on_chain_start(self, *args, **kwargs):
                raise RuntimeError("secret callback failure")

            def on_chain_end(self, *args, **kwargs):
                raise RuntimeError("secret callback failure")

        handler = telemetry._SafeCallback(Broken())
        result = RunnableLambda(lambda text: text.upper()).invoke(
            "ok", config={"callbacks": [handler]}
        )
        self.assertEqual(result, "OK")

    def test_sdk_mask_suppresses_nested_source_instead_of_regex_only(self):
        self.assertEqual(
            telemetry.mask_payload(data={"messages": ["private code"], "unknown-secret": object()}),
            "[CONTENT OMITTED]",
        )

    def test_enabled_callbacks_are_per_review(self):
        state = telemetry._State(
            SimpleNamespace(
                flush=lambda: None, start_as_current_observation=lambda **kwargs: nullcontext()
            ),
            object,
        )
        with (
            patch.dict(os.environ, self.settings(), clear=True),
            patch.object(telemetry, "_initialize", return_value=state),
        ):
            with telemetry.review_tracing() as first:
                self.assertEqual(len(first["callbacks"]), 1)
            with telemetry.review_tracing() as second:
                self.assertIsNot(first["callbacks"][0], second["callbacks"][0])

    def test_invalid_destination_never_initializes(self):
        for address in ("", "file:///tmp/traces", "https://user:password@example.com"):
            with self.subTest(address=address):
                settings = {**self.settings(), "LANGFUSE_BASE_URL": address}
                with (
                    patch.dict(os.environ, settings, clear=True),
                    patch.object(
                        telemetry, "_initialize", side_effect=AssertionError("must not initialize")
                    ),
                    telemetry.review_tracing() as config,
                ):
                    self.assertEqual(config, {})

    @unittest.skipUnless(
        importlib.util.find_spec("langfuse"), "Install .[langfuse] for SDK integration"
    )
    def test_real_initialization_creates_private_client_and_reuses_it(self):
        import uuid

        from langfuse import Langfuse
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        exporter = InMemorySpanExporter()

        def create(**kwargs):
            return Langfuse(**kwargs, span_exporter=exporter)

        key = "pk-test-" + uuid.uuid4().hex
        with (
            patch.object(telemetry, "_STATE", None),
            patch.object(telemetry, "_STATE_KEY", None),
            patch("langfuse.Langfuse", side_effect=create),
        ):
            state = telemetry._initialize(key, "fake", "http://localhost:1")
            self.assertIs(state, telemetry._initialize(key, "fake", "http://localhost:1"))
            with self.assertRaises(ValueError):
                telemetry._initialize(key, "changed", "http://localhost:1")
            try:
                result = RunnableLambda(lambda text: text).invoke(
                    "private content",
                    config={
                        "callbacks": [state.handler_factory()],
                        "run_name": "repository-review",
                    },
                )
                self.assertEqual(result, "private content")
                telemetry._flush_bounded(state)
                spans = exporter.get_finished_spans()
                self.assertTrue(spans)
                self.assertNotIn("private content", "\n".join(span.to_json() for span in spans))
                settings = {
                    **self.settings(),
                    "LANGFUSE_PUBLIC_KEY": key,
                    "LANGFUSE_SECRET_KEY": "fake",
                    "LANGFUSE_BASE_URL": "http://localhost:1",
                }
                exporter.clear()
                with (
                    patch.dict(os.environ, settings, clear=True),
                    telemetry.review_tracing() as config,
                ):
                    RunnableLambda(lambda text: text).invoke("private first", config=config)
                    RunnableLambda(lambda text: text).invoke("private retry", config=config)
                spans = exporter.get_finished_spans()
                self.assertEqual(len({span.context.trace_id for span in spans}), 1)
                self.assertEqual(len([span for span in spans if span.parent is None]), 1)
            finally:
                state.client.shutdown()

    @staticmethod
    def settings():
        return {
            "REPO_REVIEW_LANGFUSE_ENABLED": "true",
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
            "LANGFUSE_BASE_URL": "http://localhost:3000",
        }

    @unittest.skipUnless(
        importlib.util.find_spec("langfuse"), "Install .[langfuse] for SDK integration"
    )
    def test_real_sdk_exports_structure_and_usage_without_content_or_error_text(self):
        import uuid

        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        exporter = InMemorySpanExporter()
        provider = TracerProvider(shutdown_on_exit=False)
        key = "pk-test-" + uuid.uuid4().hex
        client = Langfuse(
            public_key=key,
            secret_key="fake",
            base_url="http://localhost:1",
            mask=telemetry.mask_payload,
            mask_otel_spans=telemetry.mask_spans,
            tracer_provider=provider,
            span_exporter=exporter,
        )
        try:
            handler = telemetry._SafeCallback(CallbackHandler(public_key=key))

            def broken(text):
                raise ValueError("private exception " + text)

            chain = RunnableLambda(broken)
            with self.assertRaises(ValueError):
                chain.invoke(
                    "private source code",
                    config={"callbacks": [handler], "metadata": {"private": "private metadata"}},
                )
            with client.start_as_current_observation(
                name="generation",
                as_type="generation",
                model="test-model",
                input="private prompt",
                output="private response",
                usage_details={"input": 10, "output": 4},
                model_parameters={"private": "private parameter"},
            ):
                pass
            client.flush()
            spans = exporter.get_finished_spans()
            self.assertGreaterEqual(len(spans), 2)
            dumped = "\n".join(span.to_json() for span in spans)
            self.assertNotIn("private", dumped)
            generation = next(span for span in spans if span.name == "generation")
            self.assertIn(
                '"input": 10', generation.attributes["langfuse.observation.usage_details"]
            )
            self.assertIn("generation", dumped)
        finally:
            client.shutdown()
            provider.shutdown()
