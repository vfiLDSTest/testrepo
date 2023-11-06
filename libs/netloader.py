"""
Module for communicating with device via netloader

    - Based on information found https://confluence.verifone.com:8443/display/PetroOS/Netloader+Protocol
"""
import math
import os
import socket
import time
from . import logger


class NetLoader:
    def __init__(self, ip: str, connect_timeout=10):
        self.log = logger.get_logger(f"{os.path.basename(__file__)}")
        # set values that do not change
        self.DLM = "\x00"
        self.ip = ip
        self.connect_timeout = connect_timeout
        self.port = 5142
        self.rsp_size = 2048
        self.dld_packet_size = 2048
        self.s = None

    def connect(self):
        """
        Make a connection to the device using IP:PORT
        """
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        timer = time.time()
        while self.s.connect_ex((self.ip, self.port)) != 0:
            if timer + self.connect_timeout < time.time():
                raise ConnectionError(
                    f"Could not establish connection to {self.ip}:{self.port} within {self.connect_timeout} seconds")

    def request(self, r: str) -> str:
        """
        Make a request to the device

        :param r: request packet
        :type r: str
        :return: request acknowledgement
        :rtype: str
        """
        self.s.send(r)
        return self.s.recv(self.rsp_size)

    def download(self, src: str, usr="usr1", group="users"):
        """
        download a file to the device

        :param src: path to the file to download
        :type src: str
        :param usr: user level, defaults to "usr1"
        :type usr: str, optional
        :param group: permission group, defaults to "users"
        :type group: str, optional
        """
        st = os.stat(src)
        self.connect()
        # constructing download comman
        #     DLD:filename<null>size<null>mask<null>user<null>group<null>type<null>
        #       type: F-full, P-partial download
        # DLD:<source_file_path>\x00<source_file_size>\x00664\x00<user>\x00<user_group>\x00<F full download>\x00
        download_cmd = f"DLD:{src}{self.DLM}{str(st.st_size)}{self.DLM}664{self.DLM}{usr}{self.DLM}{group}{self.DLM}F{self.DLM}"
        data = self.request(str.encode(download_cmd)).decode()
        # check the device is ready to receive download
        if (data[0:2] != "OK"):
            self.log.error("DLD failed: " + data + "\n")
            return 0
        # set offset to find when the data ends
        offset = 0
        # open source file to be sent as binary
        self.log.info(f"Sending {src}")
        fh = open(src, "rb")
        # loop to continiously send the data in the correct size chunks
        data_sent = 0
        # in order to not fill the log file with unnecessary data but
        # still have updates on the download we give an update every
        # 10% of the file being loaded
        log_marker = 0
        while (offset < st.st_size):
            data = fh.read(self.dld_packet_size)
            data_len = len(data)
            # once there is no more data break the loop
            if (data_len <= 0):
                self.log.info(f"100% sent of {src}")
                break
            self.s.send(data)
            data_sent += data_len
            offset += data_len
            percent_sent = (data_sent / st.st_size) * 100
            if percent_sent > log_marker:
                self.log.info(f"{math.floor(percent_sent)}% sent of {src}")
                log_marker += 10

        # check for the download complete flag
        data = self.s.recv(self.rsp_size).decode()
        #sys.stderr.write("\b" * 7)
        if (data[0:9] == "DNLD_DONE"):
            self.log.info("Success!")
            # close the socket after the download finishes
            self.s.close()
            return 1
        # log the error if the download failed
        else:
            self.log.error(f"Error: {data}")
            # close the socket
            self.s.close()
            return 0
