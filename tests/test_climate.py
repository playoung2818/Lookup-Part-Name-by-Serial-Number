"""Hub 2 humidity: signing, device lookup, recording, chart data and the API route.
SwitchBot is faked; tables exist only in a throwaway in-memory SQLite database."""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import unittest
from unittest.mock import patch

from sqlalchemy import (Column, DateTime, Float, Integer, MetaData, SmallInteger, String, Table,
                        UniqueConstraint, create_engine, select)

from app import create_app, start_climate_recorder
from functions import switchbot

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data


class FakeSession:
    def __init__(self, humidity=51):
        self.humidity, self.calls = humidity, []

    def get(self, url, headers, timeout):
        self.calls.append((url, headers))
        if url.endswith('/devices'):
            return FakeResponse({'statusCode': 100, 'message': 'success', 'body': {'deviceList': [
                {'deviceId': 'HUMID01', 'deviceName': 'Evaporative Humidifier 0A', 'deviceType': 'Humidifier2'},
                {'deviceId': 'HUB2AE', 'deviceName': 'Hub 2 AE', 'deviceType': 'Hub 2'}]}})
        return FakeResponse({'statusCode': 100, 'message': 'success', 'body': {
            'deviceId': 'HUB2AE', 'deviceType': 'Hub 2', 'humidity': self.humidity, 'temperature': 20.9, 'lightLevel': 1}})


def test_engine():
    engine = create_engine('sqlite://')
    Table('climate_readings', MetaData(), Column('id', Integer, primary_key=True),
          Column('device_id', String(64), nullable=False), Column('device_name', String(255)),
          Column('recorded_at', DateTime(timezone=True), nullable=False),
          Column('humidity', SmallInteger, nullable=False), Column('temperature', Float),
          Column('light_level', SmallInteger), UniqueConstraint('device_id', 'recorded_at')).create(engine)
    return engine


class SwitchBotTests(unittest.TestCase):
    def test_signature_follows_the_documented_algorithm(self):
        headers = switchbot.signed_headers('TOKEN', 'SECRET', now_ms=1661927531000, nonce='abc')
        expected = base64.b64encode(hmac.new(b'SECRET', b'TOKEN1661927531000abc', hashlib.sha256).digest()).decode()
        self.assertEqual((headers['Authorization'], headers['t'], headers['nonce'], headers['sign']),
                         ('TOKEN', '1661927531000', 'abc', expected))

    def test_finds_only_the_hub2_and_reads_it(self):
        session = FakeSession()
        device = switchbot.find_hub2('t', 's', session=session)
        self.assertEqual(device, {'id': 'HUB2AE', 'name': 'Hub 2 AE'})
        self.assertEqual(switchbot.read_hub2('HUB2AE', 't', 's', session),
                         {'humidity': 51, 'temperature': 20.9, 'light_level': 1})
        self.assertTrue(session.calls[-1][0].endswith('/v1.1/devices/HUB2AE/status'))

    def test_api_errors_raise(self):
        class Denied(FakeSession):
            def get(self, url, headers, timeout):
                return FakeResponse({'message': 'Unauthorized'}, 401)
        with self.assertRaisesRegex(switchbot.SwitchBotError, '401'):
            switchbot.find_hub2('t', 's', session=Denied())

    def test_recorder_never_raises(self):
        recorder = switchbot.Recorder(test_engine(), 't', 's', interval=300)
        with patch.object(switchbot, 'find_hub2', side_effect=switchbot.SwitchBotError('offline')), \
             self.assertLogs('functions.switchbot', 'WARNING'):
            recorder.tick()

    def test_refresh_reads_now_but_at_most_once_a_minute(self):
        recorder = switchbot.Recorder(test_engine(), 't', 's', interval=300)
        recorder.device = {'id': 'HUB2AE', 'name': 'Hub 2 AE'}
        with patch.object(switchbot, 'record_once') as record:
            self.assertTrue(recorder.refresh())
            self.assertFalse(recorder.refresh())          # second click within a minute: skipped
            self.assertEqual(record.call_count, 1)
            recorder._last_reading -= 61
            self.assertTrue(recorder.refresh())
            self.assertEqual(record.call_count, 2)

    def test_no_credentials_no_recorder(self):
        app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://', 'SWITCHBOT_TOKEN': '', 'SWITCHBOT_SECRET': ''})
        self.assertIsNone(start_climate_recorder(app))


