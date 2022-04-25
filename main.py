import re
import sys, random
from datetime import datetime
from swiplserver import PrologError, PrologMQI
import json
from config import parse_config
from infrastructure.infrastructure import Infrastructure
from infrastructure.node import Node
from application.function import PlacedFunction
from math import inf
import os
import shutil
import config
from orchestration.orchestrator import Orchestrator
import logs

def print_usage():
    print("Usage:")
    print("python3 main.py -c <config.yaml path>")


def place(dictionary : dict, placement : dict, is_guard : bool):
    expression = dictionary['functor']
    if expression == 'fp':
        function_id = dictionary.get('args')[0]
        node_id = dictionary.get('args')[5]
        sw_reqs = dictionary.get('args')[2]
        hw_reqs = dictionary.get('args')[3]
        memory_req = hw_reqs.get('args')[0]
        v_cpu_req = hw_reqs.get('args')[1].get('args')[0]
        mhz_req = hw_reqs.get('args')[1].get('args')[1]
        function = PlacedFunction(function_id, node_id, sw_reqs, memory_req, v_cpu_req, mhz_req, is_guard)
        return { 
            function_id : function
        }
    elif expression == 'if':
        guard = place(dictionary.get('args')[0], placement, True)
        c1 = place(dictionary.get('args')[1], placement, False)
        c2 = place(dictionary.get('args')[2], placement, False)
        placement.update(guard)
        placement.update(c1)
        placement.update(c2)
        return placement
    elif expression == 'par':
        c1 = place(dictionary.get('args')[0][0], placement, False)
        c2 = place(dictionary.get('args')[0][1], placement, False)
        placement.update(c1)
        placement.update(c2)
        return placement
    elif expression == 'seq':
        c1 = place(dictionary.get('args')[0], placement, False)
        c2 = place(dictionary.get('args')[1], placement, False)
        placement.update(c1)
        placement.update(c2)
        return placement


def dipendenze(dictionary: dict, dependencies: dict, caller):
    expression = dictionary['functor']
    
    if expression == 'fp':
        function : str = dictionary.get('args')[0]
        
        return function, function, expression
    elif expression == 'if':
        guard = dictionary.get('args')[0].get('args')[0]
        c11, c12, exp_type1 = dipendenze(dictionary.get('args')[1], dependencies, guard)
        c21, c22, exp_type2 = dipendenze(dictionary.get('args')[2], dependencies, guard)
        
        dependencies[guard] = caller
        dependencies[c11] = guard
        dependencies[c21] = guard
        return c12, c22, expression

    elif expression == 'par':
        c11, c12, exp_type1 = dipendenze(dictionary.get('args')[0][0], dependencies, caller)
        c21, c22, exp_type2 = dipendenze(dictionary.get('args')[0][1], dependencies, caller)

        return1 = (c11, c12) if exp_type1 not in ['fp', 'seq'] else c12
        return2 = (c21, c22) if exp_type2 not in ['fp', 'seq'] else c22
            
        return return1, return2, expression

    elif expression == 'seq':
        c11, c12, exp_type1 = dipendenze(dictionary.get('args')[0], dependencies, caller)
        c21, c22, exp_type2 = dipendenze(dictionary.get('args')[1], dependencies, c12)

        if c21 not in dependencies and type(c21) is not tuple:
            if exp_type1 == 'seq':
                dependencies[c21] = c12
            else:
                dependencies[c21] = (c11, c12) if c11 != c12 else c11
        if c22 not in dependencies and type(c22) is not tuple:
            if exp_type1 == 'seq':
                dependencies[c22] = c12
            else:
                dependencies[c22] = (c11, c12) if c11 != c12 else c11
        if c11 not in dependencies and type(c11) is not tuple:
            dependencies[c11] = caller
        if c12 not in dependencies and type(c12) is not tuple:
            dependencies[c12] = caller
        
        return1 = (c11, c12) if exp_type1 != 'fp' else c12
        return2 = (c21, c22) if exp_type2 != 'fp' else c22
            
        return return1, return2, expression


def build_placement(prolog_placement : dict) -> dict[str, PlacedFunction] :
    orchestration_id = prolog_placement["OrchestrationId"] # TODO facci qualcosa

    return place(prolog_placement['Placement'], {}, False)

