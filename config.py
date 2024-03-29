import json
import os


class Config:
    CONFIG_FILE_LOC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

    def __init__(self):
        self.dict = {}
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

        self.interrogator_interrogation_dir = None
        self.interrogator_initial_questions_file = None
        self.interrogator_questions_file = None
        self.interrogator_folder_category_mappings_file = None

        try:
            self.dict = json.load(open(Config.CONFIG_FILE_LOC, "r"))
            self.img_dir = self.validate_and_set_directory(key="img_dir")
            self.img_temps_dir = self.validate_and_set_directory(key="img_temps_dir")
            self.ipadapter_dir = self.validate_and_set_directory(key="ipadapter_dir")
            self.comfyui_loc = self.validate_and_set_directory(key="comfyui_loc")
            self.sd_webui_loc = self.validate_and_set_directory(key="sd_webui_loc")
            self.sd_prompt_reader_loc = self.validate_and_set_directory(key="sd_prompt_reader_loc")
            self.image_searcher_dir = self.validate_and_set_directory(key="sd_prompt_reader_loc")
            self.image_searcher_dir2 = self.validate_and_set_directory(key="sd_prompt_reader_loc")

            self.gen_order = self.dict["gen_order"]
            self.redo_parameters = self.dict["redo_parameters"]
            self.model_presets = self.dict["model_presets"]
            self.prompt_presets = self.dict["prompt_presets"]

            self.interrogator_interrogation_dir = self.validate_and_set_directory(key="interrogator_interrogation_dir")
            self.interrogator_initial_questions_file = self.validate_and_set_filepath(key="interrogator_initial_questions_file")
            self.interrogator_questions_file = self.validate_and_set_filepath(key="interrogator_questions_file")
            self.interrogator_folder_category_mappings_file = self.validate_and_set_filepath(key="interrogator_folder_category_mappings_file")
        except Exception as e:
            print(e)
            print("Unable to load config. Ensure config.json file settings are correct.")

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


config = Config()