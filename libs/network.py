"""
    Module for network functions
"""
import socket
import ipaddress
import subprocess
import re
import time
import os
from . import logger, env_settings, executor, android_mappings
from .config_parser import ConfigParser as cp


LOGGER = logger.get_logger(f"{os.path.basename(__file__)}")
cwd = env_settings.get_tjb_root(f"../{os.path.basename(__file__)}")
cf = cp(f"{cwd}/libs/config.ini")
TIMEOUT = cf.get_int("NETWORK", "interface_timeout")
WAIT = cf.get_int("NETWORK", "bring_up_wait")


def __run_cmd(cmd: str, executor):
    """
    Function for sending commands to either the device under test or the host machine

    :param cmd: command to be run
    :type cmd: str
    :param executor: connected executor to device, None if command is to be sent to host
    :type executor: executor
    :return: response from command
    :rtype: str
    """
    if not executor:
        LOGGER.debug(f"Sending {cmd} to local host")
        res = subprocess.run(cmd.split(),
                             check=False,
                             stdout=subprocess.PIPE,
                             universal_newlines=True,
                             timeout=30)
    else:
        LOGGER.debug(f"Sending {cmd} to device under test")
        res = executor.run(cmd, raw=True)

    LOGGER.debug(f"Response: {res.stdout}")
    return res


def ping(destination: str, count=1, interval=1.0, interface=None, timeout=5, executor=None):
    """
    Function for sending pings to a destination
    Returns % of packets lost

    If pings are to be sent from host machine set executor to None

    :param destination: where to send the pings to
    :type destination: str
    :param count: number of pings to send, defaults to 1
    :type count: int, optional
    :param interval: time to wait (sec) between pings, defaults to 1.0
    :type interval: float, optional
    :param interface: interface to send the pings from, defaults to None
    :type interface: str, optional
    :param timeout: time to wait for reply, defaults to 5
    :type timeout: int, optional
    :param executor: if given pings will be sent from device connected to executor, defaults to None, defaults to None
    :type executor: executor, optional
    :return: percent of packet loss
    :rtype: str
    """

    args = "ping" + (f" -c {count}" if count else "")\
        + (f" -i {interval}" if interval else "")\
        + (f" -I {interface}" if interface else "")\
        + (f" -W {timeout}" if timeout else "")\
        + f" {destination}"

    LOGGER.info(
        f"Pinging {destination} {count} times at intervals of {interval} seconds")
    res = __run_cmd(args, executor)

    packet_loss = re.findall(r"\d+%+|$", res.stdout)[0]

    if packet_loss == '':
        LOGGER.error(
            "Error processing results: could not find packet loss in command result")
        LOGGER.error(f"{res.stderr}")

    return packet_loss


def bring_up_interface(interface_name: str, executor=None):
    """
    Bring up specified interface

    :param interface_name: name of the interface
    :type interface_name: str
    :param executor: connected executor to device, defaults to None, None if interface is attached to host
    :type executor: executor, optional
    """
    if check_interface_state(interface_name, executor) in ["up", "unknown"]:
        LOGGER.info(f"{interface_name} is UP")
        return
    else:
        __run_cmd(f"ifconfig {interface_name} up", executor).stdout
        time.sleep(WAIT)


def bring_down_interface(interface_name: str, executor=None):
    """
    Bring down specified interface

    :param interface_name: name of the interface
    :type interface_name: str
    :param executor: connected executor to device, defaults to None, None if interface is attached to host
    :type executor: executor, optional
    """
    if check_interface_state(interface_name, executor) == "down":
        LOGGER.info(f"{interface_name} is DOWN")
        return
    else:
        __run_cmd(f"ifconfig {interface_name} down", executor)
        time.sleep(WAIT)


def check_interface_state(interface_name: str, executor=None):
    """
    Get state of specified interface

    :param interface_name: name of the interface to check
    :type interface_name: str
    :param executor: connected executor to device, defaults to None, None if checking host
    :type executor: executor, optional
    :return: state of the interface
    :rtype: str
    """
    if interface_name == "bluetooth":
        ans = __run_cmd("settings get global bluetooth_on",
                        executor).stdout.strip()
        if ans == "1":
            return "up"
        else:
            return "down"
    return __run_cmd(f"cat /sys/class/net/{interface_name}/operstate", executor).stdout.strip()


def enable_com_service(service, executor, interface=None):
    """
    enables a communication service in the options
        - data: Control mobile data connectivity
        - wifi: Control the Wi-Fi manager
        - bluetooth: Control Bluetooth service

    :param service: name of the service to enable
    :type service: str
    :param executor: connected executor
    :type executor: executor
    :param interface: name of the interface to check after enabling service
    :type interface: str (optional)
    """
    services = {"data": "rmnet_data*",
                "wifi": "wlan0",
                "bluetooth": "bluetooth",
                "ethernet": "eth0"}
    if service not in services.keys():
        raise KeyError(f'service must be in {services.keys()}')
    if not interface:
        interface = services[service]

    mappings = android_mappings.get_mappings(executor.android_release)
    if service == "ethernet":
        executor.run(mappings["enable_ethernet"])
    else:
        __run_cmd(f"svc {service} enable", executor)
    count = 0
    while check_interface_state(interface, executor) == "down":
        if count == TIMEOUT:
            raise TimeoutError(f"{interface} not up after enabling {service}")
        time.sleep(WAIT)
        count += 1
    return


