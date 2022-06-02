#
# Copyright Elasticsearch B.V. and/or licensed to Elasticsearch B.V. under one
# or more contributor license agreements. Licensed under the Elastic License 2.0;
# you may not use this file except in compliance with the Elastic License 2.0.
#
"""zoom_client modules allows to generate access token for Zoom Oauth app,
with this access token is useful for running various Zoom APIs."""
import base64
import json
import threading
import time

import requests
import requests.exceptions

from .secrets_storage import SecretsStorage
from .utils import retry

ZOOM_AUTH_BASE_URL = "https://zoom.us/oauth/token?grant_type="


class AccessTokenGenerationException(Exception):
    """This class is used to generate the custom error exception when retry_count limit is exceeded."""

    def __init__(self, errors):
        super().__init__(
            f"Error while generating the Zoom access token. \nReason: {errors}"
        )
        self.errors = errors


lock = threading.Lock()


class ZoomClient:
    """This class is used to generate the access token to call different Zoom Apis."""

    def __init__(self, config, logger):
        self.retry_count = int(config.get_value("retry_count"))
        self.client_id = config.get_value("zoom.client_id")
        self.client_secret = config.get_value("zoom.client_secret")
        self.authorization_code = config.get_value("zoom.authorization_code")
        self.redirect_uri = config.get_value("zoom.redirect_uri")
        self.secrets_storage = SecretsStorage(config, logger)
        self.logger = logger
        self.config_file_path = config.file_name
        self.access_token_expiration = time.time()

    def get_headers(self):
        """generates header to fetch refresh token from zoom.

        Returns:
            request_headers: header to be used for requesting refresh token from Zoom.
        """
        credentials = f"{self.client_id}:{self.client_secret}"
        credentials_bytes = credentials.encode("ascii")
        base64_bytes = base64.b64encode(credentials_bytes)
        base64_credentials = base64_bytes.decode("ascii")
        request_headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Authorization": f"Basic {base64_credentials}",
        }
        return request_headers

    @retry(
        exception_list=(
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
        )
    )
    def get_token(self):
        """This module generates access token and refresh token using stored refresh token. If refresh token is not stored then uses
        authorization code."""
        lock.acquire()
        if time.time() < self.access_token_expiration:
            lock.release()
            return
        self.logger.info(
            f"Generating the access token and updating refresh token for the client ID: {self.client_id}..."
        )
        refresh_token = self.secrets_storage.get_refresh_token()
        if refresh_token and len(refresh_token):
            url = f"{ZOOM_AUTH_BASE_URL}refresh_token&refresh_token={refresh_token}"
        else:
            url = f"{ZOOM_AUTH_BASE_URL}authorization_code&code={self.authorization_code}&redirect_uri={self.redirect_uri}"
        invalid_field = ""
        try:
            response = requests.post(
                url=url,
                headers=self.get_headers(),
            )
            json_data = json.loads(response.text)
            response.raise_for_status()
            if response and response.status_code == requests.codes.ok:
                refresh_token = json_data["refresh_token"]
                self.access_token = json_data["access_token"]
                self.access_token_expiration = time.time() + 3500
                self.secrets_storage.set_refresh_token(refresh_token)
        except requests.exceptions.HTTPError as http_error:
            if response.status_code in [400, 401]:
                reason = json_data.get("reason", "")
                if reason in ["Invalid Token!", "Invalid authorization code"]:
                    invalid_field = "zoom.authorization_code"
                    self.secrets_storage.set_refresh_token("")
                elif reason == "Invalid request : Redirect URI mismatch.":
                    invalid_field = "zoom.redirect_uri"
                else:
                    invalid_field = "zoom.client_id or zoom.client_secret"
                raise AccessTokenGenerationException(
                    f"HTTPError.\
                    Error: {http_error}\
                    Reason: {reason}\
                    Solution: Please update the {invalid_field} in zoom_connector.yml file.\
                    "
                )
            self.logger.exception(f"HTTPError: {http_error}")
            raise http_error
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
        ) as exception:
            raise exception
        except Exception as exception:
            raise AccessTokenGenerationException(exception)
        finally:
            lock.release()
