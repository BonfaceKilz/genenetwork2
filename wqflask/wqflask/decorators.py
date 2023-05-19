"""This module contains gn2 decorators"""
import json
import requests
from functools import wraps
from urllib.parse import urljoin
from typing import Dict, Callable

import redis
from flask import g, flash, request, url_for, redirect, current_app

from gn3.authentication import AdminRole
from gn3.authentication import DataRole

from wqflask.oauth2 import client
from wqflask.oauth2.session import session_info
from wqflask.oauth2.request_utils import process_error


def login_required(f):
    """Use this for endpoints where login is required"""
    @wraps(f)
    def wrap(*args, **kwargs):
        user_id = ((g.user_session.record.get(b"user_id") or
                    b"").decode("utf-8")
                   or g.user_session.record.get("user_id") or "")
        redis_conn = redis.from_url(current_app.config["REDIS_URL"],
                                    decode_responses=True)
        if not redis_conn.hget("users", user_id):
            return "You need to be logged in!", 401
        return f(*args, **kwargs)
    return wrap


def edit_access_required(f):
    """Use this for endpoints where people with admin or edit privileges
are required"""
    @wraps(f)
    def wrap(*args, **kwargs):
        resource_id: str = ""
        if request.args.get("resource-id"):
            resource_id = request.args.get("resource-id")
        elif kwargs.get("resource_id"):
            resource_id = kwargs.get("resource_id")
        response: Dict = {}
        try:
            user_id = ((g.user_session.record.get(b"user_id") or
                        b"").decode("utf-8")
                       or g.user_session.record.get("user_id") or "")
            response = json.loads(
                requests.get(urljoin(
                    current_app.config.get("GN2_PROXY"),
                    ("available?resource="
                     f"{resource_id}&user={user_id}"))).content)
        except:
            response = {}
        if max([DataRole(role) for role in response.get(
                "data", ["no-access"])]) < DataRole.EDIT:
            return redirect(url_for("no_access_page"))
        return f(*args, **kwargs)
    return wrap


def edit_admins_access_required(f):
    """Use this for endpoints where ownership of a resource is required"""
    @wraps(f)
    def wrap(*args, **kwargs):
        resource_id: str = kwargs.get("resource_id", "")
        response: Dict = {}
        try:
            user_id = ((g.user_session.record.get(b"user_id") or
                        b"").decode("utf-8")
                       or g.user_session.record.get("user_id") or "")
            response = json.loads(
                requests.get(urljoin(
                    current_app.config.get("GN2_PROXY"),
                    ("available?resource="
                     f"{resource_id}&user={user_id}"))).content)
        except:
            response = {}
        if max([AdminRole(role) for role in response.get(
                "admin", ["not-admin"])]) < AdminRole.EDIT_ADMINS:
            return redirect(url_for("no_access_page"))
        return f(*args, **kwargs)
    return wrap

class AuthorisationError(Exception):
    """Raise when there is an authorisation issue."""
    def __init__(self, description, user):
        self.description = description
        self.user = user
        super().__init__(self, description, user)

def required_access(access_levels: tuple[str, ...],
                    dataset_key: str = "dataset_name",
                    trait_key: str = "name") -> Callable:
    def __build_access_checker__(func: Callable):
        @wraps(func)
        def __checker__(*args, **kwargs):
            def __error__(err):
                error = process_error(err)
                raise AuthorisationError(
                    f"{error['error']}: {error['error_description']}",
                    session_info()["user"])

            def __success__(priv_info):
                if all(priv in priv_info[0]["privileges"] for priv in access_levels):
                    return func(*args, **kwargs)
                missing = tuple(f"'{priv}'" for priv in access_levels
                                if priv not in priv_info[0]["privileges"])
                raise AuthorisationError(
                    f"Missing privileges: {', '.join(missing)}",
                    session_info()["user"])
            dataset_name = kwargs.get(
                dataset_key,
                request.args.get(dataset_key, request.form.get(dataset_key, "")))
            trait_name = kwargs.get(
                trait_key,
                request.args.get(trait_key, request.form.get(trait_key, "")))
            return client.post(
                "oauth2/data/authorisation",
                json={"traits": [f"{dataset_name}::{trait_name}"]}).either(
                    __error__, __success__)
        return __checker__
    return __build_access_checker__
