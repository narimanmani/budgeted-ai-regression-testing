"""Pure command-boundary checks. No Docker, application or model runs."""
import unittest
from unittest.mock import patch

from experiment.transfer_v9.amendments import rasa_dependency as D


class DependencyCommandTests(unittest.TestCase):
    def test_only_pythonpath_is_added_before_the_unchanged_entrypoint_image(self):
        original = ["docker", "run", "--network", "none", "--read-only", "--entrypoint", "python", D.IMAGE,
                    "/study/experiment/transfer_v9/runtime/rasa_native.py", "--form-state", "parent"]
        with patch.object(D, "verify_dependency", return_value={}):
            command = D.command_shim(lambda **kwargs: list(original))(test_only=True)
        index = original.index("--entrypoint")
        self.assertEqual(command[:index], original[:index])
        self.assertEqual(command[index:index + 2], ["--env", "PYTHONPATH=" + D.DEPS_PATH])
        self.assertEqual(command[index + 2:], original[index:])
        self.assertEqual(original.count(D.IMAGE), command.count(D.IMAGE))

    def test_changed_base_image_is_rejected_without_running_anything(self):
        with patch.object(D, "verify_dependency", return_value={}):
            wrapper = D.command_shim(lambda **kwargs: ["docker", "run", "--entrypoint", "python", "rasa/rasa:latest"])
            with self.assertRaises(RuntimeError):
                wrapper()

    def test_preexisting_pythonpath_cannot_be_silently_overwritten(self):
        with patch.object(D, "verify_dependency", return_value={}):
            wrapper = D.command_shim(lambda **kwargs: ["docker", "run", "--env", "PYTHONPATH=/unknown",
                "--entrypoint", "python", D.IMAGE])
            with self.assertRaises(RuntimeError):
                wrapper()

    def test_changed_dependency_manifest_blocks_command_construction(self):
        with patch.object(D, "verify_dependency", side_effect=RuntimeError("changed bytes")):
            wrapper = D.command_shim(lambda **kwargs: ["docker", "run", "--entrypoint", "python", D.IMAGE])
            with self.assertRaisesRegex(RuntimeError, "changed bytes"):
                wrapper()


if __name__ == "__main__":
    unittest.main()
