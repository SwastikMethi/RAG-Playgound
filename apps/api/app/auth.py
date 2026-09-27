"""Hosted accounts and request credentials. Raw secrets never enter public schemas."""
import hashlib
import hmac
import re
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from cryptography.exceptions import InvalidKey
from cryptography.fernet import InvalidToken
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from fastapi import APIRouter, Request, Response
from sqlalchemy import delete, select, text

from rag_runtime.contracts import request as check_request
from rag_runtime.errors import Problem
from .connections import cipher
from .models import AuthRate, AuthSession, User

router = APIRouter(prefix="/api/v1")
COOKIE = "__Host-rag-session"
PUBLIC = {"/api/v1/health", "/api/v1/auth/me", "/api/v1/auth/register", "/api/v1/auth/login", "/api/v1/auth/recover"}


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def csrf(settings, token):
    return hmac.new(settings.master_key.get_secret_value().encode(), token.encode(), "sha256").hexdigest()


def hash_password(value):
    return Argon2id(salt=secrets.token_bytes(16), length=32, iterations=2, lanes=1,
                   memory_cost=19456).derive_phc_encoded(value.encode())


def matches_password(value, encoded):
    try:
        Argon2id.verify_phc_encoded(value.encode(), encoded)
        return True
    except (InvalidKey, ValueError):
        return False


def username(value):
    value = value.lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,31}", value):
        raise Problem("VALIDATION_ERROR", "Use 3–32 letters, numbers, underscores or hyphens for your username.")
    return value


def public_user(user):
    return {"id": user.id, "username": user.username}


def active_session(store, s, token):
    session = s.get(AuthSession, token_hash(token)) if token and len(token) <= 128 else None
    if not session or session.expires_at <= store.now(s):
        raise Problem("UNAUTHENTICATED", "Sign in to continue.", 401)
    return session


def request_identity(request):
    settings, store = request.app.state.settings, request.app.state.store
    request.state.store, request.state.profiles, request.state.user = store, request.app.state.profiles, None
    if settings.deployment != "hosted":
        return
    token = request.cookies.get(COOKIE, "")
    if not token and request.url.path in PUBLIC:
        return
    with store.session() as s:
        try:
            session = active_session(store, s, token)
        except Problem:
            if request.url.path not in PUBLIC:
                raise
            return
        user = s.get(User, session.user_id)
        request.state.user = public_user(user)
        request.state.store = store.for_user(user.id, token_hash(token))
        request.state.profiles = user_profiles(settings, request.app.state.profiles, user)
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path not in PUBLIC:
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), csrf(settings, token)):
            raise Problem("FORBIDDEN", "Reload the page and try again.", 403)


def user_profiles(settings, profiles, user):
    if settings.deployment != "hosted":
        return profiles
    key = ""
    if user and user.encrypted_openai_key:
        try:
            key = cipher(settings).decrypt(user.encrypted_openai_key.encode()).decode()
        except InvalidToken:
            raise Problem("MASTER_KEY_INVALID", "The saved provider credential cannot be decrypted.", 503) from None
    return {id: p.with_key(key) for id, p in profiles.items()}


def throttle(request, name, action):
    store = request.app.state.store
    # Serialize short counter updates across all API processes, including failures.
    exceeded = False
    with store.session() as s:
        s.execute(text("SELECT pg_advisory_xact_lock(71234003)"))
        now = store.now(s)
        s.execute(delete(AuthRate).where(AuthRate.expires_at <= now))
        s.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
        ip = request.client.host if request.client else "unknown"
        for identity, maximum in [("ip:" + ip, 30), ("user:" + name, 5)]:
            bucket = token_hash(action + ":" + identity)
            row = s.get(AuthRate, bucket)
            if not row:
                row = AuthRate(bucket=bucket, attempts=0, expires_at=now + timedelta(minutes=15))
                s.add(row)
            row.attempts += 1
            exceeded |= row.attempts > maximum
    if exceeded:
        raise Problem("RATE_LIMITED", "Too many attempts. Try again in 15 minutes.", 429)


