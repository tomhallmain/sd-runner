import os

from sd_runner.model_adapters import IPAdapter
from utils.utils import Utils

redo_files = [
    
]


preset_ip_adapters = [

]


def get_ip_adapters(ip_adapter_files=[], random_sort=True, app_actions=None) -> tuple[list[IPAdapter], bool]:
    if not ip_adapter_files or len(ip_adapter_files) == 0:
        ip_adapter_files = preset_ip_adapters[:] 
    ip_adapters = []
    recent_ip_adapters = []
    is_dir = False
    if len(ip_adapter_files) == 1 and os.path.isdir(ip_adapter_files[0]):
        ip_adapter_files = Utils.get_files_from_dir(ip_adapter_files[0], recursive=False, random_sort=random_sort)
        is_dir = True
    # Order the recent adapters to the end of the list
    for path in ip_adapter_files:
        if app_actions is not None:
            if app_actions.contains_recent_adapter_file(path):
                recent_ip_adapters.append(IPAdapter(path, "", ""))
            else:
                ip_adapters.append(IPAdapter(path, "", ""))
        else:
            ip_adapters.append(IPAdapter(path, "", ""))
    ip_adapters.extend(recent_ip_adapters)
    return ip_adapters, is_dir
 

if __name__ == "__main__":
    get_ip_adapters()
