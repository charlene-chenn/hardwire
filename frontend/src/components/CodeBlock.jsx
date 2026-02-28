import React, { useState } from 'react';

export default function CodeBlock({ code, language = 'python' }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className="results-code-panel glass">
      <div className="results-code-header">
        <span className="panel-label" style={{ margin: 0 }}>{language}</span>
        <button className="copy-btn" onClick={handleCopy}>
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <div className="results-code-body">
        <pre>{code}</pre>
      </div>
    </div>
  );
}