def unpack_nested_tuples(t: tuple):
    elements = list(t)
    to_return = []
    for elem in elements:
        if type(elem) is tuple:
            result = unpack_nested_tuples(elem)
            to_return += result
        else:
            to_return.append(elem)
    
    return to_return

def find_dependencies(prolog_placement: dict) -> dict[str, str]:
    #orchestration_id = placement["OrchestrationId"]  # TODO facci qualcosa

    dependencies = {}

    _ = dipendenze(prolog_placement['Placement'], dependencies, None)

    to_return = {}

    keys = dependencies.keys()
    for key in keys:
        if type(key) is not tuple:
            value = dependencies.get(key)
            if type(value) is tuple:
                new_value = unpack_nested_tuples(value)
                to_return[key] = new_value
            else:
                new_value = [value]
                to_return[key] = new_value

    return to_return


def take_decision(probability : float) -> bool:

    return random.random() < probability

# TODO commenta
def update_infrastructure(infrastructure : Infrastructure, output_filename: str):
    lines = []

    nodes = infrastructure.nodes

    nodes_keys = nodes.keys()
    for key in nodes_keys:
        node = nodes[key]
        # if the node is not available, don't write it
        if node.available:
            node_string = "node(" + node.id + ", " + node.provider + ", ["
            for sec_cap in node.security_capabilites:
                node_string += sec_cap + ","
            node_string = node_string.removesuffix(",")
            node_string += "], ["
            for sw_cap in node.software_capabilites:
                node_string += sw_cap + ","
            node_string = node_string.removesuffix(",")
            node_string += "], (" + str(node.memory) + "," + str(node.v_cpu) + "," + str(node.mhz) + ")).\n"
            #print(node_string)
            lines.append(node_string)

    # write non-saved data into file
    for line in infrastructure.other_data:
        lines.append(line)
    
    # write latencies informations
    first_keys = infrastructure.latencies.keys()
    for f_key in first_keys:
        first_key_links = infrastructure.latencies.get(f_key).keys()
        for s_key in first_key_links:
            latency = infrastructure.latencies.get(f_key).get(s_key)['latency']
            available = infrastructure.latencies.get(f_key).get(s_key)['available']
            # write iff link is available
            if available:
                latency_string = 'latency(' + f_key + ', ' + s_key + ', ' + str(latency) + ').\n'
                lines.append(latency_string)

    # overwrite file
    with open(output_filename, 'w') as f:
        for line in lines:
            f.write(line)

