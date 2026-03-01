import React, { Suspense } from 'react';
import { useLocation } from 'react-router-dom';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Environment, Stage } from '@react-three/drei';
import CodeBlock from '../components/CodeBlock';
import STLModel from '../components/STLModel';

/**
 * 💡 STORAGE STRATEGY:
 * - LOCAL: Place .stl files in `frontend/public/models/` and use paths like `/models/your-file.stl`.
 *   (Assets in `public/` are served from the root `/` in the browser).
 * - SUPABASE: Use the full public URL from your Supabase bucket.
 */
const DEFAULT_STL_URL = '/models/ESP32.stl'; // This will resolve to public/models/test.stl

// Example generated code — replace with data from your backend
const EXAMPLE_CODE = `# Hardwire configuration
import hardwire as hw

model = hw.Model(
    lift_coefficient=1.42,
    field_strength="9.8 N/kg",
    resonance_freq=440,
)

model.simulate(duration=10)
model.export("output.stl")
`;

export default function Results() {
  const location = useLocation();
  const reply = location.state?.reply || 'No response yet. Go back and run a query.';
  const prompt = location.state?.prompt;
  const [stlUrl, setStlUrl] = React.useState(location.state?.stlUrl || (prompt ? null : DEFAULT_STL_URL));
  const [loading, setLoading] = React.useState(!!prompt && !location.state?.stlUrl);
  const [verificationData, setVerificationData] = React.useState(null);
  const [inoFile, setInoFile] = React.useState(null);
  const objectUrlRef = React.useRef(null);
  const [expandedBlock, setExpandedBlock] = React.useState(null);

  const handleBlockClick = (blockKey) => {
    setExpandedBlock(blockKey);
  };

  const handleOverlayClick = () => {
    setExpandedBlock(null);
  };

  React.useEffect(() => {
    if (prompt && !location.state?.stlUrl) {
      const fetchSTL = async () => {
        setLoading(true);
        try {
          const response = await fetch('http://localhost:8000/stl-model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt }),
          });
          const data = await response.json();
          if (data && data.design_stl_file) {
            // Convert base64 → Blob → object URL so STLLoader can read it
            const binary = atob(data.design_stl_file);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i++) {
              bytes[i] = binary.charCodeAt(i);
            }
            const blob = new Blob([bytes], { type: 'application/octet-stream' });
            // Revoke previous object URL to avoid memory leaks
            if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
            const objUrl = URL.createObjectURL(blob);
            objectUrlRef.current = objUrl;
            setStlUrl(objUrl);

            // Store other metadata
            if (data.verification_results) setVerificationData(data.verification_results);
            if (data.ino_file) setInoFile(data.ino_file);
          } else {
            console.warn('API returned no STL file, using default.');
            setStlUrl(DEFAULT_STL_URL);
          }
        } catch (err) {
          console.error('Error fetching STL model, using default:', err);
          setStlUrl(DEFAULT_STL_URL);
        } finally {
          setLoading(false);
        }
      };
      fetchSTL();
    }
    // Revoke object URL on unmount
    return () => {
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    };
  }, [prompt]);

  return (
    <div className="results-layout glass">
      {/* Overlay — click to collapse */}
      {expandedBlock && (
        <div className="results-overlay" onClick={handleOverlayClick} />
      )}

      {/* LEFT — 3D Model Viewer */}
      <div
        className={`results-left${expandedBlock === 'model' ? ' expanded' : ''}`}
        style={{ position: 'relative' }}
        onClick={expandedBlock !== 'model' ? () => handleBlockClick('model') : undefined}
      >
        {loading && (
          <div className="loading-overlay">
            <div className="spinner"></div>
            <div className="loading-text">Generating Model...</div>
          </div>
        )}

        {!loading && stlUrl === DEFAULT_STL_URL && (
          <div className="default-model-badge">
            Display Model
          </div>
        )}

        {!loading && stlUrl ? (
          <Canvas shadows camera={{ position: [0, 0, 10], fov: 50 }}>
            <ambientLight intensity={0.5} />
            <Suspense fallback={null}>
              <Stage intensity={0.5} environment="city" adjustCamera={1.2} shadows={false}>
                <STLModel url={stlUrl} />
              </Stage>
            </Suspense>
            <OrbitControls makeDefault enablePan enableZoom enableRotate autoRotate autoRotateSpeed={2} />
          </Canvas>
        ) : (
          !loading && <div className="no-model-text">No model available.</div>
        )}
      </div>

      {/* RIGHT — Text + Code */}
      <div className="results-right">
        {/* Text Panel */}
        <div
          className={`results-text-panel${expandedBlock === 'schematics' ? ' expanded' : ''}`}
          onClick={expandedBlock !== 'schematics' ? () => handleBlockClick('schematics') : undefined}
        >
          <div className="panel-header">
            <div className="panel-label">Schematics Next Steps</div>
          </div>
          <div className="panel-body">
            {verificationData ? (
              <div className="verification-result"> 
                <p style={{ whiteSpace: 'pre-wrap' }}>{verificationData.explanation}</p>
              </div>
            ) : (
              <p>{reply}</p>
            )}
          </div>
        </div>

        {/* Code Block Panel */}
        <div
          className={`results-text-panel${expandedBlock === 'firmware' ? ' expanded' : ''}`}
          style={{ marginTop: '20px' }}
          onClick={expandedBlock !== 'firmware' ? () => handleBlockClick('firmware') : undefined}
        >
          <div className="panel-header">
            <div className="panel-label">Example Firmware (Arduino)</div>
          </div>
          <CodeBlock code={inoFile || EXAMPLE_CODE} language="cpp" />
        </div>
      </div>
    </div>
  );
}

