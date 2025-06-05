import os

from utils.globals import Globals
from sd_runner.model_adapters import ControlNet
from utils.utils import Utils

redo_files = [
    
]

preset_control_nets = [

]



def get_control_nets(control_net_files=[], random_sort=True) -> tuple[list[ControlNet], bool]:
    #preset_control_nets = glob.glob(pathname="\\*"),
    if not control_net_files or len(control_net_files) == 0:
        control_net_files = preset_control_nets[:]
    control_nets = []
    is_dir = False
    if len(control_net_files) == 1 and os.path.isdir(control_net_files[0]):
        control_net_files = Utils.get_files_from_dir(control_net_files[0], recursive=False, random_sort=random_sort)
        is_dir = True
    for path in control_net_files:
        control_nets.append(ControlNet(path, strength=Globals.DEFAULT_CONTROL_NET_STRENGTH))
    return control_nets, is_dir


if __name__ == "__main__":
    get_control_nets()
