import React from 'react';
import { Link } from 'react-router-dom';

export default function Navbar() {
  return (
    <nav className="navbar">
      <Link to="/" className="navbar-brand">Hardwire</Link>
      <div className="navbar-links">
        <Link to="/chat" className="nav-link">Chat</Link>
        {/* <Link to="/results" className="nav-link">Results</Link> */}
      </div>
    </nav>
  );
}