async def verify_challenge(request, token):
    settings = request.app.state.settings
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False) as client:
            response = await client.post("https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={"secret": settings.turnstile_secret_key.get_secret_value(), "response": token})
            response.raise_for_status()
            data = response.json()
        if (isinstance(data, dict) and data.get("success") is True and data.get("hostname") == urlsplit(settings.public_origin).hostname
                and data.get("action") == request.url.path.rsplit("/", 1)[-1]):
            return
    except (httpx.HTTPError, ValueError):
        pass
    raise Problem("CHALLENGE_FAILED", "Complete the security check and try again.", 403)


def require_hosted(request):
    if request.app.state.settings.deployment != "hosted":
        raise Problem("NOT_FOUND", "Accounts are only enabled in hosted mode.", 404)


def issue_session(request, response, s, user):
    token = secrets.token_urlsafe(32)
    s.add(AuthSession(token_hash=token_hash(token), user_id=user.id,
                      expires_at=request.app.state.store.now(s) + timedelta(days=7)))
    response.set_cookie(COOKIE, token, max_age=7 * 86400, secure=True, httponly=True, samesite="lax", path="/")
    return {"user": public_user(user), "csrf_token": csrf(request.app.state.settings, token)}


@router.get("/auth/me")
def me(request: Request):
    settings = request.app.state.settings
    return {"deployment": settings.deployment, "user": request.state.user,
            "csrf_token": csrf(settings, request.cookies[COOKIE]) if request.state.user else None,
            "turnstile_site_key": settings.turnstile_site_key if settings.deployment == "hosted" else None}


@router.post("/auth/register", status_code=201)
async def register(body: dict, request: Request, response: Response):
    require_hosted(request)
    check_request(body, "RegisterAccount")
    name = username(body["username"])
    throttle(request, name, "register")
    await verify_challenge(request, body["turnstile_token"])
    encoded, recovery = hash_password(body["password"]), secrets.token_urlsafe(32)
    store = request.app.state.store
    with store.session() as s:
        s.execute(text("SELECT pg_advisory_xact_lock(71234004)"))
        if s.scalar(select(User).where(User.username == name)):
            raise Problem("USERNAME_UNAVAILABLE", "Choose a different username.", 409)
        user = User(username=name, password_hash=encoded, recovery_hash=token_hash(recovery))
        s.add(user)
        s.flush()
        return dict(issue_session(request, response, s, user), recovery_code=recovery)


@router.post("/auth/login")
async def login(body: dict, request: Request, response: Response):
    require_hosted(request)
    check_request(body, "LoginAccount")
    name = body["username"].lower()
    throttle(request, name, "login")
    await verify_challenge(request, body["turnstile_token"])
    store = request.app.state.store
    with store.session() as s:
        user = s.scalar(select(User).where(User.username == name).with_for_update())
        # Do the expensive check for unknown accounts too.
        encoded = user.password_hash if user else request.app.state.dummy_password_hash
        valid = matches_password(body["password"], encoded)
        if not user or not valid:
            raise Problem("INVALID_CREDENTIALS", "The username or password is incorrect.", 401)
        return issue_session(request, response, s, user)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response):
    require_hosted(request)
    with request.app.state.store.session() as s:
        s.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(request.cookies.get(COOKIE, ""))))
    response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="lax", path="/")


@router.post("/auth/recover")
async def recover(body: dict, request: Request, response: Response):
    require_hosted(request)
    check_request(body, "RecoverAccount")
    name = body["username"].lower()
    throttle(request, name, "recover")
    await verify_challenge(request, body["turnstile_token"])
    store = request.app.state.store
    with store.session() as s:
        user = s.scalar(select(User).where(User.username == name).with_for_update())
        if not user or not hmac.compare_digest(user.recovery_hash, token_hash(body["recovery_code"])):
            raise Problem("INVALID_CREDENTIALS", "The username or recovery code is incorrect.", 401)
        recovery = secrets.token_urlsafe(32)
        user.password_hash, user.recovery_hash = hash_password(body["password"]), token_hash(recovery)
        s.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        return dict(issue_session(request, response, s, user), recovery_code=recovery)


@router.post("/auth/password")
def change_password(body: dict, request: Request, response: Response):
    require_hosted(request)
    check_request(body, "ChangePassword")
    throttle(request, request.state.user["id"], "password")
    with request.state.store.session() as s:
        user = s.get(User, request.state.user["id"], with_for_update=True)
        if not matches_password(body["current_password"], user.password_hash):
            raise Problem("INVALID_CREDENTIALS", "The current password is incorrect.", 401)
        user.password_hash = hash_password(body["password"])
        s.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        return issue_session(request, response, s, user)


@router.get("/me/openai-key")
def key_status(request: Request):
    require_hosted(request)
    with request.state.store.session() as s:
        return {"configured": bool(s.get(User, request.state.user["id"]).encrypted_openai_key)}


@router.put("/me/openai-key", status_code=204)
def save_key(body: dict, request: Request):
    require_hosted(request)
    check_request(body, "SaveOpenAIKey")
    with request.state.store.session() as s:
        user = s.get(User, request.state.user["id"], with_for_update=True)
        user.encrypted_openai_key = cipher(request.app.state.settings).encrypt(body["api_key"].encode()).decode()


@router.delete("/me/openai-key", status_code=204)
def remove_key(request: Request):
    require_hosted(request)
    with request.state.store.session() as s:
        s.get(User, request.state.user["id"], with_for_update=True).encrypted_openai_key = None
