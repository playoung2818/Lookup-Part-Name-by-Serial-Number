"""SwitchBot Hub 2 readings: signed API v1.1 client, background recorder and chart data.

API: https://github.com/OpenWonderLabs/SwitchBotAPI. Every request is signed with
HMAC-SHA256(token + t + nonce, secret). The Hub 2 status has humidity (%), temperature (C)
and lightLevel (1-20). There is no history endpoint, so the app records a reading every
SWITCHBOT_POLL_SECONDS (default 300 = 288 of the 10,000 calls allowed per day) into the
climate_readings table. Credentials come from .env (SWITCHBOT_TOKEN, SWITCHBOT_SECRET).
"""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import logging
import threading
import time
import uuid

import requests
from sqlalchemy import MetaData, Table, insert, select

log = logging.getLogger(__name__)
API = 'https://api.switch-bot.com/v1.1'
RANGES = {'24h': (timedelta(hours=24), None), '7d': (timedelta(days=7), 1800), '30d': (timedelta(days=30), 3 * 3600)}


class SwitchBotError(RuntimeError):
    pass


def signed_headers(token, secret, now_ms=None, nonce=None):
    t = str(now_ms if now_ms is not None else int(time.time() * 1000))
    nonce = nonce or str(uuid.uuid4())
    digest = hmac.new(secret.encode(), f'{token}{t}{nonce}'.encode(), hashlib.sha256).digest()
    return {'Authorization': token, 'sign': base64.b64encode(digest).decode(), 't': t, 'nonce': nonce,
            'Content-Type': 'application/json; charset=utf8'}


def api_get(path, token, secret, session=requests):
    response = session.get(API + path, headers=signed_headers(token, secret), timeout=15)
    if response.status_code != 200:
        raise SwitchBotError(f'SwitchBot HTTP {response.status_code}')
    data = response.json()
    if data.get('statusCode') != 100:
        raise SwitchBotError(f"SwitchBot status {data.get('statusCode')}: {data.get('message')}")
    return data.get('body') or {}


def api_post(path, body, token, secret, session=requests):
    response = session.post(API + path, headers=signed_headers(token, secret), json=body, timeout=15)
    if response.status_code != 200:
        raise SwitchBotError(f'SwitchBot HTTP {response.status_code}')
    data = response.json()
    if data.get('statusCode') != 100:
        raise SwitchBotError(f"SwitchBot status {data.get('statusCode')}: {data.get('message')}")
    return data.get('body') or {}


def find_device(token, secret, device_type, device_id='', session=requests):
    """The configured device, or the first device of `device_type` on the account."""
    devices = api_get('/devices', token, secret, session).get('deviceList', [])
    found = [d for d in devices if d.get('deviceType') == device_type and (not device_id or d.get('deviceId') == device_id)]
    if not found:
        raise SwitchBotError(f'No {device_type} found on this SwitchBot account.')
    return {'id': found[0]['deviceId'], 'name': found[0].get('deviceName') or device_type}


def find_hub2(token, secret, device_id='', session=requests):
    return find_device(token, secret, 'Hub 2', device_id, session)


def read_hub2(device_id, token, secret, session=requests):
    body = api_get(f'/devices/{device_id}/status', token, secret, session)
    humidity = body.get('humidity')
    if not isinstance(humidity, (int, float)) or not 0 <= humidity <= 100:
        raise SwitchBotError('Hub 2 returned no valid humidity.')
    temperature = body.get('temperature')
    light = body.get('lightLevel')
    return {'humidity': int(round(humidity)),
            'temperature': float(temperature) if isinstance(temperature, (int, float)) else None,
            'light_level': int(light) if isinstance(light, (int, float)) else None}


def readings_table(engine):
    # Reflection only: the table is created by scripts/climate_readings.sql (approved DDL).
    return Table('climate_readings', MetaData(), autoload_with=engine)


def record_once(engine, token, secret, device, session=requests, now=None):
    reading = read_hub2(device['id'], token, secret, session)
    row = dict(reading, device_id=device['id'], device_name=device['name'],
               recorded_at=now or datetime.now(timezone.utc).replace(microsecond=0))
    with engine.begin() as connection:
        connection.execute(insert(readings_table(engine)).values(**row))
    return row


