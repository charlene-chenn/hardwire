import React, { Suspense } from 'react';
import { useLocation } from 'react-router-dom';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Environment } from '@react-three/drei';
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
  const objectUrlRef = React.useRef(null);

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
      {/* LEFT — 3D Model Viewer */}
      <div className="results-left" style={{ position: 'relative' }}>
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
          <Canvas camera={{ position: [0, 0, 50] }}>
            <ambientLight intensity={0.6} />
            <directionalLight position={[5, 5, 5]} intensity={1} />
            <Suspense fallback={<mesh><boxGeometry args={[1, 1, 1]} /><meshStandardMaterial color="#333" wireframe /></mesh>}>
              <STLModel url={stlUrl} />
              <Environment preset="city" />
            </Suspense>
            <OrbitControls enablePan enableZoom enableRotate autoRotate autoRotateSpeed={2} />
          </Canvas>
        ) : (
          !loading && <div className="no-model-text">No model available.</div>
        )}
      </div>

      {/* RIGHT — Text + Code */}
      <div className="results-right">
        {/* Text Panel */}
        <div className="results-text-panel">
          <div className="panel-header">
            <div className="panel-label">Analysis</div>
          </div>
          <div className="panel-body">
            <p>{reply}</p>
          </div>
        </div>

        {/* Code Block Panel */}
        <CodeBlock code={EXAMPLE_CODE} language="python" />
      </div>
    </div>
  );
}

