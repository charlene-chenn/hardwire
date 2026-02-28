import React, { useRef } from 'react';
import { useLoader } from '@react-three/fiber';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader';

export default function STLModel({ url, color = "#0057ff", position = [0, 0, 0], scale = 1 }) {
    const mesh = useRef();
    const geometry = useLoader(STLLoader, url);

    return (
        <mesh
            ref={mesh}
            position={position}
            scale={scale}
            onUpdate={(self) => {
                self.geometry.computeVertexNormals();
                self.geometry.center();
            }}
        >
            <primitive object={geometry} attach="geometry" />
            <meshStandardMaterial
                color={color}
                metalness={0.6}
                roughness={0.4}
            />
        </mesh>
    );
}
