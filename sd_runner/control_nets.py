import glob
import os
import random

from utils.globals import Globals
from sd_runner.models import ControlNet

redo_files = [
    
]

preset_control_nets = [

]


def get_files_from_dir(dirpath, recursive=False):
    if not os.path.isdir(dirpath):
        raise Exception(f"Not a directory: {dirpath}")
    glob_pattern = "**/*" if recursive else "*"
    files = glob.glob(os.path.join(dirpath, glob_pattern),  recursive=recursive)
    files.sort()
    return files

def get_random_file_from_dir(dirpath, recursive=False):
    files = get_files_from_dir(dirpath, recursive)
    allowed_ext = [".jpg", ".jpeg", ".png", ".webp"]
    random.shuffle(files)
    random.shuffle(allowed_ext)
    for f in files:
        for ext in allowed_ext:
            if f.endswith(ext):
                return f


def get_control_nets(control_net_files=[]):
    #preset_control_nets = glob.glob(pathname="\\*"),
    if not control_net_files or len(control_net_files) == 0:
        control_net_files = preset_control_nets[:]
    control_nets = []
    is_dir = False
    if len(control_net_files) == 1 and os.path.isdir(control_net_files[0]):
        control_net_files = get_files_from_dir(control_net_files[0], recursive=False)
        is_dir = True
    for path in control_net_files:
        control_nets.append(ControlNet(path, strength=Globals.DEFAULT_CONTROL_NET_STRENGTH))
    return control_nets, is_dir


if __name__ == "__main__":
    get_control_nets()
