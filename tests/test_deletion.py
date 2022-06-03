#
# Copyright Elasticsearch B.V. and/or licensed to Elasticsearch B.V. under one
# or more contributor license agreements. Licensed under the Elastic License 2.0;
# you may not use this file except in compliance with the Elastic License 2.0.
#
import argparse
import logging
import os
import sys
from unittest.mock import MagicMock, Mock

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ees_zoom.configuration import Configuration  # noqa
from ees_zoom.deletion_sync_command import DeletionSyncCommand  # noqa
from ees_zoom.sync_zoom import SyncZoom  # noqa
from ees_zoom.zoom_client import ZoomClient  # noqa

USERS = "users"
MEETINGS = "meetings"
GROUPS = "groups"
CHANNELS = "channels"
AUTH_BASE_URL = "https://zoom.us/oauth/token?grant_type="

CONFIG_FILE = os.path.join(
    os.path.join(os.path.dirname(__file__), "config"),
    "zoom_connector.yml",
)

SECRETS_JSON_PATH = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    "ees_zoom",
    "secrets.json",
)


def settings(requests_mock):
    """This function loads configuration from the file and returns it,
    it also mocks the zoom refresh token generation API response.
    :param requests_mock: fixture for requests.get calls.
    :returns configuration: Configuration instance
    :returns logger: Logger instance
    """
    configuration = Configuration(file_name=CONFIG_FILE)
    if os.path.exists(SECRETS_JSON_PATH):
        os.remove(SECRETS_JSON_PATH)
    logger = logging.getLogger("unit_test_deletion_sync")
    new_refresh_token = "new_dummy_refresh_token"
    old_refresh_token = "old_dummy_refresh_token"
    access_token = "dummy_access_token"
    json_response = {"refresh_token": new_refresh_token, "access_token": access_token}
    zoom_client_object = ZoomClient(configuration, logger)
    zoom_client_object.secrets_storage.get_refresh_token = MagicMock(
        return_value=old_refresh_token
    )
    url = (
        AUTH_BASE_URL
        + f"authorization_code&code={zoom_client_object.authorization_code}"
        f"&redirect_uri={zoom_client_object.redirect_uri}"
    )
    headers = zoom_client_object.get_headers()
    requests_mock.post(
        url,
        headers=headers,
        json=json_response,
        status_code=200,
    )
    return configuration, logger


@pytest.mark.parametrize(
    "deleted_ids, storage_with_collection, updated_storage_with_collection",
    [
        (
            ["844424930334011", "543528180028451862"],
            {
                "global_keys": [
                    {"id": "844424930334011"},
                    {"id": "543528180028451862"},
                ],
                "delete_keys": [
                    {"id": "844424930334011"},
                    {"id": "543528180028451862"},
                ],
            },
            {
                "global_keys": [],
                "delete_keys": [
                    {"id": "844424930334011"},
                    {"id": "543528180028451862"},
                ],
            },
        )
    ],
)
def test_delete_documents(
    requests_mock,
    deleted_ids,
    storage_with_collection,
    updated_storage_with_collection,
):
    """Test that deletion_sync_command deletes objects from Enterprise Search.
    :param requests_mock: fixture for requests.get calls.
    :param deleted_ids: list of deleted documents ids from zoom.
    :param storage_with_collection: objects documents dictionary.
    :param updated_storage_with_collection: updated objects documents dictionary.
    """
    _, _ = settings(requests_mock)
    args = argparse.Namespace()
    args.config_file = CONFIG_FILE
    deletion_sync_obj = DeletionSyncCommand(args)
    deletion_sync_obj.workplace_search_client.delete_documents = Mock()
    deletion_sync_obj.zoom_client.get_token()
    assert (
        deletion_sync_obj.delete_documents(deleted_ids, storage_with_collection)
        == updated_storage_with_collection
    )


@pytest.mark.parametrize(
    "meeting_id_list, deletion_response",
    [
        (
            ["844424930334011"],
            {"code": 1001, "message": "Meeting does not exist: 844424930334011."},
        )
    ],
)
def test_collect_deleted_ids_for_meetings_positive(
    requests_mock,
    meeting_id_list,
    deletion_response,
):
    """Test that deletion_sync_command deletes meetings object from Enterprise Search.
    :param requests_mock: fixture for requests.get calls.
    :param meeting_id_list: list of meeting_id deleted from zoom.
    :param deletion_response: dictionary of mocked api response.
    """
    config, _ = settings(requests_mock)
    args = argparse.Namespace()
    args.config_file = CONFIG_FILE
    deletion_sync_obj = DeletionSyncCommand(args)
    headers = {
        "authorization": "Bearer dummy_access_token",
        "content-type": "application/json",
    }
    requests_mock.get(
        "https://api.zoom.us/v2/meetings/844424930334011",
        headers=headers,
        json=deletion_response,
        status_code=404,
    )
    deletion_sync_obj.zoom_client.get_token()
    deletion_sync_obj.collect_deleted_ids(meeting_id_list, MEETINGS)
    assert meeting_id_list == deletion_sync_obj.global_deletion_ids


