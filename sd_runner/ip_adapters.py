from sd_runner.models import IPAdapter

redo_files = [
    
]


preset_ip_adapters = [

]


def get_ip_adapters(ip_adapter_files=[]):
    if not ip_adapter_files or len(ip_adapter_files) == 0:
        return preset_ip_adapters[:]
    ip_adapters = []
    for path in ip_adapter_files:
        ip_adapters.append(IPAdapter(path, "", ""))
    return ip_adapters

if __name__ == "__main__":
    get_ip_adapters()
