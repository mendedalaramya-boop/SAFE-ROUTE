"""
Standard API Response Helpers
================================
Every endpoint in SafeRoute should return responses in a consistent
shape so that API consumers (and Postman tests) can rely on it:

Success:
    {
        "success": true,
        "message": "...",
        "data": { ... }
    }

Error:
    {
        "success": false,
        "message": "...",
        "error": "SOME_ERROR_CODE"
    }

Using small helper functions here (instead of building the dict
inline in every route) keeps every endpoint consistent and makes it
trivial to change the response envelope later in one place.
"""

from flask import jsonify


def success_response(message: str = "Success", data=None, status_code: int = 200):
    payload = {
        "success": True,
        "message": message,
        "data": data if data is not None else {},
    }
    return jsonify(payload), status_code


def error_response(message: str, error_code: str, status_code: int = 400):
    payload = {
        "success": False,
        "message": message,
        "error": error_code,
    }
    return jsonify(payload), status_code
