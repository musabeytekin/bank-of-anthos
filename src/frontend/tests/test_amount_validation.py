# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for amount validation on the deposit and payment forms."""

import json
import os
import sys
from unittest import mock
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import frontend  # noqa: E402  pylint: disable=wrong-import-position


@pytest.fixture(name='client')
def fixture_client(tmp_path, monkeypatch):
    """Flask test client with a signed-in user and a mocked backend."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_path = tmp_path / 'jwt.pub'
    pub_path.write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo))
    for name, value in {
            'PUB_KEY_PATH': str(pub_path),
            'LOCAL_ROUTING_NUM': '883745000',
            'ENABLE_TRACING': 'false',
            'TRANSACTIONS_API_ADDR': 'ledger',
            'USERSERVICE_API_ADDR': 'users',
            'BALANCES_API_ADDR': 'balances',
            'HISTORY_API_ADDR': 'history',
            'CONTACTS_API_ADDR': 'contacts'}.items():
        monkeypatch.setenv(name, value)
    with mock.patch('requests.get',
                    side_effect=requests.exceptions.ConnectionError):
        app = frontend.create_app()
    token = jwt.encode({'user': 'u', 'acct': '1234567890', 'name': 'U'},
                       key, algorithm='RS256')
    test_client = app.test_client()
    test_client.set_cookie('token', token)
    return test_client


def _message(response):
    assert response.status_code in (302, 303)
    return parse_qs(urlparse(response.headers['Location']).query)['msg'][0]


def _payment(client, amount):
    return client.post('/payment', data={
        'account_num': '1111111111', 'amount': amount, 'uuid': 'x'})


def _deposit(client, amount):
    account = json.dumps({'account_num': '2222222222',
                          'routing_num': '123456789'})
    return client.post('/deposit', data={
        'account': account, 'amount': amount, 'uuid': 'x'})


@pytest.mark.parametrize('amount', ['10.005', '0.001', '1.999', '5.123456'])
@pytest.mark.parametrize('submit,label',
                         [(_payment, 'Payment'), (_deposit, 'Deposit')])
def test_too_many_decimals_rejected(client, submit, label, amount):
    """Amounts with sub-cent precision are rejected and never submitted."""
    with mock.patch('requests.post') as post:
        msg = _message(submit(client, amount))
    post.assert_not_called()
    assert msg == label + ' failed: amount cannot have more than two decimal places'


@pytest.mark.parametrize('amount', ['abc', '', 'NaN', 'Infinity'])
@pytest.mark.parametrize('submit,label',
                         [(_payment, 'Payment'), (_deposit, 'Deposit')])
def test_non_numbers_rejected(client, submit, label, amount):
    """Non-numeric input is rejected with a message."""
    with mock.patch('requests.post') as post:
        msg = _message(submit(client, amount))
    post.assert_not_called()
    assert msg == '{} failed: {} is not a valid number'.format(label, amount)


@pytest.mark.parametrize('amount,cents', [
    ('10', 1000), ('10.5', 1050), ('10.50', 1050), ('10.500', 1050),
    ('0.01', 1)])
@pytest.mark.parametrize('submit,label',
                         [(_payment, 'Payment'), (_deposit, 'Deposit')])
def test_valid_amounts_accepted(client, submit, label, amount, cents):
    """Amounts with at most two significant decimals are submitted exactly."""
    with mock.patch('requests.post') as post, \
            mock.patch('frontend.sleep'):
        msg = _message(submit(client, amount))
    assert msg == label + ' successful'
    sent = json.loads(post.call_args.kwargs['data'])
    assert sent['amount'] == cents
