import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "render.yaml"
PAGES_WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"
FRONTEND_ENV_EXAMPLE = ROOT / "frontend" / ".env.production.example"


class DeploymentConfigTests(unittest.TestCase):
    def test_render_blueprint_defines_backend_service(self) -> None:
        render_yaml = RENDER.read_text(encoding="utf-8")

        self.assertIn("runtime: docker", render_yaml)
        self.assertIn("dockerfilePath: ./deploy/render.Dockerfile", render_yaml)
        self.assertIn("dockerCommand: repo-review-web", render_yaml)
        self.assertIn("healthCheckPath: /healthz", render_yaml)
        self.assertIn("REPO_REVIEW_CORS_ORIGINS", render_yaml)
        self.assertIn("REPO_REVIEW_REQUIRE_AUTH", render_yaml)
        self.assertIn("SUPABASE_SERVICE_ROLE_KEY", render_yaml)

    def test_pages_workflow_injects_live_demo_configuration(self) -> None:
        workflow = PAGES_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("VITE_API_BASE_URL", workflow)
        self.assertIn("vars.REPO_REVIEW_API_BASE_URL", workflow)
        self.assertIn("VITE_SUPABASE_URL", workflow)
        self.assertIn("VITE_SUPABASE_ANON_KEY", workflow)

    def test_frontend_production_env_example_documents_api_base_url(self) -> None:
        example = FRONTEND_ENV_EXAMPLE.read_text(encoding="utf-8")

        self.assertIn("VITE_API_BASE_URL=", example)
        self.assertIn("VITE_SUPABASE_URL=", example)
        self.assertIn("VITE_SUPABASE_ANON_KEY=", example)


if __name__ == "__main__":
    unittest.main()
