'''This library is for any file operation functions to be performed on the device under test that can be reused by other scripts'''
import random
import re
import os
from . import env_settings
from .config_parser import ConfigParser as cp

cwd = env_settings.get_tjb_root(f"../{os.path.basename(__file__)}")
cf = cp(f"{cwd}/libs/config.ini")
TTW=cf.get_int("FILE_UTILITIES", "ttw")

def search_dirs(executor, name_to_find, type, base_dir=".", timeout=TTW) -> list:
    '''
    recursively search a given directory for a pattern and return list of found paths to pattern
    arguments:
        - connected executor
        - pattern to search for
        - type (block, char, dir, file, symlink, pipe, socket)
        - base directory to start the search in
    returns: 
        - list of paths found
    '''
    if type in ['b', 'c', 'd', 'f', 'l', 'p', 's']:
        return executor.run('find %s -type %s -name %s' % (base_dir, type, name_to_find), timeout_sec=timeout).split('\n')
    else:
        raise TypeError('find type must be in [bcdflps]')


def create_rnd_chr_file(executor, file_size, dest, filename, timeout=TTW) -> str:
    '''
    create a file x bytes in size filled with random characters and return path to the file
    arguments:
        - connected executor
        - expected size of the file in bytes
        - destination of the file
        - name of the file
    returns:
        - filepath to generated file
    '''
    executor.run(
        '< /dev/urandom tr -dc "[:alnum:]" | head -c%s > %s/%s' % (file_size, dest, filename), timeout_sec=timeout)
    return dest + '/' + filename


def check_file_exists(executor, filepath, timeout=TTW) -> bool:
    '''
    check a given file exists and return true or false
    arguments:
        - connected executor
        - path to file to check
    returns:
        - bool
    '''
    return bool(int(executor.run(f"test -f {filepath} && echo 1 || echo 0", timeout_sec=timeout)))


def md5sum(executor, filepath, timeout=TTW) -> str:
    '''
    run md5sum on a given file and return the hash, returns None if file not found
    arguments:
        - connected executor
        - path to file to get hash of
    returns:
        - str of hash, None if no file found
    '''
    if check_file_exists(executor, filepath):
        return executor.run(f"md5sum -b {filepath}", timeout_sec=timeout)
    else:
        return None


def parsing_parcel_output(output: str) -> str:
    """
    Parsing the adb output in Parcel format.

    :param output: string of the raw parcel data
    :type output: str
    :return: parsed data contained in parcel
    :rtype: str

    Parsing the adb output in format:
      Result: Parcel(
        0x00000000: 00000000 00000014 00390038 00340031 '........8.9.1.4.'
        0x00000010: 00300038 00300030 00300030 00340032 '8.0.0.0.0.0.2.4.'
        0x00000020: 00350034 00330035 00320038 00310033 '4.5.5.3.8.2.3.1.'
        0x00000030: 00000000                            '....            ')
    """
    output = ''.join(re.findall(r"'(.*)'", output))
    return re.sub(r'[.\s]', '', output)

def parsing_parcel_boolean(output: bool) -> bool:
    """
    Parsing the adb output in Parcel format.

    :param output: boolean of the raw parcel data
    :type output: bool
    :return: parsed data contained in parcel
    :rtype: bool

    Parsing the adb output in format:
      Result: Parcel(00000000 00000001 '................')
    """
    if(output.find('1') > 0):
        return  True
    else:
        return False