import os
import select
import signal
import subprocess
import sys
import unittest
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from repo_review_agent.targets import _check_checkout_budget, resolve_target


class TargetBoundsTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'requires POSIX process groups')
    def test_real_clone_group_and_descendant_stop_on_breach_or_timeout(self) -> None:
        for breach in (True, False):
            with self.subTest(breach=breach):
                self._assert_real_clone_group_stops(breach)

    def _assert_real_clone_group_stops(self, breach: bool) -> None:
        real_popen = subprocess.Popen
        read_fd, write_fd = os.pipe()
        processes: list[subprocess.Popen[bytes]] = []
        created: list[Path] = []
        code = (
            'import os, pathlib, sys, time\n'
            'if os.fork() == 0:\n'
            '    time.sleep(30)\n'
            '    os._exit(0)\n'
            'if sys.argv[2] == "True":\n'
            '    pathlib.Path(sys.argv[1], "pack").write_bytes(b"x" * 1000000)\n'
            'time.sleep(30)\n'
        )

        def start(command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
            created.append(Path(command[-1]))
            proc = real_popen([sys.executable, '-c', code, command[-1], str(breach)],
                              pass_fds=(write_fd,), **kwargs)
            processes.append(proc)
            os.close(write_fd)
            return proc

        try:
            with patch.dict(os.environ, {'REPO_REVIEW_CLONE_MAX_BYTES': '1000000',
                                         'REPO_REVIEW_CLONE_TIMEOUT': '2'}), patch(
                'repo_review_agent.targets.subprocess.Popen', side_effect=start
            ), self.assertRaisesRegex(RuntimeError, 'budget') if breach else self.assertRaises(
                subprocess.TimeoutExpired
            ):
                resolve_target('https://github.com/example/repo').__enter__()
            self.assertEqual(processes[0].returncode, -signal.SIGKILL)
            self.assertFalse(created[0].parent.exists())
            # EOF proves BOTH the clone and its descendant closed their fd.
            self.assertTrue(select.select([read_fd], [], [], 2)[0])
            self.assertEqual(os.read(read_fd, 1), b'')
        finally:
            for proc in processes:
                with suppress(ProcessLookupError, PermissionError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            if not processes:
                os.close(write_fd)
            os.close(read_fd)

    def test_mid_clone_growth_kills_group_before_cleanup(self) -> None:
        for name in ('large.bin', '.git/objects/pack/large.pack'):
            with self.subTest(name=name):
                self._assert_mid_clone_growth_is_rejected(name)

    def _assert_mid_clone_growth_is_rejected(self, name: str) -> None:
        created: list[Path] = []
        proc = Mock(pid=12345)
        proc.poll.return_value = None

        def start(command: list[str], **kwargs: object) -> Mock:
            created.append(Path(command[-1]))
            return proc

        def grow(timeout: float | None = None) -> None:
            if timeout is not None:
                path = created[0] / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'x' * 1_000_000)
                raise subprocess.TimeoutExpired('git', timeout)

        def kill(pid: int, sig: int) -> None:
            self.assertTrue(created[0].exists())
            self.assertEqual((pid, sig), (proc.pid, signal.SIGKILL))

        proc.wait.side_effect = grow
        with patch.dict(os.environ, {'REPO_REVIEW_CLONE_MAX_BYTES': '1000000'}), patch(
            'repo_review_agent.targets.subprocess.Popen', side_effect=start
        ), patch('repo_review_agent.targets.os.killpg', side_effect=kill) as kill_group, self.assertRaisesRegex(
            RuntimeError, 'acquisition budget exceeded'
        ):
            resolve_target('https://github.com/example/repo').__enter__()
        kill_group.assert_called_once()
        self.assertEqual(proc.wait.call_count, 2)
        proc.wait.assert_called_with()
        self.assertFalse(created[0].parent.exists())

    def test_mid_clone_entry_overflow_and_unreadable_metadata_fail_closed(self) -> None:
        for unreadable in (False, True):
            with self.subTest(unreadable=unreadable):
                self._assert_mid_clone_probe_fails(unreadable)

    def _assert_mid_clone_probe_fails(self, unreadable: bool) -> None:
        created: list[Path] = []
        proc = Mock(pid=12345)
        proc.poll.return_value = None

        def start(command: list[str], **kwargs: object) -> Mock:
            root = Path(command[-1])
            created.append(root)
            for index in range(4):
                (root / str(index)).mkdir()
            return proc

        real_scandir = os.scandir

        def scan(path: Path | int) -> Iterator[os.DirEntry[str]]:
            # Only fail the probe, allowing fd-based TemporaryDirectory cleanup.
            if unreadable and isinstance(path, Path):
                raise PermissionError()
            return real_scandir(path)

        with patch.dict(os.environ, {'REPO_REVIEW_MAX_WALK_ENTRIES': '3'}), patch(
            'repo_review_agent.targets.subprocess.Popen', side_effect=start
        ), patch('repo_review_agent.targets.os.killpg') as kill_group, patch(
            'repo_review_agent.targets.os.scandir',
            side_effect=scan,
        ), self.assertRaisesRegex(RuntimeError, 'budget'):
            resolve_target('https://github.com/example/repo').__enter__()
        kill_group.assert_called_once_with(proc.pid, signal.SIGKILL)
        proc.wait.assert_called_once_with()
        self.assertFalse(created[0].parent.exists())

    def test_under_limit_clone_is_noninteractive_and_checked_again_after_exit(self) -> None:
        proc = Mock(pid=12345, returncode=0)
        proc.poll.side_effect = [None, 0]
        with patch('repo_review_agent.targets.subprocess.Popen', return_value=proc) as start, patch(
            'repo_review_agent.targets._check_checkout_budget', wraps=_check_checkout_budget
        ) as check, patch('repo_review_agent.targets.os.killpg') as kill:
            with resolve_target('https://github.com/example/repo') as root:
                self.assertTrue(root.is_dir())
                self.assertEqual(check.call_count, 2)
                self.assertEqual(check.call_args_list[0].kwargs, {'cloning': True})
                check.assert_called_with(root)
            self.assertFalse(root.parent.exists())
        kill.assert_not_called()
        command = start.call_args.args[0]
        self.assertEqual(command, ['git', '-c', 'credential.helper=', 'clone', '--depth', '1', '--',
                                   'https://github.com/example/repo', str(root)])
        options = start.call_args.kwargs
        self.assertTrue(options['start_new_session'])
        for stream in ('stdin', 'stdout', 'stderr'):
            self.assertEqual(options[stream], subprocess.DEVNULL)
        self.assertEqual(options['env']['GIT_TERMINAL_PROMPT'], '0')
        self.assertEqual(options['env']['GCM_INTERACTIVE'], 'never')
        self.assertEqual(options['env']['GIT_SSH_COMMAND'], 'ssh -oBatchMode=yes -oConnectTimeout=15')
        self.assertGreater(proc.wait.call_args.kwargs['timeout'], 0)
        self.assertLessEqual(proc.wait.call_args.kwargs['timeout'], 0.2)

    def test_failed_clone_kills_group_and_cleans_partial_checkout(self) -> None:
        created: list[Path] = []
        proc = Mock(pid=12345, returncode=128)
        proc.poll.return_value = 128

        def start(command: list[str], **kwargs: object) -> Mock:
            created.append(Path(command[-1]))
            (created[0] / 'partial').write_bytes(b'x')
            return proc

        with patch('repo_review_agent.targets.subprocess.Popen', side_effect=start), patch(
            'repo_review_agent.targets.os.killpg', side_effect=ProcessLookupError
        ) as kill, self.assertRaises(subprocess.CalledProcessError) as caught:
            resolve_target('https://github.com/example/repo').__enter__()
        self.assertEqual(caught.exception.returncode, 128)
        kill.assert_called_once_with(proc.pid, signal.SIGKILL)
        proc.wait.assert_called_once_with()
        self.assertFalse(created[0].parent.exists())

    def test_exact_byte_limit_is_rejected_and_symlinks_are_not_followed(self) -> None:
        with TemporaryDirectory() as temp, TemporaryDirectory() as external:
            root = Path(temp)
            (Path(external) / 'large').write_bytes(b'x' * 10000)
            (root / 'link').symlink_to(external, target_is_directory=True)
            size = (root / 'link').lstat().st_size
            with patch.dict(os.environ, {'REPO_REVIEW_CLONE_MAX_BYTES': str(size + 1)}):
                _check_checkout_budget(root)
                _check_checkout_budget(root, cloning=True)
            for cloning in (False, True):
                with patch.dict(os.environ, {'REPO_REVIEW_CLONE_MAX_BYTES': str(size)}), self.assertRaisesRegex(
                    RuntimeError, 'budget exceeded'
                ):
                    _check_checkout_budget(root, cloning=cloning)

    def test_only_live_scan_tolerates_disappearing_entries(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            for cloning in (False, True):
                with patch('repo_review_agent.targets.os.scandir', side_effect=FileNotFoundError):
                    if cloning:
                        _check_checkout_budget(root, cloning=True)
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'could not be verified'):
                            _check_checkout_budget(root)

    def test_local_target_skips_clone_and_acquisition_budget(self) -> None:
        with TemporaryDirectory() as temp, patch(
            'repo_review_agent.targets.subprocess.Popen'
        ) as start, patch('repo_review_agent.targets._check_checkout_budget') as check:
            with resolve_target(temp) as root:
                self.assertEqual(root, Path(temp).resolve())
            self.assertTrue(root.exists())
        start.assert_not_called()
        check.assert_not_called()

    def test_oversized_checkout_or_git_objects_are_cleaned(self) -> None:
        for name in ('large.bin', '.git/objects/pack/large.pack'):
            created = []

            def clone(target: str, root: Path, name: str = name, created: list[Path] = created) -> None:
                created.append(root.parent)
                path = root / name
                path.parent.mkdir(parents=True)
                path.write_bytes(b'x' * 1_000_001)

            with self.subTest(name=name), patch.dict(os.environ, {'REPO_REVIEW_CLONE_MAX_BYTES': '1000000'}), patch(
                'repo_review_agent.targets._run_monitored_clone', side_effect=clone
            ), self.assertRaisesRegex(RuntimeError, 'budget'), resolve_target('https://github.com/example/repo'):
                self.fail('oversized checkout accepted')
            self.assertFalse(created[0].exists())

    def test_checkout_entry_budget_counts_empty_directories(self) -> None:
        def clone(target: str, root: Path) -> None:
            root.mkdir()
            for index in range(4):
                (root / str(index)).mkdir()

        with patch.dict(os.environ, {'REPO_REVIEW_MAX_WALK_ENTRIES': '3'}), patch(
            'repo_review_agent.targets._run_monitored_clone', side_effect=clone
        ), self.assertRaisesRegex(RuntimeError, 'budget'), resolve_target('https://github.com/example/repo'):
            self.fail('entry budget ignored')

    def test_unverifiable_checkout_is_rejected_and_cleaned(self) -> None:
        created = []

        def clone(target: str, root: Path) -> None:
            root.mkdir()
            created.append(root.parent)

        with patch('repo_review_agent.targets._run_monitored_clone', side_effect=clone), patch(
            'repo_review_agent.targets._check_checkout_budget', side_effect=RuntimeError('Repository acquisition budget could not be verified.')
        ), self.assertRaisesRegex(RuntimeError, 'could not be verified'):
            resolve_target('https://github.com/example/repo').__enter__()
        self.assertFalse(created[0].exists())
