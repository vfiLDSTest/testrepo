'''
Created on 19.12.2018

@author: jesc
'''

import json
from . import logger
from pathlib import Path
import os
import sys
import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry
import uuid
import time
import zipfile
from datetime import datetime
from typing import List, Dict


class Device(object):
    def __init__(self, d: Dict, vhq: 'Vhq') -> None:
        self.id = None
        self.__dict__ = d
        self.vhq = vhq
        assert self.id

    def is_active(self):
        return self.status == "ACTIVE"

    def __create_diag_action(self, action_name) -> bool:
        log = logger.get_logger(sys._getframe().f_code.co_name)
        action_type_id = self.vhq.get_action_types(name=action_name)[0]["id"]
        action_id = self.vhq.create_action(action_type_id, self.id)
        log.info("Created diagnostic action '{}' with id: {}".format(
            action_name, action_id))
        error_count = 0
        action_status = None
        while action_status != "SUCCESS" and error_count < 100:
            actions = self.vhq.get_actions(id=action_id)
            if actions:
                assert len(actions) == 1
                action = actions[0]
                action_status = action["actionTaskStatus"][0]["status"]
                log.debug("Diagnostic action status: {}".format(action_status))
            else:
                error_count += 1
            time.sleep(10)
        return action_status == "SUCCESS"

    def get_device_profile(self):
        assert self.__create_diag_action("Get Device Profile")

    def wait_for_download(self, package_id, start_time) -> int:
        """
        returns download_id
        """
        log = logger.get_logger(sys._getframe().f_code.co_name)
        log.info("Waiting for download job creation")
        last_download_package_id = None
        last_download_time = datetime.min
        last_download_id = None
        error_count = 0
        loop_count = 0

        while (last_download_package_id != package_id or last_download_time < start_time) and error_count < 30 and loop_count < 30:
            downloads = self.vhq.get_downloads(deviceUid=self.id, limit=1)
            if downloads:
                assert len(downloads) == 1
                last_download = downloads[0]
                # last_download_time = datetime.fromisoformat(last_download["createdDate"])
                # above work with python>3.7, use this for compatibility:
                last_download_time = datetime.strptime(
                    last_download["createdDate"], "%Y-%m-%d %H:%M:%S.%f")
                last_download_package_id = last_download["taskStatus"][0]["packageId"]
                last_download_id = last_download["id"]
                log.debug("Last created download job created on {}".format(
                    last_download_time))
            else:
                error_count += 1
            loop_count += 1
            time.sleep(10)
        if last_download_package_id == package_id and last_download_time >= start_time:
            return last_download_id
        else:
            # no download necessary?
            return None

    def wait_for_download_success(self, download_id):
        log = logger.get_logger(sys._getframe().f_code.co_name)
        log.info("Waiting for download job completion")
        last_download_status = None
        error_count = 0

        while last_download_status != "INSTALL_SUCCESSFUL" and error_count < 100:
            downloads = self.vhq.get_downloads(id=download_id, limit=1)
            if downloads:
                last_download = downloads[0]
                last_download_status = last_download["taskStatus"][0]["status"]
                log.debug("Status: {}".format(last_download_status))
            else:
                error_count += 1
            time.sleep(10)
        assert last_download_status == "INSTALL_SUCCESSFUL"

    def wait_synchronized(self):
        log = logger.get_logger(sys._getframe().f_code.co_name)
        log.info("Checking device synchronization in_synch")
        in_synch = False
        error_count = 0
        while not in_synch and error_count < 100:
            devices = self.vhq.get_devices(id=self.id)
            if devices:
                device = devices[0]
                in_synch = device["synchronized"]
                log.debug("Device synchronized: {}".format(in_synch))
            else:
                error_count += 1
            time.sleep(10)
        assert in_synch

    def clear_assignment(self):
        assert self.vhq.assign_ref_set_to_device(0, self.id, "NONE")


