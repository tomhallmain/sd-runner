import os

from sd_runner.model_adapters import IPAdapter
from utils.utils import Utils

redo_files = [
    
]


preset_ip_adapters = [

]


def get_ip_adapters(ip_adapter_files=[], random_sort=True) -> tuple[list[IPAdapter], bool]:
    if not ip_adapter_files or len(ip_adapter_files) == 0:
        ip_adapter_files = preset_ip_adapters[:] 
    ip_adapters = []
    is_dir = False
    if len(ip_adapter_files) == 1 and os.path.isdir(ip_adapter_files[0]):
        ip_adapter_files = Utils.get_files_from_dir(ip_adapter_files[0], recursive=False, random_sort=random_sort)
        is_dir = True
    for path in ip_adapter_files:
        ip_adapters.append(IPAdapter(path, "", ""))
    return ip_adapters, is_dir
 

if __name__ == "__main__":
    get_ip_adapters()
