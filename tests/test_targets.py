import os
import unittest
from pathlib import Path
from unittest.mock import patch

from repo_review_agent.targets import resolve_target


class TargetBoundsTests(unittest.TestCase):
    def test_oversized_checkout_or_git_objects_are_cleaned(self) -> None:
        for name in ('large.bin', '.git/objects/pack/large.pack'):
            created = []

            def clone(command: list[str], name: str = name, created: list[Path] = created, **kwargs) -> None:
                root = Path(command[-1])
                created.append(root.parent)
                path = root / name
                path.parent.mkdir(parents=True)
                path.write_bytes(b'x' * 1_000_001)

            with self.subTest(name=name), patch.dict(os.environ, {'REPO_REVIEW_CLONE_MAX_BYTES': '1000000'}), patch(
                'repo_review_agent.targets.subprocess.run', side_effect=clone
            ), self.assertRaisesRegex(RuntimeError, 'budget'), resolve_target('https://github.com/example/repo'):
                self.fail('oversized checkout accepted')
            self.assertFalse(created[0].exists())

    def test_checkout_entry_budget_counts_empty_directories(self) -> None:
        def clone(command: list[str], **kwargs) -> None:
            root = Path(command[-1])
            root.mkdir()
            for index in range(4):
                (root / str(index)).mkdir()

        with patch.dict(os.environ, {'REPO_REVIEW_MAX_WALK_ENTRIES': '3'}), patch(
            'repo_review_agent.targets.subprocess.run', side_effect=clone
        ), self.assertRaisesRegex(RuntimeError, 'budget'), resolve_target('https://github.com/example/repo'):
            self.fail('entry budget ignored')

    def test_unverifiable_checkout_is_rejected_and_cleaned(self) -> None:
        created = []

        def clone(command: list[str], **kwargs) -> None:
            root = Path(command[-1])
            root.mkdir()
            created.append(root.parent)

        with patch('repo_review_agent.targets.subprocess.run', side_effect=clone), patch(
            'repo_review_agent.targets._check_checkout_budget', side_effect=RuntimeError('Repository acquisition budget could not be verified.')
        ), self.assertRaisesRegex(RuntimeError, 'could not be verified'):
            resolve_target('https://github.com/example/repo').__enter__()
        self.assertFalse(created[0].exists())
