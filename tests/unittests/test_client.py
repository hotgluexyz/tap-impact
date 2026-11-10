import unittest
from unittest.mock import MagicMock, patch
import requests
from urllib.parse import urlparse

from tap_impact.client import (
    get_exception_for_error_code,
    raise_for_error,
    ImpactBadRequestError,
    ImpactUnauthorizedError,
    ImpactForbiddenError,
    ImpactNotFoundError,
    ImpactMethodNotAllowedError,
    ImpactConflictError,
    ImpactUnprocessableEntityError,
    ImpactInternalServiceError,
    ImpactUnknownError,
    ImpactError,
    ImpactClient,
    Server5xxError,
    ERROR_CODE_EXCEPTION_MAPPING,
)


class TestGetExceptionForErrorCode(unittest.TestCase):
    """Tests for get_exception_for_error_code()."""

    def test_400_returns_bad_request(self):
        self.assertIs(get_exception_for_error_code(400), ImpactBadRequestError)

    def test_401_returns_unauthorized(self):
        self.assertIs(get_exception_for_error_code(401), ImpactUnauthorizedError)

    def test_402_returns_request_failed(self):
        from tap_impact.client import ImpactRequestFailedError
        self.assertIs(get_exception_for_error_code(402), ImpactRequestFailedError)

    def test_403_returns_forbidden(self):
        self.assertIs(get_exception_for_error_code(403), ImpactForbiddenError)

    def test_404_returns_not_found(self):
        self.assertIs(get_exception_for_error_code(404), ImpactNotFoundError)

    def test_405_returns_method_not_allowed(self):
        self.assertIs(get_exception_for_error_code(405), ImpactMethodNotAllowedError)

    def test_409_returns_conflict(self):
        self.assertIs(get_exception_for_error_code(409), ImpactConflictError)

    def test_422_returns_unprocessable(self):
        self.assertIs(get_exception_for_error_code(422), ImpactUnprocessableEntityError)

    def test_500_returns_internal(self):
        self.assertIs(get_exception_for_error_code(500), ImpactInternalServiceError)

    def test_520_returns_unknown(self):
        self.assertIs(get_exception_for_error_code(520), ImpactUnknownError)

    def test_unmapped_code_returns_base_error(self):
        self.assertIs(get_exception_for_error_code(999), ImpactError)

    def test_all_mapped_codes_present(self):
        """Ensure the ERROR_CODE_EXCEPTION_MAPPING covers the expected set of codes."""
        expected_codes = {400, 401, 402, 403, 404, 405, 409, 422, 500, 520}
        self.assertEqual(set(ERROR_CODE_EXCEPTION_MAPPING.keys()), expected_codes)


class TestRaiseForError(unittest.TestCase):
    """Tests for raise_for_error()."""

    def _make_response(self, status_code, json_body=None, content=b"error", reason="Error"):
        resp = MagicMock()
        resp.status_code = status_code
        resp.reason = reason
        resp.text = str(json_body)
        resp.content = content
        if json_body is not None:
            resp.json.return_value = json_body
            resp.raise_for_status.side_effect = requests.HTTPError(
                response=resp
            )
        else:
            resp.raise_for_status.side_effect = requests.HTTPError(
                response=resp
            )
        return resp

    def test_empty_content_raises_mapped_exception(self):
        resp = self._make_response(500, content=b"")
        resp.json.side_effect = ValueError("No JSON")
        with self.assertRaises(ImpactInternalServiceError):
            raise_for_error(resp)

    def test_impact_access_denied_body_raises_forbidden(self):
        body = {"status": 403, "title": "Access Denied"}
        resp = self._make_response(403, json_body=body)
        with self.assertRaisesRegex(ImpactForbiddenError, "Access Denied"):
            raise_for_error(resp)

    def test_http_status_determines_exception_for_different_bodies(self):
        bodies = [
            {"error": "Forbidden", "message": "No access"},
            {"error": "Forbidden", "status": "403"},
            {"error": "Forbidden", "status": 401},
            {}, [], None, "Forbidden",
        ]
        for body in bodies:
            with self.subTest(body=body):
                resp = self._make_response(403, json_body=body)
                with self.assertRaises(ImpactForbiddenError):
                    raise_for_error(resp)

    def test_non_json_forbidden_raises_forbidden(self):
        resp = self._make_response(403, content=b"Forbidden")
        resp.json.side_effect = ValueError("No JSON")
        with self.assertRaises(ImpactForbiddenError):
            raise_for_error(resp)

    def test_unauthorized_without_error_field_is_not_forbidden(self):
        resp = self._make_response(401, json_body={"title": "Unauthorized"})
        with self.assertRaises(ImpactUnauthorizedError):
            raise_for_error(resp)

    def test_json_error_field_raises_mapped_exception(self):
        body = {"error": "Unauthorized", "message": "Invalid credentials", "status": 401}
        resp = self._make_response(401, json_body=body)
        with self.assertRaises(ImpactUnauthorizedError):
            raise_for_error(resp)

    def test_json_errorCode_field_raises_mapped_exception(self):
        body = {"errorCode": "NOT_FOUND", "message": "Resource not found", "status": 404}
        resp = self._make_response(404, json_body=body)
        with self.assertRaises(ImpactNotFoundError):
            raise_for_error(resp)

    def test_json_without_error_key_raises_base_impact_error(self):
        body = {"someOtherKey": "value"}
        resp = self._make_response(500, json_body=body)
        with self.assertRaises(ImpactError):
            raise_for_error(resp)

    def test_non_json_body_raises_impact_error(self):
        resp = self._make_response(503, content=b"<html>Service Unavailable</html>")
        resp.json.side_effect = ValueError("No JSON")
        with self.assertRaises(ImpactError):
            raise_for_error(resp)


