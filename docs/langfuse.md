# Optional Langfuse tracing

Langfuse records the model and tool execution tree, timings, model name, token usage and costs when supplied by the provider. Tracing is disabled by default and is independent of the selected model provider.

Install the tested Python SDK integration:

```sh
python -m pip install -e ".[langfuse]"
# To include all model providers and the web application:
python -m pip install -e ".[all,langfuse]"
```

Set these values in the backend environment or local `.env` file:

```dotenv
REPO_REVIEW_LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=your-project-public-key
LANGFUSE_SECRET_KEY=your-project-secret-key
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

Choose the base URL for your Langfuse project region or self-hosted instance. All three connection values are required; there is no implicit destination. Keep the secret key in backend configuration. Restart the process after changing connection settings. Langfuse SDK 4.16.0 is pinned because lifecycle and privacy behavior are tested against that version.

Run an AI review normally. Agent reviews capture model and repository-tool calls in one trace. Direct synthesis and its possible repair request share one parent trace. Rules-only reviews do not produce model traces. Trace names are generic; no repository name, local path, account identifier or review ID is attached by this integration.

## Privacy behavior

The SDK mask callback replaces complete input, output and metadata payloads with an omission marker. The export-stage hook additionally removes all attributes except observation type, severity level, model name, usage, cost and completion timing. Raw exception messages are replaced before the SDK sees error events. An isolated tracer provider prevents collection of unrelated application spans. There is no content-capture option.

This means source code, prompts, reports, tool arguments, tool output, arbitrary metadata, model parameters and raw error details are omitted. Model and runnable/tool names, timing, trace identifiers and provider-reported aggregate usage remain visible. You cannot inspect prompts or generated reports in Langfuse; use the application's review report for that. Configure other tracing libraries separately: this integration does not control exporters installed by another application.

## Failure and shutdown behavior

Missing configuration, a missing optional SDK, setup errors and callback failures leave reviews operational. The review's own exceptions still propagate normally. A slow exporter never delays review cleanup by more than two seconds; at most one background flush is active per client. The client is shared within a process, while callback state is separate for every review.

Short-lived CLI and job processes flush on context exit. Delivery is best effort: a failed or slow connection may lose traces when the process exits. The integration replaces the SDK's unbounded exit cleanup with bounded best-effort cleanup. That narrow lifecycle compatibility check is covered by tests using the pinned SDK; re-run those tests before upgrading.

There is no automatic network authentication check during review startup. To troubleshoot, first verify that the optional extra is installed and that the enable flag, both project keys, and the correct destination URL are configured. Then run a small AI review and check the project's traces. Missing token or cost fields can mean the chosen provider did not return usage.

## Verification

```sh
python -m unittest discover -s tests -p 'test_telemetry.py'
python -m unittest discover -s tests -p 'test_tracing_integration.py'
```

The SDK integration tests use an in-memory exporter and fake credentials; they do not contact Langfuse. They verify masking of nested content, raw errors and model parameters; preservation of usage; and grouping of repeated calls under one trace. These tests skip when the optional SDK is not installed.

Implementation references: [LangChain integration](https://langfuse.com/integrations/frameworks/langchain), [Python v3 to v4 migration](https://langfuse.com/docs/observability/sdk/upgrade-path/python-v3-to-v4), [masking](https://langfuse.com/docs/observability/features/masking), and [Python SDK reference](https://python.reference.langfuse.com/langfuse).
