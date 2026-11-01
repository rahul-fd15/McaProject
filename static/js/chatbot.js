// Customer Support Chatbot Client

document.addEventListener('DOMContentLoaded', function() {
    const toggleBtn = document.getElementById('chatbot-toggle-btn');
    const closeBtn = document.getElementById('chatbot-close-btn');
    const chatWindow = document.getElementById('chatbot-window');
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const chatMessages = document.getElementById('chat-messages');

    if (!toggleBtn || !chatWindow) return;

    // Toggle Chatbot Window
    toggleBtn.addEventListener('click', function() {
        if (chatWindow.style.display === 'none' || chatWindow.style.display === '') {
            chatWindow.style.display = 'flex';
            toggleBtn.style.display = 'none';
            chatInput.focus();
        } else {
            chatWindow.style.display = 'none';
            toggleBtn.style.display = 'flex';
        }
    });

    closeBtn.addEventListener('click', function() {
        chatWindow.style.display = 'none';
        toggleBtn.style.display = 'flex';
    });

    // Handle Form Submit
    chatForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const text = chatInput.value.trim();
        if (!text) return;
        chatInput.value = '';
        sendChatMessage(text);
    });
});

function sendQuickChat(text) {
    const chatWindow = document.getElementById('chatbot-window');
    const toggleBtn = document.getElementById('chatbot-toggle-btn');
    if (chatWindow && (chatWindow.style.display === 'none' || chatWindow.style.display === '')) {
        chatWindow.style.display = 'flex';
        toggleBtn.style.display = 'none';
    }
    sendChatMessage(text);
}

function sendChatMessage(text) {
    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return;

    // Append User Message Bubble
    const userBubble = document.createElement('div');
    userBubble.className = 'chat-bubble user-msg';
    userBubble.innerText = text;
    chatMessages.appendChild(userBubble);

    // Append Typing Indicator
    const typingBubble = document.createElement('div');
    typingBubble.className = 'chat-bubble bot-msg typing-indicator';
    typingBubble.id = 'chatTypingIndicator';
    typingBubble.innerHTML = '<span></span><span></span><span></span>';
    chatMessages.appendChild(typingBubble);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    // Send API Request
    fetch('/api/chat', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ message: text })
    })
    .then(res => res.json())
    .then(data => {
        // Remove typing indicator
        const indicator = document.getElementById('chatTypingIndicator');
        if (indicator) indicator.remove();

        // Append Bot Bubble
        const botBubble = document.createElement('div');
        botBubble.className = 'chat-bubble bot-msg';
        botBubble.innerText = data.reply;
        chatMessages.appendChild(botBubble);

        // If card was blocked by chatbot, prompt reload to update cards visual
        if (data.action_taken === 'CARD_BLOCKED') {
            const notice = document.createElement('div');
            notice.className = 'alert alert-danger py-1 px-2 mt-1 mb-0 fs-xs text-center fw-bold';
            notice.innerHTML = '<i class="fa-solid fa-lock me-1"></i> Card status updated to BLOCKED. <a href="javascript:location.reload()" class="text-danger text-decoration-underline">Refresh view</a>';
            chatMessages.appendChild(notice);
        }

        chatMessages.scrollTop = chatMessages.scrollHeight;
    })
    .catch(err => {
        const indicator = document.getElementById('chatTypingIndicator');
        if (indicator) indicator.remove();

        const botBubble = document.createElement('div');
        botBubble.className = 'chat-bubble bot-msg text-danger';
        botBubble.innerText = 'Sorry, I encountered an error connecting to customer support. Please try again.';
        chatMessages.appendChild(botBubble);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    });
}
