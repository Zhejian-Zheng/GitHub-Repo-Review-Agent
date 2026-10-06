# Review quality evaluations

Run the bundled labeled fixtures without a model or network:

```sh
repo-review-evaluate tests/fixtures/evaluation/dataset.json --output evaluation.json
# Equivalent when the editable package entry point has not been refreshed:
python -m repo_review_agent.evaluation tests/fixtures/evaluation/dataset.json --output evaluation.json
```

A dataset is a JSON object with up to 50 cases. Each case has a unique `id`, a local `target` directory inside the dataset directory, and finding title labels. `expected_findings` lists required findings; `forbidden_findings` lists known false positives. Optional `acceptable_findings` must be an exhaustive list of allowed finding titles before a precision score is meaningful. The bundled cases use partial labels and report precision as unavailable.

```json
{"cases":[{"id":"small-service","target":"small-service",
  "expected_findings":["Add an explicit open-source license"],
  "forbidden_findings":["No major project hygiene gaps detected"]}]}
```

Each case runs against a fresh copy. The runner excludes Git data, virtual environments, installed npm packages and the expected-label file; it preserves links without following them. Datasets are bounded to 1 MB and may repeat each case up to five times. Repository code is never executed by default.

Compare models or prompt/code revisions by saving separate labeled runs:

```sh
repo-review-evaluate tests/fixtures/evaluation/dataset.json \
  --provider ollama --model llama3.2 --label baseline --repeats 3 --output baseline.json
repo-review-evaluate tests/fixtures/evaluation/dataset.json \
  --provider openrouter --model your-tool-capable-model --label candidate --repeats 3 --output candidate.json
```

AI evaluation is opt-in and uses the normal provider credentials. Dataset SHA-256 identifies the label version. Labels identify your experiment, while provider/model and per-case trials are included in output. Keep the repository fixtures and application revision fixed when comparing runs. The local result does not upload fixture contents or finding text to Langfuse.

Recall measures required titles found; precision measures found titles inside the exhaustive allowed list. `forbidden_pass` rejects known false positives. `citation_validity` checks AI quote locations against redacted source, when there are cited AI findings; it does not determine whether the defect interpretation is correct. `ai_success` checks complete structured AI output. Latency and provider-reported actual tokens are included; missing token/cost data is unknown, not zero.

The command returns nonzero when recall is below `--min-recall` (default 1), any forbidden title occurs, or an explicitly requested AI review fails. `--min-precision` requires exhaustive labels and fails when precision is unavailable. CI runs the bundled offline dataset as a separate quality gate.

With the existing Langfuse enable flag/credentials, the runner creates a parent evaluation trace and queues known aggregate numeric scores for it. Model/tool traces nest below it. No dataset ID, path, input, label text, source, report or arbitrary comments are sent as score metadata. Delivery remains best effort; `langfuse_scores_queued` means accepted by the SDK, not confirmed by the remote server. See [Langfuse setup](langfuse.md) and its [Scores API](https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-sdk).
