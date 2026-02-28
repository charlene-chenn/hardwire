import React, { Suspense } from 'react';
import { useLocation } from 'react-router-dom';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Environment } from '@react-three/drei';
import CodeBlock from '../components/CodeBlock';

// 🔌 Replace this with your actual 3D model component
function PlaceholderModel() {
  return (
    <mesh>
      <boxGeometry args={[1.5, 1.5, 1.5]} />
      <meshStandardMaterial color="#0057ff" />
    </mesh>
  );
}

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

  return (
    <div className="results-layout glass">
      {/* LEFT — 3D Model Viewer */}
      <div className="results-left">
        <Canvas camera={{ position: [0, 0, 4] }}>
          <ambientLight intensity={0.6} />
          <directionalLight position={[5, 5, 5]} intensity={1} />
          <Suspense fallback={null}>
            {/* 🔌 Swap PlaceholderModel with your actual <ModelComponent /> */}
            <PlaceholderModel />
            <Environment preset="city" />
          </Suspense>
          <OrbitControls enablePan enableZoom enableRotate />
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

