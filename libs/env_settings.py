"""
    Module for setting and retrieving environment settings
"""
import os
import requests
import time
from . import logger

log = logger.get_logger(f"{os.path.basename(__file__)}")


def get_tjb_root(path_to_file: str) -> str:
    """
    Get the TJB_ROOT environment variable (temporary location of TJB_ROOT when unpacked for testing)

    :param path_to_file: path of the file in the TJB
    :type path_to_file: str
    :return: temporary location of TJB when under test, files location in repo when building documentation
    :rtype: str

    This function was created as TJB_ROOT is a vairable needed for tjbs when they are removed from the repo to be tested
    The auto-documentation Sphinx has no way to know this variable as it changes for each test run
    Sphinx expects tests to be run where the file is saved so we return that value if its a documentation build calling the test
    """
    try:
        if os.environ["SPHINX"] == "TRUE":
            return os.path.dirname(os.path.abspath(path_to_file))
    except KeyError:
        pass
    return os.environ['TJB_ROOT']


def get_env_variable(env_var: str) -> str:
    """
    Return the value of a variable set in the lab environment

    ref: https://confluence.verifone.com:8443/pages/viewpage.action?spaceKey=RIX&title=RIX+Test+Lab+Variables

    :param env_var: name of the variable
    :type env_var: str
    :return: variable value
    :rtype: str
    """
    log.debug(f"Getting {env_var} from environment")
    try:
        return os.environ[env_var]
    except KeyError:
        return None


def power_relay_available() -> bool:
    """
    Find if there is a power relay available for the device

    :return: True if there is any power relay available
    :rtype: bool
    """
    battery_relay_available = "BATT_RELAY_OFF" in os.environ and "BATT_RELAY_ON" in os.environ
    power_relay_available = "POWER_RELAY_OFF" in os.environ and "POWER_RELAY_ON" in os.environ
    log.debug(f"Battery relay available: {battery_relay_available}")
    log.debug(f"Power relay available: {power_relay_available}")
    return battery_relay_available or power_relay_available


def __get_relay() -> list:
    """
    Return if the connected relays are battery or power or both

    :return: ["POWER"] if it is a power relay ["BATT"] if it is a battery relay, ["POWER", "BATT"] if its both
    :rtype: list
    """
    relays = []
    log.debug("Checking what relays are present in environment")
    if "POWER_RELAY_OFF" in os.environ and "POWER_RELAY_ON" in os.environ:
        log.debug("Power relay found")
        relays.append("POWER")
    if "BATT_RELAY_OFF" in os.environ and "BATT_RELAY_ON" in os.environ:
        log.debug("Battery relay found")
        relays.append("BATT")

    return relays


def __set_power_relay(url: str) -> int:
    """
    Use the relay url to set the device to on or off

    :param url: url from env variable
    :type url: str
    :return: status code from the request
    :rtype: int
    """
    log.debug(f"Sending request to {url}")
    r = requests.get(url)
    log.debug(f"Received response: {r.status_code}")
    return r.status_code


def power_relay_off() -> dict:
    """
    Power device off

    :return: dict of relays and the result code from sending request to set the relay
    :rtype: dict
    """
    res_codes = {}
    for relay in __get_relay():
        log.debug(f"Setting {relay}_RELAY_OFF")
        res_codes[relay] = __set_power_relay(get_env_variable(f"{relay}_RELAY_OFF"))
    return res_codes


def power_relay_on() -> dict:
    """
    Power device on

    :return: dict of relays and the result code from sending request to set the relay
    :rtype: dict
    """
    res_codes = {}
    for relay in __get_relay():
        log.debug(f"Setting {relay}_RELAY_ON")
        res_codes[relay] = __set_power_relay(get_env_variable(f"{relay}_RELAY_ON"))
    return res_codes


def toggle_power_relay() -> int:
    """
    Power off the device and power it back on

    :return: 1 if successful, 0 if not
    :rtype: int
    """
    log.debug("Toggling power relays")
    if power_relay_available():
        res_codes = power_relay_off()
        for res in res_codes.items():
            # successful status codes start with 2
            # https://www.tutorialspoint.com/python_network_programming/python_request_status_codes.htm
            if not str(res[1]).startswith("2"):
                log.error(f"{res[0]} returned status code {res[1]}")
                return 0
        # allow any residual power to dissipate before reengaging relay
        time.sleep(2)
        res_codes = power_relay_on()
        for res in res_codes.items():
            # successful status codes start with 2
            if not str(res[1]).startswith("2"):
                log.error(f"{res[0]} returned status code {res[1]}")
                return 0
            return 1
    else:
        return 0
