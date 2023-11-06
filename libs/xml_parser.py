"""
Module for parsing xml files

"""
import xml.etree.ElementTree as ET
from . import logger


class XMLParser():
    def __init__(self, xml_file: str):
        # path to the xml file to parse
        self.xml_file = xml_file
        self.log = logger.get_logger(self.__class__.__name__)
        # get the whole xml tree
        self.tree = ET.parse(self.xml_file)
        # get the root tag in the xml file
        self.root = self.tree.getroot()
    
    def get_element_dict(self, tag_name: str, key: str, value: str) -> dict:
        """
        Return dictionary of all the name-value pairs of elements in an xml file with given tagname

        :param tag_name: name of the tag with requested variables
        :type tag_name: str
        :param key: name of the attribute in the tag to identify the value
        :type key: str
        :param value: name of the attribute in the tag holding the value
        :type value: str
        :return: dictionary of the all the key & value pairs in the tag
        :rtype: dict
        """
        # create an empty dictionary to hold the data
        elem_dict = {}
        # loop over all the tags in the given location in the xml file
        for elem in self.tree.iter():
            # iterate over the whole tree for the specified tagname
            if elem.tag == tag_name:
                self.log.info(f"Getting {elem.tag}: name {elem.get(key)}, value {elem.get(value)}")
                # create the key value pairs from the given attribute names
                elem_dict[elem.get(key)] = elem.get(value)
        # return the dictionary
        return elem_dict

class XMLWriter():
    def __init__(self, xml_file: str):
        self.xml_file = xml_file

        self.log = logger.get_logger(self.__class__.__name__)

    def create_android_settings_file_from_dict(self, src: dict, param_tag: str):
        """
        useing a dictionary of parameter names and values create a android settings xml file

        :param src: dictionary with names and values to use for settings
        :type src: dict
        :param param_tag: name of the parameter tag in the settings file
        :type param_tag: str
        """        
        root = ET.Element("data")

        for key, value in src.items():
            element = ET.SubElement(root, param_tag)
            element.set('Name', str(f'Main/{key}'))
            element.set('Value', str(value))

        tree = ET.ElementTree(root)
        tree.write(self.xml_file, encoding='utf-8', xml_declaration=True)
        