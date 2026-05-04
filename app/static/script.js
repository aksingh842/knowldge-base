let currentSessionId = null;
let currentUserId = null;
let currentApiKey = null;

// DOM Elements
const setupModal = document.getElementById('setup-modal');
const startBtn = document.getElementById('start-btn');
const chatForm = document.getElementById('chat-form');
const userInput = document.getElementById('user-input');
const messagesContainer = document.getElementById('messages-container');
const traceContent = document.getElementById('trace-content');

const userIdDisplay = document.getElementById('user-id-display');
const sessionIdDisplay = document.getElementById('session-id-display');
const planBadge = document.getElementById('plan-badge');

// --- Initialization ---

startBtn.addEventListener('click', async () => {
    const userId = document.getElementById('setup-user-id').value;
    const apiKey = document.getElementById('setup-api-key').value;
    const plan = document.getElementById('setup-plan').value;
    
    if (!userId) return alert("Please enter a User ID");
    
    try {
        const response = await fetch('/v1/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, plan_tier: plan })
        });
        
        if (!response.ok) throw new Error("Failed to create session");
        
        const data = await response.json();
        currentSessionId = data.session_id;
        currentUserId = userId;
        currentApiKey = apiKey;
        
        // Update UI
        userIdDisplay.textContent = `User: ${userId}`;
        sessionIdDisplay.textContent = `ID: ${currentSessionId.substring(0, 8)}...`;
        planBadge.textContent = plan;
        setupModal.classList.add('hidden'); // Use class instead of style if using the new CSS
        setupModal.style.display = 'none';   // Fallback
        
        console.log("Session started:", currentSessionId);
    } catch (err) {
        console.error("Failed to start session:", err);
        alert("Server error. Is the backend running?");
    }
});

// --- Chat Logic ---

chatForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const content = userInput.value.trim();
    if (!content || !currentSessionId) return;
    
    appendMessage('user', content);
    userInput.value = '';
    
    const typingId = appendTypingIndicator();
    
    try {
        const response = await fetch(`/v1/chat/${currentSessionId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content, api_key: currentApiKey })
        });
        
        if (!response.ok) throw new Error("Chat failed");
        
        const data = await response.json();
        removeTypingIndicator(typingId);
        appendMessage('assistant', data.reply);
        
        if (data.trace_id) fetchTrace(data.trace_id);
    } catch (err) {
        removeTypingIndicator(typingId);
        appendMessage('assistant', "Error: Could not reach the server.");
    }
});

function appendMessage(role, text) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}`;
    
    const formattedText = text.replace(/\[(chunk_[^\]]+)\]/g, '<span class="citation">$1</span>');
    
    msgDiv.innerHTML = `
        <div class="avatar">${role === 'user' ? 'U' : 'H'}</div>
        <div class="bubble">${formattedText}</div>
    `;
    
    messagesContainer.appendChild(msgDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    return msgDiv;
}

function appendTypingIndicator() {
    const id = 'typing-' + Date.now();
    const div = document.createElement('div');
    div.id = id;
    div.className = 'message assistant';
    div.innerHTML = `
        <div class="avatar">H</div>
        <div class="bubble"><div class="typing"><span></span><span></span><span></span></div></div>
    `;
    messagesContainer.appendChild(div);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    return id;
}

function removeTypingIndicator(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

// --- Trace Logic ---

async function fetchTrace(traceId) {
    try {
        const response = await fetch(`/v1/traces/${traceId}`);
        const trace = await response.json();
        
        traceContent.innerHTML = '';
        const items = [
            { label: 'Trace ID', value: traceId },
            { label: 'Routed To', value: trace.routed_to },
            { label: 'Latency', value: `${trace.latency_ms}ms` },
            { label: 'Chunks', value: trace.retrieved_chunk_ids.length > 0 ? trace.retrieved_chunk_ids.join(', ') : 'None' }
        ];
        
        items.forEach(item => {
            const div = document.createElement('div');
            div.className = 'trace-item';
            div.innerHTML = `<span class="trace-label">${item.label}:</span> ${item.value}`;
            traceContent.appendChild(div);
        });
        
        if (trace.tool_calls.length > 0) {
            const toolDiv = document.createElement('div');
            toolDiv.className = 'trace-item';
            toolDiv.innerHTML = `<span class="trace-label">Tool Calls:</span><br>` + 
                trace.tool_calls.map(tc => `- ${tc.tool_name}`).join('<br>');
            traceContent.appendChild(toolDiv);
        }
    } catch (err) {
        console.error("Failed to fetch trace:", err);
    }
}

// --- Sidebar Actions ---

document.getElementById('new-chat-btn').addEventListener('click', () => {
    location.reload();
});
