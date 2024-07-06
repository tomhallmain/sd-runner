"""
THIS CODE is a modified form of some classes from https://github.com/WASasquatch/was-node-suite-comfyui which is under MIT license.
"""

import json
import numpy as np
import os
from PIL import Image
import torch

from utils.config import config


MODELS_DIR = os.path.join(config.comfyui_loc, "models")
ROOT = os.path.join(os.path.join(config.comfyui_loc, "custom_nodes"), "was-node-suite-comfyui")

if not os.path.isdir(ROOT):
    raise Exception("WAS node suite not found. Please install WAS node suite into ComfyUI custom_nodes directory.")

WAS_CONFIG_FILE = os.path.join(ROOT, 'was_suite_config.json')

#! WAS SUITE CONFIG

was_conf_template = {
                    "run_requirements": True,
                    "suppress_uncomfy_warnings": True,
                    "show_startup_junk": True,
                    "show_inspiration_quote": True,
                    "text_nodes_type": "STRING",
                    "webui_styles": None,
                    "webui_styles_persistent_update": True,
                    "blip_model_url": "https://storage.googleapis.com/sfr-vision-language-research/BLIP/models/model_base_capfilt_large.pth",
                    "blip_model_vqa_url": "https://storage.googleapis.com/sfr-vision-language-research/BLIP/models/model_base_vqa_capfilt_large.pth",
                    "sam_model_vith_url": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth",
                    "sam_model_vitl_url": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_l_0b3195.pth",
                    "sam_model_vitb_url": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth",
                    "history_display_limit": 36,
                    "use_legacy_ascii_text": False,
                    "ffmpeg_bin_path": "/path/to/ffmpeg",
                    "ffmpeg_extra_codecs": {
                        "avc1": ".mp4",
                        "h264": ".mkv",
                    },
                    "wildcards_path": os.path.join(ROOT, "wildcards"),
                    "wildcard_api": True,
                }

# Create, Load, or Update Config

def getSuiteConfig():
    global was_conf_template
    try:
        with open(WAS_CONFIG_FILE, "r") as f:
            was_config = json.load(f)
    except OSError as e:
        cstr(f"Unable to load conf file at `{WAS_CONFIG_FILE}`. Using internal config template.").error.print()
        return was_conf_template
    except Exception as e:
        cstr(f"Unable to load conf file at `{WAS_CONFIG_FILE}`. Using internal config template.").error.print()
        return was_conf_template
    return was_config

class cstr(str):
    class color:
        END = '\33[0m'
        BOLD = '\33[1m'
        ITALIC = '\33[3m'
        UNDERLINE = '\33[4m'
        BLINK = '\33[5m'
        BLINK2 = '\33[6m'
        SELECTED = '\33[7m'

        BLACK = '\33[30m'
        RED = '\33[31m'
        GREEN = '\33[32m'
        YELLOW = '\33[33m'
        BLUE = '\33[34m'
        VIOLET = '\33[35m'
        BEIGE = '\33[36m'
        WHITE = '\33[37m'

        BLACKBG = '\33[40m'
        REDBG = '\33[41m'
        GREENBG = '\33[42m'
        YELLOWBG = '\33[43m'
        BLUEBG = '\33[44m'
        VIOLETBG = '\33[45m'
        BEIGEBG = '\33[46m'
        WHITEBG = '\33[47m'

        GREY = '\33[90m'
        LIGHTRED = '\33[91m'
        LIGHTGREEN = '\33[92m'
        LIGHTYELLOW = '\33[93m'
        LIGHTBLUE = '\33[94m'
        LIGHTVIOLET = '\33[95m'
        LIGHTBEIGE = '\33[96m'
        LIGHTWHITE = '\33[97m'

        GREYBG = '\33[100m'
        LIGHTREDBG = '\33[101m'
        LIGHTGREENBG = '\33[102m'
        LIGHTYELLOWBG = '\33[103m'
        LIGHTBLUEBG = '\33[104m'
        LIGHTVIOLETBG = '\33[105m'
        LIGHTBEIGEBG = '\33[106m'
        LIGHTWHITEBG = '\33[107m'

        @staticmethod
        def add_code(name, code):
            if not hasattr(cstr.color, name.upper()):
                setattr(cstr.color, name.upper(), code)
            else:
                raise ValueError(f"'cstr' object already contains a code with the name '{name}'.")

    def __new__(cls, text):
        return super().__new__(cls, text)

    def __getattr__(self, attr):
        if attr.lower().startswith("_cstr"):
            code = getattr(self.color, attr.upper().lstrip("_cstr"))
            modified_text = self.replace(f"__{attr[1:]}__", f"{code}")
            return cstr(modified_text)
        elif attr.upper() in dir(self.color):
            code = getattr(self.color, attr.upper())
            modified_text = f"{code}{self}{self.color.END}"
            return cstr(modified_text)
        elif attr.lower() in dir(cstr):
            return getattr(cstr, attr.lower())
        else:
            raise AttributeError(f"'cstr' object has no attribute '{attr}'")

    def print(self, **kwargs):
        print(self, **kwargs)


