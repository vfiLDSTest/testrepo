"""
    Module for saving test data in TJB output files
    """
import csv
import os
import shutil


def create_directory(dir_name: str):
    """
    Create a directory in the TJB output file

    :param dir_name: name of the directory to be created
    :type dir_name: str
    :raises FileNotFoundError: raised if failed to create directory
    :return: name of directory created
    :rtype: str
    """

    try:
        os.mkdir(dir_name)
    except FileExistsError:
        pass
    if not os.path.isdir(dir_name):
        raise FileNotFoundError(f"Error creating {dir_name}")
    else:
        return dir_name


def delete_directory(dir_name: str):
    """
    Remove a directory and its contents

    :param dir_name: name of the directory to be removed
    :type dir_name: str
    """
    # attempt to remove given file
    try:
        shutil.rmtree(dir_name)
    # if file does not exist catch the error and return
    except FileNotFoundError:
        pass
    # check the file was successfully removed
    if os.path.isdir(dir_name):
        raise FileExistsError(f"{dir_name} still exists after attempting to remove")
    else:
        return 1


def write_string_to_file(filename: str, dir_name: str, data: str):
    """
    Write a string to a given file (appends to end of file if file already exists)

    :param filename: name of the file the string should be written to
    :type filename: str
    :param dir_name: name of the directory the file is in (can be a path)
    :type dir_name: str
    :param data: the string to be written to the file
    :type data: str

    If the directory does not exist it will be created
    """
    create_directory(dir_name)
    with open(f"{dir_name}/{filename}", 'a+') as f:
        f.write(data)


def write_list_to_file(filename: str, dir_name: str, data: list):
    """
    Write a list to a given file (appends to end of file if file already exists)

    :param filename: name of the file the list should be written to
    :type filename: str
    :param dir_name: name of the directory the file is in (can be a path)
    :type dir_name: str
    :param data: the list to be written to the file
    :type data: str

    If the directory does not exist it will be created
    """
    create_directory(dir_name)
    with open(f"{dir_name}/{filename}", 'a+') as f:
        f.writelines(data)


def write_to_csv_file(filename: str, dir_name: str, data: list, header=[], overwrite=False):
    """
    Write a list of lists to csv file as rows
    Header is optional and will be written to top of file

    :param filename: name of the csv file the lists should be written to
    :type filename: str
    :param dir_name: name of the directory the csv file is in (can be a path)
    :type dir_name: str
    :param data: list of lists containing the data
    :type data: list
    :param header: header to be written at the top of the file, defaults to []
    :type header: list, optional
    :param overwrite: overwrite existing file, appends to file when False, defaults to False
    :type overwrite: bool, optional

    If the directory does not exist it will be created
    """
    create_directory(dir_name)
    if overwrite:
        write_mode = 'w'
    else:
        write_mode = 'a+'
    # if a single list is provided make it a list of one list so it will still be written correctly to the file
    if type(data[0]) != list:
        data = [data]
    with open(f"{dir_name}/{filename}", write_mode, newline='') as f:
        writer = csv.writer(f)
        if header:
            writer.writerow(header)
        writer.writerows(data)


def get_file_contents_as_list(filename: str, dirname="") -> list:
    """
    Get the contents of a file as a list, each line in file will be one string in list

    :param filename: name of the file to read including file extension
    :type filename: str
    :param dirname: path to file if not in same directory as script, defaults to ""
    :type dirname: str, optional
    :return: contents of the file
    :rtype: list
    """
    if dirname and not dirname.endswith("/"):
        dirname = f"{dirname}/"
    with open(f"{dirname}{filename}", "r") as rf:
        contents = rf.readlines()
    return contents
