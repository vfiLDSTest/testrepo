"""
    Parser for reading .ini config files
    """
import configparser
import json
from ast import literal_eval as make_tuple


class ConfigParser:
    """Parses given .ini file
    """

    def __init__(self, default_vars: str):
        """
        Sets file to be parsed

        :param default_vars: file to be parsed
        :type default_vars: str
        """
        self.default_vars = default_vars
        self.config = configparser.ConfigParser()
        self.config.read(self.default_vars)

    def _get_type_with_json(self, section: str, variable: str):
        """
        return json type interpretation of object with given type of value in file

        :param section: header to look under in .ini file
        :type section: str
        :param variable: name of the variable to get value of 
        :type variable: str
        :return: json interpretation of variable in ini file
        :rtype: json.loads
        """
        return json.loads(self.config[section][variable])

    def get_str(self, section: str, variable: str):
        """
        Get string value of variable in file

        :param section: header to look under in .ini file
        :type section: str
        :param variable: name of the variable to get value of 
        :type variable: str
        :return: value of the requested variable
        :rtype: str
        """
        return self.config[section][variable]

    def get_bool(self, section: str, variable: str):
        """
        return boolean of value in file

        :param section: header to look under in .ini file
        :type section: str
        :param variable: name of the variable to get value of 
        :type variable: str
        :return: boolean of variable in ini file
        :rtype: boolean
        """
        return self.config[section].getboolean(variable)

    def get_list(self, section: str, variable: str):
        """
        return list object of value in file

        :param section: header to look under in .ini file
        :type section: str
        :param variable: name of the variable to get value of 
        :type variable: str
        :return: list of variable in ini file
        :rtype: list
        """
        return self._get_type_with_json(section, variable)

    def get_tuple(self, section: str, variable: str):
        """
        return tuple object of value in file

        :param section: header to look under in .ini file
        :type section: str
        :param variable: name of the variable to get value of 
        :type variable: str
        :return: tuple of variable in ini file
        :rtype: tuple
        """
        return make_tuple(self.config[section][variable])

    def get_dict(self, section: str, variable: str):
        """
        return dictionary object of value in file

        :param section: header to look under in .ini file
        :type section: str
        :param variable: name of the variable to get value of 
        :type variable: str
        :return: dictionary of variable in ini file
        :rtype: dict
        """
        return self._get_type_with_json(section, variable)

    def get_int(self, section: str, variable: str):
        """
        return int of value in file

        :param section: header to look under in .ini file
        :type section: str
        :param variable: name of the variable to get value of 
        :type variable: str
        :return: int of variable in ini file
        :rtype: int
        """
        return self.config[section].getint(variable)

    def get_float(self, section: str, variable: str):
        """
        return float of value in file

        :param section: header to look under in .ini file
        :type section: str
        :param variable: name of the variable to get value of 
        :type variable: str
        :return: float of variable in ini file
        :rtype: float
        """
        return self.config[section].getfloat(variable)
