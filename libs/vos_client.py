"""
    High level API for TRCS
    This is a copy of what was in qetestapps @ 18/05/2022

    Reason for copy and refactor details: https://jira.verifone.com/browse/ADKP-558
    """

import os
from os.path import basename
import trcc.client
import tarfile
import tempfile
import typing

class VosClient:
    """
    High level API for TRCS
    with docstrings, one call per one logical action and sensible defaults

    :raises trcc.client.TrcError: when sending a request to device fails
    :raises exception: 
    :return: Connected executor for Linux devices
    :rtype: class instance

    """

    def __init__(self):
        self.client = trcc.client.TrcClient()

    def __request(self, module: str, service: str, timeout_sec=30, expect_result=False, *params):
        """
        Send TRC request to device

        :param module: TRC module on device to be called
        :type module: str
        :param service: TRC service to be called
        :type service: str
        :param timeout_sec: time to wait for command to complete, defaults to 30
        :type timeout_sec: int, optional
        :param expect_result: response expected, defaults to False
        :type expect_result: bool, optional
        :raises trcc.client.TrcError: if response when no respose expected raise error
        :return: If expected_result=True returns response from TRC 
        :rtype: list

        """

        res = self.client.request(module, service, *params, timeout_sec=timeout_sec)
        if expect_result:
            return res
        elif res != []:
            msg = '\n'.join(res)
            raise trcc.client.TrcError(
                f'Request failed {module} {service}\n{msg}')

    def remove_files(self, *files: str, user='usr1', force=False):
        """
        remove files from device

        :param files: files to remove
        :type files: str
        :param user: set to 'root' remove files as root | 'usr1' - remove files as usr1
        :type user: str, optional
        :param force: False (default) - raise exception on first error | True - ignore errors like rm -f, defaults to False
        :type force: bool, optional

        """

        # TRCS supports separate std/remove_file command but it is usr1-only
        flags = '-f' if force else ''
        file_args = ' '.join(f"{i}" for i in files)
        self.run(f'rm {flags} {file_args}', user=user)

    def get_file(self, device_path: str, host_path=None) -> str:
        """
        Get file from device

        :param device_path: path to file that will be read from device
        :type device_path: str
        :param host_path: path to put file on host, pick random name if None, defaults to None
        :type host_path: str, optional
        :return: path to file on host
        :rtype: str

        """
        if host_path is None:
            f, ext = os.path.splitext(device_path)
            pref = os.path.basename(f)
            if not ext:
                ext = '.tmp'
            host_path = tempfile.mktemp(prefix=pref, suffix=ext, dir='.')
        self.__request(None, 'get_file', device_path,
                       host_path, expect_result=True)
        return host_path

    def get_file_data(self, device_path: str) -> bytes:
        """
        Get file contents from device

        :param device_path: path to file that will be read from device
        :type device_path: str
        :return: file contents as bytes
        :rtype: bytes

        """

        fname = self.get_file(device_path)
        # leave file on fs for debug of test failures
        with open(fname, 'rb') as f:
            return f.read()

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

        self.__request(None, 'put_file', device_path,
                       host_path, timeout_sec=timeout_sec)

    def install(self, host_tgz_path: str, timeout_sec=240):
        """
        Install tgz bundle from host

        :param host_tgz_path: host path to bundle file
        :type host_tgz_path: str
        :param timeout_sec: call timeout in seconds, defaults to 240
        :type timeout_sec: int, optional

        """

        device_path = os.path.join('/tmp/', basename(host_tgz_path))
        self.put_file(device_path, host_tgz_path)
        self.__request('std', 'install', device_path, timeout_sec=timeout_sec)

    def install_tr34_2016(self, json_path: str):
        """
        Install TR34-2016 file (packs into bundle)

        :param json_path: host path to TR34-2016 JSON file
        :type json_path: str

        """

        with tarfile.open('vrk2.json.tgz', 'w:gz') as t:
            t.add(basename(json_path))

        self.install('vrk2.json.tgz')

    def run(self, cmd: str, user='usr1', silent=True, timeout_sec=30) -> typing.Union[int, str]:
        """
        Run shell command on device

        :param cmd: shell command
        :type cmd: str
        :param user: user under which to execute a command, defaults to 'usr1'

        .. note::
            Be careful with complex commands with double quotes for users other than root and usr1.
            They will be wrapped in su ... -c ... with double quote escaping

        :type user: str, optional
        :param silent: True - ignore commands stdout, returns exit code | False - stdout will be copied to clients stdout, returns None , defaults to True

        .. note::
            TRCS can't handle too much output or non-ascii characters.

        :type silent: bool, optional
        :param timeout_sec: call timeout in seconds, defaults to 30
        :type timeout_sec: int, optional
        :return: non silent, returns command response, silent returns return code
        :rtype: typing.Union[int, str]

        """

        module = 'vos' if user == 'usr1' else 'vos-root'
        if user not in ['usr1', 'root']:
            escaped_cmd = cmd.replace('"', '\\"')
            cmd = f'su {user} -l -s /bin/sh -c "{escaped_cmd}"'

        # on success run returns empty list
        # run_silent returns list with one element (exit code string)
        if silent:
            [res] = self.__request(
                module, 'run_silent', cmd, expect_result=True, timeout_sec=timeout_sec)
            return int(res)
        else:
            res_stdout = self.__request(
                module, 'run', cmd, expect_result=True, timeout_sec=timeout_sec)
            return '\n'.join(res_stdout)

    def runstd(self,service: str, cmd: str, user='usr1', silent=True, timeout_sec=30) -> typing.Union[int, str]:
        """
        Run std module and run shell command on device
        :param service: which service its using eg:device_part_number,shell
        :param cmd: shell command
        :param user: user under which to execute a command, defaults to 'usr1'
        :param silent: ignore commands stdout, returns exit code | False - stdout will be copied to clients stdout, defaults to True
        :param timeout_sec: all timeout in seconds, defaults to 30
        :return: returns command response
        """
        if user not in ['usr1', 'root']:
            escaped_cmd = cmd.replace('"', '\\"')
            cmd = f'su {user} -l -s /bin/sh -c "{escaped_cmd}"'

        # on success run returns empty list
        # run_silent returns list with one element (exit code string)
        if silent:
            [res] = self.__request(
                "std", service,  cmd, 'run_silent', timeout_sec=timeout_sec, expect_result=True)
            return int(res)
        else:
            res_stdout = self.__request(
                "std",service, cmd, 'run', timeout_sec=timeout_sec, expect_result=True)
            return res_stdout

    def run_async(self, cmd: str, user='usr1'):
        """
        Run shell command on device in async mode

        :param cmd: shell command
        :type cmd: str
        :param user: user under which to execute a command, defaults to 'usr1'

        .. note::
            Be careful with complex commands with double quotes for users other than root and usr1.
            They will be wrapped in su ... -c ... with double quote escaping

        :type user: str, optional
        :return: AsyncResult object that can be tracked by the caller.
        :rtype: AsyncResult

        """

        module = 'vos' if user == 'usr1' else 'vos-root'
        if user not in ['usr1', 'root']:
            escaped_cmd = cmd.replace('"', '\\"')
            cmd = f'su {user} -l -s /bin/sh -c "{escaped_cmd}"'

        asyncres = self.client.request_async(module, 'run', cmd)

        return asyncres

    def reboot(self, root=False):
        """
        Reboot the device

        """
        self.__request('std', 'reboot', timeout_sec=300)

    def get_device_serial_number(self):

        [res] = self.__request("std", 'device_serial_number',
                   timeout_sec=30, expect_result=True)
        return [res]

