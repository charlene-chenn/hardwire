import React from 'react';
import { useNavigate } from 'react-router-dom';

import LEDGrid from '../components/LEDGrid';

export default function Landing() {
  const navigate = useNavigate();

  return (
    <>
      <LEDGrid />
      <div className="page-container">
        <div className="landing-content">
          <h1 className="landing-title">Hardwire</h1>

          <p className="landing-subtitle">
            The next generation of autonomous engineering. Build, test, and deploy
            complex systems with agent-first architecture.
          </p>

          <button className="btn-primary" onClick={() => navigate('/chat')}>
            Launch Mission Control →
          </button>
        </div>
      </div>
    </>
  );
}

