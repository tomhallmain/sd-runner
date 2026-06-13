import json
import os

from utils.logging_setup import get_logger

logger = get_logger("config")


class Config:
    CONFIGS_DIR_LOC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "configs")

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
        self.sd_webui_loc = None
        self.sd_prompt_reader_loc = None
        self.image_searcher_dir = None
        self.image_searcher_dir2 = None
        self.blacklist_prevent_execution = False  # Whether blacklisted items should prevent prompt execution
        self.purge_blacklisted_prompt_history = True  # Whether to purge blacklisted prompts from history on cache write
        self.save_last_prompt = False

        self.gen_order = ["control_nets", "ip_adapters", "resolutions", "models", "vaes", "loras"]
        self.redo_parameters = ["n_latents", "resolutions", "models", "loras"]
        self.model_presets = []
        self.prompt_presets = []
        self.wildcards = {}

        self.override_dictionary_path = None
        self.override_dictionary_append = True

        self.interrogator_interrogation_dir = None
        self.interrogator_initial_questions_file = None
        self.interrogator_questions_file = None
        self.interrogator_folder_category_mappings_file = None

        self.ui_scale_factor = 1.0
        self.max_executor_threads = 4

        self.server_port = 6000
        self.server_password = "<PASSWORD>"
        self.server_host = "localhost"

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
                        "override_dictionary_path",
        )
        self.set_values(list,
                        "gen_order",
                        "redo_parameters",
                        "model_presets",
                        "prompt_presets",
        )
        self.set_values(dict, 
                        "wildcards",
        )
        self.set_directories(
            "models_dir",
            "img_dir",
            "img_temps_dir",
            "ipadapter_dir",
            "comfyui_loc",
            "sd_webui_loc",
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
        """Get the ComfyUI output directory path."""
        if self.comfyui_loc:
            return os.path.join(self.comfyui_loc, "output")
        return "."

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
