import json
import os


class Config:
    CONFIGS_DIR_LOC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "configs")

    def __init__(self):
        self.dict = {}
        self.foreground_color = None
        self.background_color = None
        self.comfyui_url = None
        self.sd_webui_url = None
        self.sd_webui_save_path = "."
        self.models_dir = ""
        self.img_dir = None
        self.img_temps_dir = None
        self.ipadapter_dir = None
        self.comfyui_loc = None
        self.sd_webui_loc = None
        self.sd_prompt_reader_loc = None
        self.image_searcher_dir = None
        self.image_searcher_dir2 = None

        self.gen_order = ["control_nets", "ip_adapters", "resolutions", "models", "vaes", "loras"]
        self.redo_parameters = ["n_latents", "resolutions", "models", "loras"]
        self.model_presets = []
        self.prompt_presets = []
        self.wildcards = {}

        self.interrogator_interrogation_dir = None
        self.interrogator_initial_questions_file = None
        self.interrogator_questions_file = None
        self.interrogator_folder_category_mappings_file = None

        self.server_port = 6000
        self.server_password = "<PASSWORD>"
        self.server_host = "localhost"

        configs =  [ f.path for f in os.scandir(Config.CONFIGS_DIR_LOC) if f.is_file() and f.path.endswith(".json") ]
        self.config_path = None

        for c in configs:
            if os.path.basename(c) == "config.json":
                self.config_path = c
                break
            elif os.path.basename(c) != "config_example.json":
                self.config_path = c

        if self.config_path is None:
            self.config_path = os.path.join(Config.CONFIGS_DIR_LOC, "config_example.json")

        try:
            self.dict = json.load(open(self.config_path, "r"))
        except Exception as e:
            print(e)
            print("Unable to load config. Ensure config.json file settings are correct.")

        self.set_values(str,
                        "foreground_color",
                        "background_color",
                        "comfyui_url",
                        "sd_webui_url",
                        "server_password")
        self.set_values(list,
                        "gen_order",
                        "redo_parameters",
                        "model_presets",
                        "prompt_presets")
        self.set_values(dict, "wildcards")
        self.set_directories(
            "models_dir",
            "img_dir",
            "img_temps_dir",
            "ipadapter_dir",
            "comfyui_loc",
            "sd_webui_loc",
            "sd_webui_save_path",
            "sd_prompt_reader_loc",
            "image_searcher_dir2",
            "interrogator_interrogation_dir",
        )
        self.set_filepaths(
            "interrogator_initial_questions_file",
            "interrogator_questions_file",
            "interrogator_folder_category_mappings_file"
        )

    def validate_and_set_directory(self, key):
        loc = self.dict[key]
        if loc and loc.strip() != "":
            if "{HOME}" in loc:
                loc = loc.strip().replace("{HOME}", os.path.expanduser("~"))
            if not os.path.isdir(loc):
                raise Exception(f"Invalid location provided for {key}: {loc}")
            return loc
        return None

    def validate_and_set_filepath(self, key):
        filepath = self.dict[key]
        if filepath and filepath.strip() != "":
            if "{HOME}" in filepath:
                filepath = filepath.strip().replace("{HOME}", os.path.expanduser("~"))
            if not os.path.isfile(filepath):
                raise Exception(f"Invalid location provided for {key}: {filepath}")
            return filepath
        return None

    def set_directories(self, *directories):
        for directory in directories:
            # try:
            setattr(self, directory, self.validate_and_set_directory(directory))
            # except Exception as e:
            #     print(e)
            #     print(f"Failed to set {directory} from config.json file. Ensure the key is set.")

    def set_filepaths(self, *filepaths):
        for filepath in filepaths:
            try:
                setattr(self, filepath, self.validate_and_set_filepath(filepath))
            except Exception as e:
                pass
#                print(e)
#                print(f"Failed to set {filepath} from config.json file. Ensure the key is set.")

    def set_values(self, type, *names):
        for name in names:
            if type:
                try:
                    setattr(self, name, type(self.dict[name]))
                except Exception as e:
                    pass
#                    print(e)
#                    print(f"Failed to set {name} from config.json file. Ensure the value is set and of the correct type.")
            else:
                try:
                    setattr(self, name, self.dict[name])
                except Exception as e:
                    pass
#                    print(e)
#                    print(f"Failed to set {name} from config.json file. Ensure the key is set.")



config = Config()
