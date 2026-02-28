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
  const stlUrl = location.state?.stlUrl || DEFAULT_STL_URL;

  return (
    <div className="results-layout glass">
      {/* LEFT — 3D Model Viewer */}
      <div className="results-left">
        <Canvas camera={{ position: [0, 0, 50] }}>
          <ambientLight intensity={0.6} />
          <directionalLight position={[5, 5, 5]} intensity={1} />
          <Suspense fallback={<mesh><boxGeometry args={[1, 1, 1]} /><meshStandardMaterial color="#333" wireframe /></mesh>}>
            <STLModel url={stlUrl} />
            <Environment preset="city" />
          </Suspense>
          <OrbitControls enablePan enableZoom enableRotate autoRotate autoRotateSpeed={2} />
        </Canvas>
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

