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
  const examplePrompts = [
    "Design a robotic arm joint with high torque.",
    "Generate an ESP32 enclosure with cooling vents.",
    "Create a plant pot with an Arduino Uno and DHT22."
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
      const response = await fetch('http://localhost:8000/process-pipeline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: input.trim() }),
      });

      const data = await response.json();

      // Navigate to results — pass electronics data so panels populate immediately
      setTimeout(() => {
        clearInterval(interval);
        navigate('/results', {
          state: {
            prompt: input.trim(),
            verificationData: data.verification_results || null,
            inoFile: data.firmware_code || null,
            verilogCode: data.verilog_code || null,
            rtlSchematic: data.rtl_schematic || null,
          },
        });
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

  const handleExampleClick = (prompt) => {
    if (loading) return;
    setInput(prompt);
  };

  return (
    <div className="chat-page-layout">
      <div className="chat-main-column">
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
      </div>

      <div className="chat-examples-sidebar">
        <h3 className="section-title">Example Prompts</h3>
        <div className="example-prompts-list">
          {examplePrompts.map((prompt, idx) => (
            <div
              key={idx}
              className="example-prompt-card glass"
              onClick={() => handleExampleClick(prompt)}
            >
              <p>{prompt}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