@pytest.mark.parametrize(
    "meeting_id_list, deletion_response",
    [
        (
            ["844424930334011"],
            {
                "id": "844424930334011",
                "type": "meetings",
            },
        )
    ],
)
def test_collect_deleted_ids_for_meetings_negative(
    requests_mock,
    meeting_id_list,
    deletion_response,
):
    """Test that deletion_sync_command won't delete meetings object from Enterprise Search if it exist in Zoom.
    :param requests_mock: fixture for requests.get calls.
    :param meeting_id_list: list of meeting_id deleted from zoom.
    :param deletion_response: dictionary of mocked api response.
    """
    _, _ = settings(requests_mock)
    args = argparse.Namespace()
    args.config_file = CONFIG_FILE
    deletion_sync_obj = DeletionSyncCommand(args)
    headers = {
        "authorization": "Bearer dummy_access_token",
        "content-type": "application/json",
    }
    requests_mock.get(
        "https://api.zoom.us/v2/meetings/844424930334011",
        headers=headers,
        json=deletion_response,
        status_code=200,
    )
    deletion_sync_obj.zoom_client.get_token()
    deletion_sync_obj.collect_deleted_ids(meeting_id_list, MEETINGS)
    assert [] == deletion_sync_obj.global_deletion_ids


@pytest.mark.parametrize(
    "past_meeting_id_list, delete_key_list, deletion_response",
    [
        (
            ["844424930334011"],
            [
                {
                    "id": "dummy1234",
                    "type": "past_meetings",
                    "parent_id": "844424930334011",
                    "created_at": "",
                }
            ],
            {"code": 1001, "message": "Role does not exist: 844424930334011."},
        )
    ],
)
def test_collect_deleted_past_meetings_positive(
    requests_mock,
    past_meeting_id_list,
    delete_key_list,
    deletion_response,
):
    """Test that deletion_sync_command deletes past_meetings object from Enterprise Search.
    :param requests_mock: fixture for requests.get calls.
    :param past_meeting_id_list: list of past_meeting_id deleted from zoom.
    :param delete_key_list: list of dictionary of delete_keys exist in doc_id storage.
    :param deletion_response: dictionary of mocked api response.
    """
    _, _ = settings(requests_mock)
    args = argparse.Namespace()
    args.config_file = CONFIG_FILE
    deletion_sync_obj = DeletionSyncCommand(args)
    headers = {
        "authorization": "Bearer dummy_access_token",
        "content-type": "application/json",
    }
    requests_mock.get(
        "https://api.zoom.us/v2/past_meetings/844424930334011",
        headers=headers,
        json=deletion_response,
        status_code=404,
    )
    deletion_sync_obj.zoom_client.get_token()
    deletion_sync_obj.collect_deleted_past_meetings(
        past_meeting_id_list, delete_key_list
    )
    assert [delete_key_list[0]["id"]] == deletion_sync_obj.global_deletion_ids


@pytest.mark.parametrize(
    "past_meeting_id_list, delete_key_list, deletion_response",
    [
        (
            ["844424930334011"],
            [
                {
                    "id": "dummy1234",
                    "type": "past_meetings",
                    "parent_id": "844424930334011",
                    "created_at": "",
                }
            ],
            {
                "id": "844424930334011",
                "type": "past_meetings",
            },
        )
    ],
)
def test_collect_deleted_past_meetings_negative(
    requests_mock,
    past_meeting_id_list,
    delete_key_list,
    deletion_response,
):
    """Test that deletion_sync_command won't delete past_meetings object from Enterprise Search if it exist in Zoom.
    :param requests_mock: fixture for requests.get calls.
    :param past_meeting_id_list: list of past_meeting_id deleted from zoom.
    :param delete_key_list: list of dictionary of delete_keys exist in doc_id storage.
    :param deletion_response: dictionary of mocked api response.
    """
    _, _ = settings(requests_mock)
    args = argparse.Namespace()
    args.config_file = CONFIG_FILE
    deletion_sync_obj = DeletionSyncCommand(args)
    headers = {
        "authorization": "Bearer dummy_access_token",
        "content-type": "application/json",
    }
    requests_mock.get(
        "https://api.zoom.us/v2/past_meetings/844424930334011",
        headers=headers,
        json=deletion_response,
        status_code=200,
    )
    deletion_sync_obj.zoom_client.get_token()
    deletion_sync_obj.collect_deleted_past_meetings(
        past_meeting_id_list, delete_key_list
    )
    assert [] == deletion_sync_obj.global_deletion_ids