# Entry point of the simulator
def main(argv):

    # Setting up

    # logging
    logger = logs.get_logger() # TODO make it global??
    logger.info("logger is ready...")

    # define where SecFaas2Fog is
    secfaas2fog_folder = './SecFaas2Fog'
    secfaas2fog_abs_path = os.path.abspath(
        os.path.expanduser(os.path.expandvars(secfaas2fog_folder)))

    # define defaults Prolog files path
    default_placer_path = os.path.join(secfaas2fog_abs_path,'placer.pl')
    default_application_path = os.path.join(secfaas2fog_abs_path, 'application.pl')
    default_infrastructure_path = os.path.join(secfaas2fog_abs_path, 'infrastructure.pl')

    # statistical variables
    # TODO better comments
    applications_stats : dict = {}
    node_events : list = []
    link_events : list = []

    # configuration file path
    config_path = None

    # we should have 2 command line arguments
    if len(argv) != 2:
        print_usage()
        return 1

    error = False
    # parse command line arguments
    for i in range(0, len(argv) - 1, 2):
        if error:
            break
        option = argv[i]
        option_value = argv[i + 1]
        if (option == '-c'):
            # path of a valid config
            error = not os.path.isfile(option_value)
            config_path = option_value
    
    if error:
        print_usage()
        return 1
    
    # parse the config file
    config_has_parsed = parse_config(config_path)

    if not config_has_parsed:
        logger.critical("config parsing failed") # TODO devo stamparlo qui?
        print_usage()
        return 1
    
    # get from config list of applications
    applications = config.applications

    # save infrastructure file into default path
    shutil.copy(config.infrastructure_temp_path, default_infrastructure_path)

    # instance infrastructure
    nodes : dict[str, Node] = {}
    latencies : dict[str, dict[str, ( int, bool )]] = {}
    # TODO check errors on file opening
    node_pattern = r'^node\(([^,]+),([^,]+),(\[.*?\]),(\[.*?\]),\(([^,]+),([^,]+),([^\)]+)\)\)\.*'
    latency_pattern = r'^latency\(([^,]+),([^,]+),([^,]+)\)\.*'

    other_lines = []

    with open(default_infrastructure_path) as f:
        lines = f.readlines()

        for line in lines:
            if line.startswith('node'):
                line = line.replace(' ', '')
                #print(line)
                match = re.match(node_pattern, line).groups()

                node_id = match[0]
                provider = match[1]
                security_caps = match[2].replace('[','').replace(']','').split(',')
                software_caps = match[3].replace('[','').replace(']','').split(',')
                memory = inf if match[4] == 'inf' else int(match[4])
                v_cpu = inf if match[5] == 'inf' else int(match[5])
                mhz = inf if match[6] == 'inf' else int(match[6])

                node = Node(node_id, provider, security_caps, software_caps, memory, v_cpu, mhz)
                nodes[node_id] = node

                # create latency index for the node
                latencies[node_id] = {}

            elif line.startswith('latency'):
                line = line.replace(' ', '')
                match = re.match(latency_pattern, line).groups()

                first_node = match[0]
                second_node = match[1]
                latency = int(match[2])
                
                dictionary = latencies.get(first_node)
                dictionary[second_node] = { 'latency' : latency, 'available' : True }

            elif not line.startswith('%'):
                # save other crucial informations
                # discarding comments
                other_lines.append(line)
        
        #print(other_lines)
        #instance infrastructure
        infrastructure = Infrastructure(nodes, latencies, other_lines)

    
    # declare Prolog variable
    # once means that we take the first of the results
    secfaas2fog_command = "once(secfaas2fog(OrchestrationId, Placement))."

    for index in range(0, config.num_of_epochs):

        # PLACEMENT PHASE

        # we can place an application iff there is almost one active node
        if len(infrastructure.nodes) > len(infrastructure.crashed_nodes):

            # for each application
            for app in applications:
                
                # we want to trigger a new placement request?
                trigger = take_decision(app['placement_trigger_probability'])
                application_path = app['path']

                # get the name of the application (file)
                application_name = os.path.basename(application_path)

                if trigger:
                    logger.info("Placement triggered for application %s", application_name)

                    # save application file into default path
                    shutil.copy(application_path, default_application_path)

                    # try to place this app with SecFaas2Fog

                    # it will reply with a valid placement iff application can be placed
                    raw_placement = None
                    application_can_be_placed = False
                    query = False
                    
                    # save SecFaas2Fog starting time
                    start_time = datetime.now()
                    
                    with PrologMQI(prolog_path_args=[
                            "-s", default_placer_path
                    ]) as mqi:
                        with mqi.create_thread() as prolog_thread:

                            try:
                            
                                query = prolog_thread.query(secfaas2fog_command)
                            
                            except PrologError:
                                logger.error("Prolog execution failed")
                            
                            finally:
                                # save SecFaas2Fog finish time
                                end_time = datetime.now()

                    if query != False and isinstance(query, list):
                                    
                        raw_placement = query[0] # it is a dictionary

                        function_chain = find_dependencies(raw_placement)
                        placement = build_placement(raw_placement)
                        
                        #print(placement)
                        #print(function_chain)

                        application_can_be_placed = True

                        logger.info("Placement found for %s", application_name)
                    else:
                        logger.info("Placement failed for %s", application_name)
                    
                    if application_name not in applications_stats.keys():
                        applications_stats[application_name] = {}
                        applications_stats[application_name]['placements'] = []

                    # normal placement
                    placement_data : dict = {
                        'event' : "trigger",
                        'start' : start_time,
                        'end' : end_time,
                        'success' : application_can_be_placed
                    }

                    applications_stats[application_name]['placements'].append(placement_data)

                    if (application_can_be_placed) :
                        pass

                        # create application instance
                        # TODO actually we have 1 application so it is defined above

                        # place application over the infrastructure (update nodes capabilities: memory, number of vCPUs )
                        functions = placement.keys()
                        for function in functions:
                            node_id = placement[function].node_id
                            node = nodes[node_id]
                            #print("%s %s" % (function.id, node_id))
                            node.take_resources(memory = placement[function].memory, v_cpu = placement[function].v_cpu) # TODO functions are not padded

                        # launch application for a determined amount of time
                        thread = Orchestrator("Placement", 1000 + index, nodes, function_chain, placement)
                        thread.start()

                # update infastructure.pl
                update_infrastructure(infrastructure, default_infrastructure_path)

        # CRASH/RESURRECTION PHASE

        # node crash
        node_crashed = take_decision(config.node_crash_probability)

        node_resurrected = take_decision(config.node_crash_probability)

        # link crash
        link_crashed = take_decision(config.link_crash_probability)

        link_resurrected = take_decision(config.link_crash_probability)

        if node_crashed:
            node_id = infrastructure.simulate_node_crash()
            if node_id is not None:
                logger.info("Node %s crashed", node_id)
                
                # add event to the list
                event = {
                    'type' : 'crash',
                    'node_id' : node_id,
                    'when' : datetime.now()
                }
                node_events.append(event)

                # TODO there are affected applications?
        
        elif node_resurrected:
            node_id = infrastructure.simulate_node_resurrection()
            if node_id is not None:
                logger.info("Node %s resurrected", node_id)

                # add event to the list
                event = {
                    'type' : 'resurrection',
                    'node_id' : node_id,
                    'when' : datetime.now()
                }
                node_events.append(event)
        
        if link_crashed:
            first_node, second_node = infrastructure.simulate_link_crash()
            if first_node != None and second_node != None:
                logger.info("Link %s <-> %s crashed", first_node, second_node)

                # add event to the list
                event = {
                    'type' : 'crash',
                    'first_node_id' : first_node,
                    'second_node_id' : second_node,
                    'when' : datetime.now()
                }
                link_events.append(event)

                # TODO there are affected applications?
        
        elif link_resurrected:
            first_node, second_node = infrastructure.simulate_link_resurrection()
            if first_node != None and second_node != None:
                logger.info("Link %s <-> %s resurrected", first_node, second_node)

                # add event to the list
                event = {
                    'type' : 'resurrection',
                    'first_node_id' : first_node,
                    'second_node_id' : second_node,
                    'when' : datetime.now()
                }
                link_events.append(event)
        
        # update infastructure.pl
        update_infrastructure(infrastructure, default_infrastructure_path)

    # statistical prints

    global_number_of_placements = 0 # total number of placements (for all applications)
    global_successes = 0
    global_sum = 0

    applications_stats_keys = applications_stats.keys()

    for app_name in applications_stats_keys:

        application = applications_stats[app_name]
        
        # local accumulators
        num_of_placements = len(application['placements'])
        successes = 0
        sum = 0

        placement_results = application['placements']
        
        for result in placement_results:
            
            end_millisec = result['end'].timestamp() * 1000
            start_millisec = result['start'].timestamp() * 1000
            sum += end_millisec - start_millisec
            
            if result['success'] :
                successes += 1
        
        # enrich application stats
        application['num_of_placements'] = num_of_placements
        application['successes'] = successes
        application['average_secfaas2fog_execution'] = float(f'{sum/num_of_placements}')

        # accumulate global variables
        global_number_of_placements += num_of_placements
        global_successes += successes
        global_sum += sum
    
    stats_to_dump = {
        'total_placements' : global_number_of_placements,
        'total_successes' : global_successes,
        'average_secfaas2fog_execution' : float(f'{global_sum/global_number_of_placements}'),
        'node_events' : node_events,
        'link_events' : link_events,
        'data' : applications_stats
    }

    print("Number of placements: %d" % global_number_of_placements)
    print("Average time of SecFaas2Fog placement: " + str(float(f'{global_sum/global_number_of_placements:.2f}')) + " milliseconds")
    print("Successess: %d" % global_successes)

    print("Writing report file...")

    # TODO MAKE IT COMMAND ARG
    with open("stats.json", 'w') as file:
        json.dump(stats_to_dump, indent = 4, default = str, fp = file)

    print("Done!")


if __name__ == "__main__":
    main(sys.argv[1:])
