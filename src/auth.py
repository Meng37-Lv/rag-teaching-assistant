from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from src.migrations import migrate_accounts


SESSION_TTL_SECONDS = 8 * 60 * 60
PASSWORD_ITERATIONS = 600_000


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = secrets.token_bytes(16) if salt is None else salt
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split('$')
        if algorithm != 'pbkdf2_sha256':
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


class AccountStore:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        migrate_accounts(self.db_path)

    def connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        return connection

    def register(self, name: str, phone: str, password: str, confirmation: str):
        if not name.strip() or not phone.strip() or not password or not confirmation:
            raise HTTPException(400, '账户名称、手机号、密码和确认密码全部必填。')
        if password != confirmation:
            raise HTTPException(400, '两次输入的密码不一致。')
        phone = phone.strip()
        if not re.fullmatch(r'[0-9]{11}', phone):
            raise HTTPException(400, '请输入11位手机号。')
        if len(name.strip()) > 100 or len(password.encode('utf-8')) > 4096:
            raise HTTPException(400, '账户名称或密码超过支持长度。')
        account = dict(account_id=str(uuid4()), account_name=name.strip(), phone=phone)
        connection = self.connect()
        try:
            with connection:
                connection.execute('INSERT INTO accounts VALUES (?, ?, ?, ?, ?)',
                    (account['account_id'], account['account_name'], phone, password_hash(password), datetime.now(timezone.utc).isoformat()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, '该手机号已注册，请登录。') from None
        finally:
            connection.close()
        return account

    def login(self, phone: str, password: str):
        if not phone.strip() or not password:
            raise HTTPException(400, '手机号和密码必填。')
        connection = self.connect()
        try:
            row = connection.execute('SELECT * FROM accounts WHERE phone = ?', (phone.strip(),)).fetchone()
            # Equal work for an unknown phone; never reveal account existence here.
            stored = row['password_hash'] if row else password_hash('unknown', b'\0' * 16)
            valid = verify_password(password, stored)
            if row is None or not valid:
                raise HTTPException(401, '手机号或密码错误。')
            token = secrets.token_urlsafe(32)
            now = int(time.time())
            with connection:
                connection.execute('INSERT INTO account_sessions VALUES (?, ?, ?, ?)',
                    (hashlib.sha256(token.encode()).hexdigest(), row['account_id'], now + SESSION_TTL_SECONDS, now))
            return dict(token=token, expires_at=now + SESSION_TTL_SECONDS,
                        account={key: row[key] for key in ('account_id', 'account_name', 'phone')})
        finally:
            connection.close()

    def current(self, token: str):
        connection = self.connect()
        try:
            row = connection.execute('''SELECT a.account_id, a.account_name, a.phone, s.expires_at
                FROM account_sessions s JOIN accounts a ON a.account_id = s.account_id
                WHERE s.token_hash = ?''', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            if row is None or row['expires_at'] <= int(time.time()):
                raise HTTPException(401, '登录已过期或失效，请重新登录。')
            return {key: row[key] for key in ('account_id', 'account_name', 'phone')}
        finally:
            connection.close()

    def logout(self, token: str):
        connection = self.connect()
        try:
            with connection:
                connection.execute('DELETE FROM account_sessions WHERE token_hash = ?', (hashlib.sha256(token.encode()).hexdigest(),))
        finally:
            connection.close()

    def owns(self, account_id: str, course_id: str) -> bool:
        connection = self.connect()
        try:
            return connection.execute('SELECT 1 FROM course_ownership WHERE account_id = ? AND course_id = ?', (account_id, course_id)).fetchone() is not None
        finally:
            connection.close()

    def assign_legacy(self, account_id: str, course_ids: list[str]):
        """Explicit local operator action only; no registration/HTTP claim path."""
        connection = self.connect()
        try:
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                if connection.execute('SELECT 1 FROM accounts WHERE account_id = ?', (account_id,)).fetchone() is None:
                    raise ValueError('账户不存在')
                for course_id in course_ids:
                    if connection.execute('SELECT 1 FROM courses WHERE id = ?', (course_id,)).fetchone() is None:
                        raise ValueError('课程不存在')
                    owner = connection.execute('SELECT account_id FROM course_ownership WHERE course_id = ?', (course_id,)).fetchone()
                    if owner and owner[0] != account_id:
                        raise ValueError('课程已归属其他账户，不能覆盖')
                    connection.execute('INSERT OR IGNORE INTO course_ownership VALUES (?, ?)', (course_id, account_id))
        finally:
            connection.close()


def get_accounts(request: Request) -> AccountStore:
    from src.course_data import get_course_store
    provider = request.app.dependency_overrides.get(get_course_store, get_course_store)
    return AccountStore(provider().db_path)


def _token(request: Request) -> str:
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer ') or not header[7:]:
        raise HTTPException(401, '请先登录。')
    return header[7:]


PUBLIC_API = {'/api/health', '/api/auth/register', '/api/auth/login', '/api/auth/ui-config'}


async def require_business_access(request: Request):
    if not request.url.path.startswith('/api/') or request.url.path in PUBLIC_API:
        return
    accounts = get_accounts(request)
    request.state.account = accounts.current(_token(request))
    course_id = request.path_params.get('course_id')
    if request.method in {'POST', 'PUT', 'PATCH'} and course_id is None:
        content_type = request.headers.get('content-type', '')
        if content_type.startswith('application/json'):
            try:
                body = await request.json()
            except ValueError:
                raise HTTPException(400, '请求内容格式错误。') from None
            if isinstance(body, dict):
                course_id = body.get('course_id')
        elif content_type.startswith(('multipart/form-data', 'application/x-www-form-urlencoded')):
            course_id = (await request.form()).get('course_id')
    if course_id is not None and (not isinstance(course_id, str) or not accounts.owns(request.state.account['account_id'], course_id)):
        raise HTTPException(404, '课程不存在或无权访问。')


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    account_name: str
    phone: str
    password: str
    confirm_password: str


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    phone: str
    password: str


router = APIRouter(prefix='/api/auth', tags=['accounts'])


@router.post('/register', status_code=201)
def register(payload: RegisterRequest, accounts: AccountStore = Depends(get_accounts)):
    account = accounts.register(payload.account_name, payload.phone, payload.password, payload.confirm_password)
    return {'message': '注册成功，请登录', 'account': account}


@router.post('/login')
def login(payload: LoginRequest, accounts: AccountStore = Depends(get_accounts)):
    return accounts.login(payload.phone, payload.password)


@router.get('/me')
def me(request: Request):
    return request.state.account


@router.post('/logout')
def logout(request: Request, accounts: AccountStore = Depends(get_accounts)):
    accounts.logout(_token(request))
    return {'message': '已退出登录'}


@router.get('/ui-config')
def ui_config():
    url = os.getenv('SCHOOL_AERIAL_IMAGE_URL', '').strip()
    # Only an intentionally configured public image URL/path is exposed.
    valid = url.startswith(('https://', '/')) and not url.startswith('//')
    return {'school_image_url': url if valid else ''}