# Freeze PIP modules
def packages(versions=False):
    import sys
    import subprocess
    return [( r.decode().split('==')[0] if not versions else r.decode() ) for r in subprocess.check_output([sys.executable, '-s', '-m', 'pip', 'freeze']).split()]


# Tensor to PIL
def tensor2pil(image):
    return Image.fromarray(np.clip(255. * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))


# BLIP Model Loader

class WAS_BLIP_Model_Loader:
    def __init__(self):
        pass
        
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "blip_model": (["caption", "interrogate"], ),
            }
        }
    
    def blip_model(self, blip_model):
    
        if ( 'timm' not in packages() 
            or 'transformers' not in packages() 
            or 'fairscale' not in packages() ):
            cstr(f"Modules or packages are missing to use BLIP models. Please run the `{os.path.join(ROOT, 'requirements.txt')}` through ComfyUI's ptyhon executable.").error.print()
            exit
            
        if 'transformers==4.26.1' not in packages(True):
            cstr(f"`transformers==4.26.1` is required for BLIP models. Please run the `{os.path.join(ROOT, 'requirements.txt')}` through ComfyUI's ptyhon executable.").error.print()
            exit
            
        device = 'cpu'
        conf = getSuiteConfig()
        size = 384
            
        if blip_model == 'caption':

            from blip.blip_module import blip_decoder
            
            blip_dir = os.path.join(MODELS_DIR, 'blip')
            if not os.path.exists(blip_dir):
                os.makedirs(blip_dir, exist_ok=True)
                
            torch.hub.set_dir(blip_dir)
        
            if conf.__contains__('blip_model_url'):
                model_url = conf['blip_model_url']
            else:
                model_url = 'https://storage.googleapis.com/sfr-vision-language-research/BLIP/models/model_base_capfilt_large.pth'

            model_url = 'C:\\Users\\tehal\\ComfyUI\\models\\blip\\checkpoints\\model_base_capfilt_large.pth'
            model = blip_decoder(pretrained=model_url, image_size=size, vit='base')
            model.eval()
            model = model.to(device)
            
        elif blip_model == 'interrogate':
        
            from blip.blip_module import blip_vqa
            
            blip_dir = os.path.join(MODELS_DIR, 'blip')
            if not os.path.exists(blip_dir):
                os.makedirs(blip_dir, exist_ok=True)
                
            torch.hub.set_dir(blip_dir)

            if conf.__contains__('blip_model_vqa_url'):
                model_url = conf['blip_model_vqa_url']
            else:
                model_url = 'https://storage.googleapis.com/sfr-vision-language-research/BLIP/models/model_base_vqa_capfilt_large.pth'
        
            model_url = 'C:\\Users\\tehal\\ComfyUI\\models\\blip\\checkpoints\\model_base_vqa_capfilt_large.pth'
            model = blip_vqa(pretrained=model_url, image_size=size, vit='base')
            model.eval()
            model = model.to(device)
            
        result = ( model, blip_model )
            
        return ( result, )

    
        
