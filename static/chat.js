// static/chat.js – Widget de chat

document.addEventListener('DOMContentLoaded', function () {
    // Créer le conteneur du chat
    const chatContainer = document.createElement('div');
    chatContainer.id = 'chat-widget';
    chatContainer.style.position = 'fixed';
    chatContainer.style.bottom = '20px';
    chatContainer.style.right = '20px';
    chatContainer.style.zIndex = '9999';
    chatContainer.innerHTML = `
        <div id="chat-toggle" style="background:#0d6efd; color:white; border-radius:50%; width:60px; height:60px; display:flex; align-items:center; justify-content:center; cursor:pointer; box-shadow:0 2px 12px rgba(0,0,0,0.3); font-size:28px;">
            💬
        </div>
        <div id="chat-box" style="display:none; position:absolute; bottom:70px; right:0; width:350px; max-height:500px; background:white; border-radius:12px; box-shadow:0 4px 20px rgba(0,0,0,0.25); overflow:hidden; flex-direction:column; border:1px solid #ddd;">
            <div style="background:#0d6efd; color:white; padding:10px 16px; font-weight:bold; display:flex; justify-content:space-between;">
                <span>🤖 Assistant TechShop</span>
                <span id="chat-close" style="cursor:pointer;">✕</span>
            </div>
            <div id="chat-messages" style="flex:1; padding:12px; overflow-y:auto; max-height:350px; background:#f8f9fa; font-size:14px;"></div>
            <div style="display:flex; border-top:1px solid #ddd; background:white;">
                <input id="chat-input" type="text" placeholder="Écrivez votre message..." style="flex:1; border:none; padding:10px 12px; outline:none;">
                <button id="chat-send" style="background:#0d6efd; color:white; border:none; padding:10px 16px; cursor:pointer;">Envoyer</button>
            </div>
        </div>
    `;
    document.body.appendChild(chatContainer);

    // Gérer l'ouverture/fermeture
    const toggle = document.getElementById('chat-toggle');
    const box = document.getElementById('chat-box');
    const close = document.getElementById('chat-close');

    toggle.addEventListener('click', function() {
        if (box.style.display === 'none' || box.style.display === '') {
            box.style.display = 'flex';
            toggle.style.display = 'none';
        }
    });
    close.addEventListener('click', function() {
        box.style.display = 'none';
        toggle.style.display = 'flex';
    });

    // Gérer l'envoi de messages
    const input = document.getElementById('chat-input');
    const send = document.getElementById('chat-send');
    const messagesDiv = document.getElementById('chat-messages');

    function addMessage(text, sender = 'user') {
        const msg = document.createElement('div');
        msg.style.marginBottom = '8px';
        msg.style.padding = '6px 10px';
        msg.style.borderRadius = '12px';
        if (sender === 'user') {
            msg.style.background = '#e9ecef';
            msg.style.alignSelf = 'flex-end';
            msg.style.textAlign = 'right';
        } else {
            msg.style.background = '#0d6efd';
            msg.style.color = 'white';
            msg.style.alignSelf = 'flex-start';
        }
        msg.textContent = text;
        messagesDiv.appendChild(msg);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    async function sendMessage() {
        const text = input.value.trim();
        if (!text) return;
        addMessage(text, 'user');
        input.value = '';

        // Récupérer le token si présent
        const token = localStorage.getItem('token') || '';

        try {
            const res = await fetch(`/api/chat?message=${encodeURIComponent(text)}&token=${encodeURIComponent(token)}`, { method: 'POST' });
            const data = await res.json();
            addMessage(data.response, 'bot');
        } catch {
            addMessage("Désolé, une erreur s'est produite. Veuillez réessayer.", 'bot');
        }
    }

    send.addEventListener('click', sendMessage);
    input.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') sendMessage();
    });
});