class TrackingVosClient(VosClient):
    """
    Wrapper for VosClient which keeps track of default parameters in run() calls

    """

    def __init__(self):
        super().__init__()
        self.reset()

    def reset(self):
        """
        Resets user, silent and timeout_sec variables

        """
        self.user = None
        self.silent = None
        self.timeout_sec = None

    def setup(self, user=None, silent=None, timeout_sec=None):
        """
        Initiates user, silent and timeout_sec

        :param user: user under which to execute a command, defaults to None

        .. note::
            Be careful with complex commands with double quotes for users other than root and usr1.
            They will be wrapped in su ... -c ... with double quote escaping       

        :type user: str, optional
        :param silent: Run commands, defaults to None
        :type silent: True - ignore commands stdout, returns exit code | False - stdout will be copied to clients stdout, returns None, optional
        :param timeout_sec: _description_, defaults to None
        :type timeout_sec: call timeout in seconds, optional

        """
        if user != None:
            self.user = user
        if silent != None:
            self.silent = silent
        if timeout_sec != None:
            self.timeout_sec = timeout_sec

    def run(self, cmd: str, user=None, silent=None, timeout_sec=None) -> typing.Union[int, str]:
        """
        Run shell command on device

        :param cmd: shell command
        :type cmd: str
        :param user: user under which to execute a command, defaults to None

        .. note::
            Be careful with complex commands with double quotes for users other than root and usr1.
            They will be wrapped in su ... -c ... with double quote escaping

        :type user: str, optional
        :param silent: True - ignore commands stdout, returns exit code | False - stdout will be copied to clients stdout, returns None , defaults to None

        .. note::
            TRCS can't handle too much output or non-ascii characters.

        :type silent: bool, optional
        :param timeout_sec: call timeout in seconds, defaults to None
        :type timeout_sec: int, optional
        :return: non silent, returns command response, silent returns return code
        :rtype: typing.Union[int, str]

        If values left as defaults, values from setup() will be used

        """
        # mimicking default values of super().run for compatibility
        if user == None:
            if self.user != None:
                user = self.user
            else:
                user = 'usr1'
        if silent == None:
            if self.silent != None:
                silent = self.silent
            else:
                silent = True
        if timeout_sec == None:
            if self.timeout_sec != None:
                timeout_sec = self.timeout_sec
            else:
                timeout_sec = 30
        return super().run(cmd, user=user, silent=silent, timeout_sec=timeout_sec)
