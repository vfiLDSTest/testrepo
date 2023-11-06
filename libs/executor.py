"""
The purpose of this module is to unify the communication between host 
and VOS/Android Verifone devices ADBClient inherits from VosClient which 
is an API to communicate with the TRCC python module

This module should allow the writing of test cases to be OS agnostic when dealing with 
commands on the Linux level while also not inhibiting writing specific device tests

When using this library it is best to call get_executor to 
instantiate the class for you as it will determine the OS type 
and return the correct executor connected and setup

module expects the following environment variables to be set and populated
    - TRC_DEVICE_IP

Author: kennetho1
"""
from .vos_client import VosClient, TrackingVosClient
from . import logger, saving_data, env_settings
from .config_parser import ConfigParser
from typing import Callable
from datetime import datetime
import os
import re
import subprocess
import time
import trcc.client
import typing


class ADBClient(VosClient):
    """
    High level API for TRCS inheriting from pyvos.host.vos_client.VosClient
    with docstrings, one call per one logical action and sensible defaults

    :param VosClient: Inherits from VosClient
    :type VosClient: Class
    :raises ConnectionError: If executor cannot find device ID in adb devices output
    :raises ValueError: If given invalid app name
    :raises OSError: If attempt to load non .apk file onto device
    :raises TimeoutError: If device does not boot within timeout
    :return: connected executor
    :rtype: executor object
    """

    def __init__(self, usb=False, ip=False):
        """
        Gets variables from config
        Sets up logger
        Sets class variables
        """
        # instansiate parent class
        super().__init__()
        # set up instance variables
        self.user = None
        self.silent = None
        self.timeout_sec = None
        # set variables given to executor
        self.usb = usb
        self.ip = ip
        # set up config file for executor variables
        self.cwd = env_settings.get_tjb_root(f"../{os.path.basename(__file__)}")
        cf = ConfigParser(f"{self.cwd}/libs/config.ini")
        # set up logger
        self.log = logger.get_logger(
            f"{os.path.basename(__file__)}",
            cf.get_int("EXECUTOR", "console_log_level"),
            cf.get_int("EXECUTOR", "logfile_log_level"),
        )
        # get sleep time from config
        self.max_sleep_time = cf.get_int("EXECUTOR", "max_sleep_time")
        self.max_connect_retries = cf.get_int("EXECUTOR", "max_connect_retries")
        # get location to put bug report if needed
        self.bugreport_dir = cf.get_str("EXECUTOR", "bugreport_dir")
        # get port number from config
        self.adb_port = cf.get_str("EXECUTOR", "port_number")
        # set the exact adb bin call
        self.adb = "/usr/bin/adb"
        self.build_flavor = None
        self.android_release = None
        self.uptime = None

        # if connecting over usb or a specific IP TRC will not be
        # available unless IP is the same IP as test env
        trc_ip = os.getenv("TRC_DEVICE_IP")
        if not self.usb and not self.ip or self.ip == trc_ip:
            self.trc_available = True
            self.ip = self.device = trc_ip
        # if there is an IP and its is not equal to the trc_ip
        # trc will not be available
        elif self.ip and self.ip != trc_ip:
            self.trc_available = False
            self.device = self.ip
        # if we are using USB TRC will not be available
        elif self.usb:
            self.trc_available = False
            self.device = self.client.request_one(
                "std", "device_serial_number"
            ).replace("A-", "")
        if not self.usb:
            self.device = f"{self.device}:{self.adb_port}"

    def __send(self, args: list, timeout_sec=None) -> subprocess.CompletedProcess:
        """
        Run subprocess with the given args

        :param args: list of commands that will be run on host cli
        :type args: list
        :param timeout_sec: time in seconds to wait for command to run, defaults to 60
        :type timeout_sec: int, optional
        :return: subprocess object
        :rtype: subprocess.CompletedProcess
        """
        self.log.debug(f'running command: {" ".join(args)}')

        if not timeout_sec:
            timeout_sec = self.timeout_sec
        result = subprocess.run(
            args,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout_sec,
        )
        if result.stdout:
            self.log.debug(f"command returned: {result.stdout}")
        if result.stderr:
            self.log.error(f"command returned: {result.stderr}")
        return result

    def __adb_is_connected(self, device: str) -> bool:
        """
        find connected device with ``adb devices`` command

        :param device: IP or serial number to search for
        :type device: str
        :return: True if device is connected
        :rtype: bool
        """

        self.log.debug(f"Checking if {device} is connected")
        # find any adb connections with IP or Serial Num
        return bool(re.findall(device, f"{self._adb_devices()}"))

    def __get_port_via_trcc(self) -> str:
        """
        use the trc std shell command to get the adb tcp port

        :return: port number currently in use
        :rtype: str
        """
        port = self.std_request("shell", "getprop service.adb.tcp.port", expect_result=True)
        # strip returned port number of unwanted characters
        port = "".join([x for x in port if x not in ["[", "]", "'"]])
        self.log.info(f"found port in use: {port}")
        if re.findall(f"[0-9]+", port):
            return port
        else:
            raise ValueError(f"Expected port number, found {port}")

    def __connect_over_net(self):
        """
        Make a connection to the device IP over net

        Attempt to connect on default port
        If no connection can be made and TRC agent is available
        get the port in use from TRC and reset it to default

        :raises ConnectionError: If no connection can be made
        """
        self.log.info(f"Attempting to connect to {self.device} on the default port")
        if self._adb_connect(f"{self.device}"):
            self.log.info(f"Connected to {self.device}")
            return

        if self.trc_available:
            # if we still do not have a connection the device may be using
            # an incorrect port so try get the port using TRC
            port = self.__get_port_via_trcc()
            self._adb_connect(f"{self.ip}:{port}")
            if self._adb_set_port(f"{self.ip}:{port}"):
                return

        raise ConnectionError(f"Could not connect to {self.device}")

    def __adb_setup(self):
        """
        Connect to specific device (TRC IP or serial number if using USB or specif IP) on the port specified by `self.port`

        - if connecting using USB
            Connection should be available without calling connect
        - if connecting using IP (net)
            Connect using __connect_over_net method

        :raises ConnectionError: If using usb and no device is found
        """
        # first check if the device is already connected
        self.log.info(f"Checking if {self.device} is connected")
        if self.__adb_is_connected(f"{self.device}"):
            self.log.info(f"Connected to {self.device}")
            return
        # if there is no connection and we are using usb there is nothing
        # to be done to start the connection from here
        elif self.usb:
            raise ConnectionError(f"No device connected with {self.device}")
        # if there are no current connections start one if using net
        elif self.ip:
            self.log.info(f"No connection to {self.device} found")
            self.__connect_over_net()

    def _adb_connect(self, device=None) -> bool:
        """
        connect to device

        :param device: connect to ``ip:port``, defaults to None
        :type device: str, optional
        :return: True if successful connected to device
        :rtype: bool
        """
        # if no device given default to the init device
        if not device:
            device = self.device
        if self.usb:
            return self.__adb_is_connected(device)
        # try to connect to the device
        result = ""
        i = 0
        while not re.findall("connected", f"{result}") and i < self.max_connect_retries:
            result = self.__send([self.adb, "connect", device]).stdout
            time.sleep(self.max_sleep_time)
            i += 1
        return bool(re.findall("connected", f"{result}"))

    def _adb_set_port(self, device: str) -> Callable:
        """
        set adb connection port on device to self.port

        :param device: connect to ``ip:port``
        :type device: str
        :return: call to self._adb_connect
        :rtype: Callable
        """

        self.log.debug(f"resetting connection from {device} to {self.device}")
        # reset the port on the connected device to self.adb_port
        self.__send([self.adb, "-s", device, "tcpip", self.adb_port])
        time.sleep(self.max_sleep_time)
        return self._adb_connect(f'{device.split(":")[0]}:{self.adb_port}')

    def _adb_devices(self) -> str:
        """
        Execute adb devices and display output

        :return: stdout of ``adb devices`` command
        :rtype: str
        """
        # get the devices currently connected via adb
        out = self.__send([self.adb, "devices", "-l"])
        # write the found devices to a file
        with open("out.txt", "w+") as fout:
            fout.write(out.stdout)
        # write any errors that may have occurred to a file
        if out.stderr:
            with open("err.txt", "w+") as ferr:
                ferr.write(out.stderr)
        self.log.debug(f'adb devices:\n{out.stdout}')
        return out.stdout

    def _set_root(self, force=False) -> typing.Union[bool, Callable]:
        """
        Sets the adb connection to have root access

        :return: True if already root or call to self.check_root
        :rtype: typing.Union[bool, Callable]
        """

        self.log.debug("checking if connection is root")
        if not self.check_root() or force:
            self.log.debug("setting connection as root")
            # Lab has observed devices returning "" when setting root
            # this should not cause the whole test to fail so attempt
            # to set root 3 times before raising an exception
            res = ""
            i = 0
            # if result is not an empty string or if we exceed 3 attempts bail out
            while res == "" and i < self.max_connect_retries:
                res = self.__send([self.adb, "-s", self.device, "root"]).stdout.strip()
                time.sleep(self.max_sleep_time)
                self._adb_connect()
                i += 1
            if res not in ["restarting adbd as root", "adbd is already running as root"]:
                self.log.error(f"Got response: {res}")
                if "userdebug" in self.build_flavor.lower():
                    raise ConnectionError("Could not set connection to root")
            else:
                self.user = "root"
        else:
            return True
        # setting root causes the executor to disconnect
        # attempt to reconnect for 5 seconds
        i = 0
        while not self.__adb_is_connected(self.device) and i < self.max_connect_retries:
            self._adb_connect()
            time.sleep(self.max_sleep_time)
            i += 1
        return self.check_root()

    def _set_unroot(self, force=False) -> typing.Union[bool, Callable]:
        """
        Sets the adb connection to have user access

        :return: True if already unroot or call to self.check_root
        :rtype: typing.Union[bool, Callable]
        """
        self.log.debug("checking if connection is non root")
        if self.check_root() or force:
            self.log.debug("setting connection as non root")
            self.__send([self.adb, "-s", self.device, "unroot"])
            self.user = "usr1"
        else:
            return True
        # setting root causes the executor to disconnect
        # attempt to reconnect for 5 seconds
        i = 0
        while not self.__adb_is_connected(self.device) and i < self.max_connect_retries:
            self._adb_connect()
            time.sleep(self.max_sleep_time)
            i += 1
        return not self.check_root()

    def check_root(self) -> bool:
        """
        check if the current connection has root access

        :return: True if root
        :rtype: bool
        """
        if not self.user:
            self.user = self.__send(
                [self.adb, "-s", self.device, "shell", "whoami"]
            ).stdout.strip()
        self.log.debug(f"connection is {self.user}")
        return self.user == "root"

    def _check_app(self, app: str) -> bool:
        """
        Check the app name is in the correct format

        app must be in the format com.domain.appname

        :param app: name of the app
        :type app: str
        :raises ValueError: if app name does not start with com.
        :return: True if app name is in the correct format
        :rtype: boolean
        """
        if not app.startswith("com."):
            raise ValueError(f"Incorrect app name: {app}. Must start with com.")
        return True

    def _restart_app(self, app: str):
        """
        restart given application

        app must be in the format com.domain.appname

        :param app: name of app to restart
        :type app: str
        """
        self._stop_app(app)
        self._start_app(app)

    def _stop_app(self, app: str):
        """
        Terminate the given app

        app must be in the format com.domain.appname

        :param app: name of the app to terminate
        :type app: str
        """
        self._check_app(app)
        self.log.info(f"Terminating {app}")
        self.run(f"am force-stop {app}")
        time.sleep(self.max_sleep_time)

    def _start_app(self, app: str):
        """
        Force start app

        app must be in the format com.domain.appname

        :param app: name of the app to start
        :type app: str
        """
        self.log.info(f"Starting {app}")
        self.run(f"am start -n {app}/{app}.MainActivity")
        time.sleep(self.max_sleep_time)

    def std_request(self, service: str, cmd: str, timeout_sec=None, expect_result=False) -> str:
        """
        Send standard TRC request to device

        :param service: TRC service to be called
        :type service: str
        :param timeout_sec: time to wait for command to complete, defaults to 30
        :type timeout_sec: int, optional
        :param expect_result: response expected, defaults to False
        :type expect_result: bool, optional
        :raises trcc.client.TrcError: if response when no respose expected raise error
        :return: If expect_result=True returns response from TRC
        :rtype: list
        """
        if not timeout_sec:
            timeout_sec = self.timeout_sec
        return self._VosClient__request("std", service, timeout_sec, expect_result, cmd)

    def print_sw_version(self):
        """
        Print the version of the software running on the device under test to the log
        """
        self.log.info(f"Build on {self.device} : {self.run('getprop ro.build.description')}")

    def _set_build_flavor(self):
        """
        setter method for setting the os type in the build_flavor class variable
        """
        self.build_flavor = self.__send([self.adb, "-s", self.device, "shell",
                                        "getprop", "ro.build.flavor"]).stdout.strip()
        self.android_release = self.__send([self.adb, "-s", self.device, "shell",
                                            "getprop", "ro.build.version.release"]).stdout.strip().split(".")[0]

    def get_device_uptime(self):
        """
        return datetime since the system has been up

        :return: datetime of when the system came online
        :rtype: datetime object
        """
        # get the last time the system booted
        #   remove the seconds data as the uptime command can be off by 1 second when run
        #   and this may be interperted as a reboot as 2 datetimes of the same uptime would
        #   not be equal
        try:
            self.uptime = datetime.strptime(self.run("uptime -s", timeout_sec=5).strip()[:-3], "%Y-%m-%d %H:%M")
        except ValueError:
            pass
        self.log.debug(f"Current uptime {self.uptime}")
        # return the datetime of last boot
        return self.uptime

    def setup(self, user=None, silent=None, timeout_sec=None):
        """
        set all run options to given parameters

        :param user: user level the test will run under ('root', 'usr1'), defaults to None
        :type user: str, optional
        :param silent: only return exit codes from commands, defaults to None
        :type silent: bool, optional
        :param timeout_sec: time to wait in seconds for command to return, defaults to None
        :type timeout_sec: int, optional
        """
        if silent != None:
            self.silent = silent
        if timeout_sec != None:
            self.timeout_sec = timeout_sec
        self.__adb_setup()
        self._set_build_flavor()
        if user == "root":
            self._set_root(force=True)
        else:
            self._set_unroot
        self.print_sw_version()
        self.uptime = self.get_device_uptime()

    def remove_files(self, files: str, user=None, force=False):
        """
        remove files from device

        :param files: files to remove
        :type files: str
        :param user: set connection to root or non root, defaults to None
        :type user: str, optional
        :param force: False (default) - raise exception on first error, True - ignore errors like rm -f, defaults to False
        :type force: bool, optional
        :return: call to the inherited remove_files method
        """

        if not user:
            user = self.user
        self.log.debug(f"Removing {files}")
        return super().remove_files(files, user=user, force=force)

    def get_file(self, device_path: str, host_path=None) -> str:
        """Get file from device

        :param device_path: path to file that will be read from device
        :type device_path: str
        :param host_path: path to put file on host, pick random name if None, defaults to None
        :type host_path: str (path), optional
        :return: path to file on host
        :rtype: str
        """

        # if no host path is given put the file in the TJB temp dir
        if host_path is None:
            host_path = f"{saving_data.create_directory('pulled_files')}/{os.path.basename(device_path)}"

        self.log.info(f"get_file: {device_path} --> {host_path}")
        args = [self.adb, "-s", self.device, "pull", device_path, host_path]
        self.__send(args)
        return host_path

    def put_file(self, device_path: str, host_path: str, timeout_sec=30):
        """
        Put file on device

        :param device_path: path where to put file on device
        :type device_path: str
        :param host_path: path to file on host
        :type host_path: str
        :param timeout_sec: call timeout in seconds, defaults to 30
        :type timeout_sec: int, optional
        """

        if not timeout_sec:
            timeout_sec = self.timeout_sec
        self.log.info(f"put_file: {host_path} --> {device_path}")
        args = [self.adb, "-s", self.device, "push", host_path, device_path]
        self.__send(args, timeout_sec)
        return device_path

    def install(
        self,
        host_apk_path: str,
        timeout_sec=240,
        lock=False,
        replace=False,
        test_pkg=False,
        install_on_sd=False,
        grant_all=False,
    ):
        """
        Install apk bundle from host
            - push package(s) to the device and install them

        :param host_apk_path: host path to bundle file
        :type host_apk_path: str
        :param timeout_sec: call timeout in seconds, defaults to 240
        :type timeout_sec: int, optional
        :param lock: forward lock application, defaults to False
        :type lock: bool, optional
        :param replace: replace existing application, defaults to False
        :type replace: bool, optional
        :param test_pkg: allow test packages, defaults to False
        :type test_pkg: bool, optional
        :param install_on_sd: install application on sdcard, defaults to False
        :type install_on_sd: bool, optional
        :param grant_all: grant all runtime permissions, defaults to False
        :type grant_all: bool, optional
        :raises OSError: raised if file does not end in ``.apk``
        """

        if not host_apk_path.endswith(".apk"):
            raise OSError("Can only install .apk files on Android devices")
        args = [self.adb, "-s", self.device, "install"]
        if lock:
            args.append("-l")
        if replace:
            args.append("-r")
        if test_pkg:
            args.append("-t")
        if install_on_sd:
            args.append("-s")
        if grant_all:
            args.append("-g")

        args.append(host_apk_path)

        self.log.debug(f"Installing {host_apk_path}")
        self.__send(args, timeout_sec)

    def install_tr34_2016(self, json_path: str):
        """
        This method is only for VOS but exists here to stop
        stop an error being thrown when tests that have the
        install_tr34_2016 call are ran on Android devices
        """
        pass

    def uninstall(self, pkg_name: str, keep=False, timeout_sec=30):
        """
        Uninstall a apk package on the device

        :param pkg_name: name of the package to uninstall
        :type pkg_name: str
        :param keep: keep the data and cache directories, defaults to False
        :type keep: bool, optional
        :param timeout_sec: _description_, defaults to 30
        :type timeout_sec: int, optional
        """

        args = [self.adb, "-s", self.device, "uninstall"]
        if keep:
            args.append("-k")
        args.append(pkg_name)
        self.log.debug(f"Uninstalling: {pkg_name}")
        self.__send(args, timeout_sec)

    def run(self, cmd: str, user=None, silent=False, timeout_sec=None, raw=False) -> typing.Union[int, str]:
        """
        Run adb shell for sending commands to the device

        :param cmd: shell command
        :type cmd: str
        :param user: user under which to execute a command, defaults to 'root'
        :type user: str, optional
        :param silent: True - ignore commands stdout return exit code, False - stdout will be copied to clients stdout, defaults to False
        :type silent: bool, optional
        :param timeout_sec: call timeout in seconds, defaults to 30
        :type timeout_sec: int, optional
        :param raw: return the raw subprocess result object, defaults to False
        :type raw: bool, optional
        :return: returns either a int for return code or string for stdout
        :rtype: typing.Union[int, str]
        """
        if not user:
            user = self.user
        if user != "root":
            self._set_unroot()
        else:
            self._set_root()
        if not timeout_sec:
            timeout_sec = self.timeout_sec

        args = [self.adb, "-s", self.device, "shell"] + cmd.split()
        res = self.__send(args, timeout_sec)
        if silent:
            return res.returncode
        elif raw:
            return res
        else:
            return res.stdout

    def run_async(self, cmd: str, user=None) -> trcc.client.AsyncResult:
        """
        Run shell command on device in async mode

        :param cmd: shell command
        :type cmd: str
        :param user: either root or non root, defaults to None
        :type user: str, optional
        :return: AsyncResult object that can be tracked by the caller
        :rtype: trcc.client.AsyncResult
        """

        self.log.debug(f"running async command: {cmd}")
        asyncres = self.client.request_async("std", "shell", cmd)

        return asyncres

    def generate_bugreport(self, report_path=None, timeout_sec=300):
        """
        Generate a bugreport using ADB

        :param report_path: path to save the report on host machine, defaults to bugreport_dir in config.ini
        :type report_path: str, optional
        :param timeout_sec: time to wait before terminating process, defaults to 240
        :type timeout_sec: int, optional

        WARNING: devices with larger memory take a longer time to generate report so timeout may need to be increased depending on device
        """
        # remove any previous bugreports
        try:
            self.remove_files("bugreports/*")
        except FileNotFoundError:
            pass
        if not report_path:
            report_path = self.bugreport_dir
        saving_data.create_directory(report_path)
        self.log.info(f"Generating Bug Report for {self.device}")
        self.log.info("This may take a few minutes to complete")
        # trcagent needs to be restarted after the bug report completes
        self._stop_app("com.verifone.trc.agent")
        # in case the bugreport times out make sure trc agent is restarted
        try:
            args = [self.adb, "-s", self.device, "bugreport", report_path]
            self.__send(args, timeout_sec)
        finally:
            self._start_app("com.verifone.trc.agent")

    def reboot(self, timeout_sec=120):
        """
        Reboot the device
        """
        # get the latest uptime as its used in wait for reboot
        self.get_device_uptime()
        self.log.info(f"Rebooting {self.device}")
        self.__send([self.adb, "-s", self.device, "reboot"])
        self.wait_for_reboot(timeout_sec)

    def reboot_to_fastboot(self):
        """
        Reboot the device
        """
        # get the latest uptime as its used in wait for reboot
        self.get_device_uptime()
        self.log.info(f"Rebooting {self.device} to fastboot")
        self.__send([self.adb, "-s", self.device, "reboot", "bootloader"])

    def wait_for_reboot(self, timeout_sec=120):
        """
        Wait for device to power down and back up

        :param timeout_sec: time to wait for device to go down for reboot and return from reboot, defaults to 120
        :type timeout_sec: int, optional
        :raises trcc.client.TrcError: raised if device never returns from reboot
        """
        start = time.time()
        # get the latest uptime 
        pre_reboot_uptime = cur_uptime = self.uptime
        # if the self.uptime variable has not been updated take the current time as the last boot time
        if not self.uptime:
            try:
                pre_reboot_uptime = cur_uptime = self.get_device_uptime()
                # if this command succeeds we know the device is still online so
                # log message notifying user we are expecting a reboot to happen
                self.log.info(f"Monitoring {self.device} to go down for reboot")
            except Exception:
                pre_reboot_uptime = cur_uptime = datetime.strftime(datetime.now(), "%Y-%m-%d %H:%M")

        start = time.time()
        # while loop checking the current uptime
        # once uptimes do not match this signals
        # the device has rebooted
        while pre_reboot_uptime == cur_uptime:
            # check the device is available
            if self.get_state() != "device":
                # if not try to connect
                if not self._adb_connect():
                    # if fail to connect device is currently performing reboot
                    self.log.info(f"Waiting for {self.device} to come back from reboot")
                    self.__adb_setup()
                    
                else:
                    # restart loop if device is online
                    continue
            # if connected update uptime variable
            try:
                cur_uptime = self.get_device_uptime()
            # possible for device to go offline between last get_state check and
            # now so catch any exceptions when trying to update the uptime value
            except Exception:
                pass
            # timeout for loop if device never performs reboot
            if time.time() > start+timeout_sec:
                raise RuntimeError(f"{self.device} did not go down for reboot in {timeout_sec} seconds")
            # sleep to reduce log size
            time.sleep(self.max_sleep_time)
        self.log.info(f"{self.device} has booted")
        # sleep again to allow network activity to start
        time.sleep(self.max_sleep_time)
        # set up all permissions as they were before reboot
        self.setup(self.user, self.silent, self.timeout_sec)

    def disconnect(self):
        """
        Disconnect the executor
        """
        self.log.info(f"Disconnecting {self.device}")
        args = [self.adb, "disconnect", self.device]
        self.__send(args)

    def get_state(self) -> str:
        """
        Get the current state of the device
            - bootloader response only available for USB connection

        :return:  "offline" | "bootloader" | "device"
        :rtype: str
        """
        args = [self.adb, "-s", self.device, "get-state"]
        res = self.__send(args).stdout.strip()
        return res

    def forward(self, remote: int, local=0) -> int:
        """
        Forward socket connection using:
            <port> (<local> may be "0" to pick any open port)


        :param remote: remote tcp port number to forward local to
        :type remote: str
        :param local: local tcp port number to use for forwarding, defaults to 0
        :type local: str, optional
        :return: local port number used for forwarding
        :rtype: int
        """
        args = [self.adb, "-s", self.device, "forward", f"tcp:{local}", f"tcp:{remote}"]
        res = self.__send(args).stdout.strip()
        if local == 0:
            local = int(res)
        return local

    def stop_forwarding(self, local: int):
        """
        Stop forwarding traffic from local tcp port to device tcp port

        :param local: local port number currently forwarding traffic
        :type local: int
        """
        args = [self.adb, "-s", self.device, "forward", "--remove", f"tcp:{local}"]
        self.__send(args)


