"""
    Module for downloading artifacts from Artifactory
"""
#!/usr/bin/python3

from .config_parser import ConfigParser
import requests
import re
import os
import hashlib
import time
from distutils.version import LooseVersion
from . import logger, env_settings

# set up config file for executor variables
cwd = env_settings.get_tjb_root(f"../{os.path.basename(__file__)}")
cf = ConfigParser(f"{cwd}/libs/config.ini")
AUTH = (cf.get_str("ARTIFACTORY", "username"),
        cf.get_str("ARTIFACTORY", "password"))
LOGGER = logger.get_logger(os.path.basename(__file__))


def find_latest_release(regex: re.Pattern, url: str) -> str:
    """
    get the latest version of file using given version string pattern

    :param regex: pattern of the version string
    :type regex: re.Pattern
    :param url: web address holding files
    :type url: str
    :return: latest version of file at url
    :rtype: str
    """
    dir_list = requests.get(url, auth=AUTH)
    # find all json directories in the results
    versions = re.findall(regex, dir_list.text)
    # apply a set to the list to remove duplicates, turn the set
    # back into a list and use the sort function with
    # LooseVersion key to get a sorted list of the versions
    return sorted((list(set(versions))), key=LooseVersion)[-1]


def download_file(url: str, download_dir) -> str:
    """
    download file from artifactory at given url

    :param url: url to the file
    :type url: str
    :param download_dir: local directory to download the file to
    :type url: str
    :return: local path to downloaded file
    :rtype: str
    """
    # create download directory if it does not exist
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
    filename = os.path.basename(url)
    # stream the file contents to host
    response = requests.get(url, auth=AUTH, stream=True)
    if response.status_code != 200:
        raise ConnectionError(f"Failed to get {filename} from Artifactory")
    # get md5 check sum of file to compare to any local files with the same name
    checksum = response.headers.get("X-Checksum-Md5")
    # get total size of file
    total_length = int(response.headers.get('content-length'))
    if filename in os.listdir(download_dir):
        # compare checksum of remote file vs local file
        if hashlib.md5(open(f"{download_dir}/{filename}", "rb").read()).hexdigest() == checksum and os.path.getsize(f"{download_dir}/{filename}") == total_length:
            LOGGER.debug(f"{filename} already in {download_dir}")
            # return local file path
            return f"{download_dir}/{filename}"

    offset = 0
    block_size = 1024  # 1 Kilobyte
    # start writing file from stream
    last_percent_sent = 0
    LOGGER.info(f"Downloading {filename} from Artifactory")
    with open(f"{download_dir}/{filename}", "wb") as f:
        # write contents to file
        counter = time.time()
        for data in response.iter_content(block_size):
            offset += len(data)
            percent_sent = round(100 * (offset / total_length))
            if percent_sent % 10 == 0 and last_percent_sent != percent_sent and counter < time.time():
                # only show download updates every 5 seconds and if its different from the last update
                LOGGER.info(f"{percent_sent}% of {filename} Downloaded")
                last_percent_sent = percent_sent
                counter = counter + 5
            f.write(data)
    # return path to downloaded file
    LOGGER.info(f"{filename} successfully downloaded to {download_dir}")
    return f"{download_dir}/{filename}"