class Vhq:
    """
    Class which handles all communication with VHQ instance
    """

    def __init__(self, vhq_base_url, customer_name, sso_url, sso_client_id, sso_client_secret):
        log = logger.get_logger(sys._getframe().f_code.co_name)

        self.session = requests.Session()
        retries = Retry(total=5,
                        backoff_factor=0.5,
                        status_forcelist=[500, 502, 503, 504])
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

        self.vhq_base_url = vhq_base_url
        self.vhq_rest_apis = {
            "actions": vhq_base_url + "v1.1/actions",
            "actionTypes": vhq_base_url + "v1.1/actionTypes",
            "applications": vhq_base_url + "v1.1/applications",
            "customers": vhq_base_url + "v1.1/customers",
            "devices": vhq_base_url + "v1.3/devices",
            "downloads": vhq_base_url + "v1.1/downloads",
            "hierarchies": vhq_base_url + "v1.1/hierarchies",
            "models": vhq_base_url + "v1.1/models",
            "packageFiles": vhq_base_url + "v1.1/packageFiles",
            "packages": vhq_base_url + "v1.1/packages",
            "parameters": vhq_base_url + "v1.3/parameters",
            "referenceSets": vhq_base_url + "v1.2/referenceSets",
            "systemDetails": vhq_base_url + "v1.1/systemDetails",
        }
        self.sso_url = sso_url
        self.sso_client_id = sso_client_id
        self.sso_client_secret = sso_client_secret
        self.sso_token = None
        sso_token = self._get_sso_token()
        if sso_token:
            self.sso_token = sso_token
            self.headers = {
                "Authorization": "Bearer " + self.sso_token,
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            try:
                customers = self.get_customers(customerName=customer_name)
                self.log_version()
            except requests.exceptions.RetryError:
                raise ConnectionError
            if customers:
                self.customer_id = customers[0]["id"]
            else:
                raise ConnectionError
            model_list = self.get_model_list()
            if model_list:
                self.model_list = model_list
            else:
                raise ConnectionError
        else:
            log.error("Got no token from SSO server, abort...")
            raise ConnectionError

    def __del__(self):
        if self.sso_token:
            self._revoke_sso_token()

    def _get_sso_token(self):
        """
        get authentication token from SSO service
        """
        log = logger.get_logger(sys._getframe().f_code.co_name)
        sso_parameter = {"grant_type": "client_credentials", "client_id": self.sso_client_id,
                         "client_secret": self.sso_client_secret, "scope": uuid.uuid1()}
        result = self.session.post(self.sso_url + "token", data=sso_parameter)
        if result.ok:
            log.debug(result.json())
            token = result.json()["access_token"]
            lease_time = result.json()["expires_in"]
            log.info("Got token from SSO service")
            log.debug("Token: {}".format(token))
            log.debug("lease_time: {}".format(lease_time))
            return token
        else:
            log.error("Error during authentication with SSO server, error code: {}".format(
                result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))

    def _revoke_sso_token(self):
        """
        revoke authentication token
        """
        log = logger.get_logger(sys._getframe().f_code.co_name)
        data = {"token": self.sso_token, "token_type_hint": "access_token"}
        headers = {
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}
        result = self.session.post(self.sso_url + "revoke", data=data, headers=headers,
                                   auth=HTTPBasicAuth(self.sso_client_id, self.sso_client_secret))
        if result.ok:
            log.debug(result)
            log.info("Revoked token from SSO service")
            self.sso_token = None
        else:
            log.error("Error during token revoke with SSO server, error code: {}".format(
                result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))

    def log_version(self) -> None:
        log = logger.get_logger(sys._getframe().f_code.co_name)
        log.info("retrieve system details")
        details_url = self.vhq_rest_apis["systemDetails"]
        result = self.session.get(details_url, headers=self.headers)
        if result.status_code == 200:
            log.info("VHQ server version: {}".format(result.json()["version"]))
            if not result.json()["alive"]:
                log.error("the VHQ services are NOT running at server!")
                raise ConnectionError
        else:
            log.error("error code: {}".format(result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            raise ConnectionError

    def upload_package_file(self, file_path: Path) -> int:
        """
        upload file to VHQ server

        Args:
            file_path (Path): Path object of the file to be uploaded

        Returns:
            id (int): ID of the file in VHQ or None if upload was not successful
        """
        log = logger.get_logger(sys._getframe().f_code.co_name)
        log.info("Uploading {} to VHQ".format(file_path))

        headers = {
            "Authorization": "Bearer " + self.sso_token
        }
        upload_url = self.vhq_rest_apis["packageFiles"] + \
            "?customerId=" + str(self.customer_id)

        with file_path.open("rb") as f:
            files = {"newPackageFile": (file_path.name, f)}
            result = self.session.post(
                upload_url, headers=headers, files=files)
            if result.status_code == 409:
                if "Duplicate-Id" in result.headers:
                    log.debug("Header:\n{}".format(result.headers))
                    log.debug("Content:\n{}".format(result.text))
                    log.debug(
                        "Duplicate-Id: {}".format(result.headers["Duplicate-Id"]))
                    return int(result.headers["Duplicate-Id"])
            elif result.status_code == 201:
                log.debug("Url: {}".format(result.headers["New-PackageFiles"]))
                return int(result.headers["New-PackageFiles"].rpartition("/")[2])
            log.error("Upload not successful, error code: {}".format(
                result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            return None

    def create_package(self, **package_params) -> int:
        """
        create package containing a previously uploaded file

        Kwargs:
            packageFileId (int): ID of the uploaded file
            name (str): Name of the file to be uploaded
            tags (str): Tags for the package, e.g. CI
            type (str): Type of the package, can be 'APPLICATION', 'BUNDLE', 'FEATURE_ENABLEMENT_LICENSE', 'FORM', 'OS', 'PARAMETER_FILE', 'SERVICE_PACK'
            version (str): Version of the package, e.g. ADK-4.4.12-413
            postInstallAction (str): postInstallAction for the package, can be 'NONE', 'REBOOT', 'RESTART_APPLICATIONS'
            modelIds (list): List of modelIds(int) which the package supports (see also get_model_ids())

        Returns:
            id(int): ID of the package in VHQ or None if creation was not successful
        """
        log = logger.get_logger(sys._getframe().f_code.co_name)
        log.info("Create package {} in VHQ".format(package_params["name"]))
        if "type" in package_params:
            assert (package_params["type"] in
                    ['APPLICATION', 'BUNDLE', 'FEATURE_ENABLEMENT_LICENSE', 'FORM', 'OS', 'PARAMETER_FILE', 'SERVICE_PACK', 'ANDROID_OTA']), "Wrong package type!"
        if "postInstallAction" in package_params:
            assert (package_params["postInstallAction"] in
                    ['NONE', 'REBOOT', 'RESTART_APPLICATIONS']), "Wrong postInstallAction!"
        package_params["customerId"] = self.customer_id

        create_url = self.vhq_rest_apis["packages"]
        data = {
            "data": package_params
        }
        log.debug("Request-Data: {}".format(json.dumps(data)))
        result = self.session.post(
            create_url, data=json.dumps(data), headers=self.headers)
        if result.status_code == 409:
            if "Duplicate-Id" in result.headers:
                log.debug(
                    "Duplicate-Id: {}".format(result.headers["Duplicate-Id"]))
                return int(result.headers["Duplicate-Id"])
        elif result.status_code == 201:
            log.debug("Url: {}".format(result.headers["New-Package"]))
            return result.headers["New-Package"].rpartition("/")[2]
        log.error("Package creation not successful, error code: {}".format(
            result.status_code))
        log.error("Header:\n{}".format(result.headers))
        log.error("Content:\n{}".format(result.text))
        return None

    def delete_package(self, package_id: int) -> bool:
        """
        Delete a package in vhq

        Args:
            package_id (int): ID of the to be deleted package
        Returns:
            success (bool): True if successful
        """
        log = logger.get_logger(sys._getframe().f_code.co_name)
        delete_url = self.vhq_rest_apis["packages"] + "/" + \
            str(package_id) + "?customerId=" + str(self.customer_id)
        result = self.session.delete(delete_url, headers=self.headers)
        if result.status_code == 204:
            return True
        else:
            log.error("Could not delete package with id {}, error code: {}".format(
                package_id, result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            return False

    def delete_old_packages(self, **search_params):
        """
        Find list of packages which are matching given parameters and deletes them

        Kwargs:
            name (str): Name of the package
            tags (str): Free format text based tag
            version (str: Version of the package (e.g. ADK-4.4.15)
        """
        log = logger.get_logger(sys._getframe().f_code.co_name)
        search_params["limit"] = 1000
        packages = self.get_packages(**search_params)
        if packages:
            for package in packages:
                package_id = package["id"]
                log.debug("Delete old package with id: {}".format(package_id))
                self.delete_package(package_id)

    def update_device_parameters(self, **params):
        """
        Change the value of parameters associated with device applications

        Kwargs:
            app_name (str): Name of the application the parameter is associated with
            parameters (dict): key value pairs of parameter name and value
        """
        app_name = params["app_name"]
        parameters = params["parameters"]
        device_id = params["device_id"]

        log = logger.get_logger(sys._getframe().f_code.co_name)
        log.info(f"Updating {app_name} parameters in VHQ")

        parameter_url = self.vhq_rest_apis["parameters"]

        device_parameters = [{"name": k, "value": v}
                             for k, v in parameters.items()]
        log.info(f"Parameters to update: {device_parameters}")
        data = {
            "data": [{
                "deviceUid": device_id,
                "customerId": self.customer_id,
                "applicationName": app_name,
                "deviceParameters": device_parameters
            }]
        }
        log.debug("Request-Data: {}".format(json.dumps(data)))

        result = self.session.patch(
            parameter_url, data=json.dumps(data), headers=self.headers)
        if result.status_code == 204:
            log.info("ReferenceSet {} updated!".format(parameter_url))
            return True
        else:
            log.error("Return code: {}".format(result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
        return False

    def create_ref_set(self, ref_set_name: str, package_ids: List[int], model_ids: List[int], status: bool) -> int:
        """
        create a reference set with previously created packages

        Args:
            ref_set_name (str): Name of the referenceSet
            package_ids (list): List of packages(int) which should be added to the reference set
            model_ids (list): List of model_ids(int) which the reference set supports (see also get_model_ids())
            status (bool): Indicates if the Reference set is active
        Returns:
            id (int): ID of the reference set in VHQ or None if creation/update was not successful
        """

        log = logger.get_logger(sys._getframe().f_code.co_name)
        log.info("Creating/Updating referenceSet {} in VHQ".format(ref_set_name))

        ref_set_url = self.vhq_rest_apis["referenceSets"]
        ref_set_id = None

        package_assignments = []
        for package_id in package_ids:
            if "," in package_id:
                # needed to add the the extra split here as Android packages can hold
                # several more packages with a manifest file so we account for this
                # here by adding each package ID
                for p_id in package_id.split(","):
                    package_assignments.append(
                        {"assignmentType": "PACKAGE", "id": p_id})
            else:
                package_assignments.append(
                    {"assignmentType": "PACKAGE", "id": package_id})

        data = {
            "data": {
                "name": ref_set_name,
                "modelId": model_ids,
                "assignments": package_assignments,
                "active": status,
                "customerId": self.customer_id
            }
        }
        result = self.session.post(
            ref_set_url, data=json.dumps(data), headers=self.headers)
        if result.status_code == 409:
            log.warning("Conflict")
            log.info("Return code: {}".format(result.status_code))
            log.info("Header:\n{}".format(result.headers))
            log.info("Content:\n{}".format(result.text))
            log.debug(result.json())
        elif result.status_code == 201:
            log.info("ReferenceSet {} created!".format(ref_set_name))
            log.debug("Url: {}".format(result.headers["New-ReferenceSets"]))
            ref_set_id = int(
                result.headers["New-ReferenceSets"].rpartition("/")[2])
        else:
            log.error("Return code: {}".format(result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
        return ref_set_id

    def delete_ref_set(self, ref_set_id):
        """
        Delete reference set from VHQ

        Args:
            ref_set_id (int): ID of the to be deleted reference set
        """
        log = logger.get_logger(sys._getframe().f_code.co_name)
        delete_url = self.vhq_rest_apis["referenceSets"] + "/" + \
            str(ref_set_id) + "?customerId=" + str(self.customer_id)
        result = self.session.delete(delete_url, headers=self.headers)
        if result.status_code == 204:
            return True
        else:
            log.error("Could not delete reference set with id {}, error code: {}".format(
                ref_set_id, result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            return False

    def update_ref_set(self, ref_set_id: int, package_ids: List[int], model_ids: List[int], status: bool) -> int:
        """
        update a reference set and add previously created packages

        Args:
            ref_set_id (int): Name of the referenceSet
            package_ids (list): List of packages(int) which should be added to the reference set
            model_ids (list): List of model_ids(int) which the reference set supports (see also get_model_ids())
            status (bool): Indicates if the Reference set is active
        Returns:
            id (int): ID of the reference set in VHQ or None if creation/update was not successful
        """

        log = logger.get_logger(sys._getframe().f_code.co_name)
        log.info("Updating referenceSet {} in VHQ".format(ref_set_id))

        ref_set_url = self.vhq_rest_apis["referenceSets"] + \
            "/" + str(ref_set_id)

        package_assignments = []
        for package_id in package_ids:
            package_assignments.append(
                {"assignmentType": "PACKAGE", "id": package_id})
        data = {
            "data": {
                "modelId": model_ids,
                "assignments": package_assignments,
                "active": status,
                "customerId": self.customer_id
            }
        }
        log.debug("Request-Data: {}".format(json.dumps(data)))

        result = self.session.patch(
            ref_set_url, data=json.dumps(data), headers=self.headers)
        if result.status_code == 204:
            log.info("ReferenceSet {} updated!".format(ref_set_id))
            return True
        else:
            log.error("Return code: {}".format(result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
        return False

    def create_or_update_ref_set(self, ref_set_name: str, package_ids: List[int], model_ids: List[int], status: bool) -> int:
        old_id = self.get_ref_set_id(name=ref_set_name)

        if old_id:
            ret = self.update_ref_set(old_id, package_ids, model_ids, status)
            assert ret
            return old_id
        else:
            return self.create_ref_set(ref_set_name, package_ids, model_ids, status)

    def get_action_types(self, **search_params):
        log = logger.get_logger(sys._getframe().f_code.co_name)
        packages_url = self.vhq_rest_apis["actionTypes"]
        search_params["customerId"] = self.customer_id
        result = self.session.get(
            packages_url, headers=self.headers, params=search_params)
        if result.status_code == 200:
            return result.json()["data"]
        else:
            log.error("Could not find action_types with given parameters {}, error code: {}".format(
                search_params, result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            return None

    def get_actions(self, **search_params):
        log = logger.get_logger(sys._getframe().f_code.co_name)
        packages_url = self.vhq_rest_apis["actions"]
        search_params["customerId"] = self.customer_id
        result = self.session.get(
            packages_url, headers=self.headers, params=search_params)
        if result.status_code == 200:
            return result.json()["data"]
        else:
            log.error("Could not find actions with given parameters {}, error code: {}".format(
                search_params, result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            return None

    def get_customers(self, **search_params):
        log = logger.get_logger(sys._getframe().f_code.co_name)
        customers_url = self.vhq_rest_apis["customers"]
        result = self.session.get(
            customers_url, headers=self.headers, params=search_params)
        if result.status_code == 200:
            return result.json()["data"]
        else:
            log.error("Could not find customers with given parameters {}, error code: {}".format(
                search_params, result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            return None

    def get_devices(self, **search_params) -> List[Dict]:
        """
        Get list of device ids which are matching given search parameters, e.g. serialNumber=="123-456-789"

        Args:
            device_filter (str): key that should be used for filter comparison, e.g.: "serialNumber", "modelName", "macAddress"
            device_filter_value (list): value which is used for comparison, e.g. "123-456-789"

        Returns:
            ids (list): List of ids(int) matching filter parameters
        """
        log = logger.get_logger(sys._getframe().f_code.co_name)
        devices_url = self.vhq_rest_apis["devices"]
        search_params["customerId"] = self.customer_id
        result = self.session.get(
            devices_url, headers=self.headers, params=search_params)
        if result.status_code == 200:
            device_list = result.json()["data"]
            return device_list
        else:
            log.error("Could not get device ids, error code: {}".format(
                result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            return None

    def get_device_applications(self, **search_params) -> List[Dict]:
        log = logger.get_logger(sys._getframe().f_code.co_name)
        application_url = self.vhq_rest_apis["applications"]
        # search_params["customerId"] = self.customer_id
        result = self.session.get(
            application_url, headers=self.headers, params=search_params)
        if result.status_code == 200:
            device_list = result.json()["data"]
            return device_list
        else:
            log.error("Could not get device ids, error code: {}".format(
                result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            return None

    def get_device_parameters(self, **search_params) -> List[Dict]:
        log = logger.get_logger(sys._getframe().f_code.co_name)
        parameter_url = self.vhq_rest_apis["parameters"]
        result = self.session.get(
            parameter_url, headers=self.headers, params=search_params)
        if result.status_code == 200:
            device_list = result.json()["data"]
            return device_list
        else:
            log.error("Could not get device parameters, error code: {}".format(
                result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            return None

    def get_device_id(self, **search_params) -> int:
        log = logger.get_logger(sys._getframe().f_code.co_name)
        search_result = self.get_devices(**search_params)
        if search_result and len(search_result) == 1:
            device_id = search_result[0]["id"]
            return device_id
        else:
            log.error("Cannot parse search_result: {}".format(search_result))
            raise

    def get_device(self, **search_params) -> Device:
        log = logger.get_logger(sys._getframe().f_code.co_name)
        search_result = self.get_devices(**search_params)
        if not search_result:
            return None

        if len(search_result) == 1:
            return Device(d=search_result[0], vhq=self)
        else:
            log.error("Cannot parse search_result: {}".format(search_result))
            raise

    def get_downloads(self, **search_params):
        log = logger.get_logger(sys._getframe().f_code.co_name)
        packages_url = self.vhq_rest_apis["downloads"]
        search_params["customerId"] = self.customer_id
        result = self.session.get(
            packages_url, headers=self.headers, params=search_params)
        if result.status_code == 200:
            return result.json()["data"]
        else:
            log.error("Could not find downloads with given parameters {}, error code: {}".format(
                search_params, result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            return None

    def get_hierarchies(self, **search_params):
        """
        Get list of dicts containing hierarchies of the customer_id on VHQ server matching hierarchyFullPath (str)

        Returns:
           hierarchies (list): List of hierarchies (dict) , e.g.
               [{'hierarchyFullPath': 'PRE-SIT >> BHE >> INTEGRATION', 'locationIdentifier': None, 'referenceSet': [{'referenceSetId': None, 'parameterTemplateId': []}], 'ipEndingAddress': None, 'description': None, 'id': 1459, 'customerId': 3, 'timezoneId': 110, 'downloadOn': 'NEXT_CONTACT', 'childHierarchyId': [], 'name': 'INTEGRATION', 'downloadAutomationEnabled': True, 'ipStartingAddress': None, 'parentHierarchyId': 1458, 'inheritReferenceSet': False}]
        """
        log = logger.get_logger(sys._getframe().f_code.co_name)
        hierachie_url = self.vhq_rest_apis["hierarchies"]
        search_params["customerId"] = self.customer_id
        result = self.session.get(
            hierachie_url, headers=self.headers, params=search_params)
        if result.status_code == 200:
            hierarchie_list = result.json()["data"]
            return hierarchie_list
        else:
            log.error("Could not get hierarchies, error code: {}".format(
                result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            return None

    def get_model_list(self) -> List[Dict]:
        """
        Get list of dicts containing supported models of VHQ server

        Returns:
            models (list): List of models(dict), e.g. [{ "id": 0, "internalModelName": "P400", "name": "P400", "familyName": "Engage" }]
        """
        log = logger.get_logger(sys._getframe().f_code.co_name)
        model_url = self.vhq_rest_apis["models"]
        result = self.session.get(model_url, headers=self.headers, params={
                                  "limit": 1000, "customerId": self.customer_id})
        if result.status_code == 200:
            model_list = result.json()["data"]
            return model_list
        else:
            log.error(
                "Could not get model-list, error code: {}".format(result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            return None

    def get_model_ids(self, model_filter, model_filter_values: List[str]):
        """
        Get list of modelIds which are matching given filter parameters, familyName==Engage

        Args:
            model_filter (str): key that should be used for filter comparison: "id", "internalModelName", "name", "familyName"
            model_filter_values (list): List of strs which are used for comparison, e.g. "Engage"

        Returns:
            ids (list): List of ids(int) matching filter parameters
        """
        log = logger.get_logger(sys._getframe().f_code.co_name)
        filtered_list = []
        for mf in model_filter_values:
            filtered_list.extend(
                [m["id"] for m in self.model_list if m[model_filter] == mf])

        if not filtered_list:
            log.warning("model_list {} does not contain {}".format(
                self.model_list, model_filter_values))

        return filtered_list

    def get_vhq_model_from_device_model(self, device_model: str, os_type: str):
        """
        Some device models gotten from the device do not match the internalModelName or vhq name
        this method gets the correct model if different from what VHQ accepts

        :param device_model: device model as it is returned from TRC agent
        :type device_model: str
        :param os_type: os type as it is returned from TRC agent
        :type os_type: str
        """
        log = logger.get_logger(sys._getframe().f_code.co_name)
        vhq_model_dict = [dict(x) for x in self.model_list]
        for model in vhq_model_dict:
            if model["internalModelName"] == device_model:
                return model["name"]
            elif model["internalModelName"].startswith(device_model):
                log.info(f"{device_model}-{os_type}")
                if model["internalModelName"] == f"{device_model}-{os_type}":
                    return model["name"]
        
        log.debug(f"{device_model} not found in {self.model_list}")
        raise NotImplementedError(f"{device_model} not found supported VHQ model list")


    def get_packages(self, **search_params):
        """
        Get list of packages which are matching given parameters

        Kwargs:
            name (str): Name of the package
            tags (str): Free format text based tag
            version (str): Version of the package (e.g. ADK-4.4.15)

        Returns:
            packages (list): List of packages (dict) , e.g.
            [{'thumbNailLocationURL': None, 'version': 'ADK-4.4.15-RC1', 'type': 'OS', 'tags': 'CI', 'fileSize': 35256777,
            'modifiedOn': '2019-03-08 08:02:08.903', 'postInstallAction': 'REBOOT', 'deviceFileLocation': None, 'packageFileId': 1067,
            'targetUser': None, 'description': None, 'previewFileLocationURL': None, 'id': 12589, 'createdOn': '2019-03-05 13:55:32.293',
            'fileName': 'dl.adk-4.4.15-RC1-726-develop-vos2-base-prod.tgz', 'modelIds': [73, 88, 89], 'name': 'dl.adk-4.4.15-RC1-726-develop-vos2-base-prod.tgz',
            'createdByUserId': '12D38078-2E02-425C-B021-8809D86769BB', 'downloadAutomationEnabled': True,
            'modifiedByUserId': '7B74AD10-38C8-4800-8F3E-F7DD859E6CD6', 'customerId': 3, 'fileNameOnDevice': None}
        """
        log = logger.get_logger(sys._getframe().f_code.co_name)
        packages_url = self.vhq_rest_apis["packages"]
        search_params["customerId"] = self.customer_id
        result = self.session.get(
            packages_url, headers=self.headers, params=search_params)
        if result.status_code == 200:
            return result.json()["data"]
        else:
            log.error("Could not find packages with given parameters {}, error code: {}".format(
                search_params, result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            return None

    def get_ref_sets(self, **search_params) -> List[Dict]:
        """
        Get ID of a reference set

        Args:
            name (str): Name of the reference set
        """
        log = logger.get_logger(sys._getframe().f_code.co_name)
        reference_set_url = self.vhq_rest_apis["referenceSets"]
        search_params["customerId"] = self.customer_id
        result = self.session.get(
            reference_set_url, headers=self.headers, params=search_params)
        if result.status_code == 200:
            return result.json()["data"]
        else:
            log.error("Could not find ReferenceSets with given parameters {}, error code: {}".format(
                search_params, result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            return None

    def get_ref_set_id(self, **search_params) -> int:
        log = logger.get_logger(sys._getframe().f_code.co_name)
        search_result = self.get_ref_sets(**search_params)
        if not search_result:
            return None
        if len(search_result) == 1:
            ref_set_id = search_result[0]["id"]
            return ref_set_id
        else:
            log.error("Cannot parse search_result: {}".format(search_result))
            raise

    def assign_ref_set_to_device(self, reference_set_id: int, device_id: int, software_assignment_type: str = "REFERENCE_SET") -> bool:
        """
        Assign reference set to a device

        Args:
            reference_set_id (int): ID of the reference set
            device_id (int): ID of the device
            software_assignment_type (str): "REFERENCE_SET" or "NONE"
        """
        log = logger.get_logger(sys._getframe().f_code.co_name)
        device_url = self.vhq_rest_apis["devices"] + "/" + str(device_id)
        data = {
            "data": {
                "customerId": self.customer_id,
                "autoDownload": True,
                "softwareConfigurations": {
                    "softwareAssignmentType": software_assignment_type,
                    "directAssignment": True
                }
            }
        }
        if software_assignment_type != "NONE":
            data["data"]["softwareConfigurations"]["referenceSetId"] = reference_set_id
        result = self.session.patch(
            device_url, data=json.dumps(data), headers=self.headers)
        if result.status_code == 204:
            return True
        else:
            log.error("Could not assign ReferenceSet {}, error code: {}".format(
                reference_set_id, result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            return False

    def assign_device_to_hierarchy(self, device_id: int, hierarchy_name: str) -> bool:
        """
        Assign device to hierarchy

        Args:
            device_id (int): ID of the device
            hierarchy_name (str): name of the hierarchy (full path)
        """
        log = logger.get_logger(sys._getframe().f_code.co_name)
        device_url = self.vhq_rest_apis["devices"] + "/" + str(device_id)
        data = {
            "data": {
                "customerId": self.customer_id,
                "hierarchyName": hierarchy_name
            }
        }

        result = self.session.patch(
            device_url, data=json.dumps(data), headers=self.headers)
        if result.status_code == 204:
            return True
        else:
            log.error("Could not assign device to hierarchy {} error code: {}".format(
                hierarchy_name, result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            return False

    def assign_ref_set_to_hierarchie(self, ref_set_ids: List[int], hiearchie_id: int) -> bool:
        """
        Assign reference set to a hierarchie

        Args:
            ref_set_ids (list): ID of the reference set
            hiearchie_id (int): ID of the device
        """
        log = logger.get_logger(sys._getframe().f_code.co_name)
        hierachie_url = self.vhq_rest_apis["hierarchies"] + \
            "/" + str(hiearchie_id)
        data = {
            "data": {
                "customerId": self.customer_id,
                "inheritReferenceSet": False,
                "downloadOn": "NEXT_CONTACT",
                "referenceSetId": ref_set_ids
            }
        }
        result = self.session.patch(
            hierachie_url, data=json.dumps(data), headers=self.headers)
        if result.status_code == 204:
            return True
        else:
            log.error("Could not assign ReferenceSets {}, error code: {}".format(
                ref_set_ids, result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            return False

    def create_action(self, action_type_id, device_id) -> int:
        log = logger.get_logger(sys._getframe().f_code.co_name)
        actions_url = self.vhq_rest_apis["actions"]
        data = {
            "data": {
                "customerId": self.customer_id,
                "jobName": "VAL#{}".format(int(time.time())),
                "deviceUid": [device_id],
                "actionType": [{"actionTypeId": action_type_id}],
                "startOn": "NEXT_CONTACT"
            }
        }
        result = self.session.post(
            actions_url, data=json.dumps(data), headers=self.headers)
        if result.status_code == 201:
            log.debug("Url: {}".format(result.headers["New-Action"]))
            return int(result.headers["New-Action"].rpartition("/")[2])
        else:
            log.error("Could not schedule action {} on device {}, error code: {}".format(
                action_type_id, device_id, result.status_code))
            log.error("Header:\n{}".format(result.headers))
            log.error("Content:\n{}".format(result.text))
            return False


def get_solutions_dirs(config):
    """
    Get possible solution directories from actual config

    Args:
        config (dict): complete config
    """
    solutions_dirs = []
    for solution_conf_dir in config["solutionConfDirs"]:
        used_areas = solution_conf_dir.get("areas", ["main"])
        solutions_dirs.extend(
            [config["areas"][area]["importFolder"] for area in used_areas])

    return set(solutions_dirs)


def delete_old_packages(vhq, version):
    """
    Deletes all packages with given tags and version

    Args:
        vhq (obj): vhq connection object
        tags (str): tags of the packages
        version (str): version of the packages
    """
    vhq.delete_old_packages(version=version)


def get_package_path(path: str, solutions_dirs: str) -> Path:
    """
    Get complete path for solution package, try dev variant if prod is not available

    Args:
        path (str): path to the solution package
    """
    log = logger.get_logger(sys._getframe().f_code.co_name)

    for solutions_dir in solutions_dirs:
        package_path = Path(os.path.join(solutions_dir, path))
        # check if prod-package is available
        if package_path.is_file():
            return package_path
        else:
            package_path = Path(os.path.join(solutions_dir, str(
                package_path).replace("-prod", "-dev")))
            if package_path.is_file():
                log.info("Could find prod solution package, using available dev variant {}".format(
                    package_path))
                return package_path
    log.error("Cannot find solution package {}".format(package_path))
    return None


def handle_current_package(vhq, solutions_dirs, package_file, model_ids, integration_version, FULLVERSION, tags, package_type="OS"):
    package_id = None
    package_path = get_package_path(package_file, solutions_dirs)

    if package_path:
        package_file_id = vhq.upload_package_file(package_path)
        if package_file_id:
            package_full_name = package_path.name
            package_id = vhq.create_package(packageFileId=package_file_id, name=package_full_name, tags=tags,
                                            type=package_type, version=integration_version, postInstallAction="REBOOT", modelIds=model_ids)
    return package_id


def handle_current_ref_set(vhq, name, model_ids, package_ids):
    ref_set_ids = vhq.get_ref_sets(name=name)
    if ref_set_ids:
        ref_set_id = ref_set_ids[0]["id"]
        vhq.update_ref_set(ref_set_id, package_ids, model_ids, True)
    else:
        vhq.create_ref_set(name, package_ids, model_ids, True)


def get_integration_version(config):
    PREFIX = config["deployment"]["vhq"].get("VHQ_ADK_VERSION_PREFIX", "VAL-")
    integration_version = config["INTEGRATION_VERSION"]
    if "." in integration_version:
        integration_version = integration_version.split('-', 1)[0]
    return PREFIX + integration_version


def set_deployment_config(config):
    log = logger.get_logger(sys._getframe().f_code.co_name)
    config["deployment"]["vhq"].setdefault(
        "sso_url", "https://qa.account.verifonecp.com/oauth2/")
    config["deployment"]["vhq"].setdefault("customer", "VALQENEW")
    config["deployment"]["vhq"].setdefault(
        "vhq_base-url", "https://qa.mumbai.verifonehq.net/apis/")

    try:
        config["deployment"]["vhq"]["sso_client_id"] = os.environ["SSO_CLIENT_ID"]
    except KeyError:
        log.error("Cannot get SSO_CLIENT_ID from Environment!")
        return False
    try:
        config["deployment"]["vhq"]["sso_client_secret"] = os.environ["SSO_CLIENT_SECRET"]
    except KeyError:
        log.error("Cannot get SSO_CLIENT_SECRET from Environment!")
        return False

    return True


def upload_solutions(config):
    """
    Upload solution packages listed in config to vhq and create corresponding reference sets.

    Args:
        config (dict): complete config
    """
    log = logger.get_logger(sys._getframe().f_code.co_name)
    log.info("Uploading file to VHQ")

    try:
        vhq = Vhq(
            config["deployment"]["vhq"]["vhq_base-url"],
            config["deployment"]["vhq"]["customer"],
            config["deployment"]["vhq"]["sso_url"],
            config["deployment"]["vhq"]["sso_client_id"],
            config["deployment"]["vhq"]["sso_client_secret"]
        )
    except ConnectionError as e:
        log.debug(e)
        log.error("ConnectionError: Vhq class cannot be instantiated!")
        return

    integration_version = get_integration_version(config)
    FULLVERSION = config["FULLVERSION"]
    tags = config["deployment"]["vhq"].get("tags", "ADK-INTEGRATION-CI")
    try:
        package_type = config["package_type"]
    except KeyError:
        package_type = "OS"

    solutions_dirs = get_solutions_dirs(config)
    delete_old_packages(vhq, integration_version)

    for ref_set_name, package in config["deployment"]["vhq"]["refSets"].items():
        package_ids = []
        model_ids = vhq.get_model_ids("name", package["models"])
        if not model_ids:
            log.error("Failed to get model ids for {}, cannot create reference set {}".format(
                package["models"], ref_set_name))
            continue
        for package_file in package["files"]:
            package_id = handle_current_package(vhq, solutions_dirs, package_file,
                                                model_ids, integration_version, FULLVERSION, tags, package_type)
            if package_id:
                package_ids.append(package_id)
        if package_ids:
            name = integration_version + "-" + ref_set_name
            handle_current_ref_set(vhq, name, model_ids, package_ids)
    del (vhq)


def generate_tjbs(config):
    log = logger.get_logger(sys._getframe().f_code.co_name)

    if "importFolder" in config["composer"]:
        vats_dir = config["composer"]["importFolder"]
    elif "areas" in config and "vats" in config["areas"]:
        vats_dir = config["areas"]["vats"]["importFolder"]
    else:
        raise ValueError(
            "Cannot find tjb destination directory. Either 'import_folder' in 'composer' or a 'vats' area must be configured")
    tjb_folder = os.path.join(vats_dir, "test", "tjb", "vhq")
    os.makedirs(tjb_folder, exist_ok=True)
    tjb_tmpl = "tools/vhq_tjb_run_tmpl.py"
    integration_version = get_integration_version(config)
    full_version = config["FULLVERSION"]

    for name, package in config["deployment"]["vhq"]["refSets"].items():
        package_name = os.path.split(package["files"][0])[
            1].format(FULLVERSION=full_version)
        ref_set_name = integration_version + "-" + name
        filename = "vhq_" + name.lower() + ".tjb"
        zipfilepath = os.path.join(tjb_folder, filename)
        log.info("create {}".format(zipfilepath))
        zipf = zipfile.ZipFile(zipfilepath, 'w', zipfile.ZIP_DEFLATED)
        lines = []

        with open(tjb_tmpl) as fin:
            for line in fin:
                lines.append(
                    line.replace(
                        "###package_name###", package_name).replace(
                        "###ref_set_name###", ref_set_name).replace(
                        "###vhq_base_url###", config["deployment"]["vhq"]["vhq_base-url"]).replace(
                        "###customer###", config["deployment"]["vhq"]["customer"]).replace(
                        "###sso_url###", config["deployment"]["vhq"]["sso_url"]).replace(
                        "###sso_client_id###", config["deployment"]["vhq"]["sso_client_id"]).replace(
                        "###sso_client_secret###", config["deployment"]["vhq"]["sso_client_secret"]
                    )
                )
        zipf.writestr("run.py", "".join(lines))
        zipf.write("tools/vhq.py")
        zipf.close()


def device_model_mappings(device_model: str, os_type: str):
    """
    Take a device model name and return the model name VHQ uses for the device

    :param device_model: model from the device
    :type device_model: str
    :param os_type: os of the device
    :type os_type: str
    :return: vhq valid model name
    :rtype: str
    """
    # Need some logic for determining the correct model for VHQ
    # these are the valid NEO model types for VHQ
    # M425-1-Android
    # M425-1-VOS3
    # M450-1-Android
    # M450-1-VOS3
    # V640m-1
    # V640m-2
    # V640m-3
    # P630
    # P630-2-Android
    # P630-2-VOS3
    # P630-VOS3
    # UX700-ML-2-Android
    # UX700-WB
    # UX700-WBU
    # UX700-WBU-2-Android
    # V660p
    # V660p-1
    # V660p-2
    # V660p-3
    # V660p-4
    # Because of VOS3 some models get appended with -VOS3 or -Android
    # if a model of P630-2 tries to be assigned to a refset VHQ will
    # deny the download as it is expecting P630-2-Android or P630-2-VOS3
    # the following code maps the device models to valid VHQ models
    ################################################################################
    # CURRENTLY ONLY COMPLETED FOR P630 WILL BE UPDATED AS OTHER MODELS ARE TESTED #
    ################################################################################
    term_mappings = {"t650": "T650",
                     "NEO640": "V640m-1",
                     "V400m 4G +": "1L-V45G",
                     "M400 WIFI/BT": "MD-M400",
                     "P400": "FU-435A",
                     "V240m 3GBW" : "1J-3GBW",
                     "V240m 3GPlus" : "1J-3GPLUS",
                     "t650c" : "T650c",
                     "V660c-1" : "V660c-1",
                     "V660c-2" : "V660c-2",
                     "V660p-1" : "V660p-1"}

    # replace model with mapped model if in mappings
    if device_model in term_mappings.keys():
        device_model = term_mappings[device_model]
        return device_model
    # get the device under tests os type
    vhq_model = ""
    # append the ostype to the model if it matches the VHQ model required
    if os_type == "ANDROID":
        if device_model in ["P630-2", "UX700-ML-2", "UX700-WBU-2", "M425-1", "M450-1"]:
            vhq_model = device_model+"-Android"
    elif os_type == "VOS3":
        if device_model in ["P630", "P630-2", "UX700-ML-2", "UX700-WBU-2", "M425-1", "M450-1"]:
            vhq_model = f"{device_model}-{os_type}"
    if not vhq_model:
        vhq_model = device_model.upper()

    return vhq_model
