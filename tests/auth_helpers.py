from src.auth import AccountStore


def login_test_client(client, store):
    """Real authentication, with explicit ownership only in the fixture DB."""
    registration = client.post('/api/auth/register', json={
        'account_name': '测试教师', 'phone': '13800000001',
        'password': 'fixture', 'confirm_password': 'fixture',
    })
    assert registration.status_code == 201
    account_id = registration.json()['account']['account_id']
    AccountStore(store.db_path).assign_legacy(account_id, [course.id for course in store.list()])
    result = client.post('/api/auth/login', json={'phone': '13800000001', 'password': 'fixture'})
    assert result.status_code == 200
    client.headers['Authorization'] = 'Bearer ' + result.json()['token']
    return account_id