class ChartTests(unittest.TestCase):
    def setUp(self):
        self.engine = test_engine()
        self.device = {'id': 'HUB2AE', 'name': 'Hub 2 AE'}

    def record(self, minutes_ago, humidity):
        switchbot.record_once(self.engine, 't', 's', self.device, session=FakeSession(humidity),
                              now=NOW - timedelta(minutes=minutes_ago))

    def test_records_and_reports_latest_with_inclusive_range(self):
        for minutes, humidity in ((30, 85), (10, 40), (5, 80)):
            self.record(minutes, humidity)
        with self.engine.connect() as connection:
            rows = connection.execute(select(switchbot.readings_table(self.engine))).mappings().all()
        self.assertEqual([(r['device_id'], r['device_name'], r['humidity']) for r in rows][0], ('HUB2AE', 'Hub 2 AE', 85))
        data = switchbot.chart_data(self.engine, '24h', now=NOW, ok_range=(40, 80))
        self.assertEqual(data['latest']['humidity'], 80)
        self.assertTrue(data['latest']['in_range'])            # 80 is inside 40-80 inclusive
        self.assertEqual(data['latest']['age_seconds'], 300)
        self.assertEqual([p['humidity'] for p in data['points']], [85, 40, 80])
        self.assertEqual(data['ok_range'], [40, 80])

    def test_out_of_range_and_bucketing(self):
        for minutes in range(0, 60 * 24 * 3, 5):              # three days of 5-minute readings
            self.record(minutes, 39 if minutes < 60 else 60)
        data = switchbot.chart_data(self.engine, '7d', now=NOW, ok_range=(40, 80))
        self.assertFalse(data['latest']['in_range'])           # 39 is below 40
        self.assertLessEqual(len(data['points']), 7 * 48 + 1)  # averaged into 30-minute buckets
        self.assertEqual(data['points'][0]['humidity'], 60)
        day = switchbot.chart_data(self.engine, '24h', now=NOW)
        self.assertEqual(len(day['points']), 288)              # raw 5-minute points
        self.assertEqual(switchbot.chart_data(self.engine, 'bogus', now=NOW)['range'], '24h')

    def test_empty_history(self):
        data = switchbot.chart_data(self.engine, '24h', now=NOW)
        self.assertEqual((data['latest'], data['points']), (None, []))


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'x', 'SQLALCHEMY_DATABASE_URI': 'sqlite://'})
        self.client = self.app.test_client()

    def test_api_climate_uses_configured_range(self):
        with patch('functions.switchbot.chart_data', return_value={'range': '7d', 'points': [], 'latest': None,
                                                                  'ok_range': [40, 80]}) as chart:
            response = self.client.get('/api/climate?range=7d')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(chart.call_args.args[1], '7d')
        self.assertEqual(chart.call_args.kwargs['ok_range'], (40.0, 80.0))

    def test_refresh_parameter_triggers_a_reading(self):
        class Recorder:
            calls = 0
            def refresh(self):
                Recorder.calls += 1
        self.app.extensions['climate_recorder'] = Recorder()
        with patch('functions.switchbot.chart_data', return_value={'range': '24h', 'points': [], 'latest': None, 'ok_range': [40, 80]}):
            self.client.get('/api/climate')
            self.assertEqual(Recorder.calls, 0)             # normal minute-by-minute loads never read the device
            self.client.get('/api/climate?refresh=1')
            self.assertEqual(Recorder.calls, 1)

    def test_homepage_has_refresh_button(self):
        self.assertIn('id="climate-refresh"', self.client.get('/').get_data(as_text=True))

    def test_api_climate_without_table_is_503(self):
        self.assertEqual(self.client.get('/api/climate').status_code, 503)

    def test_homepage_has_the_panel(self):
        html = self.client.get('/').get_data(as_text=True)
        self.assertIn('id="climate-panel"', html)
        self.assertIn('data-ok-min="40" data-ok-max="80"', html)
        self.assertIn('40\u201380 % RH', html)
        self.assertNotIn(self.app.config.get('SWITCHBOT_SECRET') or 'no-secret-configured', html)


if __name__ == '__main__':
    unittest.main()
