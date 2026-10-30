"""Checks a built executable runs, against itself, with ``--smoke-test``.

``build_exe.py`` runs each built executable this way from outside the repo,
with the app data, configs and cache directories (and with the cache, the key
store) pointed at a scratch directory. Getting far enough to run any check
already proves the entry point's imports resolved. The window and the servers
are only constructed, never shown or bound.

Encryption is checked with the symmetric cipher only: the asymmetric one keeps
its passphrase in the OS keychain, which a smoke test must not write to.
"""

import gettext
import json
import os
import tempfile
import traceback

from lib.logging_setup import get_logger
from sd_runner.app_paths import resource_path

logger = get_logger("runtime.smoke_test")


def _check_build_info() -> str:
    """build_info.json is bundled and names this version; returns the startup log line."""
    from sd_runner.app_paths import IS_BUILD
    from sd_runner.runtime.version import BUILD_INFO_FILE, app_version, build_info, describe

    info = build_info()
    if IS_BUILD:
        if not info:
            raise FileNotFoundError(f"{BUILD_INFO_FILE} is not bundled")
        version = app_version()
        if info.get("version") != version:
            raise ValueError(f"{BUILD_INFO_FILE} names version {info.get('version')}, the app is {version}")
    return describe()


class SmokeTest:
    def __init__(self):
        self.failures = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        logger.info(f"smoke test: {name}: {'ok' if ok else 'FAILED'} {detail}".rstrip())
        if not ok:
            self.failures.append(name)

    def check_call(self, name: str, func) -> None:
        """Run *func*; it passes unless it raises. A returned string is logged."""
        try:
            detail = func()
            self.check(name, True, detail if isinstance(detail, str) else "")
        # SystemExit too: Nuitka's metadata lookup exits the build when a
        # bundled package's metadata is missing.
        except (Exception, SystemExit) as e:
            self.check(name, False, f"{type(e).__name__}: {e}")
            # The message alone can be bare (e.g. "KeyError: 2"); the build log
            # is the only place a build's failure can be diagnosed from.
            logger.error(f"smoke test: {name}: traceback:\n{traceback.format_exc()}")

    def report(self, name: str, detail: str) -> None:
        """Log something the build does not require."""
        logger.info(f"smoke test: {name}: {detail}")

    def run_common(self, expect_oqs: bool = False) -> None:
        """The checks both executables share."""
        self.check_files()
        self.check_data()
        self.check_dependencies(expect_oqs)

    def check_files(self) -> None:
        """Bundled read-only files at the paths the app resolves them under; the fault log opens."""
        from lib.translations import I18N
        from sd_runner.config import config
        from sd_runner.runtime.crash_log import enable_fault_log
        from sd_runner.runtime.version import VERSION_FILE
        from sd_runner.workflow_prompts.base import WorkflowPrompt

        self.check("config", os.path.isfile(config.config_path), config.config_path)
        self.check("locale", gettext.find("base", I18N.localedir, ["de"]) is not None, I18N.localedir)
        for subdir in ("comfyui", "sdwebui"):
            folder = os.path.join(WorkflowPrompt.PROMPTS_LOC, subdir)
            count = len([n for n in os.listdir(folder) if n.endswith(".json")]) if os.path.isdir(folder) else 0
            self.check(f"{subdir} workflows", count > 0, f"{count} in {folder}")
        self.check("version", os.path.isfile(resource_path(VERSION_FILE)))
        self.check("app icon", os.path.isfile(resource_path("assets", "icon.png")))
        self.check("sounds", os.path.isfile(resource_path("lib", "sounds", "success.wav")))
        for name in ("blacklist_default.enc", "urban_dictionary.enc", "config_example.json"):
            self.check(name, os.path.isfile(resource_path("sd_runner", "data", name)))
        self.check_call("fault log", enable_fault_log)
        self.check_call("build info", _check_build_info)

    def check_data(self) -> None:
        """Bundled encrypted data decrypts, concepts load, encryption round-trips,
        and the app info cache opens."""
        from lib.encryptor import symmetric_decrypt_data_from_file, symmetric_encrypt_data_to_file
        from lib.utils import Utils
        from sd_runner.globals import Globals

        def default_blacklist():
            from sd_runner.prompts.blacklist import Blacklist

            encoded = symmetric_decrypt_data_from_file(
                Blacklist.DEFAULT_BLACKLIST_FILE_LOC,
                (Globals.APP_IDENTIFIER + "_blacklist").encode("utf-8"),
            )
            data = json.loads(Utils.postprocess_data_from_decryption(encoded))
            tags = data if isinstance(data, list) else data.get("tags", [])
            return f"{len(tags)} items"

        def concepts():
            from sd_runner.prompts.concepts import Concepts

            words = Concepts.load("colors")
            if not words:
                raise ValueError(f"no concepts loaded from {Concepts.CONCEPTS_DIR}")
            return f"{len(words)} colors from {Concepts.CONCEPTS_DIR}"

        def symmetric_round_trip():
            path = os.path.join(tempfile.mkdtemp(prefix="sd_runner_smoke_"), "round_trip.enc")
            symmetric_encrypt_data_to_file(b"smoke test", path, b"smoke test passphrase")
            if symmetric_decrypt_data_from_file(path, b"smoke test passphrase") != b"smoke test":
                raise ValueError("decrypted data differs")

        def app_info_cache():
            from sd_runner.persistence.app_info_cache import app_info_cache as cache

            return cache._cache_loc

        self.check_call("default blacklist", default_blacklist)
        self.check_call("concepts", concepts)
        self.check_call("symmetric encryption", symmetric_round_trip)
        self.check_call("app info cache", app_info_cache)

    def check_dependencies(self, expect_oqs: bool) -> None:
        """Keyring backend, OQS, and the packages the app imports only when a
        feature is used."""
        import keyring
        import keyring.backends.fail

        backend = keyring.get_keyring()
        self.check(
            "keyring backend",
            not isinstance(backend, keyring.backends.fail.Keyring),
            f"{type(backend).__module__}.{type(backend).__name__}",
        )

        from lib import encryptor

        oqs_available = encryptor.KeyEncapsulation is not None
        if expect_oqs:
            self.check("OQS key encapsulation", oqs_available)
        else:
            self.report("OQS key encapsulation", "available" if oqs_available else "not in this build")

        def websocket():
            import websocket  # noqa: F401

        def torch():
            import torch as _torch

            return _torch.__version__

        def transformers():
            # The classes the image-to-prompt providers and the similarity
            # check load, without their weights. transformers resolves them
            # lazily, so naming them imports their modules.
            from transformers import (  # noqa: F401
                AutoProcessor,
                BlipForConditionalGeneration,
                BlipForQuestionAnswering,
                BlipProcessor,
                CLIPTokenizer,
                LlavaForConditionalGeneration,
            )

        def onnxruntime():
            import onnxruntime as ort

            return ort.__version__

        def huggingface_hub():
            from huggingface_hub import HfApi, hf_hub_download, snapshot_download  # noqa: F401

        def mcp():
            from mcp.server import MCPServer  # noqa: F401
            import uvicorn  # noqa: F401

        def lingua():
            # Missing model data would otherwise show up only as every prompt
            # being checked against every language.
            from sd_runner.prompts.language_detection import build_detector

            scores = build_detector(frozenset({"de"}))("Die Katze schläft auf dem warmen Sofa")
            if not scores or scores[0][0] != "de":
                raise ValueError(f"German text scored {scores}")
            return f"de {scores[0][1]:.2f}"

        self.check_call("websocket-client", websocket)
        self.check_call("torch", torch)
        self.check_call("transformers", transformers)
        self.check_call("onnxruntime", onnxruntime)
        self.check_call("huggingface_hub", huggingface_hub)
        self.check_call("mcp", mcp)
        self.check_call("lingua", lingua)

    def result(self) -> int:
        """Exit code: 0 if every check passed."""
        if self.failures:
            logger.error(f"smoke test failed: {', '.join(self.failures)}")
            return 1
        logger.info("smoke test passed")
        return 0
