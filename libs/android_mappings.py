"""
Module for returning Android command mappings
"""
import json
from . import env_settings


def get_mappings(android_release: str):
    """
    get all mappings from cmd_mappings.json file

    :param android_release: version of android currently under test (8 or 10)
    :type android_release: str
    :return: dictionary of mappings
    :rtype: dict
    """
    # open the mappings file and load it
    cwd = env_settings.get_tjb_root(__file__)
    with open(f"{cwd}/libs/cmd_mappings.json") as f:
        cmd_mappings = json.load(f)
    # recursively run through the mappings file getting the correct command for the
    # android version under test
    mappings = {k: v[f"android{android_release}"] for (k, v) in cmd_mappings.items()}
    # return the dictionary of correct commands for the android version under test
    return mappings