# BLIP CAPTION IMAGE

class WAS_BLIP_Analyze_Image:
    def __init__(self):
        pass
        
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "mode": (["caption", "interrogate"], ),
                "question": ("STRING", {"default": "What does the background consist of?", "multiline": True}),
            },
            "optional": {
                "blip_model": ("BLIP_MODEL",)
            }
        }
    
    def blip_caption_image(self, image_path, mode, question, blip_model=None):
            
        def transformImage(input_image, image_size, device):
            raw_image = input_image.convert('RGB')   
            raw_image = raw_image.resize((image_size, image_size))
            transform = transforms.Compose([
                transforms.Resize(raw_image.size, interpolation=InterpolationMode.BICUBIC),
                transforms.ToTensor(),
                transforms.Normalize((0.48145466, 0.4578275, 0.40821073), (0.26862954, 0.26130258, 0.27577711))
            ]) 
            image = transform(raw_image).unsqueeze(0).to(device)   
            return image.view(1, -1, image_size, image_size)  # Change the shape of the output tensor       
        
        from torchvision import transforms
        from torchvision.transforms.functional import InterpolationMode
        
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        conf = getSuiteConfig()
        image = Image.open(image_path)
        size = 384
        tensor = transformImage(image, size, device)
            
        if blip_model:
            mode = blip_model[1]
        
        if mode == 'caption':
        
            if blip_model:
                model = blip_model[0].to(device)
            else:
                from blip.blip_module import blip_decoder
                
                blip_dir = os.path.join(MODELS_DIR, 'blip')
                if not os.path.exists(blip_dir):
                    os.makedirs(blip_dir, exist_ok=True)
                    
                torch.hub.set_dir(blip_dir)
            
                if conf.__contains__('blip_model_url'):
                    model_url = conf['blip_model_url']
                else:
                    model_url = 'https://storage.googleapis.com/sfr-vision-language-research/BLIP/models/model_base_capfilt_large.pth'
                    
                model = blip_decoder(pretrained=model_url, image_size=size, vit='base')
                model.eval()
                model = model.to(device)
            
            with torch.no_grad():
                caption = model.generate(tensor, sample=False, num_beams=6, max_length=74, min_length=20) 
                # nucleus sampling
                #caption = model.generate(tensor, sample=True, top_p=0.9, max_length=75, min_length=10) 
#                cstr(f"\033[33mBLIP Caption:\033[0m {caption[0]}").msg.print()
                return (caption[0], )
                
        elif mode == 'interrogate':
        
            if blip_model:
                model = blip_model[0].to(device)
            else:
                from blip.blip_module import blip_vqa
                
                blip_dir = os.path.join(MODELS_DIR, 'blip')
                if not os.path.exists(blip_dir):
                    os.makedirs(blip_dir, exist_ok=True)
                    
                torch.hub.set_dir(blip_dir)

                if conf.__contains__('blip_model_vqa_url'):
                    model_url = conf['blip_model_vqa_url']
                else:
                    model_url = 'https://storage.googleapis.com/sfr-vision-language-research/BLIP/models/model_base_vqa_capfilt_large.pth'
            
                model = blip_vqa(pretrained=model_url, image_size=size, vit='base')
                model.eval()
                model = model.to(device)

            with torch.no_grad():
                answer = model(tensor, question, train=False, inference='generate') 
#                cstr(f"\033[33m BLIP Answer:\033[0m {answer[0]}").msg.print()
                return (answer[0], )
                
        else:
            cstr(f"The selected mode `{mode}` is not a valid selection!").error.print()
            return ('Invalid BLIP mode!', )


