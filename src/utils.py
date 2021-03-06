"""Utils functions"""


from application.placed_function import FunctionState, PlacedFunction


def get_ready_functions(application_chain: dict) -> list[str]:
    """
    Returns the list of ready functions.
    A ready function is a function without dependencies
    """
    to_return = []
    functions = application_chain.keys()
    for fun in functions:
        dependencies = application_chain[fun]
        if not dependencies or None in dependencies:
            to_return.append(fun)

    return to_return


def get_direct_dependents(application_chain: dict, function_id: str) -> list[str]:
    """
    Returns the list of directly dependent functions of function_id
    """

    to_return = []
    for function_key in application_chain:
        dependencies: list = application_chain[function_key]
        if function_id in dependencies:
            to_return.append(function_key)

    return to_return


def delete_executed_function(application_chain: dict, function_id):
    """
    Delete function_id from the chain:
    - delete its key in the chain
    - delete itself from other functions' lists
    """

    application_chain.pop(function_id)

    for function_key in application_chain:
        dependencies: list = application_chain[function_key]
        if function_id in dependencies:
            dependencies.remove(function_id)


def delete_functions_chain_by_id(application_chain: dict, function_to_remove) -> list:
    """
    Delete a chain starting from function_to_remove from the chain
    Returns the list of deleted functions
    """

    application_chain.pop(function_to_remove)

    dept_to_remove = []

    functions = application_chain.keys()
    for fun in functions:
        dependencies: list = application_chain.get(fun)
        if function_to_remove in dependencies:
            dependencies.remove(function_to_remove)

            # if it was the only dependency, remove the dependent
            if len(dependencies) == 0:
                dept_to_remove.append(fun)

    result = [function_to_remove]

    for fun in dept_to_remove:
        result += delete_functions_chain_by_id(application_chain, fun)

    return result


def get_recursive_dependents(function_id: str, application_chain: dict) -> list:
    """
    Returns the list of dependent functions of function_id
    """

    dependents = get_direct_dependents(application_chain, function_id)

    to_return = dependents

    for fun in dependents:
        to_return += get_recursive_dependents(fun, application_chain)

    return list(set(to_return))


def get_recursive_waiting_dependencies(
    function_id: str,
    application_chain: dict[str, list],
    placement: dict[str, PlacedFunction],
    to_return: set
):
    """
    Returns set of function_id's dependency functions which are interested by function_id crash
    """
    function_obj = placement[function_id]
    # if the function is not waiting, then its dependencies already finished
    if function_obj.state == FunctionState.WAITING:
        function_dependencies = application_chain[function_id]
        for dependency_id in function_dependencies:
            # add the dependency only if it is waiting or running
            # and not if it is completed
            if placement[dependency_id].state in [FunctionState.WAITING, FunctionState.RUNNING]:
                to_return.add(dependency_id)
                get_recursive_waiting_dependencies(
                    dependency_id,
                    application_chain,
                    placement,
                    to_return
                )


def find_functions_level(result: dict, function: str, chain: dict, level: int = 0):
    """
    Find for each function in the chain its level of execution
    """

    list_of_functions = get_direct_dependents(chain, function)

    old_level = result[function] if function in result.keys() else 0

    result[function] = max(old_level, level)

    if len(list_of_functions) > 0:
        for function_name in list_of_functions:
            find_functions_level(result, function_name, chain, level + 1)


def get_starting_function(
    interested_functions: list,
    original_chain: dict[str, list],
    placement: dict[str, PlacedFunction]
):
    """
    Returns the starting function between a list of interested functions
    """

    first_function = get_ready_functions(original_chain)[0]

    # build dictionary with the form
    # dict[function_id] = level
    levels_by_function = {}
    find_functions_level(levels_by_function, first_function, original_chain)

    # build dictionary with the form
    # dict[level] = {function_ids at level}
    functions_by_level: dict[int, list] = {}

    functions = levels_by_function.keys()
    for function_name in functions:
        functions_by_level[levels_by_function[function_name]] = []
    for function_name in functions:
        functions_by_level[levels_by_function[function_name]].append(function_name)

    # find the oldest between interested functions (by executing order)
    oldest = interested_functions[0]
    for function in interested_functions:
        if levels_by_function[function] < levels_by_function[oldest]:
            oldest = function

    found = False

    candidates_list = [oldest]

    while not found:
        for candidate in candidates_list:

            # get all dependent functions of the candidate
            candidate_dependents = get_recursive_dependents(candidate, original_chain)

            found = True

            # if an interested function not depends on the candidate
            # then we have to change candidate
            for function in interested_functions:
                if function == candidate:
                    continue
                if function not in candidate_dependents:
                    found = False
                    break

            if not found:
                continue

            # if a dependent of the candidate has other
            # waiting or running dependencies which are not in candidate_dependents
            # then we have to change candidate
            for dependent in candidate_dependents:
                if not found:
                    break
                dependent_dependencies = original_chain[dependent]
                for node_id in dependent_dependencies:
                    if node_id != candidate:
                        if node_id not in candidate_dependents:
                            if placement[node_id].state in [
                                FunctionState.WAITING,
                                FunctionState.RUNNING,
                            ]:
                                found = False
                                break

            if found:
                return candidate

        # search a new candidate by decrease the level
        # we are sure that, at most, the function at level 0 will be the candidate
        candidate_level = levels_by_function[candidate]
        new_candidate_level = candidate_level - 1
        candidates_list = functions_by_level[new_candidate_level]

    return None


def is_edge_part(path: list, node_x: str, node_y: str):
    """
    Returns True if the edge is part of the path
    False otherwise
    """
    try:
        index = path.index(node_x)
        index_before = index - 1
        index_after = index + 1

        check = False
        if index_before >= 0:
            check = check or path[index_before] == node_y
        if index_after < len(path):
            check = check or path[index_after] == node_y

        return check
    except ValueError:
        return False


def take_decision(true_probability: float) -> bool:
    """
    Returns True with probabilty true_probability
    """

    import random

    return random.random() < true_probability
