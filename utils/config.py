import json
import os

from utils.logging_setup import get_logger

logger = get_logger("config")


class Config:
    CONFIGS_DIR_LOC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "configs")

    # Registry of config keys the Config dialog exposes as editable.
    # Maps key → expected Python type for coercion:
    #   bool  — checkbox; value supplied as Python bool
    #   int   — line edit; coerced with int()
    #   float — line edit; coerced with float()
    #   str   — line edit; stored as stripped string
    #   None  — nullable str: empty string is stored as Python None
    DIALOG_FIELDS: dict[str, type | None] = {
        # Backend URLs
        "comfyui_url":                      None,
        "sd_webui_url":                     None,
        "forge_url":                        None,
        "sdnext_url":                       None,
        "swarmui_url":                      None,
        "invokeai_url":                     None,
        "fooocus_url":                      None,
        # Save paths
        "sd_webui_save_path":               str,
        "forge_save_path":                  str,
        "sdnext_save_path":                 str,
        "swarmui_save_path":                str,
        "invokeai_save_path":               str,
        "fooocus_save_path":                str,
        # Directories
        "models_dir":                       str,
        "img_dir":                          None,
        "img_temps_dir":                    None,
        "ipadapter_dir":                    None,
        "comfyui_loc":                      None,
        "comfyui_output_dir":               None,
        "sd_webui_loc":                     None,
        "forge_loc":                        None,
        "sdnext_loc":                       None,
        "fooocus_loc":                      None,
        "invokeai_loc":                     None,
        "swarmui_loc":                      None,
        "sd_prompt_reader_loc":             None,
        "image_searcher_dir2":              None,
        # Backend autolaunch — see backend_launch_commands below
        "backend_startup_timeout":          int,
        # UI
        "foreground_color":                 None,
        "background_color":                 None,
        "ui_scale_factor":                  float,
        "locale":                           str,
        # Behavior
        "blacklist_prevent_execution":      bool,
        "purge_blacklisted_prompt_history": bool,
        "cache_store_interval_seconds":     int,
        "save_last_prompt":                 bool,
        "delay_after_single_run":           bool,
        "blacklist_backup_retention_days":  int,
        "debug":                            bool,
        "print_settings":                   bool,
        "max_executor_threads":             int,
        # Server
        "server_host":                      str,
        "server_port":                      int,
        "server_password":                  str,
        "mcp_server_host":                  str,
        "mcp_server_port":                  int,
        "mcp_server_token":                 str,
        "server_run_max_seconds":           int,
        # Dictionary override
        "override_dictionary_path":         None,
        "override_dictionary_append":       bool,
        # Similarity check — path to ONNX or Torch CLIP text encoder (nullable)
        "clip_model_path":                  None,
        # Image to prompt — VLM backend
        "vlm_repo_id":                      str,
        "vlm_load_in_4bit":                 bool,
    }

    @staticmethod
    def resolve_config_path():
        """Resolve the active config file path, preferring config.json."""
        configs_dir = os.environ.get("SD_RUNNER_CONFIGS_DIR") or Config.CONFIGS_DIR_LOC
        configs = [f.path for f in os.scandir(configs_dir) if f.is_file() and f.path.endswith(".json")]
        config_path = None
        for c in configs:
            if os.path.basename(c) == "config.json":
                config_path = c
                break
            elif os.path.basename(c) != "config_example.json":
                config_path = c
        if config_path is None:
            config_path = os.path.join(configs_dir, "config example.json")
        return config_path

    def __init__(self):
        self.dict = {}
        self.debug = False
        self.locale = "en"
        self.print_settings = True
        self.foreground_color = None
        self.background_color = None
        self.comfyui_url = None
        self.sd_webui_url = None
        self.sd_webui_save_path = "."
        self.forge_url = None
        self.forge_save_path = "."
        self.sdnext_url = None
        self.sdnext_save_path = "."
        self.swarmui_url = None
        self.swarmui_save_path = "."
        self.invokeai_url = None
        self.invokeai_save_path = "."
        self.fooocus_url = None
        self.fooocus_save_path = "."
        self.concepts_dir = "concepts"
        self.models_dir = ""
        self.img_dir = None
        self.img_temps_dir = None
        self.ipadapter_dir = None
        self.comfyui_loc = None
        # Overrides the default <comfyui_loc>/output. Also what the unnamed-output
        # recovery scans, so an install that writes elsewhere must set it.
        self.comfyui_output_dir = None
        self.sd_webui_loc = None
        # Install directories for the remaining local backends. Only used as the
        # working directory a launch command runs from -- nothing else reads
        # them, so they stay null for anyone not using autolaunch.
        self.forge_loc = None
        self.sdnext_loc = None
        self.fooocus_loc = None
        self.invokeai_loc = None
        self.swarmui_loc = None
        self.sd_prompt_reader_loc = None
        self.image_searcher_dir = None
        self.image_searcher_dir2 = None
        self.blacklist_prevent_execution = False  # Whether blacklisted items should prevent prompt execution
        self.purge_blacklisted_prompt_history = True  # Whether to purge blacklisted prompts from history on cache write
        self.cache_store_interval_seconds = 300  # Periodic cache store interval; 0 or less disables the timer
        self.save_last_prompt = False
        self.delay_after_single_run = True  # Post-run delay when total == 1 (e.g. standalone server requests)
        self.blacklist_backup_retention_days = 30  # How long a cleared blacklist stays restorable; 0 or less keeps it until discarded

        self.gen_order = ["control_nets", "ip_adapters", "resolutions", "models", "vaes", "loras"]
        self.redo_parameters = ["n_latents", "resolutions", "models", "loras"]
        self.model_presets = []
        self.prompt_presets = []
        self.wildcards = {}

        self.override_dictionary_path = None
        self.override_dictionary_append = True
        self.clip_model_path = None

        # Image-to-prompt VLM backend. The default is the original LLaVA-1.5
        # weights in the Transformers layout; any repo Transformers can load as
        # a vision-language model works. 4-bit cuts VRAM to roughly a third at
        # some cost to quality, and needs bitsandbytes installed -- off by
        # default so an install without it behaves normally.
        self.vlm_repo_id = "llava-hf/llava-1.5-7b-hf"
        self.vlm_load_in_4bit = False

        self.interrogator_interrogation_dir = None
        self.interrogator_initial_questions_file = None
        self.interrogator_questions_file = None
        self.interrogator_folder_category_mappings_file = None

        self.ui_scale_factor = 1.0
        self.max_executor_threads = 4

        # Backends SD Runner should start for you, as {SoftwareType name: command}.
        # Each runs as its own OS process from the matching *_loc directory, so
        # backends needing different Python or conda environments coexist. The
        # command goes through a shell, so anything you would type at a prompt
        # works -- including the launcher scripts these backends ship:
        #   {"ComfyUI": "run_nvidia_gpu.bat",
        #    "SDWebUI": "C:\\miniconda3\\envs\\webui\\python.exe launch.py"}
        #
        # There are no built-in defaults: install layouts vary too much for a
        # guessed command to be reliable, and a wrong one fails after a long
        # startup wait rather than immediately. A backend that is already
        # running is left alone, and one absent from this dict is never touched.
        self.backend_launch_commands: dict = {}
        # How long to wait for a launched backend to answer. Generous, because
        # these are slow to start for real reasons -- downloading models,
        # compiling shaders, importing dozens of plugins -- and a first run is
        # slower still. Running out does not kill the backend; it is left to
        # carry on and reported as still starting.
        self.backend_startup_timeout = 600

        # Overridable so test runs can bind an OS-assigned ephemeral port
        # (SD_RUNNER_SERVER_PORT=0) instead of colliding with a real running
        # app instance's server on the default port.
        _server_port_override = os.environ.get("SD_RUNNER_SERVER_PORT")
        self.server_port = int(_server_port_override) if _server_port_override else 6000
        self.server_password = "<PASSWORD>"
        self.server_host = "localhost"
        # Model Context Protocol front end. Off until a port is set. The token
        # is required for any non-loopback bind: the other server's authkey is
        # a property of its transport and does not carry to HTTP.
        self.mcp_server_host = "localhost"
        self.mcp_server_port = 0
        self.mcp_server_token = ""
        # Ceiling on a server-triggered run's estimated duration. The
        # interactive path asks the user to confirm a long run; a server
        # request has nobody to ask, so an over-size one is refused. 0 = no
        # ceiling, which is the default so existing setups are unaffected.
        self.server_run_max_seconds = 0

        # Cloud backends — all keys live in one subdict loaded from config.json
        self.cloud_backends: dict = {}

        self.config_path = Config.resolve_config_path()

        try:
            self.dict = json.load(open(self.config_path, "r"))
        except Exception as e:
            logger.error(e)
            logger.warning("Unable to load config. Ensure config.json file settings are correct.")

        self.set_values(int,
                        "max_executor_threads",
                        "cache_store_interval_seconds",
                        "backend_startup_timeout",
                        "blacklist_backup_retention_days",
                        "mcp_server_port",
        )
        self.set_values(float,
                        "ui_scale_factor",
        )
        self.set_values(bool,
                        "debug",
                        "print_settings",
                        "save_last_prompt",
                        "override_dictionary_append",
                        "blacklist_prevent_execution",
                        "purge_blacklisted_prompt_history",
                        "delay_after_single_run",
                        "vlm_load_in_4bit",
        )
        self.set_values(str,
                        "locale",
                        "foreground_color",
                        "background_color",
                        "comfyui_url",
                        "sd_webui_url",
                        "forge_url",
                        "sdnext_url",
                        "swarmui_url",
                        "invokeai_url",
                        "fooocus_url",
                        "server_password",
                        "mcp_server_host",
                        "mcp_server_token",
                        "override_dictionary_path",
                        "clip_model_path",
                        "vlm_repo_id",
        )
        self.set_values(list,
                        "gen_order",
                        "redo_parameters",
                        "model_presets",
                        "prompt_presets",
        )
        self.set_values(dict, 
                        "wildcards",
                        "backend_launch_commands",
        )
        self.set_directories(
            "models_dir",
            "img_dir",
            "img_temps_dir",
            "ipadapter_dir",
            "comfyui_loc",
            "comfyui_output_dir",
            "sd_webui_loc",
            "forge_loc",
            "sdnext_loc",
            "fooocus_loc",
            "invokeai_loc",
            "swarmui_loc",
            "sd_webui_save_path",
            "forge_save_path",
            "sdnext_save_path",
            "swarmui_save_path",
            "invokeai_save_path",
            "fooocus_save_path",
            "sd_prompt_reader_loc",
            "image_searcher_dir2",
            "interrogator_interrogation_dir",
        )
        self.set_filepaths(
            "interrogator_initial_questions_file",
            "interrogator_questions_file",
            "interrogator_folder_category_mappings_file"
        )

        if self.override_dictionary_path is not None:
            self.set_filepaths("override_dictionary_path")
            print(f"Set override_dictionary_path to: {self.override_dictionary_path}")

        if isinstance(self.dict.get("cloud_backends"), dict):
            self.cloud_backends = self.dict["cloud_backends"]

        self.concepts_dirs = {}
        self.default_concepts_dir = "concepts"
        self.set_concepts_dirs()

    def set_concepts_dirs(self):
        concepts = "concepts"
        if not "concepts_dirs" in self.dict:
            self.dict["concepts_dirs"] = [concepts]
        self.concepts_dirs = {}
        concept_dirs_list = self.dict["concepts_dirs"]
        self.concepts_dirs[concepts] = concepts
        for i in range(len(concept_dirs_list)):
            d = concept_dirs_list[i].strip()
            if d == "" or d == concepts:
                continue
            d = self.validate_and_set_directory(d, override=True)
            if d is None:
                raise Exception("Invalid concept directory provided in config!")
            self.concepts_dirs[os.path.basename(d)] = d
        if "default_concepts_dir" in self.dict and self.dict["default_concepts_dir"] not in [None, "", concepts]:
            default_dir = self.validate_and_set_directory("default_concepts_dir")
            assert default_dir is not None and default_dir!= ""
            self.default_concepts_dir = os.path.basename(default_dir)
            if not self.default_concepts_dir in self.concepts_dirs:
                raise Exception("Invalid default concept directory provided in config, not found in concept dirs list.")
        else:
            self.default_concepts_dir = concepts

    def validate_and_set_directory(self, key, override=False):
        loc = key if override else self.dict[key]
        if loc and loc.strip() != "":
            loc = self._normalize_config_path(loc)
            if not os.path.isdir(loc):
                raise Exception(f"Invalid location provided for {key}: {loc}")
            return loc
        return None

    def validate_and_set_filepath(self, key):
        filepath = self.dict[key]
        if filepath and filepath.strip() != "":
            filepath = self._normalize_config_path(filepath)
            if not os.path.isfile(filepath):
                raise Exception(f"Invalid location provided for {key}: {filepath}")
            return filepath
        return None

    def _normalize_config_path(self, path_value: str) -> str:
        """Normalize configured paths across platforms and user input styles."""
        normalized = path_value.strip()
        if "{HOME}" in normalized:
            normalized = normalized.replace("{HOME}", os.path.expanduser("~"))
        # Handle Windows separators in configs used on POSIX machines.
        normalized = normalized.replace("\\", os.sep)
        return os.path.normpath(normalized)

    def set_directories(self, *directories):
        for directory in directories:
            try:
                setattr(self, directory, self.validate_and_set_directory(directory))
            except Exception as e:
                pass
            #    setattr(self, directory, None)
            #    logger.warning(f"Failed to set {directory} from config.json: {e}")

    def set_filepaths(self, *filepaths):
        for filepath in filepaths:
            try:
                setattr(self, filepath, self.validate_and_set_filepath(filepath))
            except Exception as e:
                pass
