from models import ControlNet

redo_files = [
    
]

preset_control_nets = [

]

# preset_control_nets = glob.glob(pathname="\\*"),



def get_control_nets(control_net_files=[]):
    if not control_net_files or len(control_net_files) == 0:
        control_net_files = preset_control_nets[:]
    control_nets = []
    for path in control_net_files:
        control_nets.append(ControlNet(path))
    return control_nets


if __name__ == "__main__":
    get_control_nets()
