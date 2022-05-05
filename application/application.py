from enum import Enum

from infrastructure.infrastructure import Infrastructure
#from orchestration.function_process import FunctionProcess


class ApplicationState(Enum):
    PLACED = 0
    RUNNING = 1
    COMPLETED = 2
    CANCELED = 3

class Application:
    id = "" # application name
    state : ApplicationState = ApplicationState.PLACED
    chain : dict
    placement : dict
    infrastructure_nodes : dict
    function_processes : list = []


    def __init__(self, app_id: str, chain: dict, placement : dict, infrastructure : dict):
        self.id = app_id
        self.chain = chain
        self.placement = placement
        self.infrastructure_nodes = infrastructure
