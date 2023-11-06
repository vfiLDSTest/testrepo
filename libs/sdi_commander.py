"""
Module for sending commands to the SDI server via TCP sockets
    - based on the ADK SDI TJB code for testing SDI
        - https://bitbucket.verifone.com:8443/projects/IFADK/repos/dev-adk-sdi/browse

:raises ConnectionError: Raised if cannot start socket on given IP:PORT
:return: SDI commander object for interacting with SDI server
:rtype: class instance
"""
from . import logger
import binascii
import os
import socket
import time


class SdiCommander():
    """
    Starts a connection to a TCP socket for sending and reading SDI commands
    """

    def __init__(self, ip: str, port: int):
        """
        Set up IP & Port and connect to the TCP socket

        :param ip: IP of the TCP socket
        :type ip: str
        :param port: Port of the TCP socket
        :type port: int
        :raises ConnectionError: If unable to connect to {IP:Port}
        """
        self.log = logger.get_logger(os.path.basename(__file__))
        self.ip = ip
        self.port = port
        self.socket = self.connect_device()
        if not self.socket:
            raise ConnectionError(f"Could not connect to {self.ip}:{self.port}")

    def decode_SDI_response(self, response: str) -> str:
        """
        Turn SDI resposes (less TLV tags) from hex into ASCII

        :param response: Encoded response from SDI without TLV tags
        :type response: bytes
        :return: decoded response in ASCII
        :rtype: str
        """
        return bytes.fromhex(response).decode("ASCII")

    def BER_TLV(self, tag: str, value: str) -> str:
        """
        Format Tag and Value to BER-TLV standard for communicating with SDI
            - More info: https://jenkins2.verifone.com:8443/job/Corporate/job/Subsystem/job/ADK/job/ADK-Integration/job/GSS-ADK-Integration-Nightlybuild_ng/ADK_20Overview_20Programmers_20Guides/pg_sdi_users_guide.html#subsubsec_sdi_data_coding

        :param tag: tag to prepend to SDI command
        :type tag: str
        :param value: Value (data) to be sent to SDI
        :type value: str
        :return: Tag and value paired together correctly to be sent to SDI server
        :rtype: str
        """
        # the following encodes a tag and value using the BER-TLV (ISO/IEC 8825) standard
        # we need to also include the length of the value data in Hex
        #   - this is %02X|%04X|%06X seen below
        #   - https://docs.python.org/2/library/string.html#formatspec
        # the final result is [tag][length_of_value_in_hex][value]
        result = ''
        result += tag
        length = int(len(value) / 2)
        if length <= 127:
            result += '%02X' % length
        elif length <= 255:
            result += '81%02X' % length
        elif length <= 65535:
            result += '82%04X' % length
        elif length <= 16777215:
            result += '83%06X' % length
        result += value

        return result

    def run_SDI_cmd(self, cmd_data: str) -> str:
        """
        Send a correctly formatted (BER-TLV standard) command to SDI and return SDIs response
            - uses e-105 protocol_C standard, for more detail - https://jenkins2.verifone.com:8443/job/Corporate/job/Subsystem/job/ADK/job/ADK-Integration/job/GSS-ADK-Integration-Nightlybuild_ng/ADK_20Overview_20Programmers_20Guides/pg_sdi_users_guide.html#sec_sdi_sw_components

        :param cmd_data: Correctly formatted command to send
        :type cmd_data: str
        :return: hex encoded SDI response
        :rtype: str
        """

        self.log.info(f"--> {cmd_data}")
        self.e105_send(cmd_data)
        response_data = self.e105_receive()
        self.log.info(f"<-- {response_data}")

        # if the first 4 digits in the response is 9E01 SDI is requesting a call back
        # this is usually when a user needs to do some action on the device
        # see more: https://jenkins2.verifone.com:8443/job/Corporate/job/Subsystem/job/ADK/job/ADK-Integration/job/GSS-ADK-Integration-Nightlybuild_ng/ADK_20Overview_20Programmers_20Guides/pg_sdi_users_guide.html#subsec_sdi_notify_cb
        while (response_data[:4] == '9E01'):
            self.log.info('##### 9E01 Callback detected')
            response_data = self.handle_callback(response_data)

        return response_data

    def test_receive(self) -> str:
        """
        Receive method for handling if a callback is needed

        :return: data received from SDI
        :rtype: str
        """
        receive_data = self.e105_receive()
        self.log.info(f"<-- {receive_data}")
        while (receive_data[:4] == '9E01'):
            self.log.info('##### 9E01 Callback detected (test_receive)')
            receive_data = self.handle_callback(receive_data)

        return receive_data

    # Delivers the value bytes for a corresponding search tag inside a TLV buffer
    # Input:  Search tag e.g. '5A'
    #         TLV buffer e.g. '5A0845719940000373045714B4571994000037304D12122011377586020400F55F24021212'
    # Return: Value e.g. '4571994000037304'
    def get_TLV_value(self, Tag: str, TLV_Buffer: str) -> str:
        """
        Get the value returned by SDI by stripping away BER-TLV tag and length data

        :param Tag: BER-TLV tag to remove from data
        :type Tag: str
        :param TLV_Buffer: contents of the SDI response less the ACK tag
        :type TLV_Buffer: str
        :return: SDI response in hex encoding
        :rtype: str
        """
        i = 0
        while i < len(TLV_Buffer):
            # Determine tag in TLV buffer
            binary_tag = ord(binascii.a2b_hex(TLV_Buffer[i:i+2]))
            i += 2
            if ((binary_tag & 0x1F) == 0x1F):
                # Second tag byte exists
                binary_tag *= 256
                binary_tag += ord(binascii.a2b_hex(TLV_Buffer[i:i+2]))
                i += 2
                if ((binary_tag & 0x80) == 0x80):
                    # Third tag byte exists
                    binary_tag *= 256
                    binary_tag += ord(binascii.a2b_hex(TLV_Buffer[i:i+2]))
                    i += 2

            # If padding bytes are reached, exit loop
            if (binary_tag >= 0x00) and (binary_tag <= 0x07):
                break

            # Determine the length of the found tag
            binary_len = ord(binascii.a2b_hex(TLV_Buffer[i:i+2]))
            i += 2
            if ((binary_len & 0x81) == 0x81):
                # Len between 128 and 255 bytes -> read 2nd length byte
                binary_len = ord(binascii.a2b_hex(TLV_Buffer[i:i+2]))
                i += 2
            elif ((binary_len & 0x82) == 0x82):
                # Len between 256 and 65535 bytes -> read 3rd length byte
                binary_len = ord(binascii.a2b_hex(TLV_Buffer[i:i+2]))
                i += 2
                binary_len *= 256
                binary_len += ord(binascii.a2b_hex(TLV_Buffer[i:i+2]))
                i += 2

            if (('%X' % int(binary_tag)) == Tag):
                return TLV_Buffer[i:i+int(binary_len)*2]

            # Set i to the next tag in buffer
            i += int(binary_len) * 2

        return ''  # Requested tag not found

    def handle_callback(self, callback_cmd: str) -> str:
        """
        Handle the possible callback responses to get SDI response
        More details -> https://jenkins2.verifone.com:8443/job/Corporate/job/Subsystem/job/ADK/job/ADK-Integration/job/GSS-ADK-Integration-Nightlybuild_ng/ADK_20Overview_20Programmers_20Guides/pg_sdi_users_guide.html#subsec_sdi_notify_cb

        :param callback_cmd: command returned by SDI
        :type callback_cmd: str
        :return: SDI response
        :rtype: str
        """

        if callback_cmd[:4] == '9101':
            callback_response = '9201'

            # Callback request for CT
            data = self.get_TLV_value('F0', callback_cmd[8:])
            if data == '':
                # Callback request for CTLS
                data = self.get_TLV_value('F0', callback_cmd[4:])

            self.log.info("Unknown Callback...")
            callback_response += 'F000'

            response_data = self.run_SDI_cmd(callback_response)

        elif callback_cmd[:4] == '9E03':
            callback_response = '23080000'

            # Callback request for CTLS
            data = self.get_TLV_value('F0', callback_cmd[4:])

            self.log.info("Unknown Callback...")
            callback_response += 'F000'

            response_data = self.run_SDI_cmd(callback_response)
            while response_data == '640A':
                time.sleep(0.01)
                response_data = self.run_SDI_cmd(callback_response)

            while (response_data[:4] == '9E01'):
                response_data = self.test_receive()

            if response_data[:4] == '9000':
                response_data = self.test_receive()
        else:
            response_data = self.test_receive()

        return response_data

    def e105_send(self, sdi_cmd: str):
        """
        Send command to SDI in the e105 protocol_C standard
        More Details -> https://jenkins2.verifone.com:8443/job/Corporate/job/Subsystem/job/ADK/job/ADK-Integration/job/GSS-ADK-Integration-Nightlybuild_ng/ADK_20Overview_20Programmers_20Guides/pg_sdi_users_guide.html#subsubsec_prot_c_multi_connection_support

        :param sdi_cmd: _description_
        :type sdi_cmd: str
        """
        send_data = f'0243{"%08x" % int(len(sdi_cmd) / 2)}{sdi_cmd}03'
        self.socket.send(binascii.a2b_hex(send_data))
        self.log.info(f" -> {send_data.upper()}")

    def e105_receive(self) -> str:
        """
        Gets responses from SDI and decodes them from bytes to UTF-8

        :return: Responses from SDI encoded in hex, empty string if no data received
        :rtype: str
        """
        response_data = ''
        i = 0
        while i < 3:
            # Up to three tries to receive data from the device
            i += 1
            receive_data = b''
            receive_bytes = 6

            receive_data += self.socket.recv(receive_bytes)
            if len(receive_data) > 5:
                bytes_received = 6
                if receive_data[1] == 0x41:
                    message_size = (
                        bytes_received - 2
                        + (receive_data[2] & 0x0F) * 256
                        + receive_data[3] + 3)  # Including ETX and CRC
                else:
                    message_size = (
                        bytes_received
                        + receive_data[2] * 16777216
                        + receive_data[3] * 65536
                        + receive_data[4] * 256
                        + receive_data[5] + 1)  # Including ETX
                while (len(receive_data) < message_size):
                    receive_data += self.socket.recv(message_size - len(receive_data))

            if receive_data[1] == 0x41 and len(receive_data) > 7:
                # Check protocol frame
                # Error detected -> send NAK
                self.log.info(f" <- {binascii.b2a_hex(receive_data).decode('utf-8').upper()}")
                send_data = '15'  # NAK

                self.socket.send(binascii.a2b_hex(send_data))

                self.log.info(f" -> {send_data}")

                if send_data == '06':
                    response_data += binascii.b2a_hex(receive_data[4:-3]).decode("utf-8").upper()
                    if ((receive_data[2] & 0xF0) != 0x00):
                        continue
                    else:
                        return response_data

            elif (receive_data[1] == 0x42 or receive_data[1] == 0x43) and len(receive_data) > 7:
                # Check protocol frame
                if receive_data[0] == 0x02 and \
                    (receive_data[2] * 16777216 + receive_data[3] * 65536 + receive_data[4] * 256 + receive_data[5]) == (len(receive_data) - 7) and \
                        receive_data[-1] == 0x03:
                    # Received data correct -> send ACK
                    self.log.info(f" <- {binascii.b2a_hex(receive_data).decode('utf-8').upper()}")
                else:
                    # Error detected -> send NAK
                    self.log.info(f" <- {binascii.b2a_hex(receive_data).decode('utf-8').upper()}")

                return binascii.b2a_hex(receive_data[6:-1]).decode("utf-8").upper()
            elif len(receive_data) == 1 and receive_data[0] == 0x06:
                return self.e105_receive()

        # Not possible to receive data
        return ''

    def connect_device(self) -> socket:
        """
        Connect to the IP:Port for sending SDI commands via TCP

        :return: Connected socket, False if connection could not be made
        :rtype: socket
        """

        # attempt to connect to the socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # get connection code from socket
        ret = s.connect_ex((self.ip, self.port))
        if ret == 0 or ret == 10056:
            self.log.info("Device connected")
            time.sleep(1)
            return s
        else:
            self.log.info(f"Connection failed (errno = {ret})")
            return False
