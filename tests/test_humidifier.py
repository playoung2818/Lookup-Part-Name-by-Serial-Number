"""Evaporative Humidifier: status parsing, command validation, caching, rate limit and routes.
SwitchBot is faked; no real device is contacted."""
import unittest
from unittest.mock import patch

from app import create_app
from functions import switchbot

STATUS = {'version': 'V2.0', 'power': 'on', 'mode': 5, 'drying': False, 'childLock': False,
          'filterElement': {'effectiveUsageHours': 240, 'usedHours': 1}, 'humidity': 54, 'deviceType': 'Humidifier2'}


class Response:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data


class FakeSession:
    def __init__(self):
        self.gets, self.posts = [], []

    def get(self, url, headers, timeout):
        self.gets.append(url)
        if url.endswith('/devices'):
            return Response({'statusCode': 100, 'body': {'deviceList': [
                {'deviceId': 'HUB2AE', 'deviceName': 'Hub 2 AE', 'deviceType': 'Hub 2'},
                {'deviceId': 'HUM640A', 'deviceName': 'Evaporative Humidifier 0A', 'deviceType': 'Humidifier2'}]}})
        return Response({'statusCode': 100, 'body': STATUS})

    def post(self, url, headers, json, timeout):
        self.posts.append((url, json))
        return Response({'statusCode': 100, 'body': {}, 'message': 'success'})


class HumidifierTests(unittest.TestCase):
    def test_parse_status(self):
        parsed = switchbot.parse_humidifier(STATUS, 'Evaporative Humidifier 0A')
        self.assertEqual((parsed['power'], parsed['mode_name'], parsed['humidity'], parsed['filter_used_hours'],
                          parsed['filter_life_hours']), ('on', 'Target humidity', 54, 1, 240))

    def test_command_validation(self):
        self.assertEqual(switchbot.humidifier_command('on')['command'], 'turnOn')
        self.assertEqual(switchbot.humidifier_command('off')['command'], 'turnOff')
        self.assertEqual(switchbot.humidifier_command('mode', 5, 60)['parameter'], {'mode': 5, 'targetHumidify': 60})
        self.assertEqual(switchbot.humidifier_command('mode', 7)['parameter'], {'mode': 7})
        for bad in (('mode', 9, None), ('mode', 5, None), ('mode', 5, 101), ('mode', '5', 60), ('explode', None, None)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                switchbot.humidifier_command(*bad)

    def test_status_is_cached_and_commands_are_rate_limited(self):
        session = FakeSession()
        humidifier = switchbot.Humidifier('t', 's', ttl=60, min_command_gap=3, session=session)
        humidifier.status(); humidifier.status()
        self.assertEqual(sum(url.endswith('/status') for url in session.gets), 1)       # cached
        humidifier.command('mode', 5, 55)
        self.assertEqual(session.posts[0], ('https://api.switch-bot.com/v1.1/devices/HUM640A/commands',
                                            {'command': 'setMode', 'parameter': {'mode': 5, 'targetHumidify': 55}, 'commandType': 'command'}))
        with self.assertRaisesRegex(ValueError, 'wait'):
            humidifier.command('off')
        self.assertEqual(len(session.posts), 1)
        humidifier.status()
        self.assertEqual(sum(url.endswith('/status') for url in session.gets), 2)       # re-read after a command


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'x', 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                               'SWITCHBOT_TOKEN': 't', 'SWITCHBOT_SECRET': 's'})
        self.session = FakeSession()
        self.app.extensions['humidifier'] = switchbot.Humidifier('t', 's', min_command_gap=0, session=self.session)
        self.client = self.app.test_client()

    def test_status(self):
        body = self.client.get('/api/humidifier').json
        self.assertEqual((body['power'], body['mode'], body['device']), ('on', 5, 'Evaporative Humidifier 0A'))

    def test_commands_only_from_the_homepage_script(self):
        self.assertEqual(self.client.post('/api/humidifier', json={'action': 'off'}).status_code, 403)
        self.assertEqual(self.client.post('/api/humidifier', data={'action': 'off'},
                                          headers={'X-Warehouse-Control': 'humidifier'}).status_code, 403)
        self.assertEqual(self.session.posts, [])
        with self.assertLogs(self.app.logger, 'WARNING') as logs:
            response = self.client.post('/api/humidifier', json={'action': 'off'}, headers={'X-Warehouse-Control': 'humidifier'})
        self.assertEqual((response.status_code, response.json['command']), (200, 'turnOff'))
        self.assertIn('Humidifier command turnOff', logs.output[0])

    def test_invalid_command_is_400(self):
        response = self.client.post('/api/humidifier', json={'action': 'mode', 'mode': 5, 'target': 120},
                                    headers={'X-Warehouse-Control': 'humidifier'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.session.posts, [])

    def test_not_configured_is_503(self):
        app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://', 'SWITCHBOT_TOKEN': '', 'SWITCHBOT_SECRET': ''})
        self.assertEqual(app.test_client().get('/api/humidifier').status_code, 503)

    def test_homepage_has_controls_and_no_secrets(self):
        html = self.client.get('/').get_data(as_text=True)
        self.assertIn('id="humidifier-panel"', html)
        self.assertIn('data-hum-action="off"', html)
        self.assertIn('anyone on the network', html)


if __name__ == '__main__':
    unittest.main()
