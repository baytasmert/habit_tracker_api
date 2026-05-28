// Global app.js - handles common functionality

// Check if user is authenticated
function isAuthenticated() {
    return !!localStorage.getItem('auth_token');
}

// Get auth token
function getToken() {
    return localStorage.getItem('auth_token');
}

// Set auth token
function setToken(token) {
    localStorage.setItem('auth_token', token);
}

// Clear auth token (logout)
function logout() {
    localStorage.removeItem('auth_token');
    window.location.href = '/login';
}

// Make authenticated API request
async function apiCall(endpoint, options = {}) {
    const token = getToken();
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };

    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(endpoint, {
        ...options,
        headers
    });

    // If unauthorized, redirect to login
    if (response.status === 401) {
        logout();
        return null;
    }

    return response;
}
