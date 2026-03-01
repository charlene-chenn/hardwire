import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

export default function Chat() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Hello! What would you like to design today?' }
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState('Thinking...');
  const thinkingMessages = [
    'Analyzing your request...',
    'Designing the component...',
    'Optimizing parameters...',
    'Almost there...',
  ];
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendMessage = async () => {
    if (!input.trim() || loading) return;

    const userMessage = { role: 'user', content: input.trim() };
    const updatedMessages = [...messages, userMessage];
    setMessages(updatedMessages);
    setInput('');
    setLoading(true);
    setLoadingMessage(thinkingMessages[0]);

    const interval = setInterval(() => {
      setLoadingMessage(prev => {
        const currentIdx = thinkingMessages.indexOf(prev);
        return thinkingMessages[(currentIdx + 1) % thinkingMessages.length];
      });
    }, 2000);

    try {
      // 🔌 REPLACE THIS URL with your actual backend endpoint
      const response = await fetch('http://localhost:8000/process-pipeline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: input.trim() }),
      });

      const data = await response.json();

      // Navigate to results after LLM responds with a 1s delay
      setTimeout(() => {
        clearInterval(interval);
        navigate('/results', { state: { reply: data.reply, prompt: input.trim() } });
      }, 1000);
    } catch (err) {
      clearInterval(interval);
      console.error('Backend error:', err);
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: 'Error connecting to backend. Check your API endpoint.' }
      ]);
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="chat-container">
      <h1 className="landing-title" style={{ fontSize: '32px' }}>Bob the Builder</h1>

      <div className="chat-messages">
        {messages.map((msg, i) => (
          <div key={i} className={`chat-message ${msg.role}`}>
            <span className="bubble">{msg.content}</span>
          </div>
        ))}
        {loading && (
          <div className="chat-message assistant">
            <span className="bubble" style={{ color: '#888' }}>{loadingMessage}</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="chat-input-row">
        <textarea
          className="chat-input"
          rows={1}
          placeholder="Type a message to Bob..."
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading}
        />
        <button className="btn-primary" onClick={sendMessage} disabled={loading} style={{ padding: '8px 20px' }}>
          Send
        </button>
      </div>
    </div>
  );
}