#                logger.error(e)
#                logger.warning(f"Failed to set {filepath} from config.json file. Ensure the key is set.")

    def set_values(self, type, *names):
        for name in names:
            if type:
                try:
                    raw_value = self.dict[name]
                    # Keep explicit nulls as None instead of coercing to "None".
                    if type is str and raw_value is None:
                        setattr(self, name, None)
                    else:
                        setattr(self, name, type(raw_value))
                except Exception as e:
                    pass
#                    logger.error(e)
#                    logger.warning(f"Failed to set {name} from config.json file. Ensure the value is set and of the correct type.")
            else:
                try:
                    setattr(self, name, self.dict[name])
                except Exception as e:
                    pass
#                    logger.error(e)
#                    logger.warning(f"Failed to set {name} from config.json file. Ensure the key is set.")

    def get(self, key: str, default=None):
        """Safely get a value from config.dict with a default if the key doesn't exist.
        
        Args:
            key: The key to look up in config.dict
            default: The default value to return if the key is not found
            
        Returns:
            The value from config.dict if the key exists, otherwise the default value
        """
        try:
            return self.dict[key]
        except KeyError:
            logger.warning(f"Config key '{key}' not found in config.json, using default value: {default}")
            return default

    def get_comfyui_save_path(self):
        """Get the ComfyUI output directory path.

        ``comfyui_output_dir`` wins when set, for an install whose output is not
        the default ``<comfyui_loc>/output`` -- a symlink elsewhere, or a
        ``--output-directory`` on the ComfyUI command line.
        """
        if self.comfyui_output_dir:
            return self.comfyui_output_dir
        if self.comfyui_loc:
            return os.path.join(self.comfyui_loc, "output")
        return "."

    def _build_persisted_config_dict(self) -> dict:
        """Build config dict for serialization, preserving all existing keys."""
        return dict(self.dict) if isinstance(self.dict, dict) else {}

    def apply_and_persist(self, raw: dict[str, object]) -> list[str]:
        """Validate *raw* field values, apply them in-memory, and persist to disk.

        *raw* maps config-key → value, where:
          - bool fields supply a Python ``bool`` directly (e.g. from a checkbox)
          - all other fields supply a ``str`` that will be coerced to the
            registered type (see ``DIALOG_FIELDS``)

        Returns a list of validation-error strings.  When the list is non-empty
        nothing has been changed — neither in-memory nor on disk.
        """
        errors: list[str] = []
        typed: dict[str, object] = {}
        for key, value in raw.items():
            if key not in self.DIALOG_FIELDS:
                logger.warning("apply_and_persist: unknown key %r ignored", key)
                continue
            expected = self.DIALOG_FIELDS[key]
            if expected is bool:
                typed[key] = bool(value)
            elif expected is None:
                s = str(value).strip()
                typed[key] = s if s else None
            elif expected is str:
                typed[key] = str(value).strip()
            else:
                try:
                    typed[key] = expected(str(value).strip())  # type: ignore[call-arg]
                except (ValueError, TypeError):
                    name = getattr(expected, "__name__", str(expected))
                    errors.append(f"{key}: expected {name}, got {str(value)!r}")
        if errors:
            return errors
        for key, val in typed.items():
            self.dict[key] = val
            setattr(self, key, val)
        self.persist()
        return []

    def persist(self) -> None:
        """Write current config.dict back to the active config file atomically.

        Uses a write-then-rename swap so a crash mid-write never leaves the
        config file in a partially-written state.
        """
        config_dict = self._build_persisted_config_dict()
        tmp_path = self.config_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(config_dict, f, ensure_ascii=False, indent=2)
            with open(tmp_path, "r", encoding="utf-8") as f:
                json.load(f)  # verify readable before replacing original
            os.replace(tmp_path, self.config_path)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
        self.dict = config_dict

    def get_cloud_save_path(self) -> str:
        """Return the output directory for cloud-generated images.

        Falls back to ``img_dir`` and then ``"."`` if ``cloud_backends.save_path``
        is not configured.
        """
        path = self.cloud_backends.get("save_path")
        if path:
            return self._normalize_config_path(path)
        return self.img_dir or "."

    def require_api_key(self, backend_name: str) -> str:
        """Return the API key for *backend_name*, raising clearly if it is missing.

        The key must be present in the ``cloud_backends`` subdict of ``config.json``
        under the name ``{backend_name}_api_key``, e.g.::

            "cloud_backends": { "bfl_api_key": "my-secret-key" }

        Args:
            backend_name: Short identifier used in the config key, e.g. ``"bfl"``.

        Raises:
            ValueError: If the key is absent or empty.
        """
        key_name = f"{backend_name}_api_key"
        value = self.cloud_backends.get(key_name)
        if not value:
            raise ValueError(
                f"API key for '{backend_name}' is not configured. "
                f"Add '{key_name}' to the 'cloud_backends' section of config.json."
            )
        return value



config = Config()
