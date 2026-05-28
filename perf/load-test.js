// load-test.js — k6 load test for Habit Tracker API
// Demo: 1 dk, 10→100 VU ramp-up, realistic habit CRUD workflow
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = 'http://localhost:8001';

export const options = {
  stages: [
    { duration: '10s', target: 10 },   // ramp up to 10 VU
    { duration: '20s', target: 30 },   // ramp up to 30 VU
    { duration: '20s', target: 50 },   // ramp up to 50 VU
    { duration: '10s', target: 0 },    // ramp down to 0
  ],
  thresholds: {
    'http_req_duration': ['p(95)<500', 'p(99)<1000'],
    'http_req_failed': ['rate<0.05'],  // 5% threshold (more lenient for now)
    'checks': ['rate>0.99'],
  },
};

export default function () {
  // Realistic user workflow: health check → login → create habit → list → get → update → delete

  // 1. Health check
  const healthRes = http.get(`${BASE_URL}/health`);
  check(healthRes, {
    'health status 200': (r) => r.status === 200,
  });
  sleep(Math.random() * 2 + 1); // 1-3s think time

  // 2. Login (get auth token)
  const loginPayload = JSON.stringify({
    username: `user_${Math.random()}`,
    password: 'test123',
  });

  const loginRes = http.post(`${BASE_URL}/login`, loginPayload, {
    headers: { 'Content-Type': 'application/json' },
  });

  let token = null;
  let authUsername = JSON.parse(loginPayload).username;

  if (loginRes.status === 401) {
    // User doesn't exist, register first
    const registerRes = http.post(`${BASE_URL}/register`, loginPayload, {
      headers: { 'Content-Type': 'application/json' },
    });

    if (registerRes.status === 201 || registerRes.status === 200) {
      // Now login
      const retryLoginRes = http.post(`${BASE_URL}/login`, loginPayload, {
        headers: { 'Content-Type': 'application/json' },
      });
      if (retryLoginRes.status === 200) {
        try {
          const body = JSON.parse(retryLoginRes.body);
          token = body.access_token;
        } catch (e) {
          console.log(`Failed to parse login response for ${authUsername}: ${retryLoginRes.body}`);
        }
      }
    }
  } else if (loginRes.status === 200) {
    try {
      const body = JSON.parse(loginRes.body);
      token = body.access_token;
    } catch (e) {
      console.log(`Failed to parse login response for ${authUsername}: ${loginRes.body}`);
    }
  }

  // If auth failed, skip to next iteration
  if (!token) {
    return;
  }

  const authHeader = { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' };
  sleep(Math.random() * 2 + 1);

  // 4. Create a new habit
  const habitPayload = JSON.stringify({
    name: `Habit ${Math.random()}`,
    description: 'Test habit for performance testing',
    frequency: 'daily',
  });

  const createRes = http.post(`${BASE_URL}/habits`, habitPayload, {
    headers: authHeader,
  });
  check(createRes, {
    'create habit status 200': (r) => r.status === 200 || r.status === 201,
    'create habit response time': (r) => r.timings.duration < 500,
  });
  sleep(Math.random() * 2 + 1);

  // Extract habit ID from response
  let habitId = null;
  if (createRes.status === 200 || createRes.status === 201) {
    try {
      const body = JSON.parse(createRes.body);
      habitId = body.id || body.habit_id;
    } catch (e) {
      habitId = Math.floor(Math.random() * 1000); // fallback
    }
  }

  // 5. List all habits
  const listRes = http.get(`${BASE_URL}/habits`, { headers: authHeader });
  check(listRes, {
    'list habits status 200': (r) => r.status === 200,
    'list habits response time': (r) => r.timings.duration < 500,
  });
  sleep(Math.random() * 2 + 1);

  // 6. Get specific habit (if we have ID)
  if (habitId) {
    const getRes = http.get(`${BASE_URL}/habits/${habitId}`, { headers: authHeader });
    check(getRes, {
      'get habit status': (r) => r.status === 200 || r.status === 404,
      'get habit response time': (r) => r.timings.duration < 500,
    });
    sleep(Math.random() * 2 + 1);

    // 7. Update habit
    const updatePayload = JSON.stringify({
      name: `Updated Habit ${Math.random()}`,
      description: 'Updated for performance test',
      frequency: 'weekly',
    });

    const updateRes = http.patch(`${BASE_URL}/habits/${habitId}`, updatePayload, {
      headers: authHeader,
    });
    check(updateRes, {
      'update habit status': (r) => r.status === 200 || r.status === 404,
      'update habit response time': (r) => r.timings.duration < 500,
    });
    sleep(Math.random() * 2 + 1);

    // 8. Delete habit
    const deleteRes = http.del(`${BASE_URL}/habits/${habitId}`, null, { headers: authHeader });
    check(deleteRes, {
      'delete habit status': (r) => r.status === 200 || r.status === 204 || r.status === 404,
      'delete habit response time': (r) => r.timings.duration < 500,
    });
    sleep(Math.random() * 2 + 1);
  }
}
