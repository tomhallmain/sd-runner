
import os

from utils.config import config
from utils.globals import Globals


class LoraBundle:
    def __init__(self, loras=[]):
        self.loras = loras
        if len(self.loras) == 0:
            raise Exception("No loras provided to Lora bundle!")
        self.is_xl = self.loras[0].is_xl()
        for lora in self.loras:
            if self.is_xl != lora.is_xl():
                raise Exception(f"Inconsistent SDXL specification for loras in lora bundle: {lora.id} expected is_xl: {self.is_xl}")

    def __str__(self):
        out = "LoraBundle: [ "
        for lora in self.loras:
            out += str(lora) + " "
        out += "]"
        return out


class IPAdapter:
    BASE_DIR = config.ipadapter_dir
    DEFAULT_SD15_MODEL = "ip-adapter_sd15_plus.pth"
    DEFAULT_SDXL_MODEL = "ip-adapter_xl.pth"
    DEFAULT_SD15_CLIP_VISION_MODEL = "SD1.5\\pytorch_model.bin"
    DEFAULT_SDXL_CLIP_VISION_MODEL = "XL\\clip_vision_g.safetensors"
    # Set to prompt extra coloration if the IP adapter image is black and white
    B_W_COLORATION = Globals.DEFAULT_B_W_COLORIZATION

    @classmethod
    def set_bw_coloration(cls, coloration):
        cls.B_W_COLORATION = coloration

    def __init__(self, id, desc="", modifiers="", strength=None):
        if strength is None:
            strength = Globals.DEFAULT_IPADAPTER_STRENGTH
        if not id or id.startswith("C:\\") or id.startswith("D:\\") or id.startswith("/"):
            self.id = id
        else:
            self.id = os.path.join(IPAdapter.BASE_DIR, id)
        self.desc = desc
        self.modifiers = modifiers
        self.strength = strength

    def is_valid(self):
        return os.path.isfile(self.id)

    def get_id(self, control_net=None):
        if self.id:
            return self.id    
        if control_net:
            return control_net.id
        raise Exception("Expected control net on IPAdapter with no id")

    def b_w_coloration_modifier(self, positive):
        if "b & w" in self.desc:
            if IPAdapter.B_W_COLORATION and IPAdapter.B_W_COLORATION != "":
                return positive  + ", " + IPAdapter.B_W_COLORATION
            return positive + ", " + Globals.PROMPTER.mix_colors()
        return positive

    def __str__(self):
        if self.desc and self.desc != "":
            if self.modifiers and self.modifiers != "":
                return f"IPAdapter image: {self.id}, desc: \"{self.desc}\", modifiers \"{self.modifiers}\", strength: {self.strength}"
            else:
                return f"IPAdapter image: {self.id}, desc: \"{self.desc}\", strength: {self.strength}"
        elif self.modifiers and self.modifiers != "":
            return f"IPAdapter image: {self.id}, modifiers \"{self.modifiers}\", strength: {self.strength}"
        else:
            return f"IPAdapter image: {self.id}, strength: {self.strength}"

    def __eq__(self, other):
        if isinstance(other, IPAdapter):
            return self.id == other.id
        return False

    def hash(self):
        return hash(self.id)


class ControlNet:
    def __init__(self, id, desc="", strength=Globals.DEFAULT_CONTROL_NET_STRENGTH):
        self.id = id
        self.desc = desc
        self.strength = strength

    def is_valid(self):
        return os.path.isfile(self.id)

    def __str__(self):
        if self.desc and self.desc != "":
            return f"ControlNet image: {self.id}, desc: \"{self.desc}\", strenth: {self.strength}"
        else:
            return f"ControlNet image: {self.id}, strength: {self.strength}"

    def __eq__(self, other):
        if isinstance(other, ControlNet):
            return self.id == other.id
        return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def hash(self):
        return hash(self.id)