def get_executor(user=None, silent=None, timeout=None, usb=False, ip=False) -> typing.Union[TrackingVosClient, ADBClient]:
    """
    determine device type using TRCC os_type and return appropriate connected executor for device under test

    :param user: user level for the test to be run with (usr1, root, etc), defaults to None
    :type user: str, optional
    :param silent: if True commands run should only return return codes, defaults to None
    :type silent: bool, optional
    :param timeout: amount of time to wait on command run before killing attempt, defaults to None
    :type timeout: int, optional
    :param usb: if True connection will be made over usb (Only Available for Android)
    :type usb: bool, optional
    :param ip: if given, connection will be made using that IP instead of what is set under TRC_DEVICE_IP (Only Available for Android)
    :type ip: str, optional
    :return: returns a connected executor of either TrackingVosClient for VOS devices or ADBClient for Android devices
    :rtype: typing.Union[TrackingVosClient, ADBClient]
    """

    # if we are attempting to connect to a specific IP and it is not the same IP as
    # the IP trc is connected to, we cannot call trcc. This is only supported on
    # Android but can expand to VOS in the future
    if ip != env_settings.get_env_variable("TRC_DEVICE_IP") and ip is not False:
        os_type = "ANDROID"
    else:
        client = trcc.client.TrcClient()
        os_type = client.request("std", "os_type")
    l = logger.get_logger("get_executor")
    l.debug(os_type)
    if "ANDROID" in os_type:
        l.debug("Android device found")
        l.debug("Using adb connection")
        adbc = ADBClient(usb, ip)
        adbc.setup(user, silent, timeout)
        return adbc
    else:
        l.debug("Linux device found")
        l.debug("Using TRCC connection")
        tvc = TrackingVosClient()
        tvc.setup(user, silent, timeout)
        return tvc
