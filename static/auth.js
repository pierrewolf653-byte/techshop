// auth.js – Version minimaliste
function goToDashboard() {
    const token = localStorage.getItem('token');
    if (!token) { window.location.href = '/static/login_client.html'; return; }
    window.location.href = '/dashboard?token_q=' + encodeURIComponent(token);
}

function goToAdmin() {
    const token = localStorage.getItem('token');
    if (!token) { window.location.href = '/static/login_client.html'; return; }
    window.location.href = '/admin?token_q=' + encodeURIComponent(token);
}

function logout() {
    localStorage.clear();
    window.location.href = '/static/index.html';
}