def disable_com_service(service, executor):
    """
    disables a communication service in the options
        - data: Control mobile data connectivity
        - wifi: Control the Wi-Fi manager
        - bluetooth: Control Bluetooth service

    :param service: name of the service to disable
    :type service: str
    :param executor: connected executor
    :type executor: executor
    """
    mappings = android_mappings.get_mappings(executor.android_release)
    services = ["data", "wifi", "bluetooth", "ethernet"]
    if service not in services:
        raise KeyError(f'service must be in {services}')
    if service == "ethernet":
        executor.run(mappings["disable_ethernet"])
    else:
        __run_cmd(f"svc {service} disable", executor)


def get_mac_address(interface, executor=None) -> str:
    """
    return the MAC address of the given interface

    :param interface: name of the interface
    :type interface: str
    :return: MAC address
    :rtype: str
    """
    return __run_cmd(f"cat /sys/class/net/{interface}/address", executor).stdout.strip()


def get_ip_address(interface, executor=None) -> str:
    """
    Get ipaddress from a given interface

    :param interface: interface to get IP address from
    :type interface: str
    :param executor: Connected executor, defaults to None
    :type executor: executor, optional, gets IP of local interface if None
    :return: IP address of the interface
    :rtype: str
    """
    ip_addr = __run_cmd(
        f"ifconfig {interface} | grep 'inet addr:' | cut -d: -f2| cut -d' ' -f1", executor).stdout.strip()

    if validate_ip(ip_addr):
        return ip_addr
    else:
        LOGGER.error(f"Could not get IP address from {interface}")
        return None


def validate_ip(ip: str) -> bool:
    """
    Checks if the given ip address is valid

    :param ip: IPV4 address
    :type ip: str
    :return: True if IP is valid, False if not
    :rtype: bool
    """
    try:
        ipaddress.ip_address(ip)
        return True
    except:
        return False


def is_port_in_use(ip: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((ip, port)) == 0


def exc_wifi_to_eth(exc:  executor, eth_interface_name: str, timeout=120, usr="root") -> executor:
    """
    change current executor from using wifi to use ethernet

    :param exc: current executor using wifi
    :type exc: executor
    :param eth_interface_name: name of the ethernet interface
    :type eth_interface_name: str
    :param timeout: time to wait to bring up ethernet interface, defaults to 120
    :type timeout: int, optional
    :param usr: user level of the new executor, defaults to root
    :type usr: str, optional
    :return: executor connected over ethernet
    :rtype: executor
    """
    enable_com_service("ethernet", exc)
    return _change_executor_interface(exc, eth_interface_name, timeout, usr)


def exc_eth_to_wifi(exc: executor, wifi_interface_name: str, timeout=120, usr="root") -> executor:
    """
    change current ethernet executor to use wifi

    :param exc: ethernet connected executor
    :type exc: executor
    :param wifi_interface_name: name of the wifi interface
    :type wifi_interface_name: str
    :param timeout: time to wait to bring up wifi interface, defaults to 120
    :type timeout: int, optional
    :param usr: user level of the new executor, defaults to root
    :type usr: str, optional
    :return: executor connected over wifi
    :rtype: executor
    """
    model = exc.run("getprop ro.product.model")
    try:
        enable_com_service("wifi", exc)
    except TimeoutError:
        LOGGER.info("Excepting timeout as ethernet has not been disabled yet")
    disable_com_service("ethernet", exc)
    # only the t650 needs to have wifi enabled and
    # connected to, all other devices auto switch
    # to wifi as soon as ethernet is disabled
    if "t650" in model:
        return _change_executor_interface(exc, wifi_interface_name, timeout, usr)
    else:
        return executor.get_executor(usr, False, 30)


def _change_executor_interface(exc: executor, to_intf: str, timeout: int, usr: str) -> executor:
    """
    change the current connected executor to the given interface

    :param exc: current connected executor
    :type exc: executor
    :param to_intf: interface to change to
    :type to_intf: str
    :param timeout: time to wait to bring up new interface
    :type timeout: int
    :param usr: user level of the new executor
    :type usr: str
    :raises TimeoutError: raised if cannot bring up new interface
    :return: executor connected over the new interface
    :rtype: executor
    """
    # get the interface ip address
    int_ip = get_ip_address(to_intf, exc)
    start = time.time()
    LOGGER.info(f"Checking for {to_intf} IP address")
    # loop for a max of TIMEOUT seconds checking for interface IP
    while not int_ip:
        try:
            int_ip = get_ip_address(to_intf, exc)
        except subprocess.TimeoutExpired as e:
            LOGGER.debug(f"Caught Exception {e}")
        if time.time() > start + timeout:
            raise TimeoutError(f"Failed to get IP address of {timeout} before timeout")
        time.sleep(1)
    # start a new connection over net using the new IP
    LOGGER.info(f"Connecting to device on {int_ip}")
    exc = executor.get_executor(usr, False, 30, ip=int_ip)
    return exc