def as_utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def chart_data(engine, range_key='24h', now=None, ok_range=(40, 80)):
    """Latest reading plus points for the chart; 7d/30d are averaged into buckets."""
    span, bucket = RANGES.get(range_key, RANGES['24h'])
    now = now or datetime.now(timezone.utc)
    table = readings_table(engine)
    with engine.connect() as connection:
        latest = connection.execute(select(table).order_by(table.c.recorded_at.desc()).limit(1)).mappings().first()
        rows = connection.execute(select(table.c.recorded_at, table.c.humidity, table.c.temperature)
                                  .where(table.c.recorded_at > now - span)
                                  .order_by(table.c.recorded_at)).all()
    points = [(as_utc(at), humidity, temperature) for at, humidity, temperature in rows]
    if bucket:
        groups = {}
        for at, humidity, temperature in points:
            key = int(at.timestamp()) // bucket * bucket
            groups.setdefault(key, []).append((humidity, temperature))
        points = [(datetime.fromtimestamp(key + bucket / 2, timezone.utc),
                   round(sum(h for h, _ in values) / len(values), 1),
                   round(sum(t for _, t in values if t is not None) / max(1, sum(t is not None for _, t in values)), 1)
                   if any(t is not None for _, t in values) else None)
                  for key, values in sorted(groups.items())]
    low, high = ok_range
    result = {'range': range_key if range_key in RANGES else '24h', 'ok_range': [low, high],
              'points': [{'t': at.isoformat(), 'humidity': h, 'temperature': t} for at, h, t in points],
              'latest': None}
    if latest:
        at = as_utc(latest['recorded_at'])
        result['latest'] = {'humidity': latest['humidity'], 'temperature': latest['temperature'],
                            'light_level': latest['light_level'], 'device': latest['device_name'],
                            't': at.isoformat(), 'age_seconds': int((now - at).total_seconds()),
                            'in_range': low <= latest['humidity'] <= high}
    return result


# Evaporative Humidifier (deviceType Humidifier2). The public API has no water level.
HUMIDIFIER_MODES = {1: 'Level 4', 2: 'Level 3', 3: 'Level 2', 4: 'Level 1', 5: 'Target humidity',
                    6: 'Sleep', 7: 'Auto', 8: 'Drying'}


def parse_humidifier(body, name):
    filter_info = body.get('filterElement') or {}
    mode = body.get('mode')
    power = str(body.get('power') or '').lower()
    return {'device': name, 'power': power if power in ('on', 'off') else 'unknown',
            'mode': mode, 'mode_name': HUMIDIFIER_MODES.get(mode, 'Unknown'),
            'humidity': body.get('humidity'), 'drying': bool(body.get('drying')),
            'child_lock': bool(body.get('childLock')),
            'filter_used_hours': filter_info.get('usedHours'), 'filter_life_hours': filter_info.get('effectiveUsageHours'),
            'version': body.get('version')}


def humidifier_command(action, mode=None, target=None):
    """Validated SwitchBot command body for on / off / mode. Raises ValueError."""
    if action == 'on':
        return {'command': 'turnOn', 'parameter': 'default', 'commandType': 'command'}
    if action == 'off':
        return {'command': 'turnOff', 'parameter': 'default', 'commandType': 'command'}
    if action != 'mode':
        raise ValueError('Unknown humidifier action.')
    if type(mode) is not int or mode not in HUMIDIFIER_MODES:
        raise ValueError('Choose a valid humidifier mode.')
    parameter = {'mode': mode}
    if mode == 5 or target is not None:
        if type(target) is not int or not 0 <= target <= 100:
            raise ValueError('Target humidity must be a whole number from 0 to 100.')
        parameter['targetHumidify'] = target
    return {'command': 'setMode', 'parameter': parameter, 'commandType': 'command'}


class Humidifier:
    """Cached status (one SwitchBot call per `ttl` seconds, however many pages are open)
    and rate-limited commands."""

    def __init__(self, token, secret, device_id='', ttl=60, min_command_gap=3, session=requests):
        self.token, self.secret, self.device_id, self.session = token, secret, device_id, session
        self.ttl, self.min_command_gap = ttl, min_command_gap
        self.device, self._cached, self._cached_at, self._last_command = None, None, 0.0, 0.0
        self._lock = threading.Lock()

    def _device(self):
        if self.device is None:
            self.device = find_device(self.token, self.secret, 'Humidifier2', self.device_id, self.session)
        return self.device

    def status(self, force=False):
        with self._lock:
            if not force and self._cached and time.monotonic() - self._cached_at < self.ttl:
                return self._cached
            device = self._device()
            body = api_get(f"/devices/{device['id']}/status", self.token, self.secret, self.session)
            self._cached = dict(parse_humidifier(body, device['name']),
                                fetched_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat())
            self._cached_at = time.monotonic()
            return self._cached

    def command(self, action, mode=None, target=None):
        body = humidifier_command(action, mode, target)
        with self._lock:
            wait = self.min_command_gap - (time.monotonic() - self._last_command)
            if wait > 0:
                raise ValueError(f'Please wait {wait:.0f} s before sending another command.')
            device = self._device()
            api_post(f"/devices/{device['id']}/commands", body, self.token, self.secret, self.session)
            self._last_command = time.monotonic()
            self._cached = None  # next status call reads the device again
        return body


class Recorder:
    """Background thread in the serving process. Never raises; logs and retries."""

    def __init__(self, engine, token, secret, interval=300, device_id=''):
        self.engine, self.token, self.secret = engine, token, secret
        self.interval, self.device_id = max(60, int(interval)), device_id
        self.device = None
        self._stop = threading.Event()

    def tick(self):
        try:
            if self.device is None:
                self.device = find_hub2(self.token, self.secret, self.device_id)
            record_once(self.engine, self.token, self.secret, self.device)
        except Exception as error:  # network, SwitchBot or database problem: try again next interval
            log.warning('Hub 2 reading not recorded: %s', error)

    def run(self):
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.interval)

    def start(self):
        threading.Thread(target=self.run, name='hub2-recorder', daemon=True).start()
        return self
