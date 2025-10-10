import os

from sd_runner.adapter_sorting import _sort_adapters_by_recency
from sd_runner.model_adapters import IPAdapter
from utils.utils import Utils

redo_files = [
    
]


preset_ip_adapters = [

]


def get_ip_adapters(ip_adapter_files=[], random_sort=True, app_actions=None) -> tuple[list[IPAdapter], bool]:
    """Get IP adapters with recency-based sorting."""
    if not ip_adapter_files or len(ip_adapter_files) == 0:
        ip_adapter_files = preset_ip_adapters[:] 
    
    is_dir = False
    if len(ip_adapter_files) == 1 and os.path.isdir(ip_adapter_files[0]):
        ip_adapter_files = Utils.get_files_from_dir(ip_adapter_files[0], recursive=False, random_sort=random_sort)
        is_dir = True
    
    def ip_adapter_factory(path: str) -> IPAdapter:
        return IPAdapter(path, "", "")
    
    ip_adapters = _sort_adapters_by_recency(
        ip_adapter_files, 
        random_sort, 
        app_actions, 
        ip_adapter_factory
    )
    
    return ip_adapters, is_dir


if __name__ == "__main__":
    get_ip_adapters()
