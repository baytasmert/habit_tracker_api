def test_create_habit(auth_client):
    # API'ye POST gönder
    response = auth_client.post("/habits", json={
        "name": "Koşu",
        "description": "Günlük koşu"
    })

    # Check 1: status code 201 (created) mi?
    assert response.status_code == 201

    # Check 2: dönen data'da name var mı?
    data = response.json()
    assert data["name"] == "Koşu"
    assert data["id"] is not None


def test_track_habit(auth_client):
    # 1. Önce habit oluştur
    create_response = auth_client.post("/habits", json={
        "name": "Meditasyon",
        "description": "Günlük meditasyon"
    })
    habit_id = create_response.json()["id"]

    # 2. Tracking ekle
    track_response = auth_client.post(f"/habits/{habit_id}/track", json={
        "done": True,
        "duration": 10,
        "notes": "Rahat bir seans"
    })

    # Check 1: status code 200 mi?
    assert track_response.status_code == 200

    # Check 2: dönen data'da done: true var mı?
    track_data = track_response.json()
    assert track_data["done"] == True


def test_get_streak(auth_client):
    # 1. Habit oluştur
    create_response = auth_client.post("/habits", json={
        "name": "Kitap okuma",
        "description": "Her gün 30 dakika"
    })
    habit_id = create_response.json()["id"]

    # 2. 2 gün tracking ekle
    auth_client.post(f"/habits/{habit_id}/track", json={"done": True})
    auth_client.post(f"/habits/{habit_id}/track", json={"done": True})

    # 3. Streak al
    streak_response = auth_client.get(f"/habits/{habit_id}/streak")

    # Check 1: status code 200 mi?
    assert streak_response.status_code == 200

    # Check 2: response valid JSON mi?
    streak_data = streak_response.json()
    assert streak_data is not None
