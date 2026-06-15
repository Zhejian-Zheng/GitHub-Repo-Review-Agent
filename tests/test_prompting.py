import json
import unittest

from repo_review_agent.prompting import build_few_shot_examples, build_prompt_tuning_guidance


class PromptingTests(unittest.TestCase):
    def test_english_few_shot_examples_keep_required_json_shape(self) -> None:
        examples = json.loads(build_few_shot_examples("en"))

        self.assertEqual(len(examples), 2)
        risky_response = examples[1]["good_response"]
        self.assertEqual(
            set(risky_response),
            {"architecture_summary", "risks", "project_highlights", "next_steps"},
        )
        self.assertIn("risky-js-app", examples[1]["input_pattern"])
        self.assertIn("package.json", " ".join(risky_response["risks"]))
        self.assertIn("Dockerfile", " ".join(risky_response["risks"]))

    def test_chinese_few_shot_examples_use_chinese_content_and_fixed_keys(self) -> None:
        examples = json.loads(build_few_shot_examples("zh-CN"))

        healthy_response = examples[0]["good_response"]
        self.assertEqual(
            set(healthy_response),
            {"architecture_summary", "risks", "project_highlights", "next_steps"},
        )
        self.assertIn("测试和交付纪律", healthy_response["project_highlights"][0])
        self.assertIn(".github/workflows/ci.yml", healthy_response["architecture_summary"][0])

    def test_prompt_tuning_guidance_is_evidence_bound(self) -> None:
        guidance = build_prompt_tuning_guidance("en")

        self.assertIn("source of truth", guidance)
        self.assertIn("evidence_paths", guidance)
        self.assertIn("Return only the JSON object", guidance)

    def test_chinese_prompt_tuning_guidance_is_evidence_bound(self) -> None:
        guidance = build_prompt_tuning_guidance("zh-CN")

        self.assertIn("确定性扫描", guidance)
        self.assertIn("evidence_paths", guidance)
        self.assertIn("只能是 JSON 对象", guidance)


if __name__ == "__main__":
    unittest.main()