class TestImpactClientInit(unittest.TestCase):
    """Tests for ImpactClient construction — no network calls."""

    def test_base_url_construction(self):
        client = ImpactClient(
            account_sid="ACCT123",
            auth_token="TOKEN456",
            api_catalog="Advertisers",
        )
        self.assertIn("ACCT123", client.base_url)
        self.assertIn("Advertisers", client.base_url)

    def test_base_url_contains_api_host(self):
        client = ImpactClient(
            account_sid="ACCT",
            auth_token="TOK",
            api_catalog="Partners",
        )
        parsed = urlparse(client.base_url)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.hostname, "api.impact.com")

    def test_different_api_catalog(self):
        client1 = ImpactClient("A", "T", "Advertisers")
        client2 = ImpactClient("A", "T", "Partners")
        self.assertNotEqual(client1.base_url, client2.base_url)


class TestImpactClientAccess(unittest.TestCase):
    def _make_response(self, status_code):
        resp = requests.Response()
        resp.status_code = status_code
        resp._content = b'{"title":"Access Denied"}'
        return resp

    @patch('tap_impact.client.requests.Session')
    def test_forbidden_credentials_fail_at_startup(self, session):
        session.return_value.get.return_value = self._make_response(403)
        with self.assertRaises(ImpactForbiddenError):
            with ImpactClient('ACCT', 'TOKEN', 'Advertisers'):
                pass
        session.return_value.get.assert_called_once()
        session.return_value.request.assert_not_called()

    @patch('tap_impact.client.requests.Session')
    def test_invalid_credentials_still_fail_at_startup(self, session):
        session.return_value.get.return_value = self._make_response(401)
        with self.assertRaises(ImpactUnauthorizedError):
            with ImpactClient('ACCT', 'TOKEN', 'Advertisers'):
                pass
        session.return_value.get.assert_called_once()
        session.return_value.request.assert_not_called()

    @patch('backoff._sync.time.sleep')
    @patch('tap_impact.client.requests.Session')
    def test_startup_retries_server_errors_until_success(self, session, sleep):
        for status in [500, 503, 520]:
            with self.subTest(status=status):
                session.return_value.get.reset_mock()
                sleep.reset_mock()
                session.return_value.get.side_effect = [
                    self._make_response(status), self._make_response(200),
                ]

                with ImpactClient('ACCT', 'TOKEN', 'Advertisers'):
                    pass

                self.assertEqual(session.return_value.get.call_count, 2)
                sleep.assert_called_once()

    @patch('backoff._sync.time.sleep')
    @patch('tap_impact.client.requests.Session')
    def test_startup_stops_after_seven_server_errors(self, session, sleep):
        response = self._make_response(503)
        response._content = b''
        session.return_value.get.return_value = response

        with self.assertRaises(Server5xxError):
            with ImpactClient('ACCT', 'TOKEN', 'Advertisers'):
                pass

        self.assertEqual(session.return_value.get.call_count, 7)
        self.assertEqual(sleep.call_count, 6)
